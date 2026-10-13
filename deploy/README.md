# Starter 0.3.1 deployment contract

The offline Starter release ZIP contains `payload/QingGuiAI-CAD-0.3.0-Setup.exe`, this `deploy/` directory, five complete `share-skills/` directories, and three `Install-*.cmd` launchers. A GitHub source ZIP does not include the native installer/runtime.

Double-click `Install-Codex.cmd`, `Install-Claude.cmd`, or `Install-OpenClaw.cmd`. The PowerShell process execution policy is scoped to that invocation; no machine or user policy is changed. The installer does not change model settings, credentials, CAD security settings, or any unrelated MCP server. It does not open CAD or invoke a model API.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy\Install.ps1 -Client codex
```

Optional parameters:

| Parameter | Meaning |
| --- | --- |
| `-Client codex`, `claude`, `openclaw` | Select the skill destination and supported client registration flow. |
| `-SkillsDirectory C:\somewhere\skills` | Explicit skill installation directory; useful for a profile or isolated check. |
| `-SkipCadInstall` | Use an already available engine; skip native installer execution. |
| `-EnginePath C:\somewhere\Contents\Engine` | Explicit engine directory, containing `runtime/python.exe`, `planning_cli.py`, and `planning_mcp.py`. |
| `-SkipMcpRegistration` | Install skills and run local doctor checks without writing client configuration. |
| `-ReceiptDirectory C:\somewhere\receipts` | Explicit local deployment receipt directory. |

Default skills destinations are `%USERPROFILE%\.agents\skills` for Codex, `%USERPROFILE%\.claude\skills` for Claude Code, and `%OPENCLAW_STATE_DIR%\skills` or `%USERPROFILE%\.openclaw\skills` for OpenClaw. A named OpenClaw profile may need `-SkillsDirectory`; no OpenClaw configuration is invented or rewritten.

The native installer is pinned by SHA-256. If the existing native installer receipt records the same payload SHA-256 and **all** its recorded file hashes match, native installation is skipped, preserving loaded CAD DLLs. Otherwise the pinned native installer is called. It will refuse to replace its own DLL while loaded; save drawings and close the relevant CAD instance only if an actual version update is needed.

Skill installation preflights all five sources and all five targets. Unrelated same-name skills, symbolic links, and junctions cause a stop. An earlier `planning-workbench` wrapper with recognized metadata and wrapper marker, or a current `qinggui-starter` skill, can be migrated. Entire original directories, including hand-edited notes and additional resources, are backed up with SHA-256 records before any replacement. Updates use directory renames and restore the original directories if activation fails. The local backup is under the client directory's `qinggui-skill-backups/`; a successful update intentionally retains it. Repeating the same install with identical files is a no-op.

The `doctor.py` helper imports the real geometry/DXF dependencies, runs the synthetic parcel validator, and performs an actual stdio MCP initialization, tools listing and `planning_cases` call. No CAD drawing is opened. This verifies the installed engine/protocol, not discovery in an AI chat or a CAD save/undo roundtrip.

Codex registration uses `codex mcp add qinggui-cad -- <python> -B -u <planning_mcp.py>` and reads it back with `codex mcp get ... --json`. Claude registration uses `claude mcp add --scope user --transport stdio ...`, preserving existing configuration and reading back only the new entry. A same-name server with another target is left untouched. OpenClaw uses the installed skill's CLI helper; no automatic MCP configuration is promised.

Exit codes: **0** means the requested local installation/checks completed; **2** means skills are installed but MCP client registration requires attention; **1** means deployment failed. Read `deployment.json` and its `evidence_layers` rather than inferring readiness from an exit code alone. With `-SkipMcpRegistration`, status explicitly says registration was skipped. If the client CLI is missing, a machine-local `mcp-configuration.example.json` is produced with `needs_client_registration`; restart or reload the appropriate AI client after registration to test discovery.

The user-local `local-engine.json`, receipts, backups and generated MCP examples contain that machine's paths. They are not release inputs and must never be copied into a public skills archive.

Sources checked for the client conventions: [Claude Code skills](https://code.claude.com/docs/en/skills), [Claude Code MCP](https://code.claude.com/docs/en/mcp), [OpenClaw skill locations](https://docs.openclaw.ai/help/faq/skills-and-automation). The installed Codex and Claude CLIs' `mcp add --help` were also checked; deployment probes the installed command before registration.
