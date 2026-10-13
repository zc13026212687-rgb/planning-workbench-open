[CmdletBinding()]
param(
    [ValidateSet('codex','claude','openclaw')][string]$Client = 'codex',
    [string]$SkillsDirectory,
    [switch]$SkipCadInstall,
    [string]$EnginePath,
    [switch]$SkipMcpRegistration,
    [string]$ReceiptDirectory
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$PackageRoot = Split-Path -Parent $PSScriptRoot
$ExpectedSetupHash = '964a7f192da324c7c1d688dbec2511aac11b34f247a07b64c3e44bd9297ce365'
$ExpectedPayloadHash = '3ee14655a68c7bccc2c474816a818e576422e35bddb833555207a8fea81d14d1'
$Bundle = Join-Path $env:APPDATA 'Autodesk\ApplicationPlugins\QingGuiAI.bundle'
$Utf8 = New-Object System.Text.UTF8Encoding($false)

function Assert-PlainPath([string]$Path) {
    $itemPath = [IO.Path]::GetFullPath($Path)
    while ($itemPath) {
        if (Test-Path -LiteralPath $itemPath) {
            $item = Get-Item -LiteralPath $itemPath -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Symbolic link or junction is not an installation target: $itemPath"
            }
        }
        $parent = Split-Path -Parent $itemPath
        if ($parent -eq $itemPath) { break }
        $itemPath = $parent
    }
}

function Write-Json([string]$Path, $Value) {
    [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 30), $Utf8)
}

function Test-InstalledBundle {
    $receiptPath = Join-Path $Bundle 'qinggui-install-receipt.json'
    if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) { return $false }
    Assert-PlainPath $Bundle
    try { $receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { return $false }
    if ($receipt.Identity -ne 'QingGuiAI.CAD.Native' -or $receipt.PayloadSha256 -ne $ExpectedPayloadHash) { return $false }
    if (-not $receipt.Files -or @($receipt.Files.PSObject.Properties).Count -lt 5) { return $false }
    $prefix = [IO.Path]::GetFullPath($Bundle).TrimEnd('\') + '\'
    $required = @('PackageContents.xml','Contents/Windows/QingGuiAI.Cad.dll','Contents/Engine/runtime/python.exe','Contents/Engine/planning_cli.py','Contents/Engine/planning_mcp.py')
    foreach ($name in $required) {
        if (-not $receipt.Files.PSObject.Properties[$name]) { return $false }
    }
    foreach ($entry in $receipt.Files.PSObject.Properties) {
        $path = [IO.Path]::GetFullPath((Join-Path $Bundle $entry.Name))
        if (-not $path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { return $false }
        Assert-PlainPath $path
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $false }
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.Value) { return $false }
    }
    return $true
}

function Invoke-Client([string]$Executable, [string[]]$Arguments) {
    $oldPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $lines = @(& $Executable @Arguments 2>&1)
        $code = $LASTEXITCODE
        # Native stderr is an ErrorRecord in Windows PowerShell. Keep it out
        # of machine-readable JSON and never print client configuration.
        $capture = ($lines | Where-Object { $_ -is [string] } | Out-String)
        return @{ ExitCode = $code; Output = $capture }
    } finally { $ErrorActionPreference = $oldPreference }
}

function Test-SameTarget($Entry, [string]$Python, [string]$McpScript) {
    if (-not $Entry) { return $false }
    if ($Entry.PSObject.Properties['transport']) { $Entry = $Entry.transport }
    if (-not $Entry.PSObject.Properties['command'] -or -not $Entry.PSObject.Properties['args']) { return $false }
    return ($Entry.command -eq $Python -and (@($Entry.args) -join "`n") -eq (@('-B','-u',$McpScript) -join "`n"))
}

function Register-Mcp([string]$Python, [string]$McpScript, [string]$StatePath) {
    $configuration = @{ mcpServers = @{ 'qinggui-cad' = @{ command = $Python; args = @('-B','-u',$McpScript) } } }
    $example = Join-Path $StatePath 'mcp-configuration.example.json'
    Write-Json $example $configuration
    if ($SkipMcpRegistration) { return @{ status = 'skipped_by_request'; example = $example } }
    if ($Client -eq 'openclaw') {
        return @{ status = 'skills_cli_ready'; note = 'OpenClaw uses the installed skill run.py; no unsupported MCP configuration was written.' }
    }
    $cli = Get-Command $Client -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $cli) { return @{ status = 'needs_client_registration'; reason = 'Client CLI is not installed or not on PATH'; example = $example } }
    $help = Invoke-Client $cli.Source @('mcp','add','--help')
    if ($help.ExitCode -ne 0 -or $help.Output -notmatch 'mcp add') {
        return @{ status = 'needs_client_registration'; reason = 'Installed client MCP command could not be confirmed'; example = $example }
    }
    if ($Client -eq 'codex') {
        $listing = Invoke-Client $cli.Source @('mcp','list','--json')
        if ($listing.ExitCode -ne 0) { return @{ status = 'needs_client_registration'; reason = 'Cannot safely inspect existing Codex MCP configuration'; example = $example } }
        try { $entries = ConvertFrom-Json -InputObject $listing.Output }
        catch { return @{ status = 'needs_client_registration'; reason = 'Codex MCP inventory was not JSON'; example = $example } }
        $existing = @(foreach ($entry in $entries) {
            if ($null -ne $entry -and $entry.PSObject.Properties['name'] -and $entry.name -eq 'qinggui-cad') { $entry }
        })
        if ($existing.Count) {
            if ($existing[0].PSObject.Properties['enabled'] -and -not $existing[0].enabled) {
                return @{ status = 'needs_client_registration'; reason = 'Existing qinggui-cad is disabled; its user setting was preserved'; example = $example }
            }
            if (Test-SameTarget $existing[0] $Python $McpScript) { return @{ status = 'already_registered'; server = 'qinggui-cad' } }
            return @{ status = 'name_conflict_unchanged'; server = 'qinggui-cad'; example = $example }
        }
        $added = Invoke-Client $cli.Source @('mcp','add','qinggui-cad','--',$Python,'-B','-u',$McpScript)
        if ($added.ExitCode -ne 0) { return @{ status = 'needs_client_registration'; reason = 'Codex official add command failed; existing servers were not replaced'; example = $example } }
        $check = Invoke-Client $cli.Source @('mcp','get','qinggui-cad','--json')
        if ($check.ExitCode -eq 0) {
            try { if (Test-SameTarget ($check.Output | ConvertFrom-Json) $Python $McpScript) { return @{ status = 'registered'; server = 'qinggui-cad'; verified = $true } } } catch {}
        }
        return @{ status = 'needs_client_registration'; reason = 'Post-registration command and arguments could not be verified'; example = $example }
    }
    # Claude has no get --json. Inspect only its documented user config, then
    # use the official add command and read back that one new entry.
    if ($env:CLAUDE_CONFIG_DIR) {
        return @{ status = 'needs_client_registration'; reason = 'Custom CLAUDE_CONFIG_DIR requires explicit client registration'; example = $example }
    }
    $claudeConfig = Join-Path $env:USERPROFILE '.claude.json'
    $config = $null
    if (Test-Path -LiteralPath $claudeConfig) {
        try { $config = Get-Content -LiteralPath $claudeConfig -Raw -Encoding UTF8 | ConvertFrom-Json }
        catch { return @{ status = 'needs_client_registration'; reason = 'Cannot parse existing Claude user configuration'; example = $example } }
    }
    $existing = $null
    if ($config -and $config.PSObject.Properties['mcpServers']) { $existing = $config.mcpServers.PSObject.Properties['qinggui-cad'] }
    if ($existing) {
        if (Test-SameTarget $existing.Value $Python $McpScript) { return @{ status = 'already_registered'; server = 'qinggui-cad' } }
        return @{ status = 'name_conflict_unchanged'; server = 'qinggui-cad'; example = $example }
    }
    # Do not shadow a project-local server with the same name.
    $scan = (Get-Location).Path
    while ($scan) {
        $projectFile = Join-Path $scan '.mcp.json'
        if (Test-Path -LiteralPath $projectFile) {
            try {
                $project = Get-Content -LiteralPath $projectFile -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($project.PSObject.Properties['mcpServers'] -and $project.mcpServers.PSObject.Properties['qinggui-cad']) {
                    return @{ status = 'name_conflict_unchanged'; reason = 'Project-local qinggui-cad exists'; example = $example }
                }
            } catch { return @{ status = 'needs_client_registration'; reason = 'Cannot inspect project-local MCP configuration'; example = $example } }
        }
        $next = Split-Path -Parent $scan
        if ($next -eq $scan) { break }
        $scan = $next
    }
    if ($config -and $config.PSObject.Properties['projects']) {
        foreach ($projectEntry in $config.projects.PSObject.Properties) {
            if ($projectEntry.Value.PSObject.Properties['mcpServers'] -and $projectEntry.Value.mcpServers.PSObject.Properties['qinggui-cad']) {
                return @{ status = 'name_conflict_unchanged'; reason = 'An existing Claude project owns qinggui-cad'; example = $example }
            }
        }
    }
    $added = Invoke-Client $cli.Source @('mcp','add','--scope','user','--transport','stdio','qinggui-cad','--',$Python,'-B','-u',$McpScript)
    if ($added.ExitCode -eq 0 -and (Test-Path -LiteralPath $claudeConfig)) {
        try {
            $verified = Get-Content -LiteralPath $claudeConfig -Raw -Encoding UTF8 | ConvertFrom-Json
            if (Test-SameTarget $verified.mcpServers.'qinggui-cad' $Python $McpScript) { return @{ status = 'registered'; server = 'qinggui-cad'; verified = $true } }
        } catch {}
    }
    return @{ status = 'needs_client_registration'; reason = 'Claude official add/readback did not complete'; example = $example }
}

$report = [ordered]@{ product = 'QingGuiAI Starter'; version = '0.3.1'; client = $Client; status = 'starting'; cad = 'not_checked'; skills = $null; doctor = $null; mcp = $null;
    evidence_layers = @{ skill_files_installed = 'not_tested'; engine_case_verified = 'not_tested'; mcp_protocol_verified = 'not_tested'; client_registration = 'not_tested'; client_tools_discovered = 'not_tested'; cad_roundtrip_verified = 'not_tested' } }
$state = $null
try {
    if (-not $SkillsDirectory) {
        switch ($Client) {
            'codex' { $SkillsDirectory = Join-Path $env:USERPROFILE '.agents\skills' }
            'claude' { $SkillsDirectory = Join-Path $env:USERPROFILE '.claude\skills' }
            'openclaw' {
                if ($env:OPENCLAW_STATE_DIR) { $SkillsDirectory = Join-Path $env:OPENCLAW_STATE_DIR 'skills' }
                else { $SkillsDirectory = Join-Path $env:USERPROFILE '.openclaw\skills' }
            }
        }
    }
    $SkillsDirectory = [IO.Path]::GetFullPath($SkillsDirectory)
    Assert-PlainPath $SkillsDirectory
    if (-not $ReceiptDirectory) { $ReceiptDirectory = Join-Path $env:LOCALAPPDATA 'QingGuiAI\Starter\receipts' }
    Assert-PlainPath $ReceiptDirectory
    $state = Join-Path $ReceiptDirectory ((Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssfffffffZ') + '-' + [Guid]::NewGuid().ToString('N').Substring(0,8))
    [IO.Directory]::CreateDirectory($state) | Out-Null
    Write-Host 'QingGuiAI Starter 0.3.1 - local setup and read-only engine checks'
    if ($SkipCadInstall) { $report.cad = 'skipped_by_request' }
    elseif (Test-InstalledBundle) {
        $report.cad = 'already_installed_all_receipt_hashes_verified'
        Write-Host 'Native CAD plugin is already current; loaded DLLs will not be replaced.'
    } else {
        $setup = Join-Path $PackageRoot 'payload\QingGuiAI-CAD-0.3.0-Setup.exe'
        if (-not (Test-Path -LiteralPath $setup -PathType Leaf)) { throw 'Missing offline payload. Download and fully extract the Starter release ZIP; a GitHub source ZIP alone does not contain the CAD runtime.' }
        Assert-PlainPath $setup
        if ((Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedSetupHash) { throw 'CAD installer SHA-256 differs from the pinned release. Nothing was executed.' }
        Write-Host 'Verified CAD installer. Installing original plugin through its native installer...'
        $process = Start-Process -FilePath $setup -ArgumentList @('--install','--silent') -WindowStyle Hidden -Wait -PassThru
        if ($process.ExitCode -ne 0) { throw ('Native installer failed with exit code ' + $process.ExitCode + '. If an older plugin is loaded, save your drawings and close its CAD instance before updating.') }
        if (-not (Test-InstalledBundle)) { throw 'Native installer finished but installed file hashes did not verify.' }
        $report.cad = 'installed_all_receipt_hashes_verified'
    }
    if (-not $EnginePath) { $EnginePath = Join-Path $Bundle 'Contents\Engine' }
    $EnginePath = [IO.Path]::GetFullPath($EnginePath)
    Assert-PlainPath $EnginePath
    $python = Join-Path $EnginePath 'runtime\python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Bundled engine Python was not found. Use -EnginePath only for a verified existing engine.' }
    $doctorReceipt = Join-Path $state 'doctor.json'
    & $python -B (Join-Path $PSScriptRoot 'doctor.py') --engine $EnginePath --python $python --receipt $doctorReceipt
    if ($LASTEXITCODE -ne 0) { throw 'Local engine doctor failed; skills and AI client registration were not changed.' }
    $report.doctor = Get-Content -LiteralPath $doctorReceipt -Raw -Encoding UTF8 | ConvertFrom-Json
    $report.evidence_layers.engine_case_verified = 'passed'
    $report.evidence_layers.mcp_protocol_verified = 'passed'
    $skillsReceipt = Join-Path $state 'skills.json'
    & $python -B (Join-Path $PSScriptRoot 'install_portable_skills.py') --source (Join-Path $PackageRoot 'share-skills') --dest $SkillsDirectory --engine $EnginePath --python $python --receipt $skillsReceipt
    if ($LASTEXITCODE -ne 0) { throw 'Skills install failed. Existing managed skills were preserved or rolled back; see transaction receipts.' }
    $report.skills = Get-Content -LiteralPath $skillsReceipt -Raw -Encoding UTF8 | ConvertFrom-Json
    $report.evidence_layers.skill_files_installed = 'passed'
    $report.mcp = Register-Mcp $python (Join-Path $EnginePath 'planning_mcp.py') $state
    $report.evidence_layers.client_registration = $report.mcp.status
    $report.status = 'ready'
    if ($report.mcp.status -in @('needs_client_registration','name_conflict_unchanged')) { $report.status = 'needs_client_registration' }
    if ($SkipMcpRegistration) { $report.status = 'skills_ready_mcp_registration_skipped' }
    $reportPath = Join-Path $state 'deployment.json'
    Write-Json $reportPath $report
    Write-Host ('Result: ' + $report.status)
    Write-Host ('Receipt: ' + $reportPath)
    Write-Host 'Restart or reload your AI client to discover the skills. CAD UI drawing is a separate verification step.'
    if ($report.status -eq 'needs_client_registration') { exit 2 }
    exit 0
} catch {
    $report.status = 'failed'
    $report['error'] = $_.Exception.Message
    if ($state) { Write-Json (Join-Path $state 'deployment.json') $report }
    Write-Error $_.Exception.Message -ErrorAction Continue
    if ($state) { Write-Host ('Receipt: ' + (Join-Path $state 'deployment.json')) }
    exit 1
}
