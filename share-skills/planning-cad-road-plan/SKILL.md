---
name: planning-cad-road-plan
description: 从已知中心线与宽度生成并校核道路边界、真圆弧和限定T/X路口，输出可编辑CAD图形；用于控规道路平面教学与参数修改。
---

# planning-cad-road-plan

## 找到可执行入口

本技能由清规AI Starter 部署。先读取本技能目录的 `local-engine.json`；其中 `root` 是引擎目录，`python` 是已安装解释器。调用时使用这两个实际绝对路径，保留路径中的空格；不把文档中的变量名当成实际路径。

```powershell
$meta = Get-Content -Raw -Encoding UTF8 -LiteralPath '本技能实际目录/local-engine.json' | ConvertFrom-Json
& $meta.python -B '本技能实际目录/scripts/run.py' cases
& $meta.python -B '本技能实际目录/scripts/run.py' validate --spec '参数的绝对路径.json'
& $meta.python -B '本技能实际目录/scripts/run.py' generate --spec '参数的绝对路径.json' --out '尚不存在的成果目录'
```

如果配置文件不存在或引擎路径失效，说明技能尚未完整部署；使用 Starter 的部署/诊断入口，不凭空猜测 Python 路径。执行 CLI 的返回码和质量报告决定结果；成功安装不代表模型客户端已发现工具或 CAD 已绘图。

已注册 MCP 时可用 `planning_cases`、`planning_validate`、`planning_export`、`planning_export_control_sheet`。CLI 和 MCP 调用同一确定性引擎。MCP 不是读取当前 CAD 选择集的接口；当前选择集由 CAD 内 `QGROAD`/`QGPARCEL` 交互命令处理。

## 工作步骤

1. 阅读 [模块契约](references/module-guide.md)，按其中的输入语义建立参数；工程源码、案例与 docs 路径均相对于 `local-engine.json.root`。
2. 先核实输入来源、单位和坐标。真实场地缺少定标时保留缺项；合成练习必须标明 synthetic。
3. 先 validate，再向新目录 generate；errors 非空不得作为合格成果交付。
4. 需要 CAD 落图时沿用当前用户授权并明确目标图纸；CLI `--cad-new` 只建立独立新图。
5. 回读参数、图层、实体和保存结果；按实际完成范围交付，不把 DXF 导出称为已验证 DWG。

完整课程流程使用 `qinggui-cad-workflow`。道路、断面、地块的 schema 不互相代替。
