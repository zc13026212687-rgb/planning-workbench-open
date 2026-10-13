using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;
[assembly: AssemblyTitle("清规AI · CAD原生插件")]
[assembly: AssemblyProduct("清规AI · CAD原生插件")]
[assembly: AssemblyVersion("0.3.0.0")]
[assembly: AssemblyFileVersion("0.3.0.0")]
namespace QingGuiAI {
    internal static class Launcher {
        [STAThread] static int Main(string[] args) {
            Options options = null;
            try {
                options = Options.Parse(args);
                string directory = AppDomain.CurrentDomain.BaseDirectory;
                string bundle = Product.Destination(Path.Combine(directory, @"..\.."));
                string cad = Product.DetectCad(options.Cad);
                string script = Product.Under(bundle, options.SelfTest ? @"Contents\Launcher\QingGuiSelfTest.scr" : @"Contents\Launcher\QingGuiStart.scr");
                string plugin = Product.Under(bundle, @"Contents\Windows\QingGuiAI.Cad.dll");
                if (cad == null) throw new IOException("未找到 AutoCAD 2025。请先安装并正常启动自己的 AutoCAD 2025，再使用清规AI。该安装包不包含 AutoCAD。");
                if (!File.Exists(script) || !File.Exists(plugin)) throw new IOException("清规AI 插件文件缺失，请重新运行完整安装包。");
                string arguments = "/nologo /b \"" + script + "\"";
                if (options.Check || options.DryRun) {
                    if (!String.IsNullOrEmpty(options.Result)) Product.Json(options.Result, new { ok=true, cad=cad, bundle=bundle, script=script, arguments=arguments, projects=Product.Projects });
                    return 0;
                }
                Directory.CreateDirectory(Product.Projects);
                var start = new ProcessStartInfo(cad, arguments) { WorkingDirectory=Product.Projects, UseShellExecute=true };
                using (var process=Process.Start(start)) {
                    string logDir=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),@"QingGuiAI\Logs");
                    Directory.CreateDirectory(logDir);
                    var launchResult=new { ok=true, pid=process.Id, cad=cad, arguments=arguments, bundle=bundle, selfTest=options.SelfTest, launchedUtc=DateTime.UtcNow.ToString("o") };
                    Product.Json(Path.Combine(logDir,"last-launch.json"),launchResult);
                    if (!String.IsNullOrEmpty(options.Result)) Product.Json(options.Result,launchResult);
                }
                return 0;
            } catch (Exception ex) {
                if (options != null && !String.IsNullOrEmpty(options.Result)) Product.Json(options.Result, new { ok=false, error=ex.Message });
                if (options == null || !options.Silent) MessageBox.Show(ex.Message, Product.Name, MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
        }
    }
}
