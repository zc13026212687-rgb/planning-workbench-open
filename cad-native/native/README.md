# 清规AI · CAD 原生插件 0.3.0

这是原创 AutoCAD 2025 Windows x64 .NET 8 插件源码。加载后在 AutoCAD 内显示“清规AI”Ribbon 页签和原生 PaletteSet 停靠面板；没有浏览器界面依赖。

## 构建与安装契约

```powershell
$cadSdk = Read-Host '输入本机 AutoCAD 2025 安装目录'
dotnet build -c Release "-p:AutoCADSdkDir=$cadSdk"
```

构建机需要 .NET 8 或支持目标框架的较新 SDK，及本机 AutoCAD 2025 的 AcMgd、AcDbMgd、AcCoreMgd、AdWindows 程序集。Autodesk 引用均设置 `Private=false`；不得将这些宿主 DLL 包装为清规AI内容分发。发布仅复制 `QingGuiAI.Cad.dll`、可选的自有 `.pdb` 和 `.deps.json`。

宿主 AutoCAD 提供 .NET 8 Windows Desktop 运行环境。计算引擎为独立子进程，从下列固定相对位置定位：

```text
QingGuiAI.bundle/
  PackageContents.xml
  Contents/
    Windows/QingGuiAI.Cad.dll
    Engine/planning_cli.py
    Engine/app/...
    Engine/runtime/python.exe
```

## 可执行命令

| 命令 | 行为 |
|---|---|
| QGOPEN | 显示清规AI原生面板，并在 Ribbon 可用时注册清规AI页签 |
| QGROAD | 选择当前图纸的 LINE、ARC 或开放直线 LWPOLYLINE，输入左右宽度及路口半径，校核后向当前图纸添加结果 |
| QGROADDEMO | 新建米单位图纸，生成原创 X/T 路口教学例子 |
| QGSECTION | 原生对话框编辑两侧六个组成的宽度、横坡、用途和基准高程，向新图写入断面 |
| QGPARCEL | 选择一个闭合直线 LWPOLYLINE 边界，以及可选的 LINE/开放直线 LWPOLYLINE 道路中心线；输入统一道路总宽后向当前图纸添加净地块与标签 |
| QGPARCELDEMO | 新建图纸生成带有明确教学假设的合成地块例子 |
| QGSHEET | 输入当前进程最近地块成果的地块编号，向新图生成模型空间图则 |
| QGSPEC | 选择原创引擎支持的参数 JSON，校核后在新图生成 |
| QGABOUT | 显示版本、依赖和实际能力边界 |
| QGSELFTEST | 创建专用自测项目与新图，计算道路/断面/地块三种例子，原生复制实体、保存DWG、独立数据库重开，并在本任务新图中验证真实 U/REDO |

`QGAPPLY` 是新图延迟落图的内部命令，没有关联任务时不会写入。它在新图自身的普通模态命令上下文中落图，使用 `DocumentLock` 与事务，便于单步 `U` 撤销。模型空间目标文档被固定；原图选择命令在读取与写入前检查米单位，所有源中心线/边界保留。

## 结果和验证

每次生成在 `%LOCALAPPDATA%\QingGuiAI\Projects\任务类型-UTC-随机标识` 保存独立项目，包括输入参数、质量报告、DXF、引擎日志和 `native-cad-receipt.json`。回执包含真实 CAD 进程号、目标图纸名称、实体句柄及数量。不会将这些用户项目放进安装包。

自测索引是 `%LOCALAPPDATA%\QingGuiAI\last-selftest.json`。只有空模板新建图纸、当前三组固定例子共87个实体、DWG保存及重开均正确时，才在落图命令结束后向自己的图纸排队执行真实 `U`。固定在自测图纸上的 `Document.CommandEnded` 事件使用只读 `OpenCloseTransaction` 观察数量，不提交事务、不修改视图，也不在 `U` 与 `REDO` 之间插入自定义命令。观察到0后直接排队 `REDO`，在其结束事件中再次只读数量并解除事件订阅。`before_undo`、`after_undo`、`after_redo` 都来自实际数据库计数，只有87→0→87且此前保存重开通过才写 `passed_native_import_save_reopen_undo_redo`。中间状态或失败状态不能视为通过。回执只读记录 `SECURELOAD`，不修改安全设置。测试只创建自己的新图，不操作已有用户图纸；面板可见状态和编辑操作仍需宿主视觉检查。

## 计算与范围

当前图纸落图只接受 INSUNITS=6（米）、WCS XY 平面 Z=0 的适用输入。不会把单位标签更改当作缩放或把3D数据静默投影。道路不接受带 bulge 的多段线；独立 ARC 允许用于道路平面命令。地块道路只接受直线/直线多段线，按统一总宽缓冲扣除，不将其声称为路口工程红线。

用户选取边界的地块模式不自动推断孔洞、用地分类、容积率、覆盖率、绿地率或限高。缺失指标保持待核；需要更复杂参数时使用 QGSPEC。横断面是六组成连续路表，不包含纵断面、结构层、缘石和排水设计。QGSHEET 是模型空间图则，不是完整的图纸空间批量出图系统。

首次构建成功不代表宿主运行验收完成；真实 AutoCAD 验收由对应发布记录提供。此插件不是湘源控规的完整功能复制，不携带其程序、授权或专有资产。
