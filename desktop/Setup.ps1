param([switch]$Install, [switch]$Rebuild)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:PYTHONUTF8 = '1'
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
$pythonWindowless = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
$desktopExe = Join-Path $projectRoot 'desktop\publish\PlanningStudio.exe'
$webEntry = Join-Path $projectRoot 'web\dist\index.html'
$lockFile = Join-Path $projectRoot 'requirements.lock.txt'
$issues = [System.Collections.Generic.List[string]]::new()
function Report([string]$Name, [bool]$Ready, [string]$Detail) {
    if ($Ready) { Write-Host ('[OK] ' + $Name + ' - ' + $Detail) -ForegroundColor Green }
    else { Write-Host ('[MISSING] ' + $Name + ' - ' + $Detail) -ForegroundColor Yellow; $issues.Add($Name) }
}
function NativeChecked([string]$Executable, [string[]]$Arguments) {
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw ('Command failed: ' + [IO.Path]::GetFileName($Executable) + '; exit ' + $LASTEXITCODE) }
}
if ($Install) {
    if (!(Test-Path -LiteralPath $pythonExe)) {
        $pyCommand = Get-Command py.exe -ErrorAction SilentlyContinue
        if (!$pyCommand) { throw 'Python 3.14 launcher is required to create the tested environment. Install Python first; this script does not modify global runtimes.' }
        NativeChecked $pyCommand.Source @('-3.14','-m','venv',(Join-Path $projectRoot '.venv'))
    }
    NativeChecked $pythonExe @('-m','ensurepip','--upgrade')
    NativeChecked $pythonExe @('-m','pip','install','-r',$lockFile)
    if ($Rebuild -or !(Test-Path -LiteralPath $webEntry)) {
        $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
        if (!$npmCommand) { throw 'Node.js and npm are required to build missing web assets.' }
        NativeChecked $npmCommand.Source @('ci','--prefix',(Join-Path $projectRoot 'web'))
        NativeChecked $npmCommand.Source @('run','build','--prefix',(Join-Path $projectRoot 'web'))
    }
    if ($Rebuild -or !(Test-Path -LiteralPath $desktopExe)) {
        $sdk = Get-Command dotnet.exe -ErrorAction SilentlyContinue
        if (!$sdk) { throw '.NET 10 SDK is required to build the desktop host.' }
        NativeChecked $sdk.Source @('publish',(Join-Path $projectRoot 'desktop\PlanningStudio.csproj'),'--configuration','Release','--output',(Join-Path $projectRoot 'desktop\publish'))
    }
}
Write-Host 'Planning Studio dependency check (read-only unless -Install is supplied)' -ForegroundColor Cyan
Report 'Desktop executable' (Test-Path -LiteralPath $desktopExe) 'desktop/publish/PlanningStudio.exe'
Report 'Web assets' (Test-Path -LiteralPath $webEntry) 'web/dist/index.html'
$pythonReady = (Test-Path -LiteralPath $pythonExe) -and (Test-Path -LiteralPath $pythonWindowless)
if ($pythonReady) {
    & $pythonExe '-c' 'import fastapi, uvicorn, httpx, ezdxf, shapely, jsonschema, win32com.client, win32crypt, multipart; print(True)'
    $pythonReady = $LASTEXITCODE -eq 0
}
Report 'Project Python and imports' $pythonReady '.venv, backend libraries and Windows CAD COM support'
$dotnet = Get-Command dotnet.exe -ErrorAction SilentlyContinue
$desktopRuntime = $false
if ($dotnet) { $installedRuntimes = & $dotnet.Source --list-runtimes; $desktopRuntime = @($installedRuntimes -match '^Microsoft.WindowsDesktop.App 10\.').Count -gt 0 }
Report '.NET Desktop Runtime 10' $desktopRuntime 'Required by this framework-dependent desktop build'
$webViewPresent = $false
foreach ($base in @(${env:ProgramFiles(x86)}, $env:ProgramFiles, $env:LOCALAPPDATA)) {
    if (!$base) { continue }
    $edgeRoot = Join-Path $base 'Microsoft\EdgeWebView\Application'
    if (Test-Path -LiteralPath $edgeRoot) {
        foreach ($version in Get-ChildItem -LiteralPath $edgeRoot -Directory -ErrorAction SilentlyContinue) {
            if (Test-Path -LiteralPath (Join-Path $version.FullName 'msedgewebview2.exe')) { $webViewPresent = $true; break }
        }
    }
}
Report 'WebView2 Runtime discovery' $webViewPresent 'File discovery only; the desktop cold-start verifies actual rendering'
if ($issues.Count) {
    Write-Host ('Missing or unresolved: ' + ($issues -join ', ')) -ForegroundColor Yellow
    Write-Host 'Install only project dependencies / missing builds with: desktop\Setup.ps1 -Install'
    Write-Host 'Force both builds with: desktop\Setup.ps1 -Install -Rebuild (close this app first).'
    exit 1
}
Write-Host 'Dependencies ready. Open the existing desktop/publish/PlanningStudio.exe or the root launch entry.' -ForegroundColor Green
exit 0

