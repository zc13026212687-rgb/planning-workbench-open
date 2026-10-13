using System.Diagnostics;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.Wpf;
using Microsoft.Win32;

namespace PlanningStudio;
public sealed class StudioWindow : Window
{
    private readonly Uri _target;
    private readonly Grid _root = new();
    private readonly WebView2 _web = new();
    private readonly TextBlock _status = new() { Text = "正在连接本地设计工作台…", FontSize = 17, Foreground = new SolidColorBrush(Color.FromRgb(70,100,80)), TextWrapping = TextWrapping.Wrap, HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(50) };
    public StudioWindow(Uri target)
    {
        _target = target; Title = "清规AI · PlanningWorkbench Open";
        Width = 1480; Height = 960; MinWidth = 920; MinHeight = 660;
        WindowStartupLocation = WindowStartupLocation.CenterScreen;
        Background = new SolidColorBrush(Color.FromRgb(247,248,245));
        Content = _root; _root.Children.Add(_web); _root.Children.Add(_status);
        Loaded += async (_, _) => await InitializeAsync();
        Closed += (_, _) => _web.Dispose();
    }
    private async Task InitializeAsync()
    {
        try
        {
            var data = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "PlanningStudio", "WebView2");
            var environment = await CoreWebView2Environment.CreateAsync(null, data);
            await _web.EnsureCoreWebView2Async(environment);
            _web.DefaultBackgroundColor = System.Drawing.Color.FromArgb(247,248,245);
            _web.CoreWebView2.Settings.IsStatusBarEnabled = false;
            _web.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
            _web.CoreWebView2.Settings.AreBrowserAcceleratorKeysEnabled = false;
            _web.CoreWebView2.NavigationStarting += (_, e) =>
            {
                if (!Uri.TryCreate(e.Uri, UriKind.Absolute, out var destination)) { e.Cancel = true; return; }
                if (destination.Scheme == "about") return;
                // Browser-generated DXF blobs belong to the already authenticated local origin.
                if (destination.Scheme == "blob" && destination.OriginalString.StartsWith("blob:" + _target.GetLeftPart(UriPartial.Authority) + "/", StringComparison.Ordinal)) return;
                if (!destination.IsLoopback || destination.GetLeftPart(UriPartial.Authority) != _target.GetLeftPart(UriPartial.Authority)) e.Cancel = true;
            };
            _web.CoreWebView2.NavigationCompleted += (_, e) =>
            {
                if (e.IsSuccess) _status.Visibility = Visibility.Collapsed;
                else { _status.Visibility = Visibility.Visible; _status.Text = "未连接到本地服务。\n请先通过项目启动器启动后端，再重新打开工作台。\n浏览器状态：" + e.WebErrorStatus; }
            };
            _web.CoreWebView2.NewWindowRequested += (_, e) =>
            {
                e.Handled = true;
                if (e.IsUserInitiated && Uri.TryCreate(e.Uri, UriKind.Absolute, out var link) && link.Scheme == "https")
                    Process.Start(new ProcessStartInfo(link.AbsoluteUri) { UseShellExecute = true });
            };
            _web.CoreWebView2.DownloadStarting += (_, e) =>
            {
                var deferral = e.GetDeferral(); e.Handled = true;
                Dispatcher.BeginInvoke(new Action(() =>
                {
                    try
                    {
                        var extension = Path.GetExtension(e.ResultFilePath).ToLowerInvariant();
                        var zip = extension == ".zip";
                        var dialog = new SaveFileDialog { Title = zip ? "保存规划成果包" : "保存可编辑道路图纸", FileName = Path.GetFileName(e.ResultFilePath), Filter = zip ? "ZIP 成果包 (*.zip)|*.zip|所有文件 (*.*)|*.*" : "DXF 图纸 (*.dxf)|*.dxf|所有文件 (*.*)|*.*", DefaultExt = zip ? ".zip" : ".dxf", AddExtension = true, OverwritePrompt = true };
                        if (dialog.ShowDialog(this) == true) e.ResultFilePath = dialog.FileName;
                        else e.Cancel = true;
                    }
                    finally { deferral.Complete(); }
                }));
            };
            _web.CoreWebView2.Navigate(_target.AbsoluteUri);
        }
        catch (Exception ex)
        {
            _status.Text = "桌面视图启动失败。\n请确认已安装 Microsoft Edge WebView2 Runtime。\n" + ex.Message;
            _status.Visibility = Visibility.Visible;
        }
    }
}
