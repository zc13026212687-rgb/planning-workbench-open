using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;
[assembly: AssemblyTitle("清规AI 卸载")]
[assembly: AssemblyProduct("清规AI · CAD原生插件")]
[assembly: AssemblyVersion("0.3.0.0")]
namespace QingGuiAI {
    internal static class Uninstaller {
        [STAThread] static int Main(string[] args) {
            Options o = null;
            bool silent=args.Length==1 && args[0]=="--cleanup";
            string resultPath=null;
            try {
                if (args.Length == 1 && args[0] == "--cleanup") {
                    var r = Product.Read<CleanupRequest>(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "destination.json"));
                    silent=r.silent; resultPath=r.result;
                    try { using (var p = Process.GetProcessById(r.parent)) p.WaitForExit(5000); } catch (ArgumentException) {}
                    string[] kept = Product.Uninstall(r.destination);
                    if (!String.IsNullOrEmpty(r.result)) Product.Json(r.result, new { ok=kept.Length==0, preserved=kept, projectsPreserved=Product.Projects });
                    if (!r.silent) MessageBox.Show(kept.Length == 0 ? "清规AI已卸载。用户项目保留在：\n" + Product.Projects : "卸载已执行，以下修改过或正在使用的文件已保留：\n" + String.Join("\n", kept), Product.Name);
                    return kept.Length == 0 ? 0 : 2;
                }
                o = Options.Parse(args);
                silent=o.Silent; resultPath=o.Result;
                o.Destination = Product.Destination(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, @"..\.."));
                if (!o.Silent && MessageBox.Show("卸载清规AI的自有插件文件？\n\n用户项目、原有 AutoCAD 和其他插件均保留。请先关闭加载清规AI的 AutoCAD。", Product.Name, MessageBoxButtons.OKCancel, MessageBoxIcon.Question) != DialogResult.OK) return 0;
                // Run a copy outside the installation to permit removal of the uninstaller itself.
                string temp = Path.Combine(Path.GetTempPath(), "QingGui-Uninstall-" + Guid.NewGuid().ToString("N"));
                Directory.CreateDirectory(temp);
                string helper = Path.Combine(temp, "QingGuiAI.Cleanup.exe");
                File.Copy(Assembly.GetExecutingAssembly().Location, helper);
                Product.Json(Path.Combine(temp, "destination.json"), new CleanupRequest { destination=o.Destination, silent=o.Silent, result=o.Result, parent=Process.GetCurrentProcess().Id });
                Process.Start(new ProcessStartInfo(helper, "--cleanup") { UseShellExecute=false, CreateNoWindow=true });
                return 0;
            } catch (Exception ex) {
                if(!String.IsNullOrEmpty(resultPath)) Product.Json(resultPath,new {ok=false,error=ex.Message});
                if (!silent) MessageBox.Show(ex.Message, Product.Name, MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
        }
    }
    internal sealed class CleanupRequest { public string destination {get;set;} public bool silent {get;set;} public string result {get;set;} public int parent {get;set;} }
}
