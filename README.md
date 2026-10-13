# 清规AI · PlanningWorkbench Open 0.2.0

面向规划本科教学的独立开源 CAD 工作台：给定场地边界、道路几何和明确控制指标，生成可编辑道路、地块、指标表和单地块图则。支持本地交互页、命令行、Codex Skill 和 stdio MCP；确定性计算与 DXF 导出不需要模型 API。

**0.2.0 新增地块与图则完整操作页、地块拓扑与指标引擎、四工具 MCP、独立控规技能。** 地块例子是原创 240×180 米场地，含 30×30 米孔洞、两条道路和四个地块；它是 synthetic 教学输入，不代表北京大钟寺实测底图、法定红线或已批控制指标。源码采用 MIT。项目仓库：https://github.com/zc13026212687-rgb/planning-workbench-open 。

完整源码包包含下述网页和桌面源码；独立技能/MCP 包只包含计算引擎、CLI、MCP、技能、例子与文档，使用“命令行生成与校核”和“安装新技能与连接 MCP”即可。

## 获取源码与版本包

- **Windows 普通使用者优先下载 [最新版本中的 QingGui-AI-0.2.0-windows-x64.zip](https://github.com/zc13026212687-rgb/planning-workbench-open/releases/latest)**：完整解压，双击 `安装清规AI.cmd` 创建桌面入口，再打开“清规AI · PlanningWorkbench Open 0.2.0”。便携包已包含独立 Python、依赖和完整界面，不需另装 Python、Node 或 .NET。
- 使用 Git：`git clone https://github.com/zc13026212687-rgb/planning-workbench-open.git`
- 或在本页 **Code → Download ZIP** 获取源码。
- [Releases](https://github.com/zc13026212687-rgb/planning-workbench-open/releases) 提供完整源码包和独立技能/MCP 包。

下载后先解压并进入项目根目录，再执行下列安装步骤。AutoCAD 需要自行安装；确定性计算与 DXF 导出可独立运行。

便携版适用于 Windows 10/11 x64；源码版仍需准备依赖。桌面快捷方式启动本机浏览器工作台，提供道路平面、道路横断面、地块与图则三个入口。操作和构建步骤见 [Windows 便携版说明](docs/windows-portable.md)，本次验收见 [便携发行说明](docs/release-qinggui-0.2.0.md)，完整功能状态见 [功能证据与验收清单](docs/functional-coverage.md)。移动目录后重跑安装入口创建新快捷方式；已安装的技能另用 `install_skills.py --relocate-from 旧目录` 迁移和备份。

## 从新操作页开始

以下环境准备针对源码包；便携版可直接打开上述入口。源码包首次使用在项目根目录准备 Python 3.14 环境：

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
```

随后双击 **启动地块与图则.cmd**。旧启动文件名保留兼容，窗口内统一显示“清规AI”。该入口打开本机 `/regulatory` 页面；这一页使用原生 HTML，不需要安装 Node 或构建桌面宿主。常规运行以项目 `.venv` 为解释器；本机另行配置的解释器定位文件不会进入公开包。

页面顶部提供“道路平面／道路横断面／地块与图则”入口。地块页按“参数 → 预览 → 指标归属 → 校核 → 成果”操作：

1. 加载原创案例，检查边界、孔洞、单位与道路总宽。修改后重新生成，旧预览会标明待更新。
2. 点击地块查看面积、输入用地说明和控制指标。缺失值保持为空；计容面积上限只按输入容积率计算，不等于实际建筑面积。
3. 查看总图、单地块图则与面积平衡。已绑定指标的地块几何改变时，需要重新核对指标归属，不能按编号直接沿用。
4. 校核无阻断错误后导出成果 ZIP：原生可编辑 DXF、地块 CSV/JSON、参数、质量报告与逐地块图则。默认例子得到四张图则，其他输入按实际地块数生成。
5. 需要 CAD 时使用“CAD 新图落图并保存”。该操作使用 AutoCAD ActiveX 新建独立图纸并保存 DWG，结果以实际回读为准。

完整桌面工作台仍保留道路、横断面、资料检索与模型接口。源码包不含已编译桌面程序；需要它时按 `desktop/Setup.ps1` 的依赖检查与构建流程准备 Node、.NET 与 WebView2。新地块页和 CLI 不依赖桌面构建。

## 命令行生成与校核

```powershell
.\.venv\Scripts\python.exe planning_cli.py cases
.\.venv\Scripts\python.exe planning_cli.py validate --spec examples/regulatory-parcels.json
.\.venv\Scripts\python.exe planning_cli.py generate --spec examples/regulatory-parcels.json --out data/parcel-lesson-01
.\.venv\Scripts\python.exe planning_cli.py sheet --spec examples/regulatory-parcels.json --parcel P001 --out data/parcel-sheet-01
.\.venv\Scripts\python.exe planning_cli.py generate --case regulatory-road-plan --variant oblique-t60 --out data/road-lesson-01
.\.venv\Scripts\python.exe planning_cli.py generate --case road-cross-section --out data/section-lesson-01
```

各输出目录必须是新的。已明确要求 CAD 落图时，可为 `generate` 或 `sheet` 加 `--cad-new`；未加时只输出文件。COM 写入需要 Windows、可用的 AutoCAD 和 pywin32；本轮真实落图验收环境为 AutoCAD 2025，其他 CAD 产品或版本需另行验证。几何通过不等于规划合规，错误方案不会输出为合格 DXF。

道路平面支持明确范围内的直线、独立真圆弧及同标高直路 T/X 口；横断面根据组成宽度、横坡和基准高程累加。地块的道路计算走廊用于面切分，不自动代表法定红线，也不替代道路平面模块的路口设计。参数结构见 [地块输入说明](docs/regulatory-schema.md)，适用边界见 [原创实现范围](docs/open-implementation.md) 与 [几何限制](docs/geometry-limitations.md)。

## 安装新技能与连接 MCP

仅安装新增技能，不改动原来的三个技能入口：

```powershell
.\.venv\Scripts\python.exe install_skills.py --only planning-cad-regulatory-suite
```

安装器默认写入当前用户的 `.agents/skills/planning-cad-regulatory-suite`。Windows 下优先使用项目现存的 `runtime/python.exe`，没有时使用 `.venv/Scripts/python.exe`；其他系统仍使用 `.venv/bin/python`。如使用已有虚拟环境，可加 `--python 解释器完整路径`；该本机定位信息只保存在安装后的 wrapper 中。安装器拒绝覆盖其他引擎来源的同名技能。新开会话后可使用：

```text
使用 $planning-cad-regulatory-suite。
读取原创 regulatory-parcels 案例，校核边界、孔洞、地块指标和面积平衡。
生成新的 DXF、地块表和四张图则，并解释哪些指标只是课堂假设。
```

`install_skills.py --only` 支持多个公开技能名；省略时选择所有四个入口。已有旧引擎技能需要保留时，使用上面的单技能命令。MCP 是单独的客户端连接配置，安装 Skill 不会自动注册它。

本项目的 stdio MCP 提供四个真实工具：`planning_cases`、`planning_validate`、`planning_export`、`planning_export_control_sheet`。详情及客户端配置见 [MCP 使用说明](docs/mcp-usage.md)。MCP 默认只计算和导出；CAD 新图操作要求 `cad_new=true` 与 `confirm_cad_new=true`。目前未声称所有 MCP 客户端都已兼容验收。

## 测试与公开源码包

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe build_release.py
```

打包器生成完整源码包与独立技能/MCP 包，写入逐文件 SHA-256 清单，并回读压缩包校验。白名单包含原创源码、合成例子、技能、测试、公开来源元数据与文档；排除用户资料、课堂底图、商业程序、注册材料、`.venv`、`node_modules`、`data`、`evidence`、编译产物和本机绝对用户路径。项目根旧 `source-manifest.json` 不进入包，发行包生成新的清单。

本项目围绕控规常见任务独立实现计算与交互。对商业产品的本机菜单观察属于功能需求调查，未完成其付费流程对照、行为等价性或性能评测；不宣称完整复刻湘源。规范条目、真实场地测绘和授权资料仍需独立核实。详见 [0.2.0 更新](docs/release-0.2.0.md) 和 [实现及开源边界](docs/open-implementation.md)。
