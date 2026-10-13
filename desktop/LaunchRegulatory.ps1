param([switch]$CheckOnly, [switch]$DependenciesOnly, [switch]$NoBrowser, [ValidateSet('main','regulatory')][string]$Page = 'regulatory')

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
    $candidates.Add((Join-Path $projectRoot 'runtime\python.exe'))
    $candidates.Add((Join-Path $projectRoot '.venv\Scripts\python.exe'))
    if (Test-Path -LiteralPath $engineConfig -PathType Leaf) {
        # A copied machine-specific config must not prevent a ready portable
        # runtime from being used. The config itself is never rewritten here.
        try {
            $config = Get-Content -LiteralPath $engineConfig -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($config.python_executable) {
                $configured = Resolve-LocalPath ([string]$config.python_executable)
                if ($configured) { $candidates.Add($configured) }
            }
        } catch {}
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
    throw 'No ready Python environment was found. Run InstallQingGui.ps1, use the complete portable package, or set python_executable in local-engine.json to a prepared Python environment. Nothing was installed by this launcher.'
}

function Read-ServerState {
    # Inspection is read-only, including for copied records of live services.
    # A foreign PID is never contacted and is never a dependency failure.
    $status = [PSCustomObject]@{ state = 'missing'; server = $null }
    if (!(Test-Path -LiteralPath $stateFile -PathType Leaf)) { return $status }
    $status.state = 'invalid'
    try { $record = Get-Content -LiteralPath $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { return $status }
    $serverPid = 0; $serverPort = 0
    if (![int]::TryParse([string]$record.pid, [ref]$serverPid) -or $serverPid -le 0) { return $status }
    if (![int]::TryParse([string]$record.port, [ref]$serverPort) -or $serverPort -lt 1 -or $serverPort -gt 65535) { return $status }
    if ($record.application -ne 'planning-workbench' -or [string]::IsNullOrWhiteSpace([string]$record.token)) { return $status }
    if ($record.root) {
        try {
            $recordRoot = [IO.Path]::GetFullPath([string]$record.root).TrimEnd('\')
            if ($recordRoot -ine $projectRoot.TrimEnd('\')) { $status.state = 'foreign'; return $status }
        } catch { return $status }
    }
    try { $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$serverPid" -ErrorAction Stop }
    catch { $status.state = 'unverifiable'; return $status }
    if (!$processInfo) { $status.state = 'stale'; return $status }
    if ([string]::IsNullOrWhiteSpace([string]$processInfo.CommandLine)) { $status.state = 'unverifiable'; return $status }
    $commandLine = ([string]$processInfo.CommandLine).Replace('/', '\')
    $expectedScript = $serverScript.Replace('/', '\')
    # Require the whole absolute script argument, not a substring path match.
    $scriptArgument = '(?i)(?:^|\s)(?:"' + [Regex]::Escape($expectedScript) + '"|' + [Regex]::Escape($expectedScript) + ')(?=\s|$)'
    if ($processInfo.Name -notmatch '^pythonw?([0-9.]*)?\.exe$' -or
        $commandLine -notmatch $scriptArgument) {
        $status.state = 'foreign'; return $status
    }
    $baseUrl = 'http://127.0.0.1:' + $serverPort
    $ownedRecord = [PSCustomObject]@{ pid = $serverPid; port = $serverPort; token = [string]$record.token; base_url = $baseUrl; ready = $false }
    $status.state = 'owned'; $status.server = $ownedRecord
    try {
        $health = Invoke-RestMethod -Uri ($baseUrl + '/health') -TimeoutSec 3
        if ($health.application -ne 'planning-workbench' -or $health.status -ne 'ok') { return $status }
        $example = Invoke-RestMethod -Uri ($baseUrl + '/api/regulatory/example') -Headers @{ 'X-Local-Token' = [string]$record.token } -TimeoutSec 4
        if ($example.kind -ne 'regulatory_parcels') { return $status }
        $ownedRecord.ready = $true
        return $status
    } catch { return $status }
}

function Preserve-PreviousState {
    if (!(Test-Path -LiteralPath $stateFile -PathType Leaf)) { return }
    $archiveName = 'server.previous-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '-' + [Guid]::NewGuid().ToString('N').Substring(0,8) + '.json'
    $archivePath = [IO.Path]::GetFullPath((Join-Path $dataDir $archiveName))
    if ((Split-Path -Parent $archivePath) -ine [IO.Path]::GetFullPath($dataDir)) { throw 'The previous-state archive must remain inside this project data directory.' }
    # Preserve the exact local state for review; do not edit, stop, or contact
    # the process described by the old record. This runs only under the mutex.
    Move-Item -LiteralPath $stateFile -Destination $archivePath -ErrorAction Stop
}

try {
    if (!(Test-Path -LiteralPath $serverScript -PathType Leaf)) { throw 'run_server.py is missing. Keep the launcher inside the complete project folder.' }
    $pythonRuntime = $null; $dependencyError = $null
    try { $pythonRuntime = Find-Python } catch { $dependencyError = $_.Exception.Message }
    if ($DependenciesOnly) {
        [PSCustomObject]@{ python_ready = [bool]$pythonRuntime; dependency_error = $dependencyError; project = $projectRoot; server_checked = $false; writes_performed = $false } | ConvertTo-Json -Compress
        exit $(if ($pythonRuntime) { 0 } else { 2 })
    }
    $serviceState = Read-ServerState
    $server = $serviceState.server
    if ($CheckOnly) {
        [PSCustomObject]@{ python_ready = [bool]$pythonRuntime; dependency_error = $dependencyError; project = $projectRoot; main_ui_ready = (Test-Path -LiteralPath (Join-Path $projectRoot 'web\dist\index.html') -PathType Leaf); server_ready = [bool]($server -and $server.ready); server_belongs_to_project = [bool]$server; server_state = $serviceState.state; writes_performed = $false } | ConvertTo-Json -Compress
        exit $(if ($pythonRuntime) { 0 } else { 2 })
    }
    if (!$pythonRuntime) { throw $dependencyError }
    $hash = [Security.Cryptography.SHA256]::Create()
    try { $key = ([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($projectRoot.ToLowerInvariant())))).Replace('-', '').Substring(0,24) }
    finally { $hash.Dispose() }
    $launchMutex = New-Object Threading.Mutex($false, ('Local\PlanningRegulatory_' + $key))
    try { $mutexOwned = $launchMutex.WaitOne(45000) } catch [Threading.AbandonedMutexException] { $mutexOwned = $true }
    if (!$mutexOwned) { throw 'Another launch is still preparing this workbench. Please wait and open it again.' }
    $serviceState = Read-ServerState
    if ($serviceState.state -eq 'unverifiable') { throw 'The local service record could not be verified. No service was stopped or replaced. Check read access to the recorded process before retrying.' }
    $server = $serviceState.server
    $backendProcess = $null
    if (!$server) {
        if (!(Test-Path -LiteralPath $dataDir -PathType Container)) { New-Item -ItemType Directory -Path $dataDir | Out-Null }
        Preserve-PreviousState
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
            $serviceState = Read-ServerState
            $server = $serviceState.server
            if ($server -and $server.ready) { break }
            if ($backendProcess -and $backendProcess.HasExited) { throw 'The local service exited before it became ready. Review data/backend.log; no CAD operation was started.' }
        } while ([DateTime]::UtcNow -lt $deadline)
        if (!$server -or !$server.ready) { throw 'The local service did not become ready in time. Review data/backend.log before retrying; the launcher did not stop any existing CAD or server process.' }
    }
    if (!$NoBrowser) {
        $startPath = if ($Page -eq 'main') { '/' } else { '/regulatory' }
        $targetUrl = $server.base_url + $startPath + '#token=' + [Uri]::EscapeDataString($server.token)
        Start-Process -FilePath $targetUrl | Out-Null
    }
    if ($NoBrowser) { Write-Output 'Ready: this project workbench is running on loopback. No browser was opened.' }
} catch {
    $message = $_.Exception.Message
    if ($CheckOnly -or $DependenciesOnly -or $NoBrowser) { Write-Error $message -ErrorAction Continue }
    else {
        try {
            Add-Type -AssemblyName System.Windows.Forms
            [Windows.Forms.MessageBox]::Show($message, 'QingGui AI - Launch', [Windows.Forms.MessageBoxButtons]::OK, [Windows.Forms.MessageBoxIcon]::Information) | Out-Null
        } catch { Write-Error 'The workbench could not start. Run desktop/LaunchRegulatory.ps1 -CheckOnly for a read-only check.' -ErrorAction Continue }
    }
    exit 1
} finally {
    if ($launchMutex) { if ($mutexOwned) { $launchMutex.ReleaseMutex() }; $launchMutex.Dispose() }
}
