param(
    [string]$Repository = (Join-Path $PSScriptRoot "..\..\testJARVIS"),
    [string]$Baseline = "demo-bug-start",
    [ValidateRange(1, 20)]
    [int]$Runs = 3,
    [switch]$AllowRemote,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $AllowRemote) {
    throw "This evaluation sends selected TaskBoard source and test output to the configured model. Review the provider policy, then rerun with -AllowRemote."
}

$source = (Resolve-Path -LiteralPath $Repository).Path
if (-not (Test-Path -LiteralPath (Join-Path $source ".git"))) {
    throw "Repository is not a Git worktree: $source"
}

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$jarvis = Join-Path $projectRoot ".venv\Scripts\jarvis.exe"
if (-not (Test-Path -LiteralPath $jarvis)) {
    throw "JARVIS executable not found: $jarvis"
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$outputRoot = Join-Path $projectRoot ".eval-runs\taskboard-$timestamp"
New-Item -ItemType Directory -Path $outputRoot | Out-Null

$prompt = @"
先运行完整测试复现失败，定位三个失败的根本原因，做最小修改并补充必要的边界测试。
不要删除、跳过或弱化已有测试，不要修改无关文件。
完成后重新运行完整测试，并总结根因、修改文件和验证结果。
"@.Trim()

function Get-OptionalProperty {
    param([object]$InputObject, [string]$Name)
    if ($null -eq $InputObject) { return $null }
    $property = $InputObject.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

$summaries = @()
for ($index = 1; $index -le $Runs; $index++) {
    $runRoot = Join-Path $outputRoot ("run-{0:D2}" -f $index)
    $runDirectory = Join-Path $runRoot "workspace"
    New-Item -ItemType Directory -Path $runRoot | Out-Null
    & git clone --quiet $source $runDirectory
    if ($LASTEXITCODE -ne 0) { throw "git clone failed for run $index" }
    & git -C $runDirectory switch --quiet --detach $Baseline
    if ($LASTEXITCODE -ne 0) { throw "Cannot switch to baseline '$Baseline'" }

    Push-Location $runDirectory
    try {
        $baselineOutput = & $Python -m unittest discover -s tests -v 2>&1
        $baselineExit = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    $baselineOutput | Set-Content -LiteralPath (Join-Path $runRoot "baseline-tests.txt") -Encoding utf8

    $agentOutput = & $jarvis `
        --workspace $runDirectory `
        --allow-remote `
        --yes `
        --no-session `
        --no-stream `
        --json `
        $prompt 2>&1
    $agentExit = $LASTEXITCODE
    $agentText = $agentOutput -join [Environment]::NewLine
    $agentText | Set-Content -LiteralPath (Join-Path $runRoot "agent-result.json") -Encoding utf8

    Push-Location $runDirectory
    try {
        $finalOutput = & $Python -m unittest discover -s tests -v 2>&1
        $finalExit = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    $finalOutput | Set-Content -LiteralPath (Join-Path $runRoot "final-tests.txt") -Encoding utf8

    $diff = & git -C $runDirectory diff --no-ext-diff
    $diff | Set-Content -LiteralPath (Join-Path $runRoot "changes.diff") -Encoding utf8
    $diffStat = (& git -C $runDirectory diff --stat) -join [Environment]::NewLine

    $agentResult = $null
    try {
        $agentResult = $agentText | ConvertFrom-Json
    } catch {
        $agentResult = [pscustomobject]@{ ok = $false; status = "invalid_json"; stop_reason = "invalid_json" }
    }
    $summary = [pscustomobject]@{
        run = $index
        passed = ($baselineExit -ne 0 -and $agentExit -eq 0 -and $finalExit -eq 0)
        baseline_exit = $baselineExit
        agent_exit = $agentExit
        final_test_exit = $finalExit
        agent_status = Get-OptionalProperty $agentResult "status"
        stop_reason = Get-OptionalProperty $agentResult "stop_reason"
        turns = Get-OptionalProperty $agentResult "turns"
        tool_calls = Get-OptionalProperty $agentResult "tool_calls"
        tool_usage = Get-OptionalProperty $agentResult "tool_usage"
        verification_status = Get-OptionalProperty $agentResult "verification_status"
        usage = Get-OptionalProperty $agentResult "usage"
        elapsed_seconds = Get-OptionalProperty $agentResult "elapsed_seconds"
        diff_stat = $diffStat
        workspace = $runDirectory
        artifacts = $runRoot
    }
    $summaries += $summary
    $summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $runRoot "summary.json") -Encoding utf8
}

$report = [pscustomobject]@{
    repository = $source
    baseline = $Baseline
    requested_runs = $Runs
    passed_runs = @($summaries | Where-Object { $_.passed }).Count
    output_directory = $outputRoot
    runs = $summaries
}
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $outputRoot "report.json") -Encoding utf8
$report | ConvertTo-Json -Depth 8

if ($report.passed_runs -ne $Runs) { exit 1 }
