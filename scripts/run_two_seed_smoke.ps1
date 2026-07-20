param(
    [int[]]$Seeds = @(12001,12002),
    [int]$TimeoutSeconds = 900,
    [string]$Goal = "gather 16 oak_log",
    [int]$BrainPort = 8766,
    [int]$MinecraftPort = 25565
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root "brain\.venv\Scripts\python.exe"
$DataRoot = Join-Path $Root "data"
$Output = Join-Path $DataRoot "smoke-evaluation-results.json"

function Assert-ValidSmokeSeeds($SeedsToCheck) {
    $seedList = @($SeedsToCheck)
    if ($seedList.Count -ne 2) {
        throw "Smoke requires exactly two independent seeds: 12001 and 12002."
    }
    if ($seedList[0] -ne 12001 -or $seedList[1] -ne 12002) {
        throw "Smoke seeds must be passed as a PowerShell array: -Seeds @(12001,12002)."
    }
}

Assert-ValidSmokeSeeds $Seeds
New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null

$results = @()
$allFailures = @{}
foreach ($seed in @($Seeds)) {
    $seedIndex = @($results).Count
    $seedMinecraftPort = $MinecraftPort + $seedIndex
    $seedData = Join-Path $DataRoot "smoke-$seed"
    Remove-Item -LiteralPath $seedData -Recurse -Force -ErrorAction SilentlyContinue
    & (Join-Path $Root "scripts\run_ten_seed_evaluation.ps1") -Seeds @($seed) -TimeoutSeconds $TimeoutSeconds -DataDir $seedData -Goal $Goal -BrainPort $BrainPort -MinecraftPort $seedMinecraftPort | Out-Null
    $seedResult = Get-Content -LiteralPath (Join-Path $seedData "evaluation-results.json") -Raw | ConvertFrom-Json
    $results += $seedResult.results
    foreach ($prop in $seedResult.summary.failure_code_distribution.PSObject.Properties) {
        $allFailures[$prop.Name] = ([int]($allFailures[$prop.Name])) + ([int]$prop.Value)
    }
}

$passedCount = @($results | Where-Object { $_.passed }).Count
$hungCount = @($results | Where-Object { $_.outcome -eq "timeout" }).Count
$unsafeCount = ($results | Measure-Object -Property unsafe_continuations -Sum).Sum
$invalidLogCount = ($results | Measure-Object -Property adapter_invalid_lifecycle_log -Sum).Sum
$faultCount = ($results | Measure-Object -Property adapter_faults -Sum).Sum
$unresolvedCount = ($results | Measure-Object -Property adapter_unresolved_execution -Sum).Sum
$postStopCount = ($results | Measure-Object -Property adapter_post_stop_activity -Sum).Sum
$duplicateTerminalCount = ($results | Measure-Object -Property adapter_duplicate_terminal_events -Sum).Sum
$newBeforeSettleCount = ($results | Measure-Object -Property adapter_new_action_before_prior_settlement -Sum).Sum
$deathCount = ($results | Measure-Object -Property deaths -Sum).Sum
$criticalFailureCount = @($results | Where-Object { $_.critical_skill_failures -and @($_.critical_skill_failures.PSObject.Properties).Count -gt 0 }).Count
$times = @($results | Where-Object { $_.passed } | ForEach-Object { [double]$_.completion_time_seconds } | Sort-Object)
$median = $null
$p95 = $null
if ($times.Count -gt 0) {
    $middle = [int]($times.Count / 2)
    $median = if ($times.Count % 2 -eq 0) { ($times[$middle - 1] + $times[$middle]) / 2 } else { $times[$middle] }
    $p95Index = [Math]::Min($times.Count - 1, [int][Math]::Ceiling($times.Count * 0.95) - 1)
    $p95 = $times[$p95Index]
}

$summary = [pscustomobject]@{
    passed = $passedCount
    total = $results.Count
    completion_rate = [Math]::Round($passedCount / [Math]::Max(1, $results.Count), 3)
    median_completion_time_seconds = $median
    p95_completion_time_seconds = $p95
    navigation_retries = ($results | Measure-Object -Property navigation_retries -Sum).Sum
    exploration_retries = ($results | Measure-Object -Property exploration_retries -Sum).Sum
    deaths = $deathCount
    stuck_recoveries = ($results | Measure-Object -Property stuck_recoveries -Sum).Sum
    hung_runs = $hungCount
    unsafe_continuations = $unsafeCount
    adapter_invalid_lifecycle_log = $invalidLogCount
    adapter_faults = $faultCount
    adapter_unresolved_execution = $unresolvedCount
    adapter_post_stop_activity = $postStopCount
    adapter_duplicate_terminal_events = $duplicateTerminalCount
    adapter_new_action_before_prior_settlement = $newBeforeSettleCount
    critical_skill_failure_runs = $criticalFailureCount
    failure_code_distribution = $allFailures
    acceptance_gate_passed = ($passedCount -eq 2 -and $results.Count -eq 2 -and $hungCount -eq 0 -and $deathCount -eq 0 -and $unsafeCount -eq 0 -and $invalidLogCount -eq 0 -and $faultCount -eq 0 -and $unresolvedCount -eq 0 -and $postStopCount -eq 0 -and $duplicateTerminalCount -eq 0 -and $newBeforeSettleCount -eq 0 -and $criticalFailureCount -eq 0)
}

@{ summary = $summary; results = $results } | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $Output -Encoding UTF8
Get-Content -LiteralPath $Output
