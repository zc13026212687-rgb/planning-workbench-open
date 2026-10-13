param([switch]$CheckOnly, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$launchFile = Join-Path $PSScriptRoot 'LaunchRegulatory.ps1'
$mainReady = Test-Path -LiteralPath (Join-Path $projectRoot 'web\dist\index.html') -PathType Leaf
$startPage = if ($mainReady) { 'main' } else { 'regulatory' }
if (!$mainReady -and !$CheckOnly -and !$NoBrowser) {
    Add-Type -AssemblyName System.Windows.Forms
    [Windows.Forms.MessageBox]::Show('主工作台界面尚未构建，本次先打开地块与图则。完整道路和横断面界面需要运行“安装清规AI.cmd”，或使用包含已构建界面的便携包。', '清规AI · 部分界面可用', [Windows.Forms.MessageBoxButtons]::OK, [Windows.Forms.MessageBoxIcon]::Information) | Out-Null
}
& $launchFile -CheckOnly:$CheckOnly -NoBrowser:$NoBrowser -Page $startPage
