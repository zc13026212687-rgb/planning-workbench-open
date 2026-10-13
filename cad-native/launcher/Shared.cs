using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;
using Microsoft.Win32;

namespace QingGuiAI {
    internal static class Product {
        internal const string Name = "清规AI · CAD原生插件";
        internal const string Version = "0.3.0";
        internal const string Identity = "QingGuiAI.CAD.Native";
        internal const string ReceiptName = "qinggui-install-receipt.json";
        internal const string UninstallKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\QingGuiAI.CAD.Native";
        internal static string DefaultDestination { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), @"Autodesk\ApplicationPlugins\QingGuiAI.bundle"); } }
        internal static string Projects { get { return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), @"QingGuiAI\Projects"); } }
        internal static string Sha(string file) { using (var s = File.OpenRead(file)) using (var h = SHA256.Create()) return BitConverter.ToString(h.ComputeHash(s)).Replace("-", "").ToLowerInvariant(); }
        internal static string Sha(Stream s) { using (var h = SHA256.Create()) return BitConverter.ToString(h.ComputeHash(s)).Replace("-", "").ToLowerInvariant(); }
        internal static void Json(string path, object value) { File.WriteAllText(path, new JavaScriptSerializer().Serialize(value), new UTF8Encoding(false)); }
        internal static T Read<T>(string path) { return new JavaScriptSerializer().Deserialize<T>(File.ReadAllText(path, Encoding.UTF8)); }
        internal static string Full(string path) { return Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar); }
        internal static string Under(string root, string relative) {
            if (String.IsNullOrWhiteSpace(relative) || Path.IsPathRooted(relative) || relative.Contains(":")) throw new IOException("无效的包内路径：" + relative);
            string full = Full(Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar)));
            if (!full.StartsWith(Full(root) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) throw new IOException("路径超出安装目录：" + relative);
            for (string p = full; p != null && p.Length >= Full(root).Length; p = Path.GetDirectoryName(p)) {
                if ((File.Exists(p) || Directory.Exists(p)) && (File.GetAttributes(p) & FileAttributes.ReparsePoint) != 0) throw new IOException("包内路径含符号链接或联接：" + p);
            }
            return full;
        }
        internal static string Destination(string value) {
            if (!Path.IsPathRooted(value)) throw new IOException("安装目录必须是绝对路径。");
            string full = Full(value);
            if (!String.Equals(Path.GetFileName(full), "QingGuiAI.bundle", StringComparison.OrdinalIgnoreCase)) throw new IOException("安装目录末级名称必须是 QingGuiAI.bundle。");
            if (full.StartsWith(@"\\") || full.Length < 12) throw new IOException("请使用本机磁盘中的独立 QingGuiAI.bundle 目录。");
            for (var d = new DirectoryInfo(full); d != null; d = d.Parent) {
                if (d.Exists && (d.Attributes & FileAttributes.ReparsePoint) != 0) throw new IOException("安装路径不能经过符号链接或联接：" + d.FullName);
            }
            return full;
        }
        internal static bool Cad2025(string path) {
            if (!File.Exists(path) || !String.Equals(Path.GetFileName(path), "acad.exe", StringComparison.OrdinalIgnoreCase)) return false;
            var v = FileVersionInfo.GetVersionInfo(path);
            return v.ProductMajorPart == 25 && v.ProductMinorPart == 0;
        }
        internal static string DetectCad(string explicitPath) {
            if (!String.IsNullOrEmpty(explicitPath)) {
                if (!Cad2025(explicitPath)) throw new IOException("指定文件不是受支持的 AutoCAD 2025 acad.exe。");
                return Full(explicitPath);
            }
            foreach (var p in Process.GetProcessesByName("acad")) { try { string s = p.MainModule.FileName; if (Cad2025(s)) return s; } catch {} finally { p.Dispose(); } }
            foreach (var hive in new[] { RegistryHive.LocalMachine, RegistryHive.CurrentUser }) {
                using (var b = RegistryKey.OpenBaseKey(hive, RegistryView.Registry64)) using (var release = b.OpenSubKey(@"SOFTWARE\Autodesk\AutoCAD\R25.0")) {
                    if (release == null) continue;
                    foreach (string sub in release.GetSubKeyNames()) using (var k = release.OpenSubKey(sub)) {
                        foreach (string name in new[] { "AcadLocation", "InstallLocation", "Location" }) {
                            string s = k.GetValue(name) as string;
                            if (!String.IsNullOrEmpty(s)) { s = Path.Combine(s, "acad.exe"); if (Cad2025(s)) return s; }
                        }
                    }
                }
            }
            string standard = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), @"Autodesk\AutoCAD 2025\acad.exe");
            return Cad2025(standard) ? standard : null;
        }
        internal static string Shortcut(string destination, out bool created) {
            string desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
            string target = Under(destination, @"Contents\Launcher\QingGuiAI.Launcher.exe");
            string path = Path.Combine(desktop, Name + ".lnk");
            dynamic shell = Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
            if (File.Exists(path)) {
                dynamic previous = shell.CreateShortcut(path);
                if (!String.Equals((string)previous.TargetPath, target, StringComparison.OrdinalIgnoreCase)) {
                    int suffix = 2; do { path = Path.Combine(desktop, Name + " (" + suffix++ + ").lnk"); } while (File.Exists(path));
                }
            }
            created=!File.Exists(path);
            dynamic link = shell.CreateShortcut(path);
            link.TargetPath = target; link.WorkingDirectory = Path.GetDirectoryName(target); link.Description = Name + " " + Version + " — 在 AutoCAD 内打开清规面板";
            link.IconLocation = target + ",0"; link.Save();
            return path;
        }
        internal static bool ShortcutMatches(string shortcut, string target) {
            if (String.IsNullOrEmpty(shortcut) || !File.Exists(shortcut)) return false;
            dynamic shell = Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
            dynamic link = shell.CreateShortcut(shortcut);
            return String.Equals((string)link.TargetPath, target, StringComparison.OrdinalIgnoreCase);
        }
        internal static void Register(string destination, string version = Version) {
            using (var k = Registry.CurrentUser.CreateSubKey(UninstallKey)) {
                k.SetValue("DisplayName", Name); k.SetValue("DisplayVersion", version); k.SetValue("InstallLocation", destination);
                k.SetValue("DisplayIcon", Under(destination, @"Contents\Launcher\QingGuiAI.Launcher.exe"));
                string exe = Under(destination, @"Contents\Launcher\QingGuiAI.Uninstall.exe");
                k.SetValue("UninstallString", "\"" + exe + "\" --uninstall");
                k.SetValue("QuietUninstallString", "\"" + exe + "\" --uninstall --silent");
                k.SetValue("NoModify", 1); k.SetValue("NoRepair", 1);
            }
        }
        internal static void Unregister(string destination) {
            using (var k = Registry.CurrentUser.OpenSubKey(UninstallKey)) {
                if (k == null || !String.Equals(k.GetValue("InstallLocation") as string, destination, StringComparison.OrdinalIgnoreCase)) return;
            }
            Registry.CurrentUser.DeleteSubKey(UninstallKey, false);
        }
        internal static void EnsureUnloaded(string destination, Receipt receipt) {
            // Only this bundle's executables are checked. Other AutoCAD sessions may remain open.
            foreach (string relative in receipt.Files.Keys) {
                string extension=Path.GetExtension(relative);
                if (!String.Equals(extension,".dll",StringComparison.OrdinalIgnoreCase) && !String.Equals(extension,".exe",StringComparison.OrdinalIgnoreCase) && !String.Equals(extension,".pyd",StringComparison.OrdinalIgnoreCase)) continue;
                string path=Under(destination,relative);
                if (!File.Exists(path)) continue;
                try { using (var stream=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.None)) {} }
                catch(IOException) { throw new IOException("清规AI的文件正在使用，安装内容保持不变。请仅关闭加载此清规AI插件的 AutoCAD/计算进程后重试：\n"+path); }
            }
        }
        internal static string[] Uninstall(string destination) {
            destination = Destination(destination);
            string receiptPath = Under(destination, ReceiptName);
            Receipt r = Read<Receipt>(receiptPath);
            if (r.Identity != Identity || !String.Equals(Full(r.Destination), destination, StringComparison.OrdinalIgnoreCase)) throw new IOException("安装收据不匹配，未删除任何文件。");
            EnsureUnloaded(destination,r);
            var preserved = new List<string>();
            foreach (var file in r.Files) {
                string path = Under(destination, file.Key);
                if (!File.Exists(path)) continue;
                if (Sha(path) != file.Value) { preserved.Add(file.Key + " (已修改)"); continue; }
                try { File.Delete(path); } catch (IOException) { preserved.Add(file.Key + " (正在使用)"); } catch (UnauthorizedAccessException) { preserved.Add(file.Key + " (无权删除)"); }
            }
            string launcher = Under(destination, @"Contents\Launcher\QingGuiAI.Launcher.exe");
            if (ShortcutMatches(r.Shortcut, launcher)) File.Delete(r.Shortcut);
            if (r.Registered) Unregister(destination);
            // The receipt is retained when files were preserved so the user can retry later.
            if (preserved.Count == 0) File.Delete(receiptPath);
            var directories = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (string relative in r.Files.Keys) {
                for (string d = Path.GetDirectoryName(Under(destination, relative)); d != null && d.Length > destination.Length; d = Path.GetDirectoryName(d)) directories.Add(d);
            }
            foreach (string d in directories.OrderByDescending(x => x.Length)) {
                if (!Directory.Exists(d)) continue;
                if ((File.GetAttributes(d) & FileAttributes.ReparsePoint) == 0 && Directory.GetFileSystemEntries(d).Length == 0) Directory.Delete(d);
            }
            if (Directory.Exists(destination) && Directory.GetFileSystemEntries(destination).Length == 0) Directory.Delete(destination);
            return preserved.ToArray();
        }
    }
    internal sealed class Receipt {
        public string Identity { get; set; }
        public string Version { get; set; }
        public string Destination { get; set; }
        public string PayloadSha256 { get; set; }
        public string InstalledUtc { get; set; }
        public string Shortcut { get; set; }
        public bool Registered { get; set; }
        public Dictionary<string,string> Files { get; set; }
    }
    internal sealed class Options {
        internal string Destination = Product.DefaultDestination;
        internal string Cad;
        internal string Result;
        internal bool Silent, Install, Uninstall, DryRun, NoShortcut, NoRegister, Check, SelfTest;
        internal static Options Parse(string[] args) {
            var o = new Options();
            for (int i=0; i<args.Length; i++) {
                switch (args[i]) {
                    case "--dest": o.Destination = args[++i]; break;
                    case "--acad": o.Cad = args[++i]; break;
                    case "--result": o.Result = args[++i]; break;
                    case "--silent": o.Silent = true; break;
                    case "--install": o.Install = true; break;
                    case "--uninstall": o.Uninstall = true; break;
                    case "--dry-run": o.DryRun = true; break;
                    case "--no-shortcut": o.NoShortcut = true; break;
                    case "--no-register": o.NoRegister = true; break;
                    case "--check": o.Check = true; break;
                    case "--self-test": o.SelfTest = true; break;
                    default: throw new ArgumentException("未知参数：" + args[i]);
                }
            }
            return o;
        }
    }
}
