# 清规AI Windows 便携版

产品显示名为 **清规AI · PlanningWorkbench Open 0.2.0**。技术项目名、MCP 工具名和四个技能 ID 保持稳定。发布构建使用单独的 `v0.2.0-qinggui.1` 标记，保留此前 `v0.2.0` 发布记录。

## 普通使用者

Windows 10/11 x64 使用者下载 `QingGui-AI-0.2.0-windows-x64.zip`，先完整解压到可写目录，再双击 `安装清规AI.cmd`。检查通过后创建当前用户的桌面快捷方式；后续双击桌面“清规AI · PlanningWorkbench Open 0.2.0”，或目录中的 `启动清规AI.cmd`。

便携包包含独立的 Python、固定版本依赖和预构建界面，不要求使用者安装 Python、Node 或 .NET。默认浏览器承载本机工作台，计算服务仅监听本机地址。它没有内置 AutoCAD；DXF 文件可独立生成，实时 CAD 新图落图需要另有可用的 AutoCAD 和 ActiveX 注册。模型 API 为可选功能，模型费用和账号由使用者选择。

工作台入口包括道路平面、道路横断面和地块与图则。现有算法适用范围仍以 `geometry-limitations.md`、`regulatory-schema.md` 和 `open-implementation.md` 为准。便携分发不增加尚未实现的规划算法，不表示完整替代商业控规软件。

安装四个 Codex 技能可在解压目录执行：

```powershell
.\runtime\python.exe install_skills.py
```

新开会话后调用 `beijing-regulatory-cad`、`planning-cad-road-plan`、`planning-cad-cross-section` 或 `planning-cad-regulatory-suite`。已有同名技能指向其他引擎时安装器会拒绝覆盖；应先核对来源并备份，再迁移。MCP 配置中的解释器改为本目录的 `runtime/python.exe`，其余见 `mcp-usage.md`。

### 移动文件夹后的入口迁移

安装入口负责环境检查和桌面快捷方式，**不会自动安装或迁移 Codex 技能，也不会修改 MCP 客户端配置**。移动前记录旧目录的完整路径，保存任务并停止旧工作台后台服务；只关闭浏览器不会停止后台。个人方案、会话和成果留在该目录的 `data`，不能为了迁移入口而删除整份数据。

移动后从新目录运行 `安装清规AI.cmd`。若桌面已有指向旧位置的同名快捷方式，安装器会保留它，并创建带 `(2)` 等后缀的新入口；不会擅自接管另一个工程。确认新入口能够打开后，可自行清理不再使用的旧快捷方式。

已经安装过本项目技能时，在新目录运行明确迁移命令。下面的旧路径应替换为自己移动前的真实位置，不是新位置：

```powershell
.\runtime\python.exe install_skills.py --relocate-from "C:\Apps\QingGui-old"
```

默认先预检四个技能：原记录必须匹配指定旧路径，技能名称及 `scripts/run.py` 必须属于本安装器已知模板。旧引擎目录可以已经不存在；修改过的脚本、其他引擎或不明来源入口会被拒绝，预检失败不写入。如果只安装过其中一个技能，请明确选择已安装子集：

```powershell
.\runtime\python.exe install_skills.py --relocate-from "C:\Apps\QingGui-old" --only planning-cad-regulatory-suite
```

迁移先把完整旧技能备份到技能目录同级的可见目录 `planning-workbench-skill-backups/<时间ID>/`；默认位置为当前用户 `.agents` 目录下。备份校验通过后才更新所选入口，保留其他技能和附加文件。输出列出备份位置与 `migration.json`；写入异常会尝试恢复，若恢复失败则在该记录明确列出，不能当成迁移成功。普通首次安装仍不使用 `--relocate-from`。迁移后新开 Codex 会话，再验证技能入口；MCP 配置中解释器和服务器脚本的绝对路径需另行更新。

如果复制目录带有旧位置的后台记录，启动器会在当前目录保留为 `data/server.previous-时间-随机.json`，再创建当前目录的独立服务；不会接管或停止旧服务。无法核实进程归属时会停止并给出提示，不能据此关闭无关 Python/CAD 进程。分享时使用发布包，不直接压缩自己用过的工作目录。

## 从源码构建

构建者需要 Python 3.14 与 pip，以及用于生成网页的 Node/npm。先按锁文件构建 `web/dist`，下载 `requirements.lock.txt` 中的 Windows x64 wheel，再使用 `build_windows_portable.py`。此脚本只组装明确白名单内的原创源码、构建后的网页和经摘要校验的依赖，不复制现有虚拟环境或用户文件。

```powershell
python -m pip --isolated download --only-binary=:all: --index-url https://pypi.org/simple --dest C:\QingGuiBuild\wheels -r requirements.lock.txt
python build_windows_portable.py --python-archive C:\QingGuiBuild\python-3.14.4-embed-amd64.zip --wheels C:\QingGuiBuild\wheels --runtime-out C:\QingGuiBuild\runtime
python build_windows_portable.py --runtime C:\QingGuiBuild\runtime --out C:\QingGuiBuild\release-01
```

输出目录必须尚不存在。Python 嵌入包来自 [Python 3.14.4 官方发布页](https://www.python.org/downloads/release/python-3144/)，脚本固定核对该页公布的 SHA-256；每个 wheel 重新对照 PyPI 同版本元数据的 SHA-256。运行时按照 [Python 官方嵌入分发说明](https://docs.python.org/3.14/using/windows.html#the-embeddable-package) 隔离，终端用户无需用 pip 管理这个嵌入环境。

运行时保留 Python LICENSE、包内第三方许可及依赖来源摘要。项目 MIT 许可只覆盖本项目原创部分；不替换 NumPy、Shapely 及其他依赖自己的许可。包内 `THIRD_PARTY_NOTICES.md` 与 `runtime/DEPENDENCIES.json` 提供索引。

## 验收范围

发布前应检查：完整解压、中文及空格路径、独立 Python 导入与 CLI 计算、全部回归检查、网页三个模块、桌面快捷方式指向、重复启动不重复服务、原生 DXF 回读、需要时 CAD 新图保存。未在第二台真实电脑或所有 Windows/CAD 版本实测之前，不应声称“所有人和所有 CAD 都可用”。
