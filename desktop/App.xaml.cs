using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace PlanningStudio;
public partial class App : Application
{
    private Process? _ownedLauncher, _ownedBackend;
    private ServerConnection? _connection;
    private Mutex? _instanceMutex;
    private bool _ownsMutex;
    private EventWaitHandle? _activateEvent;
    private RegisteredWaitHandle? _activationWait;
    private sealed record ServerConnection(Uri Url, string Token, int Pid);
    protected override async void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory != null && !File.Exists(Path.Combine(directory.FullName, "run_server.py"))) directory = directory.Parent;
        var root = directory?.FullName;
        var identity = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(Path.GetFullPath(root ?? AppContext.BaseDirectory).TrimEnd(Path.DirectorySeparatorChar).ToUpperInvariant())))[..24];
        _instanceMutex = new Mutex(false, @"Local\PlanningStudio-" + identity);
        try { _ownsMutex = _instanceMutex.WaitOne(0); } catch (AbandonedMutexException) { _ownsMutex = true; }
        var activationName = @"Local\PlanningStudio-Activate-" + identity;
        if (!_ownsMutex)
        {
            try { using var signal = EventWaitHandle.OpenExisting(activationName); signal.Set(); } catch (WaitHandleCannotBeOpenedException) { }
            Shutdown(); return;
        }
        _activateEvent = new EventWaitHandle(false, EventResetMode.AutoReset, activationName);
        _activationWait = ThreadPool.RegisterWaitForSingleObject(_activateEvent, (_, _) => Dispatcher.BeginInvoke(new Action(() =>
        {
            if (MainWindow is { IsLoaded: true } window) { if (window.WindowState == WindowState.Minimized) window.WindowState = WindowState.Normal; window.Show(); window.Activate(); }
        })), null, Timeout.Infinite, false);
        var progress = new Window { Title = "规绘 · Planning Studio", Width = 460, Height = 180, ResizeMode = ResizeMode.NoResize, WindowStartupLocation = WindowStartupLocation.CenterScreen, Background = new SolidColorBrush(Color.FromRgb(247,248,245)), Content = new TextBlock { Text = "正在准备本地设计空间…", FontSize = 18, VerticalAlignment = VerticalAlignment.Center, HorizontalAlignment = HorizontalAlignment.Center } };
        progress.Show();
        try
        {
            string? suppliedUrl = null;
            for (int i = 0; i < e.Args.Length; i++)
                if (e.Args[i] == "--url")
                { if (i + 1 >= e.Args.Length) throw new InvalidOperationException("--url 后缺少本机地址。"); suppliedUrl = e.Args[++i]; }
            Uri target;
            if (suppliedUrl != null)
            {
                if (!ValidLocalUri(suppliedUrl, out var uri)) throw new InvalidOperationException("工作台只接受本机 HTTP/HTTPS 地址。请检查 --url 参数。");
                target = uri!;
            }
            else
            {
                if (root == null) throw new InvalidOperationException("没有找到项目 run_server.py。请将桌面程序保留在 PlanningWorkbench 项目目录内。");
                var metadata = Path.Combine(root, "data", "server.json");
                _connection = await ReadHealthyConnection(metadata);
                if (_connection == null)
                {
                    var python = Path.Combine(root, ".venv", "Scripts", "pythonw.exe");
                    if (!File.Exists(python)) throw new InvalidOperationException("项目 Python 环境尚未准备完成。请运行根目录“检查与安装依赖.cmd”。");
                    var start = new ProcessStartInfo(python) { WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden };
                    start.ArgumentList.Add(Path.Combine(root, "run_server.py"));
                    start.Environment["PLANNING_DATA_DIR"] = Path.Combine(root, "data");
                    _ownedLauncher = Process.Start(start) ?? throw new InvalidOperationException("无法启动本地计算服务。");
                    _ = _ownedLauncher.Handle;
                    var until = DateTime.UtcNow.AddSeconds(45);
                    while (DateTime.UtcNow < until)
                    {
                        var candidate = await ReadHealthyConnection(metadata);
                        if (candidate != null)
                        {
                            var backend = ProcessOwnership.CaptureOwnedProcess(candidate.Pid, _ownedLauncher);
                            if (backend != null) { _ownedBackend = backend; _connection = candidate; break; }
                        }
                        if (_ownedLauncher.HasExited) throw new InvalidOperationException("本地计算服务提前退出。请检查 data/backend.log 与项目依赖。");
                        await Task.Delay(300);
                    }
                    if (_connection == null) throw new InvalidOperationException("本地计算服务未能在 45 秒内就绪。请检查 data/backend.log 后重试。");
                }
                target = _connection.Url;
            }
            MainWindow = new StudioWindow(target);
            MainWindow.Closed += async (_, _) => { await StopOwnedServer(); Shutdown(); };
            MainWindow.Show(); progress.Close();
        }
        catch (Exception ex)
        {
            progress.Close(); await StopOwnedServer();
            MessageBox.Show(ex.Message, "规绘 · 启动未完成", MessageBoxButton.OK, MessageBoxImage.Warning); Shutdown(2);
        }
    }
    protected override void OnExit(ExitEventArgs e)
    {
        _activationWait?.Unregister(null); _activateEvent?.Dispose();
        if (_ownsMutex) { _instanceMutex?.ReleaseMutex(); _ownsMutex = false; }
        _instanceMutex?.Dispose(); base.OnExit(e);
    }
    private static bool ValidLocalUri(string value, out Uri? uri) => Uri.TryCreate(value, UriKind.Absolute, out uri) && uri.IsLoopback && string.IsNullOrEmpty(uri.UserInfo) && (uri.Scheme == "http" || uri.Scheme == "https");
    private static async Task<ServerConnection?> ReadHealthyConnection(string file)
    {
        try
        {
            if (!File.Exists(file)) return null;
            using var document = JsonDocument.Parse(await File.ReadAllTextAsync(file)); var data = document.RootElement;
            if (data.GetProperty("application").GetString() != "planning-workbench") return null;
            var pid = data.GetProperty("pid").GetInt32();
            using var process = Process.GetProcessById(pid); if (process.HasExited) return null;
            if (!ValidLocalUri(data.GetProperty("url").GetString() ?? "", out var uri)) return null;
            var token = data.GetProperty("token").GetString() ?? "";
            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(2) };
            using var response = await client.GetAsync(new Uri(uri!, "/health"));
            if (!response.IsSuccessStatusCode) return null;
            using var health = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
            if (health.RootElement.GetProperty("application").GetString() != "planning-workbench") return null;
            return new ServerConnection(uri!, token, pid);
        }
        catch (Exception) { return null; }
    }
    private static void KillOwned(Process? process)
    {
        try { if (process != null && !process.HasExited) process.Kill(entireProcessTree: true); } catch (Exception) { }
    }
    private async Task StopOwnedServer()
    {
        var launcher = _ownedLauncher; var backend = _ownedBackend;
        _ownedLauncher = null; _ownedBackend = null;
        if (launcher == null) return; // --url and reused services remain owned by their original launcher.
        try
        {
            if (backend != null && !backend.HasExited && _connection != null && _connection.Pid == backend.Id)
            {
                using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(3) };
                client.DefaultRequestHeaders.Add("X-Local-Token", _connection.Token);
                using var response = await client.PostAsync(new Uri(_connection.Url, "/api/shutdown"), null);
                response.EnsureSuccessStatusCode();
                await backend.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(5));
            }
            if (!launcher.HasExited) await launcher.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(2));
        }
        catch (Exception) { KillOwned(backend); KillOwned(launcher); }
        finally { KillOwned(backend); KillOwned(launcher); backend?.Dispose(); launcher.Dispose(); }
    }
}
