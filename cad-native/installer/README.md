# 清规AI · CAD原生插件 0.3.0 安装器

这是原创 Windows WinForms 安装器与启动器源码。安装器为真正的 Windows x64 PE EXE，内嵌完整的 `QingGuiAI.bundle` ZIP；不需要网络下载 Python 或 Node，不包含 AutoCAD 或任何湘源二进制。

## 安装与启动

双击 `QingGuiAI-CAD-0.3.0-Setup.exe`，点击“安装清规AI”。默认写入：

`%APPDATA%\Autodesk\ApplicationPlugins\QingGuiAI.bundle`

安装器创建桌面入口“清规AI · CAD原生插件”和当前用户的卸载登记。桌面入口执行自己的 `QingGuiAI.Launcher.exe`，找到 AutoCAD 2025 后用官方 `/b` 启动脚本参数调用 `QGOPEN`。它不打开浏览器，不替换 AutoCAD，也不修改其他插件、CUI、SECURELOAD 或 TRUSTEDPATHS。

这是尚未购买代码签名证书的原创安装包，`signed=false` 会写入构建记录。Windows/AutoCAD 可以显示各自的安全确认。AutoCAD 的安全策略可能阻止未经信任的插件；需由用户核对名称、来源与路径后处理安全提示，组织设备应遵循其管理员策略。首次真实加载必须在 AutoCAD 中验证，文件安装成功不等于插件已经成功加载。

用户项目路径为 `%LOCALAPPDATA%\QingGuiAI\Projects`，卸载保留此目录。

## 构建

1. 执行 `launcher/Build-Launcher.ps1`，生成原创多尺寸道路图标及两个 EXE 和两个 SCR。
2. 将 `launcher/bin` 的四个文件放入 bundle 的 `Contents/Launcher/`。
3. bundle 根应包含 `PackageContents.xml`、`Contents/Windows/QingGuiAI.Cad.dll` 和 `Contents/Engine/runtime/python.exe`，以及完整引擎、依赖与许可证。
4. 将 bundle **内部内容**压成 ZIP，不额外套一层 `QingGuiAI.bundle`。
5. 执行：

```powershell
.\installer\Build-Setup.ps1 -BundleZip <bundle.zip> -OutputDirectory <新的发布目录>
```

构建使用 Windows `.NET Framework` 编译器；安装器仅依赖系统 .NET Framework，不与 AutoCAD 插件的 .NET 8 运行时混淆。Windows 10 的具体 .NET Framework 随系统版本变化，建议目标 Windows 10 22H2 或 Windows 11。实际插件宿主兼容性目前限定为 AutoCAD 2025。

构建脚本拒绝覆盖现有同名 EXE，生成安装器 SHA-256、载荷 SHA-256 和 unsigned 标记。安装前再次校验内嵌 ZIP 摘要并拒绝越界路径、符号链接、重名条目及缺失的必要文件。

## 自动验收接口

```powershell
# 仅读取内嵌完整包、检测 CAD 与目标路径；不安装
QingGuiAI-CAD-0.3.0-Setup.exe --dry-run --silent --result <结果JSON>

# 隔离文件验收；自定义目录不在CAD自动加载范围，不创建桌面/系统登记
QingGuiAI-CAD-0.3.0-Setup.exe --install --silent --dest <绝对路径\QingGuiAI.bundle> --no-shortcut --no-register --result <结果JSON>

# 卸载指定验收目录
QingGuiAI-CAD-0.3.0-Setup.exe --uninstall --silent --dest <绝对路径\QingGuiAI.bundle> --result <结果JSON>

# 已安装 Launcher 仅检测宿主、脚本与DLL路径
QingGuiAI.Launcher.exe --check --silent --result <结果JSON>

# 启动新的 AutoCAD 进程，执行 QGOPEN、QGSELFTEST
QingGuiAI.Launcher.exe --self-test --result <启动结果JSON>
```

启动 PID、路径和 UTC 时间写入 `%LOCALAPPDATA%\QingGuiAI\Logs\last-launch.json`。结果 JSON 不包含口令或访问令牌。安装/启动的错误退出码是 1，卸载保留被修改文件的退出码是 2。

卸载器复制自身到临时目录后等待原进程结束，再按安装收据逐一校验、删除原始未修改文件。正在使用本 bundle 的 EXE/DLL/PYD 会在操作前检查并拒绝卸载/升级；不要求关闭未加载此 bundle 的其他 AutoCAD 会话。用户修改过的文件保留；只清理收据所列文件的空父目录，不递归删除用户新增目录或沿符号链接操作。

## 官方依据

- [Autodesk：使用启动参数执行脚本](https://help.autodesk.com/cloudhelp/2025/ENU/AutoCAD-Core/files/GUID-7FDC500C-E04A-432D-A73D-EB1B6C6728B1.htm)
- [Microsoft：Windows 的 .NET Framework 安装与内置版本](https://learn.microsoft.com/en-us/dotnet/framework/install/)

具体功能和真实 CAD 验收结果以主包的功能清单及验收记录为准，安装器不声明已等同于任何商业控规软件全部功能。
