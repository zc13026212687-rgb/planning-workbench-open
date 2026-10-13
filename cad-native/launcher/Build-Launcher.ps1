param([string]$OutputDirectory = (Join-Path $PSScriptRoot 'bin'))
$ErrorActionPreference = 'Stop'
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $csc)) { throw 'Windows .NET Framework compiler is unavailable.' }
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$shared = Join-Path $PSScriptRoot 'Shared.cs'
$manifest = Join-Path (Split-Path $PSScriptRoot) 'installer\app.manifest'
& (Join-Path $PSScriptRoot 'Build-Icon.ps1')
$icon=Join-Path $PSScriptRoot 'QingGuiAI.ico'
$common = @('/nologo','/target:winexe','/platform:x64','/optimize+','/codepage:65001',('/win32manifest:'+$manifest),('/win32icon:'+$icon),'/r:System.Windows.Forms.dll','/r:System.Drawing.dll','/r:System.Web.Extensions.dll','/r:Microsoft.CSharp.dll')
foreach ($item in @(@('Launcher.cs','QingGuiAI.Launcher.exe'),@('Uninstall.cs','QingGuiAI.Uninstall.exe'))) {
    $output = Join-Path $OutputDirectory $item[1]
    & $csc @common ('/out:'+$output) $shared (Join-Path $PSScriptRoot $item[0])
    if ($LASTEXITCODE -ne 0) { throw "Compilation failed: $($item[0])" }
}
[IO.File]::WriteAllText((Join-Path $OutputDirectory 'QingGuiStart.scr'), "QGOPEN`r`n", [Text.Encoding]::ASCII)
[IO.File]::WriteAllText((Join-Path $OutputDirectory 'QingGuiSelfTest.scr'), "QGOPEN`r`nQGSELFTEST`r`n", [Text.Encoding]::ASCII)
Get-ChildItem -LiteralPath $OutputDirectory | Select-Object Name,Length
