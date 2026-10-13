param([switch]$CheckOnly, [switch]$NoBrowser)

# A local, movable launcher. No installation, no hard-coded user paths.
# A server is reused only when its PID belongs to this exact run_server.py
# and its loopback API accepts the token from this project's server.json.
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$serverScript = Join-Path $projectRoot 'run_server.py'
$dataDir = Join-Path $projectRoot 'data'
$stateFile = Join-Path $dataDir 'server.json'
$engineConfig = Join-Path $projectRoot 'local-engine.json'
$launchMutex = $null
$mutexOwned = $false

function Resolve-LocalPath([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return $null }
    if ([IO.Path]::IsPathRooted($Value)) { return [IO.Path]::GetFullPath($Value) }
    return [IO.Path]::GetFullPath((Join-Path $projectRoot $Value))
}

function Test-PythonImports([string]$Executable) {
    $probeInfo = New-Object System.Diagnostics.ProcessStartInfo
    $probeInfo.FileName = $Executable
    $probeInfo.Arguments = '-c "import fastapi, uvicorn, httpx, ezdxf, shapely, jsonschema, win32com.client, win32crypt, multipart"'
    $probeInfo.WorkingDirectory = $projectRoot
    $probeInfo.UseShellExecute = $false
    $probeInfo.CreateNoWindow = $true
    $probeInfo.RedirectStandardOutput = $true
    $probeInfo.RedirectStandardError = $true
    $probe = New-Object System.Diagnostics.Process
    $probe.StartInfo = $probeInfo
    try {
        if (!$probe.Start()) { return $false }
        if (!$probe.WaitForExit(12000)) {
            # This is the short-lived probe created above, never the CAD/server.
            try { $probe.Kill() } catch {}
            return $false
        }
        return $probe.ExitCode -eq 0
    } catch { return $false }
    finally { $probe.Dispose() }
}

function Find-Python {
    $candidates = New-Object 'System.Collections.Generic.List[string]'
    $candidates.Add((Join-Path $projectRoot '.venv\Scripts\python.exe'))
    if (Test-Path -LiteralPath $engineConfig -PathType Leaf) {
        $config = Get-Content -LiteralPath $engineConfig -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($config.python_executable) {
            $configured = Resolve-LocalPath ([string]$config.python_executable)
            if ($configured) { $candidates.Add($configured) }
        }
    }
    $pathPython = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pathPython -and $pathPython.Source) { $candidates.Add($pathPython.Source) }
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (!(Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        if (!(Test-PythonImports $candidate)) { continue }
        $windowless = Join-Path (Split-Path -Parent $candidate) 'pythonw.exe'
        return [PSCustomObject]@{
            executable = $candidate
            background = $(if (Test-Path -LiteralPath $windowless -PathType Leaf) { $windowless } else { $candidate })
        }
    }
    throw 'No ready Python environment was found. Run the existing dependency-check entry, or set python_executable in local-engine.json to a prepared Python environment. Nothing was installed.'
}

function Read-OwnedServer {
    if (!(Test-Path -LiteralPath $stateFile -PathType Leaf)) { return $null }
    try { $record = Get-Content -LiteralPath $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { return $null }
    $serverPid = 0; $serverPort = 0
    if (![int]::TryParse([string]$record.pid, [ref]$serverPid) -or $serverPid -le 0) { return $null }
    if (![int]::TryParse([string]$record.port, [ref]$serverPort) -or $serverPort -lt 1 -or $serverPort -gt 65535) { return $null }
    if ($record.application -ne 'planning-workbench' -or [string]::IsNullOrWhiteSpace([string]$record.token)) { return $null }
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$serverPid" -ErrorAction SilentlyContinue
    if (!$processInfo) { return $null }
    $commandLine = ([string]$processInfo.CommandLine).Replace('/', '\')
    $expectedScript = $serverScript.Replace('/', '\')
    if ($processInfo.Name -notmatch '^pythonw?([0-9.]*)?\.exe$' -or
        $commandLine.IndexOf($expectedScript, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
        throw 'The live service record does not belong to this project. The launcher will not reuse or replace that service. Check this project data/server.json.'
    }
    $baseUrl = 'http://127.0.0.1:' + $serverPort
    $ownedRecord = [PSCustomObject]@{ pid = $serverPid; port = $serverPort; token = [string]$record.token; base_url = $baseUrl; ready = $false }
    try {
        $health = Invoke-RestMethod -Uri ($baseUrl + '/health') -TimeoutSec 3
        if ($health.application -ne 'planning-workbench' -or $health.status -ne 'ok') { return $ownedRecord }
        $example = Invoke-RestMethod -Uri ($baseUrl + '/api/regulatory/example') -Headers @{ 'X-Local-Token' = [string]$record.token } -TimeoutSec 4
        if ($example.kind -ne 'regulatory_parcels') { return $ownedRecord }
        $ownedRecord.ready = $true
        return $ownedRecord
    } catch { return $ownedRecord }
}

try {
    if (!(Test-Path -LiteralPath $serverScript -PathType Leaf)) { throw 'run_server.py is missing. Keep the launcher inside the complete project folder.' }
    $pythonRuntime = Find-Python
    $server = Read-OwnedServer
    if ($CheckOnly) {
        [PSCustomObject]@{ python_ready = $true; project = $projectRoot; server_ready = [bool]($server -and $server.ready); server_belongs_to_project = [bool]$server } | ConvertTo-Json -Compress
        exit 0
    }
    $hash = [Security.Cryptography.SHA256]::Create()
    try { $key = ([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($projectRoot.ToLowerInvariant())))).Replace('-', '').Substring(0,24) }
    finally { $hash.Dispose() }
    $launchMutex = New-Object Threading.Mutex($false, ('Local\PlanningRegulatory_' + $key))
    try { $mutexOwned = $launchMutex.WaitOne(45000) } catch [Threading.AbandonedMutexException] { $mutexOwned = $true }
    if (!$mutexOwned) { throw 'Another launch is still preparing this workbench. Please wait and open it again.' }
    $server = Read-OwnedServer
    $backendProcess = $null
    if (!$server) {
        if (!(Test-Path -LiteralPath $dataDir -PathType Container)) { New-Item -ItemType Directory -Path $dataDir | Out-Null }
        $previousData = $env:PLANNING_DATA_DIR
        $previousUtf8 = $env:PYTHONUTF8
        try {
            $env:PLANNING_DATA_DIR = $dataDir
            $env:PYTHONUTF8 = '1'
            $quotedScript = '"' + $serverScript + '"'
            $backendProcess = Start-Process -FilePath $pythonRuntime.background -ArgumentList @($quotedScript) -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
        } finally {
            $env:PLANNING_DATA_DIR = $previousData
            $env:PYTHONUTF8 = $previousUtf8
        }
    }
    if (!$server -or !$server.ready) {
        $deadline = [DateTime]::UtcNow.AddSeconds(40)
        do {
            Start-Sleep -Milliseconds 350
            $server = Read-OwnedServer
            if ($server -and $server.ready) { break }
            if ($backendProcess -and $backendProcess.HasExited) { throw 'The local service exited before it became ready. Review data/backend.log; no CAD operation was started.' }
        } while ([DateTime]::UtcNow -lt $deadline)
        if (!$server -or !$server.ready) { throw 'The local service did not become ready in time. Review data/backend.log before retrying; the launcher did not stop any existing CAD or server process.' }
    }
    if (!$NoBrowser) {
        $targetUrl = $server.base_url + '/regulatory#token=' + [Uri]::EscapeDataString($server.token)
        Start-Process -FilePath $targetUrl | Out-Null
    }
    if ($NoBrowser) { Write-Output 'Ready: this project regulatory workbench is running on loopback. No browser was opened.' }
} catch {
    $message = $_.Exception.Message
    if ($CheckOnly -or $NoBrowser) { Write-Error $message -ErrorAction Continue }
    else {
        try {
            Add-Type -AssemblyName System.Windows.Forms
            [Windows.Forms.MessageBox]::Show($message, 'Planning Studio - Launch', [Windows.Forms.MessageBoxButtons]::OK, [Windows.Forms.MessageBoxIcon]::Information) | Out-Null
        } catch { Write-Error 'The workbench could not start. Run desktop/LaunchRegulatory.ps1 -CheckOnly for a read-only check.' -ErrorAction Continue }
    }
    exit 1
} finally {
    if ($launchMutex) { if ($mutexOwned) { $launchMutex.ReleaseMutex() }; $launchMutex.Dispose() }
}
