using System.Text.Json.Nodes;
using Forms = System.Windows.Forms;

namespace QingGuiAI.Cad;

internal sealed class SectionForm : Forms.Form
{
    private readonly Forms.DataGridView grid = new() { Dock = Forms.DockStyle.Fill, AllowUserToAddRows = false, AllowUserToDeleteRows = false, AutoSizeColumnsMode = Forms.DataGridViewAutoSizeColumnsMode.Fill, RowHeadersVisible = false };
    private readonly Forms.NumericUpDown elevation = new() { DecimalPlaces = 3, Minimum = -10000, Maximum = 100000, Value = 100, Width = 120 };
    internal SectionForm()
    {
        Text = "清规AI｜道路横断面参数"; Width = 840; Height = 475; StartPosition = Forms.FormStartPosition.CenterParent; MinimizeBox = false; MaximizeBox = false;
        var top = new Forms.FlowLayoutPanel { Dock = Forms.DockStyle.Top, Height = 80, Padding = new Forms.Padding(12) };
        top.Controls.Add(new Forms.Label { Text = "基准高程(m)", AutoSize = true, Margin = new Forms.Padding(3, 8, 3, 3) }); top.Controls.Add(elevation);
        top.Controls.Add(new Forms.Label { Text = "从中心向外排序；负横坡向外下降。以下初始值仅为教学参数。\n结果在新图中按真实米单位绘制，不构成规范校核。", AutoSize = true });
        grid.Columns.Add(new Forms.DataGridViewTextBoxColumn { Name = "side", HeaderText = "侧别", ReadOnly = true });
        grid.Columns.Add(new Forms.DataGridViewTextBoxColumn { Name = "order", HeaderText = "顺序", ReadOnly = true });
        grid.Columns.Add(new Forms.DataGridViewComboBoxColumn { Name = "role", HeaderText = "组成", DataSource = new[] { "车行", "骑行", "步行", "绿带", "分隔" } });
        grid.Columns.Add("width", "宽度(m)"); grid.Columns.Add("slope", "横坡(%)");
        foreach (Forms.DataGridViewColumn column in grid.Columns) column.SortMode = Forms.DataGridViewColumnSortMode.NotSortable;
        foreach (var side in new[] { "左", "右" }) { grid.Rows.Add(side, 1, "车行", 7m, -2m); grid.Rows.Add(side, 2, side == "左" ? "骑行" : "绿带", 2m, -1.5m); grid.Rows.Add(side, 3, "步行", 3m, -1m); }
        var bottom = new Forms.FlowLayoutPanel { Dock = Forms.DockStyle.Bottom, Height = 54, FlowDirection = Forms.FlowDirection.RightToLeft, Padding = new Forms.Padding(10) };
        var ok = new Forms.Button { Text = "新建图纸并绘制", Width = 155 }; ok.Click += (_, _) => { try { _ = BuildSpec(); DialogResult = Forms.DialogResult.OK; Close(); } catch (Exception ex) { Forms.MessageBox.Show(this, ex.Message, "请修正参数"); } };
        var cancel = new Forms.Button { Text = "取消", DialogResult = Forms.DialogResult.Cancel };
        bottom.Controls.Add(ok); bottom.Controls.Add(cancel); CancelButton = cancel;
        Controls.Add(grid); Controls.Add(bottom); Controls.Add(top);
    }
    internal JsonObject BuildSpec()
    {
        grid.EndEdit();
        var roles = new Dictionary<string, string> { ["车行"] = "carriageway", ["骑行"] = "cycleway", ["步行"] = "sidewalk", ["绿带"] = "greenbelt", ["分隔"] = "median" };
        var parts = new JsonArray();
        foreach (Forms.DataGridViewRow row in grid.Rows)
        {
            if (!double.TryParse(Convert.ToString(row.Cells["width"].Value), out var width) || !double.IsFinite(width) || width <= 0 || width > 10000) throw new InvalidOperationException("宽度必须为0至10000之间的正数。");
            if (!double.TryParse(Convert.ToString(row.Cells["slope"].Value), out var slope) || !double.IsFinite(slope) || Math.Abs(slope) > 100) throw new InvalidOperationException("横坡须为-100至100之间的有限数。");
            var side = Convert.ToString(row.Cells["side"].Value) == "左" ? "left" : "right";
            var order = Convert.ToInt32(row.Cells["order"].Value) - 1;
            parts.Add(new JsonObject { ["id"] = side + "-" + order, ["side"] = side, ["order"] = order, ["role"] = roles[Convert.ToString(row.Cells["role"].Value)!], ["width"] = width, ["slope_percent"] = slope });
        }
        return new JsonObject { ["schema_version"] = "1.0", ["kind"] = "road_cross_section", ["units"] = "m", ["coordinate_reference"] = "local_cartesian", ["reference_elevation"] = (double)elevation.Value, ["elevation_reference"] = "user_confirmed_local_datum", ["slope_convention"] = "outward_rise_percent", ["source"] = "user_entered_native_CAD_dialog", ["normative_status"] = "user_parameters_not_compliance", ["components"] = parts };
    }
}
