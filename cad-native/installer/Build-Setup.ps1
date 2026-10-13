param([Parameter(Mandatory=$true)][string]$BundleZip,[Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
$payload = (Resolve-Path -LiteralPath $BundleZip).Path
$destination = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $destination -Force | Out-Null
$exe = Join-Path $destination 'QingGuiAI-CAD-0.3.0-Setup.exe'
if (Test-Path -LiteralPath $exe) { throw "Refusing to overwrite existing installer: $exe" }
$hash = (Get-FileHash -LiteralPath $payload -Algorithm SHA256).Hash.ToLowerInvariant()
$buildInfo = Join-Path $destination 'BuildInfo.g.cs'
[IO.File]::WriteAllText($buildInfo, ('namespace QingGuiAI { internal static class BuildInfo { internal const string PayloadSha256 = "'+$hash+'"; } }'), [Text.UTF8Encoding]::new($false))
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$shared = Join-Path (Split-Path $PSScriptRoot) 'launcher\Shared.cs'
$icon=Join-Path (Split-Path $PSScriptRoot) 'launcher\QingGuiAI.ico'
if (-not (Test-Path -LiteralPath $icon)) { & (Join-Path (Split-Path $PSScriptRoot) 'launcher\Build-Icon.ps1') }
$args = @('/nologo','/target:winexe','/platform:x64','/optimize+','/codepage:65001',('/win32manifest:'+(Join-Path $PSScriptRoot 'app.manifest')),('/win32icon:'+$icon),('/out:'+$exe),('/resource:'+$payload+',QingGuiAI.Payload.zip'),'/r:System.Windows.Forms.dll','/r:System.Drawing.dll','/r:System.Web.Extensions.dll','/r:System.IO.Compression.dll','/r:System.IO.Compression.FileSystem.dll','/r:Microsoft.CSharp.dll')
& $csc @args $shared (Join-Path $PSScriptRoot 'Setup.cs') $buildInfo
if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
$metadata = [ordered]@{ product='清规AI · CAD原生插件'; version='0.3.0'; file=(Split-Path $exe -Leaf); bytes=(Get-Item -LiteralPath $exe).Length; sha256=(Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant(); payload_sha256=$hash; signed=$false }
$metadata | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $destination 'installer-build.json') -Encoding UTF8
$metadata | ConvertTo-Json
