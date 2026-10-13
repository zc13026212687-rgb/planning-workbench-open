param([switch]$CheckOnly, [switch]$NoLaunch, [switch]$NoShortcut)

# Current-user setup for a complete source/portable folder. Existing prepared
# environments are read-only. Missing dependencies are installed ONLY into
# this project's .venv. No system Python or execution-policy changes.
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$launcher = Join-Path $PSScriptRoot 'LaunchQingGui.ps1'
$dependencyProbe = Join-Path $PSScriptRoot 'LaunchRegulatory.ps1'
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$requirements = Join-Path $projectRoot 'requirements.lock.txt'
$desktopFolder = [Environment]::GetFolderPath('Desktop')
$shortcutBase = '清规AI · PlanningWorkbench Open 0.2.0'
$powershellExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$env:PYTHONUTF8 = '1'
Set-Location -LiteralPath $projectRoot

function Ready-Report {
    # This checks only imports. Copied/stale service metadata must never be
    # treated as missing Python or trigger dependency installation.
    $probeInfo = New-Object Diagnostics.ProcessStartInfo
    $probeInfo.FileName = $powershellExe
    $probeInfo.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $dependencyProbe + '" -DependenciesOnly'
    $probeInfo.WorkingDirectory = $projectRoot
    $probeInfo.UseShellExecute = $false
    $probeInfo.CreateNoWindow = $true
    $probeInfo.RedirectStandardOutput = $true
    $probeInfo.RedirectStandardError = $true
    $probeProcess = New-Object Diagnostics.Process
    $probeProcess.StartInfo = $probeInfo
    try {
        if (!$probeProcess.Start()) { throw '无法启动依赖检查进程，未尝试安装软件包。' }
        if (!$probeProcess.WaitForExit(55000)) { try { $probeProcess.Kill() } catch {}; throw '依赖检查超时，未据此判断缺少 Python，也未尝试安装软件包。' }
        $outputText = $probeProcess.StandardOutput.ReadToEnd()
        if ($probeProcess.ExitCode -notin @(0,2)) { throw ('依赖检查程序异常退出（' + $probeProcess.ExitCode + '），未尝试安装软件包。请运行 desktop/LaunchRegulatory.ps1 -DependenciesOnly 查看详情。') }
        $report = $outputText | ConvertFrom-Json
        if (!$report -or $report.PSObject.Properties.Name -notcontains 'python_ready') { throw '依赖检查返回格式无效，未尝试安装软件包。' }
        return $report
    }
    finally { $probeProcess.Dispose() }
}

function Native-Checked([string]$Program, [string[]]$ArgumentArray) {
    & $Program @ArgumentArray
    if ($LASTEXITCODE -ne 0) { throw ('依赖准备未完成：' + [IO.Path]::GetFileName($Program) + ' 返回 ' + $LASTEXITCODE + '。请保留上方错误，修复网络或环境后再次运行；现有资料未删除。') }
}

function Find-BasePython {
    $candidates = New-Object 'System.Collections.Generic.List[string]'
    $candidates.Add((Join-Path $projectRoot 'runtime\python.exe'))
    $candidates.Add($venvPython)
    $configPath = Join-Path $projectRoot 'local-engine.json'
    if (Test-Path -LiteralPath $configPath -PathType Leaf) {
        try {
            $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($config.python_executable) {
                $path = [string]$config.python_executable
                if (![IO.Path]::IsPathRooted($path)) { $path = Join-Path $projectRoot $path }
                $candidates.Add([IO.Path]::GetFullPath($path))
            }
        } catch { Write-Host '[提示] 本机 local-engine.json 无法读取；继续检查便携环境及其他 Python，不改写此配置。' -ForegroundColor Yellow }
    }
    $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        try {
            $located = & $pyLauncher.Source -3.14 -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $located) { $candidates.Add(([string]$located).Trim()) }
        } catch {}
    }
    $pathPython = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pathPython) { $candidates.Add($pathPython.Source) }
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (!(Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        try {
            $versionText = & $candidate -c 'import sys,venv; print(str(sys.version_info.major)+chr(46)+str(sys.version_info.minor))' 2>$null
            if ($LASTEXITCODE -eq 0 -and ([string]$versionText).Trim() -eq '3.14') { return $candidate }
        } catch {}
    }
    if (Test-Path -LiteralPath (Join-Path $projectRoot 'runtime\python.exe') -PathType Leaf) {
        throw '发现 runtime/python.exe，但其依赖尚未就绪，且没有可创建 .venv 的 Python 3.14。请重新完整解压便携包，或安装 Python 3.14 后重试。现有 runtime 未被修改。'
    }
    throw '未找到已准备好的运行环境，也未找到用于源码安装的 Python 3.14。可下载含 runtime 的完整便携包；或先安装 Python 3.14，再双击本入口。此脚本不会自动下载系统安装程序。'
}

function Ensure-Dependencies {
    $ready = Ready-Report
    if ($ready -and $ready.python_ready) { Write-Host '[就绪] 复用现有 Python 环境，不修改其中的软件包。' -ForegroundColor Green; return }
    $basePython = Find-BasePython
    if (!(Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        Write-Host '[准备] 在当前工程中创建 .venv，不修改系统 Python。' -ForegroundColor Cyan
        Native-Checked $basePython @('-m','venv',(Join-Path $projectRoot '.venv'))
    }
    $venvVersion = & $venvPython -c 'import sys; print(str(sys.version_info.major)+chr(46)+str(sys.version_info.minor))' 2>$null
    if ($LASTEXITCODE -ne 0 -or ([string]$venvVersion).Trim() -ne '3.14') {
        throw '当前工程的 .venv 不是所需 Python 3.14 环境，未改写或删除它。请先自行备份并重命名旧 .venv 后重试，或使用含 runtime 的完整便携包。'
    }
    Write-Host '[准备] 按 requirements.lock.txt 安装本工程依赖，首次需要网络。' -ForegroundColor Cyan
    Native-Checked $venvPython @('-m','ensurepip')
    Native-Checked $venvPython @('-m','pip','--disable-pip-version-check','install','--no-input','-r',$requirements)
    $ready = Ready-Report
    if (!$ready -or !$ready.python_ready) { throw '软件包安装已返回，但依赖导入检查仍未通过。请检查 Python 版本和上方输出；没有创建快捷方式。' }
}

function Ensure-Web {
    $webEntry = Join-Path $projectRoot 'web\dist\index.html'
    if (Test-Path -LiteralPath $webEntry -PathType Leaf) { Write-Host '[就绪] 完整主工作台界面已包含。' -ForegroundColor Green; return $true }
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (!$npm) {
        Write-Host '[部分可用] 未提供 web/dist 且没有 npm；可使用地块与图则页。道路/断面完整界面需要安装 Node.js 后重新运行，或使用便携包。' -ForegroundColor Yellow
        return $false
    }
    Write-Host '[准备] 依据前端锁文件构建完整主界面，首次可能需要网络。' -ForegroundColor Cyan
    Native-Checked $npm.Source @('ci','--prefix',(Join-Path $projectRoot 'web'))
    Native-Checked $npm.Source @('run','build','--prefix',(Join-Path $projectRoot 'web'))
    if (!(Test-Path -LiteralPath $webEntry -PathType Leaf)) { throw '前端构建未生成 web/dist/index.html，请查看上方构建输出。' }
    return $true
}

function Create-DesktopShortcut {
    if ([string]::IsNullOrWhiteSpace($desktopFolder) -or !(Test-Path -LiteralPath $desktopFolder -PathType Container)) { throw '无法定位当前用户桌面；请使用工程内“启动清规AI.cmd”启动。' }
    $shell = New-Object -ComObject WScript.Shell
    try {
        $shortcutPath = Join-Path $desktopFolder ($shortcutBase + '.lnk')
        $suffix = 2
        while (Test-Path -LiteralPath $shortcutPath) {
            $old = $shell.CreateShortcut($shortcutPath)
            $isSameProject = ([string]$old.WorkingDirectory).TrimEnd('\') -ieq $projectRoot.TrimEnd('\') -and ([string]$old.Arguments).Contains($launcher)
            if ($isSameProject) { break }
            $shortcutPath = Join-Path $desktopFolder ($shortcutBase + ' (' + $suffix + ').lnk'); $suffix++
        }
        $shortcut = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = $powershellExe
        $shortcut.Arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $launcher + '"'
        $shortcut.WorkingDirectory = $projectRoot
        $shortcut.Description = '清规AI：道路、横断面、地块指标与图则的本地工作台'
        $shortcut.WindowStyle = 7
        $nativeIcon = Join-Path $projectRoot 'desktop\publish\PlanningStudio.exe'
        $shortcut.IconLocation = $(if (Test-Path -LiteralPath $nativeIcon -PathType Leaf) { $nativeIcon + ',0' } else { (Join-Path $env:SystemRoot 'System32\shell32.dll') + ',21' })
        $shortcut.Save()
        $readback = $shell.CreateShortcut($shortcutPath)
        if ($readback.TargetPath -ine $powershellExe -or $readback.Arguments -notlike ('*' + $launcher + '*')) { throw '快捷方式回读与当前工程不一致，未尝试启动。' }
        return $shortcutPath
    } finally { if ($shell) { [Runtime.InteropServices.Marshal]::ReleaseComObject($shell) | Out-Null } }
}

try {
    foreach ($required in @('run_server.py','requirements.lock.txt','web\regulatory.html','desktop\LaunchQingGui.ps1')) {
        if (!(Test-Path -LiteralPath (Join-Path $projectRoot $required) -PathType Leaf)) { throw ('完整工程缺少 ' + $required + '。请完整解压后运行，不要在压缩包预览窗口内直接启动。') }
    }
    if ($CheckOnly) {
        $ready = Ready-Report
        [PSCustomObject]@{ application='清规AI'; version='0.2.0'; project=$projectRoot; python_ready=[bool]($ready -and $ready.python_ready); main_ui_ready=(Test-Path -LiteralPath (Join-Path $projectRoot 'web\dist\index.html')); regulatory_ui_ready=$true; desktop_resolved=(![string]::IsNullOrWhiteSpace($desktopFolder)); writes_performed=$false } | ConvertTo-Json -Compress
        exit $(if ($ready -and $ready.python_ready) { 0 } else { 2 })
    }
    Write-Host '清规AI · PlanningWorkbench Open 0.2.0' -ForegroundColor Cyan
    Write-Host '仅准备当前工程依赖和当前用户桌面入口；保留原有项目、图纸和配置。'
    Ensure-Dependencies
    $mainReady = Ensure-Web
    if (!$NoShortcut) { $createdShortcut = Create-DesktopShortcut; Write-Host ('[完成] 桌面入口：' + $createdShortcut) -ForegroundColor Green }
    Write-Host $(if ($mainReady) { '[就绪] 完整主工作台可启动。' } else { '[部分就绪] 地块与图则页可启动；完整主界面待构建。' }) -ForegroundColor $(if ($mainReady) {'Green'} else {'Yellow'})
    if (!$NoLaunch) {
        Start-Process -FilePath $powershellExe -ArgumentList @('-NoProfile','-WindowStyle','Hidden','-ExecutionPolicy','Bypass','-File',('"'+$launcher+'"')) -WorkingDirectory $projectRoot -WindowStyle Hidden | Out-Null
    }
    exit 0
} catch {
    Write-Host ('[未完成] ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host '已有资料和正在使用的 CAD 均未关闭。可修复上述缺项后重试；也可使用含运行时的完整便携包。' -ForegroundColor Yellow
    exit 1
}
