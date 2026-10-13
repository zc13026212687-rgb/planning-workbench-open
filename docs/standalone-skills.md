# 清规AI独立技能使用

桌面与脚本共用 app 内的几何引擎、CAD 桥和规范规则。无需模型 API 即可使用。

四个公开技能入口保持既有名称，展示品牌为“清规AI”。安装后的 `scripts/run.py` 从本技能 `local-engine.json` 读取引擎与解释器位置，再调用同一 `planning_cli.py`；不能只复制入口文件夹而丢弃引擎。

| 安装与调用名称 | 源码说明 | 作用 |
|---|---|---|
| `beijing-regulatory-cad` | `skills/beijing-regulatory-cad/SKILL.md` | 来源、规范适用条件与CAD工作流程 |
| `planning-cad-road-plan` | `skills/road-plan/SKILL.md` | 道路平面、限定T/X路口与几何校核 |
| `planning-cad-cross-section` | `skills/road-cross-section/SKILL.md` | 明确组成的道路横断面 |
| `planning-cad-regulatory-suite` | `skills/regulatory-suite/SKILL.md` | 地块、指标、图则及成果整理 |

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe planning_cli.py cases
.\.venv\Scripts\python.exe planning_cli.py library '北京 控规'
.\.venv\Scripts\python.exe planning_cli.py generate --case regulatory-road-plan --out data/my-road
.\.venv\Scripts\python.exe planning_cli.py generate --case regulatory-road-plan --variant oblique-x60 --out data/my-oblique-road
.\.venv\Scripts\python.exe planning_cli.py generate --spec my-confirmed-spec.json --out data/my-drawing --cad-new
```

输出目录必须不存在，以保留历史成果。`--cad-new` 真实连接本机 AutoCAD、新建测试图、绘制、回读并保存 DWG；未加此参数仅生成 DXF、参数和报告。CAD 桥需米制；转换其他单位时必须实际缩放几何。

`cases` 的 available_variants 给出可用方案 ID；道路示例含 orthogonal、oblique-x60、oblique-t60。`--variant` 不能和 `--spec` 同用。错误方案名会阻断，不会悄悄退回默认案例。

独立技能包包含源码与技能，不含图库、API配置或个人资料。先按 requirements.lock.txt 创建 Python 环境。运行 `python install_skills.py --only planning-cad-regulatory-suite` 仅安装新增控规入口；省略 `--only` 会选择四个公开入口。默认目标为当前用户 `.agents/skills`，不覆盖不同来源的同名技能。移动引擎后应重新安装；本机定位文件不进入公开源码包。新聊天可能才会发现技能，安装不是所有Agent已调用的证明。

安装器在 Windows 下优先选择项目内现存的 `runtime/python.exe`，没有时使用 `.venv/Scripts/python.exe`；其他系统仍使用 `.venv/bin/python`。`--python` 可显式覆盖这一选择，指定已安装引擎依赖的解释器。若使用带 `runtime` 的发行包，上述命令中的 `.venv/Scripts/python.exe` 可替换为 `runtime/python.exe`；不要把别台电脑安装后的 `local-engine.json` 当作共享配置。

如同名技能仍定位其他引擎，安装器会拒绝覆盖。先确认保留旧版本还是迁移，并备份旧入口；不要为了通过安装而直接删除来源记录。技能安装不自动注册 MCP，配置方法见 `docs/mcp-usage.md`。

院内规则先加入有来源的参考条目。要自动校核，应在 app/rules.py 编写明确适用范围与回归用例；未验证做法保留为参考，不升级成合规判定。当前不开放任意第三方脚本执行器；模板限于已注册的执行器。
