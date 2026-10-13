# 清规AI原生 CAD 0.3.0 验收记录（公开脱敏摘要）

本记录摘自 2026 年 10 月 13 日的本机真实 AutoCAD 验收回执。公开内容保留版本、实体数量、观察状态和文件摘要；省略用户名、本机路径、进程号、图纸内部句柄和课程数据。它是一次已执行验收的摘要，不是本次源码归档时重新运行的结果，也不表示任意电脑均已通过测试。

验收宿主为 **AutoCAD 2025、Windows x64、R25.0、.NET 8**。原生插件版本为 0.3.0，使用原创合成教学输入，在本次测试新建图纸中执行。

| 检查 | 实测结果 |
|---|---:|
| 道路平面 DXF 原始实体 / CAD 导入实体 | 34 / 34 |
| 道路横断面 DXF 原始实体 / CAD 导入实体 | 39 / 39 |
| 控规地块 DXF 原始实体 / CAD 导入实体 | 14 / 14 |
| 三组实体合计 | **34 + 39 + 14 = 87** |
| 保存 DWG 后独立数据库重新打开的实体数 | **87** |
| INSUNITS | **6（米）** |
| 真正执行 U 前 / U 后 / REDO 后的实体数 | **87 → 0 → 87** |
| SECURELOAD 只读记录 | 1 |

原生运行回执状态为 `passed_native_import_save_reopen_undo_redo`。撤销与重做计数来自 AutoCAD 命令结束事件中的实际数据库只读观察，记录为 `observed_87_to_0_to_87_command_ended`。这与仅导出 DXF、统计 JSON 中实体数或检查安装目录存在不同。测试保留已有用户图纸；没有把源课程底图作为可分发测试数据。

## 仍然存在的验收边界

原始回执中的三个字段原样保留其布尔含义：

```json
{
  "native_menu_palette_observed": true,
  "final_responsive_layout_pixel_recheck": false,
  "manual_selected_geometry_commands_full_coverage": false
}
```

曾观察到原生菜单和停靠面板；最后一次响应式面板布局修正后的像素复查尚未完成。人工选择中心线、闭合边界及全部交互命令尚未逐条覆盖。这两个 `false` 不能被安装包构建成功、自动自测或前一次界面观察替代。

已验收范围为道路、路表横断面、地块和基础图则所使用的原生接入及三组合成案例。87 个实体的自动自测不单独证明所有 `QGROAD`、`QGPARCEL`、`QGSECTION`、`QGSHEET` 或 `QGSPEC` 的交互分支。真实规划合规、真实场地方案适用性、其他 CAD 版本和第三方 AI 客户端发现过程也不在这一记录的结论内。

竖向设计、土方平衡、管线综合、完整地方标准库和完整批量出图系统未实现。`full_xiangyuan_parity=false`，`vendor_programs_redistributed=false`：当前版本是原创实现，不能称为湘源控规 9.0 的全功能复刻。

## 当时交付文件的 SHA-256

| 对象 | SHA-256 |
|---|---|
| 已安装原生插件 DLL | `cb5395b65a9a931809521adb93b7449fd2de0c8b01b097587e33214be6d6b37e` |
| 0.3.0 EXE 安装包 | `964a7f192da324c7c1d688dbec2511aac11b34f247a07b64c3e44bd9297ce365` |
| 当时独立源码 ZIP | `ea973235c25fb4d9e745945408115cf448177d0a36700d37bfac21af54da8ed1` |

这里的源码 ZIP 摘要对应最初的独立包，不是当前 Git 仓库摘要。此次将原生源码归档到 `cad-native/`，共享仓库根目录计算引擎，并补充构建路径与许可说明；因此重新打包的源码 ZIP 将产生新的摘要。原生 C# 功能代码没有因此改变。

## 在自己的电脑复验

安装适用版本后，在一个专用于验证的 CAD 会话运行 `QGSELFTEST`。它会新建自己的测试图纸；等待 `%LOCALAPPDATA%\QingGuiAI\last-selftest.json` 最终状态，只有完整通过状态才算自动自测成功。中间 `pending_undo_redo` 或启动器的 `ok=true` 不能算功能通过。需要另外实际观察面板并检查计划采用的人工选图交互。

源码、构建步骤和许可分别见 [原生插件](../cad-native/README.md)、[BUILD.md](../cad-native/BUILD.md)、[NOTICE.md](../cad-native/NOTICE.md)。
