# 清规AI · CAD原生插件 0.3.0

这是直接运行在 AutoCAD 内的原创控规教学插件，提供原生停靠面板、命令、参数窗口和标准可编辑 CAD 实体。桌面入口启动 AutoCAD。计算在本机完成，不依赖浏览器服务、系统 Python、模型 API 或湘源插件。

## 安装和打开

1. 在已安装 AutoCAD 2025 Windows x64 的电脑上双击 `QingGuiAI-CAD-0.3.0-Setup.exe`。本版以 R25.0、.NET 8 的 AutoCAD 2025 环境为验收对象。
2. 按安装窗口说明安装。默认位置是 `%APPDATA%\Autodesk\ApplicationPlugins\QingGuiAI.bundle`，不替换 CAD 原文件。安装包包含 Python 和计算依赖；AutoCAD 须自行安装。
3. 双击桌面“清规AI · CAD原生插件”。首次加载可能出现 AutoCAD 的安全确认，核对路径确为本插件后选择加载；安装器不关闭 `SECURELOAD`，不自动扩大 `TRUSTEDPATHS`。
4. 点击 CAD 顶部“清规AI”页签，或在命令行输入 `QGOPEN` 打开停靠面板。若命令尚未注册，先确认插件已在当前 CAD 会话完成加载。

## CAD 内的使用方式

| 命令 | 操作与输出 |
|---|---|
| `QGOPEN` | 打开清规AI原生停靠面板 |
| `QGROADDEMO` | 在新图纸生成道路示例，方便首次检查 |
| `QGROAD` | 选择已有中心线并输入道路参数，生成可编辑道路实体 |
| `QGSECTION` | 原生参数窗口设置道路组成宽度、坡度，生成横断面 |
| `QGPARCEL` | 选择闭合边界、中心线并给定路宽，进行地块划分 |
| `QGPARCELDEMO` | 新图纸演示地块划分和面积核算 |
| `QGSPEC` | 选择原创引擎支持的 JSON 参数文件，供 AI / Skill 工作流传入 |
| `QGSHEET` | 从本次地块成果选择地块，生成单地块控制图则 |
| `QGABOUT` | 查看版本、计算引擎与结果位置 |
| `QGSELFTEST` | 在自有新图纸中进行道路、断面和地块验收，写入测试记录 |

实际场地绘图前，须确认 CAD 单位为米，边界与中心线使用同一坐标。道路等级、宽度、保留建筑和保护边界由设计者依据任务书确定。教学示例不是大钟寺实测底图，也不是法定控规成果。缺少地块指标时保留待填写状态，不自动推定容积率或用地代码。

成果和日志保存至 `%LOCALAPPDATA%\QingGuiAI\Projects`。保留生成的参数文件可以追溯每次计算；标准线、圆弧、多段线、文字可继续在 CAD 编辑。新版本安装时应先关闭正在加载本插件的 CAD 会话，托管 DLL 不支持任意热替换。卸载入口为安装目录 `Contents\Launcher\QingGuiAI.Uninstall.exe`，保留用户成果目录。

## 功能范围

本版交付原生 CAD 接入、道路几何、横断面、地块切分、面积检查和基础控制图则。它是独立实现的开源项目，未使用湘源程序、专有图块、许可文件或反编译代码，也没有完整复刻湘源9.0的全部模块。竖向设计、土方平衡、管线综合、完整地方标准数据库、各类专项规划和商业 CAD 平台适配尚不属于本版已验收能力。

AI / Skill 可以生成或修改本项目的结构化参数，再由 `QGSPEC` 在 CAD 中执行。当前确定性绘图不需要模型 API；安装这个插件本身并不意味着已经内置聊天模型或能自动作出规划判断。

## 源码与构建

原创插件、安装器、启动器和规划引擎使用 MIT 许可，源码许可说明见 [NOTICE.md](NOTICE.md)。第三方 Python 包保留各自许可；完整安装包内的 `THIRD_PARTY_NOTICES.md` 和 `Contents/Engine/runtime/DEPENDENCIES.json` 给出清单。Autodesk 程序和 SDK DLL 不随包分发。

源码结构：`native/`（.NET 8 AutoCAD 插件）、`launcher/`（Windows 启动/卸载入口）、`installer/`（Windows 安装器）、`build_bundle.py`（白名单打包）、`PackageContents.xml`（AutoCAD 注册）。原生插件构建须在开发者自己的 AutoCAD 安装中引用 `AcMgd.dll`、`AcDbMgd.dll`、`AcCoreMgd.dll` 和 `AdWindows.dll`，并保持 `Private=false`。适配其他宿主或版本需要另行编译和实测。

本仓库中原生源码位于 `cad-native/`，计算引擎共享仓库根目录，不重复复制。按 [BUILD.md](BUILD.md) 构建；`build_bundle.py` 和 `build_source.py` 的 `--engine` 可指定引擎根目录，默认兼容仓库布局与独立源码包布局。历史验收的公开脱敏摘要位于仓库 `docs/native-verification.md`，其中明确保留了两项尚未完成的人工/视觉验收。
