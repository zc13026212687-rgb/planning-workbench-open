using System.Diagnostics;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace QingGuiAI.Cad;

internal sealed record EngineJob(string Directory, string Drawing, string Parameters, string Kind);

internal static class Engine
{
    internal const string Product = "清规AI · CAD原生插件 0.3.0";
    internal static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true, Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping };
    internal static string Home => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "QingGuiAI");
    internal static string Root => Path.GetFullPath(Path.Combine(Path.GetDirectoryName(typeof(Engine).Assembly.Location)!, "..", "Engine"));
    internal static string NewProject(string name)
    {
        var path = Path.Combine(Home, "Projects", name + "-" + DateTime.UtcNow.ToString("yyyyMMddTHHmmssfffZ") + "-" + Guid.NewGuid().ToString("N")[..8]);
        Directory.CreateDirectory(path);
        return path;
    }
    internal static void WriteJson(string path, object data) => File.WriteAllText(path, JsonSerializer.Serialize(data, JsonOptions), new UTF8Encoding(false));
    internal static EngineJob Generate(string project, string name, JsonObject? spec = null, string? caseId = null, string? sourceSpec = null, string? parcel = null)
    {
        var python = Path.Combine(Root, "runtime", "python.exe");
        var cli = Path.Combine(Root, "planning_cli.py");
        if (!File.Exists(python) || !File.Exists(cli)) throw new InvalidOperationException("缺少清规AI随包计算引擎，请重新安装完整CAD插件安装包。引擎路径：" + Root);
        var outPath = Path.Combine(project, name);
        var specPath = sourceSpec;
        if (spec != null) { specPath = Path.Combine(project, name + "-input.json"); WriteJson(specPath, spec); }
        var info = new ProcessStartInfo(python) { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true, WorkingDirectory = Root, StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8 };
        foreach (var a in new[] { "-B", "-X", "utf8", cli, parcel == null ? "generate" : "sheet", "--out", outPath }) info.ArgumentList.Add(a);
        if (specPath != null) { info.ArgumentList.Add("--spec"); info.ArgumentList.Add(specPath); }
        else { info.ArgumentList.Add("--case"); info.ArgumentList.Add(caseId ?? "regulatory-road-plan"); }
        if (parcel != null) { info.ArgumentList.Add("--parcel"); info.ArgumentList.Add(parcel); }
        using var process = Process.Start(info) ?? throw new InvalidOperationException("不能启动计算引擎。");
        var stdout = process.StandardOutput.ReadToEndAsync();
        var stderr = process.StandardError.ReadToEndAsync();
        if (!process.WaitForExit(120000)) { process.Kill(true); throw new TimeoutException("计算超过120秒，任务已停止；原始CAD实体未修改。"); }
        Task.WaitAll(stdout, stderr);
        File.WriteAllText(Path.Combine(project, name + "-engine.stdout.log"), stdout.Result, Encoding.UTF8);
        File.WriteAllText(Path.Combine(project, name + "-engine.stderr.log"), stderr.Result, Encoding.UTF8);
        if (process.ExitCode != 0)
        {
            var quality = Path.Combine(outPath, "quality.json");
            var detail = File.Exists(quality) ? File.ReadAllText(quality, Encoding.UTF8) : stderr.Result + stdout.Result;
            throw new InvalidOperationException("计算校核未通过，未向CAD写入。\n" + detail[..Math.Min(detail.Length, 2200)] + "\n日志：" + project);
        }
        var drawing = Path.Combine(outPath, "drawing.dxf");
        var parameters = Path.Combine(outPath, "parameters.json");
        if (!File.Exists(drawing) || !File.Exists(parameters)) throw new InvalidOperationException("引擎缺少可验证成果，未向CAD写入：" + outPath);
        var saved = JsonNode.Parse(File.ReadAllText(parameters, Encoding.UTF8))!;
        if (saved["units"]?.GetValue<string>() != "m") throw new InvalidOperationException("仅接受米单位成果。");
        return new(outPath, drawing, parameters, saved["kind"]?.GetValue<string>() ?? "road_plan");
    }
}
