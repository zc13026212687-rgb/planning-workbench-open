using System.Text.Json;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.Runtime;
using Autodesk.AutoCAD.Windows;
using Acad = Autodesk.AutoCAD.ApplicationServices.Core.Application;
using AcadUi = Autodesk.AutoCAD.ApplicationServices.Application;
using Forms = System.Windows.Forms;
using AcException = Autodesk.AutoCAD.Runtime.Exception;
using Exception = System.Exception;

[assembly: ExtensionApplication(typeof(QingGuiAI.Cad.Commands))]
[assembly: CommandClass(typeof(QingGuiAI.Cad.Commands))]

namespace QingGuiAI.Cad;

public sealed class Commands : IExtensionApplication
{
    private static PaletteSet? palette;
    private static readonly Dictionary<Document, Pending> pending = new();
    private static readonly HashSet<Document> selfTestDocuments = new();
    private static readonly Dictionary<Document, JsonObject> undoProbes = new();
    private static string? lastParcelSpec;
    private static bool idleSubscribed;
    private static Autodesk.Windows.RibbonTab? ribbonTab;
    private sealed record Pending(List<EngineJob> Jobs, string Project, bool SelfTest);
    public void Initialize()
    {
        Acad.DocumentManager.MdiActiveDocument?.Editor.WriteMessage("\n清规AI CAD原生插件 0.3.0 已加载。输入 QGOPEN 打开工具面板。\n");
        if (!idleSubscribed) { Acad.Idle += OnIdle; idleSubscribed = true; }
    }
    public void Terminate() { if (idleSubscribed) Acad.Idle -= OnIdle; palette?.Dispose(); if (ribbonTab != null) Autodesk.Windows.ComponentManager.Ribbon?.Tabs.Remove(ribbonTab); }
    private static void OnIdle(object? sender, EventArgs e)
    {
        if (Acad.DocumentManager.MdiActiveDocument == null) return;
        Acad.Idle -= OnIdle; idleSubscribed = false;
        try { ShowPalette(); } catch (Exception ex) { Acad.DocumentManager.MdiActiveDocument.Editor.WriteMessage("\n清规AI面板：" + ex.Message); }
    }
    [CommandMethod("QGOPEN", CommandFlags.Session)] public void Open() => Guard(ShowPalette);
    [CommandMethod("QGABOUT", CommandFlags.Session)] public void About() => Acad.ShowAlertDialog(Engine.Product + "\n原创控规教学工具，直接在AutoCAD中生成可编辑标准实体。\n支持AutoCAD 2025 Windows x64；计算引擎随包提供。\n道路平面、横断面、地块与图则；不含完整湘源功能，不绕过任何软件授权。\n真实规划规范、指标与测绘基础由使用者确认。\n项目成果目录：" + Path.Combine(Engine.Home, "Projects"));
    private static void ShowPalette()
    {
        EnsureRibbon();
        if (palette == null)
        {
            palette = new PaletteSet("清规AI · CAD原生插件", new Guid("74543d7f-d7d6-4bcd-a2e8-027920534418")) { Size = new System.Drawing.Size(420, 710), MinimumSize = new System.Drawing.Size(300, 460), Style = PaletteSetStyles.ShowAutoHideButton | PaletteSetStyles.ShowCloseButton | PaletteSetStyles.ShowPropertiesMenu };
            var panel = new ResponsivePalettePanel { Dock = Forms.DockStyle.Fill, FlowDirection = Forms.FlowDirection.TopDown, WrapContents = false, AutoScroll = true, Padding = new Forms.Padding(16), BackColor = System.Drawing.Color.FromArgb(242, 246, 250) };
            panel.Controls.Add(new Forms.Label { Text = "清规AI", Font = new System.Drawing.Font("Microsoft YaHei UI", 22, System.Drawing.FontStyle.Bold), AutoSize = true, ForeColor = System.Drawing.Color.FromArgb(28, 60, 91) });
            panel.Controls.Add(new Forms.Label { Text = "CAD原生插件 · 0.3.0\n选择原图实体 → 参数计算 → 原生落图", AutoSize = true, Margin = new Forms.Padding(3, 0, 3, 15) });
            AddButton(panel, "道路｜选择中心线生成边线与路口", "QGROAD");
            AddButton(panel, "道路｜X / T 路口教学示例（新图）", "QGROADDEMO");
            AddButton(panel, "断面｜编辑六组成参数（新图）", "QGSECTION");
            AddButton(panel, "地块｜选择边界和道路计算地块", "QGPARCEL");
            AddButton(panel, "地块｜控规教学示例（新图）", "QGPARCELDEMO");
            AddButton(panel, "图则｜最近地块生成单块图则（新图）", "QGSHEET");
            AddButton(panel, "输入｜导入规划参数 JSON（新图）", "QGSPEC");
            AddButton(panel, "关于清规AI与能力范围", "QGABOUT");
            panel.Controls.Add(new Forms.Label { Text = "原图落图要求 INSUNITS=6（米）。\n源中心线、边界均保留；每次生成保留独立成果。\n输入 U 可撤销本次落图。保存图纸请用 QSAVE。\n参数与质量报告位于本机项目文件夹。\n示例仅用于教学，指标缺失保持待核。", AutoSize = true, Margin = new Forms.Padding(3, 16, 3, 5) });
            palette.Add("规划绘图", panel);
        }
        palette.Visible = true;
    }
    private static void EnsureRibbon()
    {
        var ribbon = Autodesk.Windows.ComponentManager.Ribbon;
        if (ribbon == null || ribbon.Tabs.Any(t => t.Id == "QINGGUIAI_NATIVE_030")) return;
        ribbonTab = new Autodesk.Windows.RibbonTab { Title = "清规AI", Id = "QINGGUIAI_NATIVE_030" };
        foreach (var group in new[] {
            ("道路", new[] { ("选线生成", "QGROAD"), ("路口示例", "QGROADDEMO"), ("横断面", "QGSECTION") }),
            ("地块与图则", new[] { ("选边界分块", "QGPARCEL"), ("地块示例", "QGPARCELDEMO"), ("单块图则", "QGSHEET") }),
            ("清规AI", new[] { ("工具面板", "QGOPEN"), ("参数导入", "QGSPEC"), ("关于", "QGABOUT") }) })
        {
            var source = new Autodesk.Windows.RibbonPanelSource { Title = group.Item1 };
            foreach (var item in group.Item2) source.Items.Add(new Autodesk.Windows.RibbonButton { Text = item.Item1, ShowText = true, Size = Autodesk.Windows.RibbonItemSize.Standard, CommandParameter = item.Item2, CommandHandler = new RibbonCommand() });
            ribbonTab.Panels.Add(new Autodesk.Windows.RibbonPanel { Source = source });
        }
        ribbon.Tabs.Add(ribbonTab);
    }
    private sealed class RibbonCommand : System.Windows.Input.ICommand
    {
        public event EventHandler? CanExecuteChanged { add { } remove { } }
        public bool CanExecute(object? parameter) => Acad.DocumentManager.MdiActiveDocument != null;
        public void Execute(object? parameter)
        {
            if (parameter is Autodesk.Windows.RibbonButton button && button.CommandParameter is string command) Acad.DocumentManager.MdiActiveDocument?.SendStringToExecute(command + " ", true, false, false);
        }
    }
    private static void AddButton(Forms.FlowLayoutPanel panel, string label, string command)
    {
        var button = new Forms.Button { Text = label, Height = 44, TextAlign = System.Drawing.ContentAlignment.MiddleLeft, Padding = new Forms.Padding(8, 4, 8, 4), Margin = new Forms.Padding(0, 3, 0, 3), FlatStyle = Forms.FlatStyle.Flat, BackColor = System.Drawing.Color.White };
        button.Click += (_, _) => { var doc = Acad.DocumentManager.MdiActiveDocument; if (doc != null) doc.SendStringToExecute(command + " ", true, false, false); };
        panel.Controls.Add(button);
    }
    private static Document Active() => Acad.DocumentManager.MdiActiveDocument ?? throw new InvalidOperationException("请先打开一个AutoCAD图纸。");
    private static void Guard(Action action)
    {
        try { action(); }
        catch (OperationCanceledException) { Acad.DocumentManager.MdiActiveDocument?.Editor.WriteMessage("\n清规AI：已取消，原始实体保持不变。\n"); }
        catch (Exception ex) { Acad.DocumentManager.MdiActiveDocument?.Editor.WriteMessage("\n清规AI失败：" + ex.Message + "\n"); Acad.ShowAlertDialog("清规AI\n" + ex.Message); }
    }
    private static void RequireMetres(Document doc)
    {
        if (doc.Database.Insunits != UnitsValue.Meters) throw new InvalidOperationException("当前图纸INSUNITS不是6（米）。为避免错误缩放，本次未写入。请确认/转换所有几何的实际单位后再运行；仅改单位标签不构成尺度转换。示例命令会新建米单位图纸。");
        if (doc.Database.TileMode == false) throw new InvalidOperationException("请切换到模型空间后运行。");
    }
    private static double AskPositive(Editor editor, string label, double value, bool zero = false)
    {
        var result = editor.GetDouble(new PromptDoubleOptions("\n" + label) { DefaultValue = value, UseDefaultValue = true, AllowNegative = false, AllowZero = zero });
        if (result.Status != PromptStatus.OK) throw new OperationCanceledException();
        if (!double.IsFinite(result.Value)) throw new InvalidOperationException("参数须为有限数。"); return result.Value;
    }
    private static JsonArray Point(Point3d p)
    {
        if (Math.Abs(p.Z) > 1e-7) throw new InvalidOperationException("当前版本只接受WCS XY平面（Z=0）的二维几何；未自动投影或丢弃高程。");
        return new JsonArray(p.X, p.Y);
    }
    private static List<Point3d> StraightPolyline(Polyline p, bool mustClosed)
    {
        if (p.Closed != mustClosed) throw new InvalidOperationException(mustClosed ? "边界须为闭合LWPOLYLINE。" : "道路中心线须为开放LWPOLYLINE。");
        if (!p.Normal.IsEqualTo(Vector3d.ZAxis, new Tolerance(1e-8, 1e-8))) throw new InvalidOperationException("不支持倾斜或反向法向的多段线。");
        var points = new List<Point3d>();
        for (int i = 0; i < p.NumberOfVertices; i++) { if (Math.Abs(p.GetBulgeAt(i)) > 1e-10) throw new InvalidOperationException("该命令暂不接受带圆弧段的多段线；请使用独立ARC（道路命令）或提供直线中心线。没有自动折线近似。" ); var pt = p.GetPoint3dAt(i); _ = Point(pt); points.Add(pt); }
        if (points.Count < (mustClosed ? 3 : 2)) throw new InvalidOperationException("多段线顶点不足。"); return points;
    }
    private static JsonArray RoadSegments(Entity entity)
    {
        if (entity is Line line) return new JsonArray(new JsonObject { ["type"] = "line", ["start"] = Point(line.StartPoint), ["end"] = Point(line.EndPoint) });
        if (entity is Arc arc)
        {
            if (!arc.Normal.IsEqualTo(Vector3d.ZAxis, new Tolerance(1e-8, 1e-8))) throw new InvalidOperationException("ARC须在正向WCS XY平面。");
            return new JsonArray(new JsonObject { ["type"] = "arc", ["center"] = Point(arc.Center), ["radius"] = arc.Radius, ["start_angle"] = arc.StartAngle, ["end_angle"] = arc.EndAngle, ["clockwise"] = false });
        }
        if (entity is Polyline polyline)
        {
            var points = StraightPolyline(polyline, false); var segments = new JsonArray();
            for (int i = 1; i < points.Count; i++) segments.Add(new JsonObject { ["type"] = "line", ["start"] = Point(points[i - 1]), ["end"] = Point(points[i]) }); return segments;
        }
        throw new InvalidOperationException("请选择LINE、ARC或开放的直线段LWPOLYLINE。");
    }
    [CommandMethod("QGROAD", CommandFlags.Modal)] public void Road() => Guard(() =>
    {
        var doc = Active(); RequireMetres(doc); var ed = doc.Editor;
        var selection = ed.GetSelection(new PromptSelectionOptions { MessageForAdding = "\n选择中心线LINE / ARC / 开放直线多段线：" }, new SelectionFilter(new[] { new TypedValue((int)DxfCode.Start, "LINE,ARC,LWPOLYLINE") }));
        if (selection.Status != PromptStatus.OK) throw new OperationCanceledException();
        var left = AskPositive(ed, "沿中心线方向的左侧宽度(m，教学初值)：", 8); var right = AskPositive(ed, "右侧宽度(m，教学初值)：", 8); var radius = AskPositive(ed, "路口转角半径(m，教学初值)：", 4);
        var roads = new JsonArray(); var sources = new List<string>();
        using (var tr = doc.Database.TransactionManager.StartTransaction())
        {
            foreach (var id in selection.Value.GetObjectIds()) { var ent = (Entity)tr.GetObject(id, OpenMode.ForRead); var index = roads.Count + 1; roads.Add(new JsonObject { ["id"] = "CAD-R" + index, ["name"] = "选择中心线" + index, ["segments"] = RoadSegments(ent), ["level"] = 0, ["direction"] = "segment_order", ["station_start"] = 0, ["junction_type"] = "at_grade" }); sources.Add(ent.Handle.ToString()); }
            tr.Commit();
        }
        var spec = new JsonObject { ["schema_version"] = "1.0", ["units"] = "m", ["coordinate_reference"] = "local_cartesian", ["source"] = "CAD_selected_centerlines_WCS_m", ["synthetic"] = false, ["normative_status"] = "user_parameters_not_compliance", ["width_semantics"] = "road_boundary", ["left_width"] = left, ["right_width"] = right, ["junction_radius"] = radius, ["qa_tolerance"] = 0.005, ["roads"] = roads, ["constraints"] = new JsonArray(), ["context_entities"] = new JsonArray() };
        var project = Engine.NewProject("road"); Engine.WriteJson(Path.Combine(project, "cad-source.json"), new { document = doc.Name, handles = sources, units = "m", unchanged = true });
        var job = Engine.Generate(project, "road", spec); Apply(doc, new Pending(new() { job }, project, false));
    });
    [CommandMethod("QGPARCEL", CommandFlags.Modal)] public void Parcel() => Guard(() =>
    {
        var doc = Active(); RequireMetres(doc); var ed = doc.Editor;
        var options = new PromptEntityOptions("\n选择场地闭合直线LWPOLYLINE边界："); options.SetRejectMessage("\n请选择闭合多段线。"); options.AddAllowedClass(typeof(Polyline), true);
        var boundary = ed.GetEntity(options); if (boundary.Status != PromptStatus.OK) throw new OperationCanceledException();
        JsonArray outer;
        using (var tr = doc.Database.TransactionManager.StartTransaction()) { outer = new JsonArray(StraightPolyline((Polyline)tr.GetObject(boundary.ObjectId, OpenMode.ForRead), true).Select(p => (JsonNode)Point(p)).ToArray()); tr.Commit(); }
        var selection = ed.GetSelection(new PromptSelectionOptions { MessageForAdding = "\n选择用于扣除道路用地的LINE / 开放直线多段线（回车不扣道路）：" }, new SelectionFilter(new[] { new TypedValue((int)DxfCode.Start, "LINE,LWPOLYLINE") }));
        if (selection.Status != PromptStatus.OK && selection.Status != PromptStatus.None) throw new OperationCanceledException();
        var roads = new JsonArray(); var handles = new List<string> { boundary.ObjectId.Handle.ToString() };
        if (selection.Status == PromptStatus.OK)
        {
            var width = AskPositive(ed, "所选道路统一总宽(m，由你确认，不是规范推荐值)：", 20);
            using var tr = doc.Database.TransactionManager.StartTransaction();
            foreach (var id in selection.Value.GetObjectIds())
            {
                if (id == boundary.ObjectId) throw new InvalidOperationException("边界不能同时作为道路中心线。");
                var ent = (Entity)tr.GetObject(id, OpenMode.ForRead); JsonArray points;
                if (ent is Line l) points = new JsonArray(Point(l.StartPoint), Point(l.EndPoint));
                else if (ent is Polyline p) points = new JsonArray(StraightPolyline(p, false).Select(x => (JsonNode)Point(x)).ToArray());
                else throw new InvalidOperationException("道路仅接受LINE或直线多段线。");
                roads.Add(new JsonObject { ["id"] = "R" + (roads.Count + 1), ["centerline"] = points, ["total_width_m"] = width }); handles.Add(ent.Handle.ToString());
            }
            tr.Commit();
        }
        var spec = new JsonObject { ["schema_version"] = "1.0", ["kind"] = "regulatory_parcels", ["mode"] = "roads", ["units"] = "m", ["coordinate_reference"] = "local_cartesian", ["synthetic"] = false, ["source"] = "CAD_selected_boundary_and_centerlines_WCS_m", ["normative_status"] = "user_parameters_not_compliance", ["boundary"] = new JsonObject { ["outer"] = outer, ["holes"] = new JsonArray() }, ["roads"] = roads, ["sliver_threshold_m2"] = 0, ["parcel_attributes"] = new JsonObject(), ["notes"] = "CAD选择的单一边界，不含保留孔洞；道路按统一总宽缓冲扣除，非道路路口工程边线；缺失指标保持待核。" };
        var project = Engine.NewProject("parcels"); Engine.WriteJson(Path.Combine(project, "cad-source.json"), new { document = doc.Name, handles, units = "m", unchanged = true });
        var job = Engine.Generate(project, "parcels", spec); Apply(doc, new Pending(new() { job }, project, false)); lastParcelSpec = job.Parameters;
    });
    [CommandMethod("QGROADDEMO", CommandFlags.Session)] public void RoadDemo() => Guard(() => NewExample("regulatory-road-plan", "road-demo"));
    [CommandMethod("QGPARCELDEMO", CommandFlags.Session)] public void ParcelDemo() => Guard(() => NewExample("regulatory-parcels", "parcel-demo"));
    private static void NewExample(string id, string name) { var project = Engine.NewProject(name); var job = Engine.Generate(project, name, caseId: id); if (job.Kind == "regulatory_parcels") lastParcelSpec = job.Parameters; NewDrawing(new Pending(new() { job }, project, false)); }
    [CommandMethod("QGSECTION", CommandFlags.Session)] public void Section() => Guard(() =>
    {
        using var form = new SectionForm(); if (AcadUi.ShowModalDialog(form) != Forms.DialogResult.OK) return;
        var project = Engine.NewProject("section"); var job = Engine.Generate(project, "section", form.BuildSpec()); NewDrawing(new Pending(new() { job }, project, false));
    });
    [CommandMethod("QGSPEC", CommandFlags.Session)] public void Spec() => Guard(() =>
    {
        using var dialog = new Forms.OpenFileDialog { Title = "清规AI｜选择参数JSON（将在新图中生成）", Filter = "规划参数 JSON (*.json)|*.json", CheckFileExists = true };
        if (dialog.ShowDialog() != Forms.DialogResult.OK) return;
        var source = JsonNode.Parse(File.ReadAllText(dialog.FileName)) as JsonObject ?? throw new InvalidOperationException("参数须为JSON对象。");
        var project = Engine.NewProject("json-input"); var job = Engine.Generate(project, "drawing", source); if (job.Kind == "regulatory_parcels") lastParcelSpec = job.Parameters; NewDrawing(new Pending(new() { job }, project, false));
    });
    [CommandMethod("QGSHEET", CommandFlags.Session)] public void Sheet() => Guard(() =>
    {
        if (lastParcelSpec == null || !File.Exists(lastParcelSpec)) throw new InvalidOperationException("请先运行QGPARCEL或QGPARCELDEMO生成地块；或用QGSPEC导入地块参数。");
        using var form = new Forms.Form { Text = "清规AI｜生成单地块图则", Width = 460, Height = 220, StartPosition = Forms.FormStartPosition.CenterParent };
        var label = new Forms.Label { Text = "输入最近一次地块成果的编号（例如P001）。\n将在新图生成模型空间图则，未提供的指标保持待核。", Dock = Forms.DockStyle.Top, Height = 65 };
        var input = new Forms.TextBox { Text = "P001", Dock = Forms.DockStyle.Top }; var ok = new Forms.Button { Text = "生成图则", Dock = Forms.DockStyle.Bottom, Height = 40, DialogResult = Forms.DialogResult.OK };
        form.Controls.Add(input); form.Controls.Add(label); form.Controls.Add(ok); form.AcceptButton = ok;
        if (AcadUi.ShowModalDialog(form) != Forms.DialogResult.OK) return;
        var project = Engine.NewProject("sheet"); var job = Engine.Generate(project, "sheet", sourceSpec: lastParcelSpec, parcel: input.Text.Trim()); NewDrawing(new Pending(new() { job }, project, false));
    });
    private static void NewDrawing(Pending job)
    {
        string template;
        try { template = HostApplicationServices.Current.FindFile("acadiso.dwt", Active().Database, FindFileHint.Default); }
        catch (AcException) { template = ""; } // Add("") asks AutoCAD for a new default drawing; never reuses the active drawing.
        var doc = Acad.DocumentManager.Add(template);
        using (doc.LockDocument()) { doc.Database.Insunits = UnitsValue.Meters; doc.Database.TileMode = true; }
        if (job.SelfTest)
        {
            if (Count(doc.Database) != 0) throw new InvalidOperationException("自测模板不是空模型空间，已停止自动撤销验收。新图保留，已有用户图纸未修改。");
            selfTestDocuments.Add(doc);
        }
        Acad.DocumentManager.MdiActiveDocument = doc; pending.Add(doc, job); doc.SendStringToExecute("QGAPPLY ", true, false, false);
    }
    [CommandMethod("QGAPPLY", CommandFlags.Modal | CommandFlags.NoHistory)] public void ApplyPending() => Guard(() =>
    {
        var doc = Active(); if (!pending.Remove(doc, out var job)) throw new InvalidOperationException("没有待落图任务；请从清规AI面板启动。当前图纸未修改。"); Apply(doc, job);
    });
    private static void Apply(Document doc, Pending pendingJob)
    {
        if (!ReferenceEquals(doc, Active())) throw new InvalidOperationException("目标图纸已经切换，已停止写入。");
        RequireMetres(doc); var entries = new List<object>(); var allIds = new List<ObjectId>();
        using (doc.LockDocument())
        using (var tr = doc.Database.TransactionManager.StartTransaction())
        {
            var target = (BlockTableRecord)tr.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(doc.Database), OpenMode.ForWrite);
            for (int i = 0; i < pendingJob.Jobs.Count; i++)
            {
                var job = pendingJob.Jobs[i]; using var input = new Database(false, true); input.DxfIn(job.Drawing, Path.Combine(job.Directory, "autocad-dxf-import.log"));
                if (input.Insunits != UnitsValue.Meters) throw new InvalidOperationException("DXF单位不为米，已中止整次落图。");
                var ids = new ObjectIdCollection();
                using (var sourceTr = input.TransactionManager.StartTransaction()) { var source = (BlockTableRecord)sourceTr.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(input), OpenMode.ForRead); foreach (ObjectId id in source) ids.Add(id); sourceTr.Commit(); }
                var mapping = new IdMapping(); input.WblockCloneObjects(ids, target.ObjectId, mapping, DuplicateRecordCloning.MangleName, false);
                var imported = new List<ObjectId>();
                foreach (IdPair pair in mapping) if (pair.IsCloned && pair.IsPrimary && tr.GetObject(pair.Value, OpenMode.ForRead) is Entity) imported.Add(pair.Value);
                if (imported.Count != ids.Count) throw new InvalidOperationException("CAD实体数量与DXF不一致，已中止整次落图。");
                if (pendingJob.SelfTest && i > 0) foreach (var id in imported) ((Entity)tr.GetObject(id, OpenMode.ForWrite)).TransformBy(Matrix3d.Displacement(new Vector3d(i * 400, 0, 0)));
                allIds.AddRange(imported); entries.Add(new { kind = job.Kind, source_dxf = job.Drawing, source_entity_count = ids.Count, imported_entity_count = imported.Count, handles = imported.Select(id => id.Handle.ToString()).ToArray() });
            }
            tr.Commit();
        }
        doc.Editor.Regen(); Zoom(doc);
        var receipt = new { product = Engine.Product, status = "native_entities_imported", process_id = Environment.ProcessId, target_document = doc.Name, units = "m", insertion_count = allIds.Count, source_geometry_preserved = true, imports = entries, output_directory = pendingJob.Project, undo = "single_modal_command_user_U", utc = DateTime.UtcNow };
        Engine.WriteJson(Path.Combine(pendingJob.Project, "native-cad-receipt.json"), receipt);
        doc.Editor.WriteMessage("\n清规AI：已写入 " + allIds.Count + " 个可编辑原生实体。源几何保留。U撤销本次；QSAVE保存。\n成果与参数：" + pendingJob.Project + "\n");
        if (pendingJob.SelfTest) SaveSelfTest(doc, pendingJob.Project, allIds.Count, entries);
    }
    private static void Zoom(Document doc)
    {
        try
        {
            doc.Database.UpdateExt(true); using var view = doc.Editor.GetCurrentView(); var min = doc.Database.Extmin; var max = doc.Database.Extmax;
            if (max.X > min.X && max.Y > min.Y) { view.CenterPoint = new Point2d((min.X + max.X) / 2, (min.Y + max.Y) / 2); view.Width = (max.X - min.X) * 1.15; view.Height = (max.Y - min.Y) * 1.15; view.ViewDirection = Vector3d.ZAxis; view.ViewTwist = 0; view.Target = Point3d.Origin; doc.Editor.SetCurrentView(view); }
        }
        catch { /* Drawing remains valid when the current view does not support extents zoom. */ }
    }
    [CommandMethod("QGSELFTEST", CommandFlags.Session)] public void SelfTest() => Guard(() =>
    {
        var project = Engine.NewProject("selftest");
        Engine.WriteJson(Path.Combine(Engine.Home, "last-selftest.json"), new { status = "computing", process_id = Environment.ProcessId, project, utc = DateTime.UtcNow });
        var jobs = new List<EngineJob> { Engine.Generate(project, "road", caseId: "regulatory-road-plan"), Engine.Generate(project, "section", caseId: "road-cross-section"), Engine.Generate(project, "parcels", caseId: "regulatory-parcels") };
        lastParcelSpec = jobs[^1].Parameters;
        NewDrawing(new Pending(jobs, project, true));
    });
    private static int Count(Database db)
    {
        using var tr = db.TransactionManager.StartTransaction(); var ms = (BlockTableRecord)tr.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForRead); var count = ms.Cast<ObjectId>().Count(); tr.Commit(); return count;
    }
    private static void SaveSelfTest(Document doc, string project, int importedCount, List<object> entries)
    {
        var dwg = Path.Combine(project, "qinggui-native-selftest.dwg"); if (File.Exists(dwg)) throw new InvalidOperationException("自测输出已存在，未覆盖。");
        doc.Database.SaveAs(dwg, DwgVersion.Current);
        int reopened; UnitsValue units;
        using (var recheck = new Database(false, true)) { recheck.ReadDwgFile(dwg, FileOpenMode.OpenForReadAndAllShare, true, ""); reopened = Count(recheck); units = recheck.Insunits; }
        // Only this command's own empty new drawing may enter the automatic undo probe.
        // The current three fixed examples are 34 road + 39 section + 14 parcel entities.
        var beforeUndo = Count(doc.Database);
        var ready = selfTestDocuments.Contains(doc) && ReferenceEquals(doc, Active()) && importedCount == 87 && reopened == importedCount && beforeUndo == importedCount && units == UnitsValue.Meters;
        var result = JsonSerializer.SerializeToNode(new { status = ready ? "pending_undo_redo" : "failed_before_undo", process_id = Environment.ProcessId, project, drawing = dwg, active_document = doc.Name, imported_count = importedCount, reopened_count = reopened, insunits = (int)units, secureload_readonly = Convert.ToInt32(Acad.GetSystemVariable("SECURELOAD")), imports = entries, before_undo = beforeUndo, after_undo = (int?)null, after_redo = (int?)null, undo_status = ready ? "queued_U_after_apply_command" : "not_run", utc = DateTime.UtcNow })!.AsObject();
        WriteSelfTestResult(result);
        doc.Editor.WriteMessage("\n清规AI自测：" + reopened + "个实体已保存并由独立数据库重开。结果：" + project + "\n");
        if (ready)
        {
            undoProbes.Add(doc, result);
            doc.CommandEnded += OnSelfTestCommandEnded;
            doc.CommandCancelled += OnSelfTestCommandInterrupted;
            doc.CommandFailed += OnSelfTestCommandInterrupted;
            // SendStringToExecute runs only after the enclosing QGAPPLY command has finished.
            // No custom command is inserted between U and REDO: even a NoUndoMarker
            // command can invalidate AutoCAD's redo branch.
            doc.SendStringToExecute("_.U\n", true, false, false);
        }
    }
    private static void WriteSelfTestResult(JsonObject result)
    {
        var project = result["project"]!.GetValue<string>();
        Engine.WriteJson(Path.Combine(project, "selftest-result.json"), result);
        Engine.WriteJson(Path.Combine(Engine.Home, "last-selftest.json"), result);
    }
    private static int CountInCommandEvent(Database db)
    {
        using var tr = db.TransactionManager.StartOpenCloseTransaction();
        var modelSpace = (BlockTableRecord)tr.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForRead);
        return modelSpace.Cast<ObjectId>().Count(); // Read-only; deliberately no Commit, lock, view operation or command.
    }
    private static void DetachUndoObserver(Document doc)
    {
        doc.CommandEnded -= OnSelfTestCommandEnded;
        doc.CommandCancelled -= OnSelfTestCommandInterrupted;
        doc.CommandFailed -= OnSelfTestCommandInterrupted;
        undoProbes.Remove(doc); selfTestDocuments.Remove(doc);
    }
    private static void OnSelfTestCommandEnded(object sender, CommandEventArgs e)
    {
        if (sender is not Document doc || !selfTestDocuments.Contains(doc) || !undoProbes.TryGetValue(doc, out var report)) return;
        var name = e.GlobalCommandName.TrimStart('_', '.').ToUpperInvariant();
        try
        {
            if (name is "U" or "UNDO" && report["after_undo"] == null)
            {
                var actual = CountInCommandEvent(doc.Database); report["after_undo"] = actual;
                if (actual != 0 || !ReferenceEquals(doc, Acad.DocumentManager.MdiActiveDocument))
                {
                    report["status"] = "failed_undo"; report["undo_status"] = actual != 0 ? "U_did_not_restore_empty_modelspace" : "target_document_changed";
                    WriteSelfTestResult(report); DetachUndoObserver(doc); return;
                }
                report["status"] = "undo_passed_pending_redo"; report["undo_status"] = "observed_0_after_U_command_ended";
                WriteSelfTestResult(report);
                doc.SendStringToExecute("_.REDO\n", true, false, false);
            }
            else if (name == "REDO" && report["after_undo"] != null)
            {
                var actual = CountInCommandEvent(doc.Database); report["after_redo"] = actual;
                var passed = report["after_undo"]!.GetValue<int>() == 0 && actual == report["before_undo"]!.GetValue<int>() && actual == 87;
                report["status"] = passed ? "passed_native_import_save_reopen_undo_redo" : "failed_redo";
                report["undo_status"] = passed ? "observed_87_to_0_to_87_command_ended" : "REDO_did_not_restore_expected_entities";
                report["completed_utc"] = DateTime.UtcNow;
                WriteSelfTestResult(report); DetachUndoObserver(doc);
                doc.Editor.WriteMessage("\n清规AI：真实U/REDO实体数 " + report["before_undo"] + " → " + report["after_undo"] + " → " + actual + "。验收" + (passed ? "通过" : "未通过") + "。\n");
            }
        }
        catch (Exception ex)
        {
            report["status"] = "failed_undo_observer"; report["observer_error"] = ex.Message;
            DetachUndoObserver(doc); WriteSelfTestResult(report);
        }
    }
    private static void OnSelfTestCommandInterrupted(object sender, CommandEventArgs e)
    {
        if (sender is not Document doc || !undoProbes.TryGetValue(doc, out var report)) return;
        var name = e.GlobalCommandName.TrimStart('_', '.').ToUpperInvariant();
        if (name is not ("U" or "UNDO" or "REDO")) return;
        report["status"] = "failed_command_interrupted"; report["interrupted_command"] = name;
        DetachUndoObserver(doc);
        WriteSelfTestResult(report);
    }
}
