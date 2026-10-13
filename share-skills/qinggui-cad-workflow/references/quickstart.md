# 第一堂课：先跑通，再换真实场地

安装 Starter 后重启 AI 客户端。在 Codex 中点名 `$qinggui-cad-workflow`，Claude Code 中用 `/qinggui-cad-workflow`，OpenClaw 中明确要求使用 `qinggui-cad-workflow`（须在本地可执行工具的环境）。

推荐首条提示词：

> 使用 qinggui-cad-workflow，先检查本地清规AI引擎是否可调用。在新的成果目录运行合成控规案例，生成道路平面、横断面、地块和 P001 图则。保持所有教学假设标记，列出错误、缺失指标和输出文件。本次先导出DXF，不操作当前CAD图纸。

运行示例：先将 S 改为本技能实际安装目录，将 OUT 改为新成果根目录。其余变量从安装配置读取。

```powershell
$S = '本技能的实际绝对目录'
$meta = Get-Content -Raw -Encoding UTF8 -LiteralPath "$S/local-engine.json" | ConvertFrom-Json
$P = $meta.python
$ENGINE = $meta.root
$OUT = '本次新成果根目录的绝对路径'
& $P -B "$S/scripts/run.py" cases
& $P -B "$S/scripts/run.py" generate --case regulatory-road-plan --out "$OUT/roads"
& $P -B "$S/scripts/run.py" generate --case road-cross-section --out "$OUT/section"
& $P -B "$S/scripts/run.py" validate --spec "$ENGINE/examples/regulatory-parcels.json"
& $P -B "$S/scripts/run.py" generate --spec "$ENGINE/examples/regulatory-parcels.json" --out "$OUT/parcels"
& $P -B "$S/scripts/run.py" sheet --spec "$ENGINE/examples/regulatory-parcels.json" --parcel P001 --out "$OUT/sheet-P001"
```

先核实示例文件存在；如果版本更换，读取 cases 与 examples 后使用真实文件名，不臆造。OUT 下各子目录必须尚不存在。以上三个例子用于分别测试模块，并不是同一真实场地的完整设计。

真实场地第二条提示词：

> 使用 qinggui-cad-workflow。项目为北京大钟寺，以我提供的DWG和任务书为依据。先读取单位、坐标、研究边界、保留要素与外部接点；缺失项保留待核验。采用半自动方式，提出3个可比较的中心线草案，说明通达性、保留冲突和宽度假设；我选定后再细化路口、断面、地块。不要把合成案例当成大钟寺底图。

进入 CAD：首次可在空白测试图运行 QGROADDEMO / QGPARCELDEMO；QGSECTION 打开断面参数窗。QGSPEC 是人工选择参数JSON的文件桥。已有任务授权并指定新图时，也可使用 CLI 的 --cad-new；实际CAD连接或保存失败时保留DXF结果和错误，不宣称DWG成功。
