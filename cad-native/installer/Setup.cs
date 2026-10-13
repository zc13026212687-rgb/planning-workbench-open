using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;
[assembly: AssemblyTitle("清规AI · CAD原生插件 安装程序")]
[assembly: AssemblyProduct("清规AI · CAD原生插件")]
[assembly: AssemblyVersion("0.3.0.0")]
[assembly: AssemblyFileVersion("0.3.0.0")]
namespace QingGuiAI {
    internal static class Setup {
        internal static string PayloadResource = "QingGuiAI.Payload.zip";
        internal static Dictionary<string,object> Install(Options o, Action<string> log) {
            string destination = Product.Destination(o.Destination);
            string[] discoveredDestinations = new[] { Product.DefaultDestination, Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),@"Autodesk\ApplicationPlugins\QingGuiAI.bundle"), Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),@"Autodesk\ApplicationPlugins\QingGuiAI.bundle") };
            bool autoloadLocation=discoveredDestinations.Any(x=>String.Equals(Product.Full(x),destination,StringComparison.OrdinalIgnoreCase));
            if (!autoloadLocation && (!o.NoShortcut || !o.NoRegister)) throw new IOException("此目录不在 AutoCAD 插件搜索范围内。正常安装请使用默认目录；隔离验收目录仅允许同时使用 --no-shortcut --no-register。");
            string cad = Product.DetectCad(o.Cad);
            if (!Environment.Is64BitOperatingSystem) throw new IOException("清规AI CAD原生插件仅支持64位Windows。");
            using (var payload = Assembly.GetExecutingAssembly().GetManifestResourceStream(PayloadResource)) {
                if (payload == null || Product.Sha(payload) != BuildInfo.PayloadSha256) throw new IOException("安装包载荷校验失败，未写入插件。");
                log("安装包 SHA-256 校验通过。");
                payload.Position = 0;
                using (var zip = new ZipArchive(payload, ZipArchiveMode.Read)) {
                    var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                    long length = 0;
                    foreach (var entry in zip.Entries) {
                        if (String.IsNullOrEmpty(entry.Name)) continue;
                        Product.Under(destination, entry.FullName);
                        if (!names.Add(entry.FullName.Replace('\\','/'))) throw new IOException("安装包存在重名文件。");
                        if (((entry.ExternalAttributes >> 16) & 0xF000) == 0xA000) throw new IOException("安装包含符号链接。");
                        length += entry.Length;
                    }
                    foreach (string required in new[] { "PackageContents.xml", "Contents/Windows/QingGuiAI.Cad.dll", "Contents/Launcher/QingGuiAI.Launcher.exe", "Contents/Launcher/QingGuiAI.Uninstall.exe", "Contents/Launcher/QingGuiStart.scr", "Contents/Engine/runtime/python.exe" }) {
                        if (!names.Contains(required)) throw new IOException("完整安装包缺少：" + required);
                    }
                    var result = new Dictionary<string,object> { {"ok",true}, {"version",Product.Version}, {"destination",destination}, {"cad",cad}, {"payloadSha256",BuildInfo.PayloadSha256}, {"fileCount",names.Count}, {"unpackedBytes",length}, {"dryRun",o.DryRun}, {"autoloadLocation",autoloadLocation} };
                    if (o.DryRun) return result;
                    if (Directory.Exists(destination)) {
                        string old = Product.Under(destination, Product.ReceiptName);
                        if (!File.Exists(old) || Product.Read<Receipt>(old).Identity != Product.Identity) throw new IOException("目标目录已有非本安装器管理的内容。请改用新的独立目录，原文件未修改。");
                        Product.EnsureUnloaded(destination,Product.Read<Receipt>(old));
                    }
                    Directory.CreateDirectory(Path.GetDirectoryName(destination));
                    string stage = destination + ".staging-" + Guid.NewGuid().ToString("N");
                    string backup = null;
                    Directory.CreateDirectory(stage);
                    try {
                        var files = new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);
                        int count = 0;
                        foreach (var entry in zip.Entries) {
                            if (String.IsNullOrEmpty(entry.Name)) continue;
                            string path = Product.Under(stage, entry.FullName);
                            Directory.CreateDirectory(Path.GetDirectoryName(path));
                            using (var input = entry.Open()) using (var output = new FileStream(path, FileMode.CreateNew)) input.CopyTo(output);
                            files.Add(entry.FullName.Replace('\\','/'), Product.Sha(path));
                            if (++count % 250 == 0) log("已安装 " + count + " / " + names.Count + " 个文件…");
                        }
                        var receipt = new Receipt { Identity=Product.Identity, Version=Product.Version, Destination=destination, PayloadSha256=BuildInfo.PayloadSha256, InstalledUtc=DateTime.UtcNow.ToString("o"), Files=files, Registered=!o.NoRegister };
                        Product.Json(Product.Under(stage, Product.ReceiptName), receipt);
                        Receipt priorReceipt=null;
                        if (Directory.Exists(destination)) priorReceipt=Product.Read<Receipt>(Product.Under(destination,Product.ReceiptName));
                        bool activated=false, shortcutCreated=false;
                        try {
                        if (Directory.Exists(destination)) {
                            // Both resolved paths are scoped siblings of the explicit bundle directory.
                            backup = destination + ".backup-" + DateTime.UtcNow.ToString("yyyyMMddTHHmmss") + "-" + Guid.NewGuid().ToString("N").Substring(0,6);
                            if (!String.Equals(Path.GetDirectoryName(backup), Path.GetDirectoryName(destination), StringComparison.OrdinalIgnoreCase)) throw new IOException("备份路径超界。");
                            Directory.Move(destination, backup);
                        }
                        Directory.Move(stage, destination);
                        activated=true;
                            if (!o.NoShortcut) receipt.Shortcut = Product.Shortcut(destination,out shortcutCreated);
                            if (!o.NoRegister) Product.Register(destination);
                            Product.Json(Product.Under(destination, Product.ReceiptName), receipt);
                        } catch {
                            // Keep the new files reviewable and restore the previous bundle if available.
                            if(shortcutCreated && Product.ShortcutMatches(receipt.Shortcut,Product.Under(destination,@"Contents\Launcher\QingGuiAI.Launcher.exe"))) File.Delete(receipt.Shortcut);
                            if(activated) {
                                if(!o.NoRegister) Product.Unregister(destination);
                                string failed = destination + ".incomplete-" + Guid.NewGuid().ToString("N");
                                Directory.Move(destination, failed);
                            }
                            if (backup != null && !Directory.Exists(destination)) Directory.Move(backup, destination);
                            if(priorReceipt!=null && priorReceipt.Registered && Directory.Exists(destination)) Product.Register(destination,priorReceipt.Version);
                            throw;
                        }
                        result["shortcut"] = receipt.Shortcut;
                        result["backup"] = backup;
                        result["projects"] = Product.Projects;
                        result["cadAvailable"] = cad != null;
                        log("清规AI安装完成。桌面入口直接启动 AutoCAD。");
                        if (cad == null) log("本机未检出 AutoCAD 2025；安装包已安装，运行前仍需自己的 AutoCAD 2025。");
                        return result;
                    } catch (Exception ex) { throw new IOException(ex.Message + "\n安装中间文件如有保留，位于：" + stage, ex); }
                }
            }
        }
        [STAThread] static int Main(string[] args) {
            Options o = null;
            try {
                o = Options.Parse(args);
                Application.EnableVisualStyles();
                if (!o.Silent && !o.Install && !o.DryRun && !o.Uninstall) { Application.Run(new SetupForm(o)); return 0; }
                object result;
                if (o.Uninstall) { string[] kept = Product.Uninstall(o.Destination); result = new { ok=kept.Length==0, preserved=kept, projectsPreserved=Product.Projects }; if (!String.IsNullOrEmpty(o.Result)) Product.Json(o.Result,result); return kept.Length==0 ? 0 : 2; }
                result = Install(o, delegate(string line) {});
                if (!String.IsNullOrEmpty(o.Result)) Product.Json(o.Result, result);
                return 0;
            } catch (Exception ex) {
                if (o != null && !String.IsNullOrEmpty(o.Result)) Product.Json(o.Result, new { ok=false, error=ex.Message });
                if (o == null || !o.Silent) MessageBox.Show(ex.Message, Product.Name, MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
        }
    }
    internal sealed class SetupForm : Form {
        private readonly Options options;
        private readonly TextBox destination = new TextBox();
        private readonly TextBox status = new TextBox();
        private readonly Button install = new Button();
        private readonly Button launch = new Button();
        private bool busy;
        internal SetupForm(Options o) {
            options=o; Text=Product.Name + " " + Product.Version + " 安装程序"; Size=new Size(720,570); MinimumSize=Size; StartPosition=FormStartPosition.CenterScreen; Font=new Font("Microsoft YaHei UI",10); BackColor=Color.White; AutoScaleMode=AutoScaleMode.Dpi;
            var title = new Label {Text="清规AI",Font=new Font("Microsoft YaHei UI",25,FontStyle.Bold),Location=new Point(28,22),AutoSize=true,ForeColor=Color.FromArgb(17,68,65)};
            var subtitle = new Label {Text="CAD 原生插件  ·  0.3.0",Location=new Point(30,78),AutoSize=true,ForeColor=Color.FromArgb(70,87,92)};
            var description = new Label {Text="在 AutoCAD 2025 内使用清规工具面板\n道路平面 · 道路横断面 · 地块与图则\n\n本安装包包含清规原创插件与计算引擎。需要你自己的 AutoCAD。\n首次加载时 AutoCAD 可能提示安全确认，请核对插件名称与路径。",Location=new Point(30,119),Size=new Size(650,125)};
            var label = new Label {Text="安装到当前用户（不修改已有 CAD 配置）",Location=new Point(30,250),AutoSize=true};
            destination.Text=o.Destination; destination.Location=new Point(30,279); destination.Size=new Size(642,28); destination.ReadOnly=true;
            status.Multiline=true; status.ReadOnly=true; status.ScrollBars=ScrollBars.Vertical; status.Location=new Point(30,323); status.Size=new Size(642,112); status.BackColor=Color.FromArgb(246,249,249);
            status.Text="准备安装。用户项目单独保存在 LocalAppData\\QingGuiAI\\Projects。";
            install.Text="安装清规AI"; install.Location=new Point(30,457); install.Size=new Size(160,42); install.BackColor=Color.FromArgb(20,108,101); install.ForeColor=Color.White; install.FlatStyle=FlatStyle.Flat;
            launch.Text="打开 AutoCAD"; launch.Location=new Point(206,457); launch.Size=new Size(160,42); launch.Enabled=false;
            var close = new Button {Text="关闭",Location=new Point(548,457),Size=new Size(124,42)};
            close.Click += delegate { if (!busy) Close(); };
            install.Click += async delegate {
                busy=true; install.Enabled=false; destination.Enabled=false; options.Destination=destination.Text;
                try {
                    await Task.Run(delegate { Setup.Install(options, Log); });
                    launch.Enabled=Product.DetectCad(options.Cad)!=null; install.Text="安装完成";
                } catch(Exception ex) { Log("安装失败：" + ex.Message); install.Enabled=true; destination.Enabled=true; } finally { busy=false; }
            };
            launch.Click += delegate { System.Diagnostics.Process.Start(Product.Under(options.Destination,@"Contents\Launcher\QingGuiAI.Launcher.exe")); };
            FormClosing += delegate(object s,FormClosingEventArgs e) { if(busy) e.Cancel=true; };
            Controls.AddRange(new Control[] {title,subtitle,description,label,destination,status,install,launch,close});
        }
        private void Log(string line) { if (InvokeRequired) BeginInvoke(new Action<string>(Log),line); else status.AppendText(Environment.NewLine + line); }
    }
}
