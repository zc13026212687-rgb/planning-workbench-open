# 原创地块与控制指标模块：参数、输出及证据边界

实现：`app/parcels.py`。该模块独立实现平面多边形运算、用户指标乘法与可编辑图则，不使用第三方规划软件的代码、资源、规则表或图框。几何通过不等于法定规划或工程设计审查通过。

## 1. 输入契约

输入必须是 JSON 对象。API 和 CLI 拒绝 NaN、Infinity、非 JSON 值；输入 JSON 当前限制为 1,000,000 个字符。未知顶层元数据被保留，但不自动变成计算规则。

| 字段 | 要求与含义 |
|---|---|
| `kind` | 必须为 `regulatory_parcels` |
| `units` | 必须为 `m`，所有输入坐标与道路总宽均以米计 |
| `coordinate_reference` | 必须为 `local_cartesian`；不是 WGS84、经纬度或自动配准坐标 |
| `mode` | 必须明确为 `roads` 或 `explicit` |
| `boundary` | 必填有效场地多边形，支持孔洞 |
| `roads` | 可选道路列表，最多 200 条；两种模式均可提供 |
| `parcels` | `explicit` 模式必填，1–1000 块显式地块；`roads` 模式不接受非空此字段 |
| `parcel_attributes` | `roads` 模式可选，生成地块 ID 到指标对象的映射；不得引用不存在的 ID |
| `attribute_geometry_bindings` | 可选，地块 ID 到 64 位小写 SHA-256 的映射，详见第 4 节 |
| `sliver_threshold_m2` | 可选非负有限数，默认 10；只用于提示小地块，不是规划限值，也不触发删除 |
| `schema_version`、`synthetic`、`source`、`notes`、`normative_status` | 可保留的来源说明；引擎不会把这些文字视为经过验证的事实或法定批准 |

### 多边形

接受外环点列表，或者以下对象：

```json
{
  "outer": [[0, 0], [100, 0], [100, 100], [0, 100]],
  "holes": [[[40, 40], [60, 40], [60, 60], [40, 60]]]
}
```

每环 3–10000 个输入点，每点恰好两个有限数，坐标绝对值不超过 10,000,000。允许末点重复首点作为闭合表示；不允许连续重复点。必须至少有三个不同顶点且有正面积。自交、孔洞越界、孔洞相交等非法拓扑直接报错，**不会调用 `buffer(0)`、吸附或其他静默修复**。布尔值不是数值。

边界孔洞作为排除空间，既不计入有效边界面积，也不进入占比的分母。不据此判断其土地用途、权属或保护要求。

## 2. 两种地块来源

### `roads`：由道路计算走廊分割

```json
{
  "kind": "regulatory_parcels",
  "mode": "roads",
  "units": "m",
  "coordinate_reference": "local_cartesian",
  "boundary": [[0, 0], [100, 0], [100, 100], [0, 100]],
  "roads": [
    {"id": "R1", "centerline": [[50, 0], [50, 100]], "total_width_m": 10}
  ],
  "parcel_attributes": {
    "P001": {"land_use_code": "TEACH-A", "land_use_name": "课堂假设", "far_max": 1.5}
  }
}
```

每条道路具有唯一非空 `id`、2–10000 个点的 `centerline` 和正有限的 `total_width_m`（不超过 1,000,000）。中心线不得零长、自交或含连续重复点。按半宽缓冲，端部为平头，折点为斜接，斜接限制为 5；随后裁到有效边界，并对所有道路走廊求并集。道路与有效边界无面积交集时报错。

计算顺序为 **道路并集 → 从有效边界扣除 → 保留全部正面积地块**。交叉路口共享面积只计一次。允许不同道路 ID 的走廊重叠，但不能重复道路 ID。这些走廊没有交叉口圆角、展宽、立交、排水或交通组织设计含义。

生成 ID 为 `P001`、`P002` 等：按地块质心由北向南，同纬由西向东，再以几何排序打破并列。编号不是永久地籍标识；几何改变后可能重排，指标必须使用第 4 节的几何绑定防止错配。

### `explicit`：校核已有地块

```json
{
  "kind": "regulatory_parcels",
  "mode": "explicit",
  "units": "m",
  "coordinate_reference": "local_cartesian",
  "boundary": [[0, 0], [100, 0], [100, 100], [0, 100]],
  "parcels": [
    {"id": "A-01", "polygon": [[0, 0], [50, 0], [50, 100], [0, 100]],
     "attributes": {"land_use_name": "课堂假设", "far_max": 1.5}}
  ]
}
```

每块有唯一非空 `id`、`polygon` 和可选 `attributes`。地块可以共边，但面积不能重叠；不得越出有效边界、填入边界孔洞，或侵占输入道路的计算走廊。未覆盖面积单列为 `unallocated_area_m2`，不会自动补成地块。此模式不接受非空 `parcel_attributes`，指标必须放在每块的 `attributes`。

## 3. 指标：只计算用户声明值

| 属性 | 输入限制 | 衍生计算 |
|---|---|---|
| `land_use_code` | 1–80 个可打印字符 | 原样保留，不验证其是否法定分类代码 |
| `land_use_name` | 1–80 个可打印字符 | 原样保留 |
| `far_max` | 非负有限数，不超过 10,000,000 | `max_gfa_m2 = area_m2 × far_max` |
| `coverage_max_pct` | 0–100 | `max_building_footprint_m2 = area_m2 × coverage_max_pct / 100` |
| `green_min_pct` | 0–100 | `min_green_area_m2 = area_m2 × green_min_pct / 100` |
| `height_max_m` | 非负有限数，不超过 10,000,000 | 仅记录高度上限，不推导建筑层数或容量 |

所有属性可缺失或为 `null`。缺失值保留为空，不用 0 代替、不填入规范默认值。未知属性名称报错，避免拼写错误被忽略。`max_gfa_m2` 是用户上限条件下的乘法结果，**不是实际建筑面积，也不证明这个强度能够实现**。

## 4. 首次赋值与几何绑定

首次不含 `attribute_geometry_bindings` 的明确参数输入可以生成，非空指标标记为 `caller_assigned`。这是调用者当前赋值的声明，不代表已确认长期归属。

结果提供：

```python
result["geometry_bindings"]             # {"P001": "...64位sha256..."}
result["geometry_binding_algorithm"]    # sha256_normalized_wkb_2d_le_v1
result["parcels"][0]["geometry_sha256"]
result["parcels"][0]["data"]["attribute_binding_status"]
```

签名使用规范化二维 WKB、固定小端字节序及 SHA-256。外环和孔洞起点、方向、孔洞顺序被规范化。不以面积或视觉相近判断同一块；不进行坐标取整。新增共线点、极小数值改变也可能要求重新确认。

明确确认当前归属后：

```python
from app import parcels

preview = parcels.generate(spec)
# 此处由调用端展示当前地块及指标，并取得明确的归属确认。
bound_spec = parcels.bind_attributes(spec, preview)
# 保存 bound_spec，而不是继续保存未绑定的原 spec。
```

`bind_attributes` 返回新副本，核对当前参数的几何和指标都与确认预览一致。旧预览、单块图则或指标已变化的预览会被拒绝。

输入一旦包含绑定字段，空 `{}` 也表示启用绑定校验。所有非空指标（包括 `far_max=0`）必须具有匹配签名，否则报 `attribute_binding_mismatch`，没有可导出的实体。仅改指标而不改几何可以保留绑定；改路宽、边界或地块形状后必须重新确认归属，不能自动删除或刷新绑定绕过检查。

重新确认流程：保存旧版 → 复制一个去掉绑定字段的候选版本 → 重新生成并展示候选地块和指标 → 明确确认或调整归属 → 调用 `bind_attributes` → 保存新版本。绑定失败时结果仍提供当前 `geometry_bindings` 供诊断，不表示调用端可以自动接受它们。

## 5. 返回结构与面积校核

`generate(spec)` 返回 `entities`、`bounds`、`report`、`metrics`、`spec`、`parcels`、`geometry_bindings`。

- `report.errors` 是阻断问题；`warnings` 是适用范围、缺失指标等提示；`checks` 是已实际执行的几何和算术检查。
- `entities` 是具有唯一 ID 的可编辑 `polyline`／`line`／`text` 对象，坐标为米。闭合孔洞使用独立图层与环角色保留。
- `parcels` 每项含 `id`、`polygon`、`geometry_sha256`、`data`；`data` 含面积、指标、衍生乘法及绑定状态。
- `bounds` 是 `[minx, miny, maxx, maxy]`。

关键指标：`boundary_gross_area_m2` 为外环面积，`boundary_holes_area_m2` 为边界孔洞面积，`boundary_area_m2` 为两者相减。每块 `area_ha = area_m2 / 10000`，`share_of_boundary_pct = area_m2 / boundary_area_m2 × 100`。

面积守恒校核为：

```text
有效边界 = 道路并集 + 地块面积合计 + 未分配面积
```

`area_conservation_residual_m2` 记录残差。容差为 `max(1e-7, 有效边界面积 × 1e-10)`，只属于数值计算容差，不是规划验收阈值。`indicator_compliance` 恒为 `not_evaluated`，不能改读为“符合规范”。

## 6. DXF、CSV、JSON 与独立图则

```python
result = parcels.generate(spec)
parcels.export_parcels_dxf(result, new_dxf_path)
parcels.export_parcels_csv(result, new_csv_path)
parcels.export_parcels_json(result, new_json_path)
sheet = parcels.build_control_sheet(result, "P001")
parcels.export_parcels_dxf(sheet, new_sheet_dxf_path)
```

导出拒绝覆盖已有文件，存在 `report.errors` 时拒绝导出。DXF 为 R2013、`INSUNITS=6`（米），使用可编辑多段线、线和 TEXT，含原始参数 XRECORD。CSV 为 UTF-8 BOM，空值保持空白；公式样式的用户文字以前置单引号作为文本导出，原字符串保留在 JSON。JSON 明确 `local_cartesian`、`is_geojson=false`，不冒充 RFC 7946 GeoJSON。

独立图则是**以米为图框单位的 A3 横向模型空间版面**：`bounds=[0,0,0.420,0.297]`，实际内框有 0.01 米页边距。图内地块经过等比例缩小，`metrics.map_scale_denominator` 记录 `1:n` 中的 `n`；`metrics.sheet_size_m` 记录名义纸面大小。图则的模型坐标不是原场地工程坐标。打印时应按完整 420×297 毫米纸面对应 0.420×0.297 模型米设置窗口和比例，不能根据内框自动“布满图纸”后仍宣称比例精确；当前没有自动配置打印机、布局或视口。

`sheet.data` 保留原始地块坐标和指标；`sheet.spec` 仍是总图源参数，**没有 `spec.parcel_id`**。所选编号应读取 `sheet.data.id`。图则 JSON 保留该块签名。图中文字为普通 TEXT，不是关联式尺寸约束；字框使用保守估算，最终字体与出图效果需在 CAD 中复核。

Web 成果包中 `sheet-index.json` 记录所选编号、签名、图框单位、比例与对应 `sheet-NNN.json` 完整图则结果。CLI 单图则会额外输出 `sheet-metadata.json`，避免仅凭总图 `parameters.json` 误判比例和所选地块。

## 7. CLI 与失败记录

```powershell
.\.venv\Scripts\python.exe planning_cli.py validate --spec examples\regulatory-parcels.json
.\.venv\Scripts\python.exe planning_cli.py generate --spec examples\regulatory-parcels.json --out work\parcel-run-new
.\.venv\Scripts\python.exe planning_cli.py sheet --spec examples\regulatory-parcels.json --parcel P003 --out work\sheet-run-new
```

输出目录必须不存在；使用新目录保留版本。默认生成 DXF，不调用 CAD。只有明确添加 `--cad-new` 才请求新建独立 CAD 图纸；桥仅管理自己创建的图纸。退出码：0 成功，1 执行或部分导出失败，2 校核失败，3 可编辑文件成功而 CAD 步骤失败或状态未知。`receipt.json` 记录状态与文件清单；总图完整包另有 `export-status.json` 记录阶段、完成文件与失败原因。失败时保留已有文件用于诊断，不宣称 CAD 副作用已经撤销。

Web API 的 CAD 导出使用共享桥允许的 `data/cad` 路径保存原生 DWG，再完整复制到本次成果目录；收据分别记录源 DWG 和包内 DWG 路径。DXF 成功而 CAD 失败返回 `partial_success`，不是完整 CAD 成功。压缩失败不提供可下载的成功链接。

## 8. 当前范围限制

这是控规地块和指标工作流的可审计计算基础，不是其他商业插件的完整复刻。尚未实现地籍拓扑、法定分类校验、建筑退界、消防、日照、限高论证、道路纵断面、真实地形、公共服务容量或自动合规结论。道路为等宽平面缓冲，生成地块上限 1000；CAD 单次实体限制为 5000，导出包会在写图之前校验这一限制。小地块全部保留，图内放不下的文字会省略并报告，指标仍在表格中。

附带 240×180 米案例完全为原创合成数据，含 30×30 米保留空间孔洞；有效边界 42,300 m²、道路并集 7,120 m²、四地块合计 35,180 m²。它没有大钟寺实测、审批或现状依据。
