# 清规AI · PlanningWorkbench Open

**让AI把规划参数变成可编辑的CAD成果。** 面向规划本科教学的原创开源工具：道路平面、路表横断面、地块切分、指标表、单地块图则，以及可追溯的校核和出图流程。

本次 **Starter 0.3.1** 将已实战的四个专业技能、一个完整流程技能、确定性引擎与 **AutoCAD Native 0.3.0** 插件整理成可移植套件。源码 MIT；几何计算和DXF导出无需模型API。AI客户端、AutoCAD及其授权由使用者自行准备。

## 下载、部署、开始画图

**[下载 Windows 完整入门包](https://github.com/zc13026212687-rgb/planning-workbench-open/releases/download/v0.3.1/QingGuiAI-Starter-0.3.1-windows-x64.zip)** · [全部发行文件](https://github.com/zc13026212687-rgb/planning-workbench-open/releases/tag/v0.3.1)

1. 完整解压 Starter ZIP，双击 **Install-Codex.cmd**。Claude Code / OpenClaw 用户选择对应命名的入口。
2. 查看部署回执，重启AI客户端会话，输入下面的示例。原生插件安装到稳定位置，运行时已内置；无需手动pip安装。
3. 在 AutoCAD 2025 输入 **QGOPEN** 打开面板；**QGSPEC** 选择AI产出的参数JSON，或用 **QGROAD** 人工选择中心线绘图。

> 使用 qinggui-cad-workflow，检查清规AI引擎是否可用。在新目录生成合成道路平面、横断面、地块和P001图则，列出校核、缺失指标和成果。本次先导出DXF。

完整安装要求、MCP接入、配置冲突与移除方法见 **[安装说明](docs/starter-installation.md)**。原生命令和构建入口见 [CAD插件](cad-native/README.md)。GitHub的 **Code → Download ZIP** 是源码，未包含大型运行时安装包；普通使用者请选择上面的Starter。

## 五个技能各做什么

| 技能 | 用途 |
|---|---|
| `qinggui-cad-workflow` | 串联资料核验、三种协作方式、道路—断面—地块—图则与验收 |
| `beijing-regulatory-cad` | 组织单位、坐标、依据、保留条件和缺项 |
| `planning-cad-road-plan` | 已知中心线与宽度 → 道路边界、真圆弧、限定T/X路口 |
| `planning-cad-cross-section` | 组件宽度、横坡、高程 → 道路路表横断面 |
| `planning-cad-regulatory-suite` | 边界与道路走廊 → 地块、面积、指标与单地块图则 |

技能负责让AI正确组织任务；引擎进行可复算的几何计算；原生插件在CAD生成标准可编辑实体。CLI与四工具stdio MCP也可以独立导出DXF。MCP新图通道与原生选线命令是不同入口，MCP不自动读取CAD当前选择集。

## 课堂里怎样用

学生可以选择 **AI提出候选方案、AI给方案后人工选择、自己画中心线再辅助细化**。道路细化后检查断面总宽，地块切分后检查面积和指标归属，最后在CAD回读并保存成果。具体步骤见 [控规课程流程](docs/teaching-workflow.md) 和技能内的 [第一堂课练习](share-skills/qinggui-cad-workflow/references/quickstart.md)。

公开示例是合成教学数据，不包含私人课程底图，也不代表北京大钟寺实测范围、已批红线或法定指标。真实项目使用自己有权使用的资料，完成定标、边界与依据核对后再设计。一级/二级/三级是可讨论的课程分级，不能自动替代法定道路等级。

## 已验证什么，还有哪些边界

- AutoCAD 2025 原生验收记录：**87个实体（道路34、断面39、地块14）**，保存重读87，撤销/重做 **87→0→87**。见 [脱敏验收记录](docs/native-verification.md)。
- 本版安装/技能/协议及合成成果复现结果见 [Starter发行记录](docs/release-0.3.1.md)。技能已安装、客户端已发现、CAD已绘图是不同验收层。
- 限定直线T/X路口、独立真圆弧、路表横断面、地块与基础图则已有实现；复杂路网自动优化、竖向土方、管线综合、所有地方标准和商业软件全模块不在本版已验收范围。
- 手动选取几何命令尚未全覆盖验收，最终响应式面板修改仍缺逐像素复查。其他CAD版本与其他电脑需要重新验证。

我们把 SketchUp、3ds Max、QGIS、ArcPy 的历史成功接入方法整理成了 [可选设计工具经验](docs/optional-design-tools.md)。这些工具不是首发必装依赖；未核清许可或仅有安装文本的第三方技能不混装进来。完整来源与证据分级见 [技能盘点](docs/skill-inventory.md)。

## 开发与许可

`share-skills/` 是可分发技能；`deploy/` 是安装与只读诊断；`app/`、`planning_cli.py`、`planning_mcp.py` 是计算引擎与接口；`cad-native/` 是原生插件/安装器/启动器源码。旧0.2.0网页/浏览器便携入口保留，使用说明见 [旧版文档](docs/legacy-web-0.2.0.md)。

本仓库原创源码使用 [MIT License](LICENSE)，第三方Python依赖保留各自许可；运行时与依赖清单封装在原生安装包中。AutoCAD、第三方软件与专有图块/素材不随仓库分发；本项目不依赖湘源程序或破解文件。

从干净源码构建原生插件需自己的AutoCAD SDK和相应.NET构建工具，见 [构建说明](cad-native/BUILD.md)。Starter重打包使用 `build_starter.py --native-installer <已验证EXE路径> --out <新目录>`，会校验固定EXE哈希、扫描公开源码路径、生成逐文件清单与ZIP哈希。
