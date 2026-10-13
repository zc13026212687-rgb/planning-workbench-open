# 安装与接入：清规AI Starter 0.3.1

Starter 0.3.1 将五个技能、部署器和已验收的 **CAD Native 0.3.0** 安装包放在一起。计算引擎仍为 0.2.0，三个版本分别对应交付层、原生插件层和几何引擎；不意味着算法新增了全套商用功能。

## 新用户要准备什么

| 项目 | 用途 | 是否由本包安装 |
|---|---|---|
| Windows x64 | 本版部署与原生插件运行环境 | 用户已有；本机验收环境为 Windows 11 |
| AutoCAD 2025 | 原生按钮、面板、选线、DWG落图 | 用户自行安装和授权；其他CAD版本未验证 |
| Codex / Claude Code / OpenClaw 本地客户端之一 | 自然语言调用技能 | 用户自行安装、登录；本包不代开模型服务 |
| 独立 Python 和依赖 | 确定性计算、DXF、MCP | 安装包已内置，无需全局pip安装 |
| 五个清规AI技能 | 参数组织、校核与实战步骤 | Starter 自动部署 |

只做计算与DXF导出不需要打开CAD。`-SkipCadInstall -EnginePath` 接受已安装bundle的引擎，或按 `cad-native/BUILD.md` 准备好 `runtime/python.exe` 的引擎目录。普通venv源码用户可直接运行CLI/MCP，但不能把仅含 `.venv` 的目录交给此部署入口。浏览器云端聊天不能直接调用另一台电脑上的CAD。

## 三步使用

1. 从 [v0.3.1 发行页](https://github.com/zc13026212687-rgb/planning-workbench-open/releases/tag/v0.3.1) 下载 `QingGuiAI-Starter-0.3.1-windows-x64.zip`，完整解压到可写目录。不要直接在ZIP预览中运行。
2. 使用 Codex 双击 `Install-Codex.cmd`；Claude Code 用 `Install-Claude.cmd`；OpenClaw 用 `Install-OpenClaw.cmd`。安装器校验内置EXE哈希，将插件/引擎放到稳定路径，复制技能，运行诊断并输出回执。已有相同有效bundle会跳过重复安装。
3. 重启所选AI客户端会话，明确使用 `qinggui-cad-workflow`，先运行合成案例。AutoCAD 启动后输入 `QGOPEN` 打开面板；已有CAD进程若未加载新插件，保存工作后自行重启CAD。

首次提示词：

> 使用 qinggui-cad-workflow，先检查清规AI引擎和工具是否可用。在新目录生成合成道路平面、横断面、地块和P001图则，列出校核、缺失指标和输出文件。本次只导出DXF。

接着可要求在新CAD图纸落图。输入缺项时先完善参数；不要把示例数值当成道路规范限值。

## 客户端与目录

| 客户端 | 技能目录 | 本版工具接入 |
|---|---|---|
| Codex | `~/.agents/skills` | 使用官方CLI注册 `qinggui-cad` stdio MCP |
| Claude Code 本机 | `~/.claude/skills` | 使用官方CLI注册用户级 `qinggui-cad` stdio MCP |
| OpenClaw 本机 | 默认 `~/.openclaw/skills`，自定义state/profile需检查实际位置 | Skill + 本地CLI；本版不自动注册其MCP节点 |

Codex 中可点名 `$qinggui-cad-workflow`；Claude Code 中用 `/qinggui-cad-workflow`；OpenClaw 中明确点名并先确认技能被当前profile发现。官方路径及行为依据：[Codex](https://learn.chatgpt.com/docs/build-skills)、[Claude Code skills](https://code.claude.com/docs/en/skills)、[Claude Code MCP](https://code.claude.com/docs/en/mcp)、[OpenClaw skills](https://docs.openclaw.ai/tools/skills)。Claude Code 的本机个人技能不自动同步到 Cowork 或云会话。

高级参数（在完整解压目录中运行）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\Install.ps1 -Client codex
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\Install.ps1 -Client claude -SkipCadInstall -EnginePath '已安装引擎的绝对路径'
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\Install.ps1 -Client openclaw -SkillsDirectory '指定profile的技能目录'
```

命令中的 ExecutionPolicy 仅作用于这个启动进程；脚本不会永久修改系统策略。参数 `-SkipMcpRegistration` 可只部署技能。源码仓库没有大型 `payload/*.exe`；若尚未安装原生包，优先使用完整Starter ZIP。

## 如何判断成功

- `skill_files_installed`：五个目录已复制并绑定本机路径。
- `engine_case_verified`：Python/CLI 案例可执行。
- `mcp_protocol_verified`：MCP子进程初始化、列出工具并返回案例。
- 客户端注册成功只说明配置写入并能读回；**模型实际发现和调用须在新会话验收**。
- CAD 原生落图、保存重读、撤销/重做须在自己的空白测试图中验收；doctor不会操作当前CAD。

查看部署器输出的回执路径，按失败层排查。遇到同名外部技能或同名不同目标MCP时会停在对应步骤，不覆盖。相同包重复部署不重写技能；本包升级会先完整备份并校验，保留人工修改供恢复。安装回执中的本机路径仅在用户电脑保存，不随公开包分发。

原生0.3.0安装器使用.NET Framework文件接口，自定义过深的目标路径可能触及Windows `MAX_PATH` 限制；本次清洁验收已遇到并保留该失败记录。普通部署使用默认APPDATA位置；自行指定原生 `--dest` 时选短路径，出现路径过长后不要反复安装到同一深目录。

## 更新与移除

更新时下载完整新包并重新运行相应入口；保留部署输出的备份路径。不要手工复制某个SKILL.md代替完整升级。普通技能是说明层，计算引擎和CAD原生插件是执行层，三者都需要可定位。

只移除AI接入时，先核对 `local-engine.json.installer` 确属本包，再备份并移走这五个技能目录。MCP通过 `codex mcp remove qinggui-cad` 或 `claude mcp remove --scope user qinggui-cad` 移除自己的记录；其他MCP保持不动。原生插件的卸载使用其安装器支持的卸载入口，操作前先关闭加载该DLL的CAD。工作图纸与Projects属于用户成果，应保留。任何不认识的同名文件先核对来源。
