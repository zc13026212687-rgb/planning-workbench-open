# 从源码构建清规AI · CAD原生插件 0.3.0

仓库的 `cad-native/` 保存原创 C# 插件、Windows 启动器和安装器。计算引擎直接使用仓库根目录；这里没有另一份 `engine/`。独立源码 ZIP 则将引擎放在 `engine/`。两个打包脚本均能自动区分这两种布局，也可通过 `--engine` 指定引擎根目录。源码不包含 AutoCAD、SDK DLL、Python 运行时、已编译 EXE/DLL 或课程底图。

## 构建环境

- Windows x64，建议 Windows 10 22H2 或 Windows 11。
- 开发者自己的 AutoCAD 2025 安装，提供 `AcMgd.dll`、`AcDbMgd.dll`、`AcCoreMgd.dll`、`AdWindows.dll`。
- 可构建 `net8.0-windows` 的 .NET SDK。首次构建可能需要从官方 NuGet 恢复目标框架引用包。
- 构建用 CPython 3.14 x64 和 pip；安装包内嵌运行时固定为官方 CPython 3.14.4，安装包使用者无需另装 Python。
- Windows 的 `.NET Framework` 编译器 `%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe`，用于安装器和启动器；它不替代 CAD 插件使用的 .NET 8。

在仓库 `cad-native/` 目录，或解压出的独立源码包根目录打开 PowerShell：

```powershell
$engineRoot = if (Test-Path -LiteralPath '.\engine\planning_cli.py') {
    (Resolve-Path -LiteralPath '.\engine').Path
} else {
    (Resolve-Path -LiteralPath '..').Path
}
$acadSdkDir = Read-Host '请输入自己的 AutoCAD 2025 安装目录'
dotnet build .\native\QingGuiAI.Cad.csproj -c Release "-p:AutoCADSdkDir=$acadSdkDir"
if ($LASTEXITCODE -ne 0) { throw 'Native plugin build failed.' }
& .\launcher\Build-Launcher.ps1
```

Autodesk 引用须保持 `Private=false`。不要复制这些宿主 DLL 到发布包。原生代码与初次 0.3.0 验收版本相同；本次归档仅适配源码布局、打包和说明。

## 准备独立 Python 运行时

网络下载只发生在构建阶段。`requirements.lock.txt` 固定全部包版本；运行时准备脚本校验官方 CPython ZIP 的固定 SHA-256，并逐一将 wheel 摘要与官方 PyPI 元数据比对。wheel 目录须与锁定依赖完全一致。第三方原许可证随运行时保留，详见 [NOTICE.md](NOTICE.md)。

```powershell
New-Item -ItemType Directory -Force -Path .\.build\downloads, .\.build\wheels | Out-Null
$pythonArchive = Join-Path (Get-Location) '.build\downloads\python-3.14.4-embed-amd64.zip'
if (Test-Path -LiteralPath $pythonArchive) { throw 'Use a new download path, or verify the existing archive first.' }
Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.14.4/python-3.14.4-embed-amd64.zip' -OutFile $pythonArchive
py -3.14 -m pip --isolated download --only-binary=:all: --dest .\.build\wheels -r (Join-Path $engineRoot 'requirements.lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency download failed.' }
py -3.14 -X utf8 (Join-Path $engineRoot 'build_windows_portable.py') --python-archive $pythonArchive --wheels .\.build\wheels --runtime-out (Join-Path $engineRoot 'runtime')
if ($LASTEXITCODE -ne 0) { throw 'Runtime verification/preparation failed.' }
```

`runtime/` 必须是新目录；若已有经验证的同版运行时，可保留使用，不重复执行准备命令。此步骤不需要 Node，也不构建浏览器界面。可在引擎根目录运行已有测试：

```powershell
Push-Location $engineRoot
try {
    & .\runtime\python.exe -B -m pytest .\tests -q
    if ($LASTEXITCODE -ne 0) { throw 'Engine tests failed.' }
} finally { Pop-Location }
```

## 生成 bundle 与完整 EXE

每次选择新的输出目录；脚本拒绝覆盖旧包：

```powershell
py -3.14 -B -X utf8 .\build_bundle.py --engine $engineRoot --native .\native\bin\Release\net8.0-windows --launcher .\launcher\bin --output .\out\bundle
if ($LASTEXITCODE -ne 0) { throw 'Bundle packaging failed.' }
& .\installer\Build-Setup.ps1 -BundleZip .\out\bundle\QingGuiAI-CAD-0.3.0-bundle.zip -OutputDirectory .\out\installer
```

主要输出为 `out/installer/QingGuiAI-CAD-0.3.0-Setup.exe`，内嵌原生插件、启动/卸载程序、规划引擎、Python 与锁定依赖。`BUNDLE-MANIFEST.json`、`bundle-build.json`、`installer-build.json` 给出逐文件或整包摘要。安装器未加入商业代码签名证书，构建记录为 `signed=false`；它不关闭 Windows 或 AutoCAD 的安全功能。

可先执行不修改 CAD 的安装包检查：

```powershell
$setupPath = (Resolve-Path -LiteralPath '.\out\installer\QingGuiAI-CAD-0.3.0-Setup.exe').Path
$resultPath = Join-Path (Get-Location) 'out\installer-dry-run.json'
$checkProcess = Start-Process -FilePath $setupPath -ArgumentList @('--dry-run','--silent','--result',('"'+$resultPath+'"')) -WindowStyle Hidden -Wait -PassThru
if ($checkProcess.ExitCode -ne 0) { throw 'Installer dry-run failed; inspect the result JSON.' }
```

文件检查通过仍须在 AutoCAD 2025 中验证面板、命令、实体参数、撤销和保存重开。其他 CAD 宿主或版本须分别适配与验收。

## 重打独立源码包

```powershell
py -3.14 -B -X utf8 .\build_source.py --engine $engineRoot --check-only
py -3.14 -B -X utf8 .\build_source.py --engine $engineRoot --output .\out\source
```

`--check-only` 不写文件；源码 ZIP 的 `SOURCE-MANIFEST.json` 给出相对路径、大小和 SHA-256。原生代码按后缀白名单选取，引擎使用仓库 `build_release.files(True)` 白名单。SDK、运行时、构建缓存、用户项目和课程图纸均不入源码包。

编译器、PE 时间戳及依赖打包过程可能使重建二进制摘要不同。本项目不宣称 EXE 位级可复现；公开的历史验收摘要对应当时的 0.3.0 安装包，新构建须生成自己的构建记录。
