param(
    [int[]]$Seeds = @(12001,12002,12003,12004,12005,12006,12007,12008,12009,12010),
    [int]$TimeoutSeconds = 900,
    [string]$DataDir = "",
    [string]$Goal = "gather 16 oak_log",
    [int]$BrainPort = 8765,
    [int]$MinecraftPort = 25565
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$ServerDir = Join-Path $Root "server"
$BrainDir = Join-Path $Root "brain"
$AdapterDir = Join-Path $Root "adapter"
if ([string]::IsNullOrWhiteSpace($DataDir)) {
    $DataDir = Join-Path $Root "data"
} elseif (-not [System.IO.Path]::IsPathRooted($DataDir)) {
    $DataDir = Join-Path $Root $DataDir
}
$Node = "C:\Users\noahj\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
$Python = "C:\Users\noahj\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$PythonSitePackages = Join-Path $BrainDir ".venv\Lib\site-packages"
$ServerScript = Join-Path $Root "scripts\start_disposable_server.ps1"
$Output = Join-Path $DataDir "evaluation-results.json"

function Assert-ValidSeeds($SeedsToCheck) {
    if ($null -eq $SeedsToCheck -or @($SeedsToCheck).Count -lt 1) {
        throw "At least one seed is required."
    }
    foreach ($seed in @($SeedsToCheck)) {
        if ($seed -lt 1 -or $seed -gt 1000000) {
            throw "Invalid evaluation seed '$seed'. Pass seeds as a PowerShell array, for example: -Seeds @(12001,12002)."
        }
    }
}

function Stop-Tree($Process) {
    if ($null -eq $Process) { return }
    try {
        $children = Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $Process.Id }
        foreach ($child in $children) {
            Stop-Tree (Get-Process -Id $child.ProcessId -ErrorAction SilentlyContinue)
        }
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        try { (Get-Process -Id $Process.Id -ErrorAction SilentlyContinue).WaitForExit(5000) } catch {}
    } catch {}
}

function Get-ServerProcesses() {
    @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*server.jar*' })
}

function Stop-ServerProcesses() {
    foreach ($serverProcess in Get-ServerProcesses) {
        Stop-Process -Id $serverProcess.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Wait-Port($Port, $ShouldBeOpen, $TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $matches = @(netstat -ano | Select-String -Pattern ("127\.0\.0\.1:$Port\s+0\.0\.0\.0:0\s+LISTENING"))
        $open = ($matches.Count -gt 0)
        if ($open -eq $ShouldBeOpen) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Wait-ServerReady($Process, $LogPath, $TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if ($null -ne $Process -and $Process.HasExited) {
            throw "server exited before ready with code $($Process.ExitCode)"
        }
        $text = ""
        if (Test-Path -LiteralPath $LogPath) {
            $text = Get-Content -LiteralPath $LogPath -Raw -ErrorAction SilentlyContinue
        }
        if ($text -match 'Done \(') { return $true }
        if ($text -match 'FAILED TO BIND TO PORT|Address already in use|The exception was:') {
            throw "server startup failed: bind error"
        }
        if ($text -match 'Failed to request yggdrasil public key') {
            Write-Host "Server logged yggdrasil key fetch timeout; waiting for ready marker..."
        }
        Start-Sleep -Seconds 2
    }
    throw "server did not reach ready marker within $TimeoutSeconds seconds"
}

function Read-RunStatus($StartedAfter) {
    $db = Join-Path $DataDir "experiences.db"
    $json = & $Python (Join-Path $BrainDir "live_eval_helper.py") status --db $db --started-after $StartedAfter --adapter-log $script:AdapterLifecycleLog
    if ([string]::IsNullOrWhiteSpace($json) -or $json.Trim() -eq "{}") { return $null }
    return $json | ConvertFrom-Json
}

function Test-Pass($Run) {
    if ($null -eq $Run -or -not $Run.completed_at) { return @($false, @("completed_run_record")) }
    $missing = New-Object System.Collections.Generic.List[string]
    $inventory = @{}
    $evidence = @{}
    if ($Run.final_inventory_json) { $inventory = $Run.final_inventory_json | ConvertFrom-Json }
    if ($Run.evidence_json) { $evidence = $Run.evidence_json | ConvertFrom-Json }
    if ($Run.outcome -ne "success") { $missing.Add("outcome_success") }
    if ($Goal -eq "bootstrap 1 iron_ingot") {
        if (($inventory.iron_ingot -as [int]) -lt 1) { $missing.Add("inventory_iron_ingot_1") }
        if ($evidence.phase2_bootstrap_iron -ne $true) { $missing.Add("phase2_bootstrap_iron") }
        if (($evidence.furnace.output -as [string]) -ne "iron_ingot") { $missing.Add("furnace_iron_output") }
        if ($null -eq $evidence.furnace_transition_evidence) { $missing.Add("furnace_transition_evidence") }
        elseif ([string]::IsNullOrWhiteSpace(($evidence.furnace_transition_evidence.action_id -as [string]))) { $missing.Add("furnace_transition_action_id") }
        elseif ($evidence.furnace_transition_evidence.furnace_transition.output_slot_before_take.name -ne "iron_ingot") { $missing.Add("furnace_transition_output_slot") }
    } else {
        if (($inventory.oak_log -as [int]) -lt 16) { $missing.Add("inventory_oak_log_16") }
    }
    if ($evidence.verified_goal_complete -ne $true) { $missing.Add("verified_goal_complete") }
    if ($evidence.verified_stopped -ne $true) { $missing.Add("verified_stopped") }
    if ($evidence.initial_inventory_empty -ne $true) { $missing.Add("initial_inventory_empty") }
    if (($Run.unsafe_continuations -as [int]) -ne 0) { $missing.Add("no_unsafe_continuation") }
    if (($Run.adapter_invalid_lifecycle_log -as [int]) -ne 0) { $missing.Add("valid_adapter_lifecycle_log") }
    if (($Run.adapter_faults -as [int]) -ne 0) { $missing.Add("no_adapter_faults") }
    if (($Run.adapter_unresolved_execution -as [int]) -ne 0) { $missing.Add("no_adapter_unresolved_execution") }
    if (($Run.adapter_post_stop_activity -as [int]) -ne 0) { $missing.Add("no_adapter_post_stop_activity") }
    if (($Run.adapter_duplicate_terminal_events -as [int]) -ne 0) { $missing.Add("no_adapter_duplicate_terminal_events") }
    if (($Run.adapter_new_action_before_prior_settlement -as [int]) -ne 0) { $missing.Add("no_new_action_before_prior_settlement") }
    if ($Run.critical_skill_failures -and @($Run.critical_skill_failures.PSObject.Properties).Count -gt 0) { $missing.Add("no_craft_place_smelt_failures") }
    return @(($missing.Count -eq 0), $missing.ToArray())
}

function Quote-PowerShellLiteral($Value) {
    return "'" + ([string]$Value).Replace("'", "''") + "'"
}

Assert-ValidSeeds $Seeds
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
Remove-Item -LiteralPath (Join-Path $DataDir "experiences.db"),(Join-Path $DataDir "explorer_policy.json") -Force -ErrorAction SilentlyContinue
$env:PYTHONPATH = "$PythonSitePackages;$env:PYTHONPATH"
$results = @()
$allFailures = @{}
$requiredPasses = 8
if ($Goal -eq "bootstrap 1 iron_ingot") {
    $requiredPasses = if (@($Seeds).Count -eq 3) { 2 } else { @($Seeds).Count }
}

$seedIndex = 0
foreach ($seed in $Seeds) {
    $seedMinecraftPort = $MinecraftPort + $seedIndex
    $seedIndex += 1
    $world = "ai-eval-seed-$seed"
    $prefix = Join-Path $DataDir "eval-$seed"
    $serverOut = "$prefix-server.out.log"
    $serverErr = "$prefix-server.err.log"
    $brainOut = "$prefix-brain.out.log"
    $brainErr = "$prefix-brain.err.log"
    $adapterOut = "$prefix-adapter.out.log"
    $adapterErr = "$prefix-adapter.err.log"
    $adapterLifecycleLog = "$prefix-adapter-lifecycle.jsonl"
    $brainLaunch = "$prefix-brain-launch.ps1"
    $adapterLaunch = "$prefix-adapter-launch.ps1"
    $script:AdapterLifecycleLog = $adapterLifecycleLog
    Remove-Item -LiteralPath $serverOut,$serverErr,$brainOut,$brainErr,$adapterOut,$adapterErr,$adapterLifecycleLog,$brainLaunch,$adapterLaunch -Force -ErrorAction SilentlyContinue

    $server = $null
    $brain = $null
    $adapter = $null
    $started = Get-Date
    try {
        if (Wait-Port $seedMinecraftPort $true 1) { throw "server port $seedMinecraftPort is already occupied before seed $seed" }
        $existingServers = Get-ServerProcesses
        if (@($existingServers).Count -gt 0) {
            $pids = (@($existingServers) | ForEach-Object { $_.ProcessId }) -join ","
            Write-Host "Warning: server-like processes already visible before seed ${seed}: $pids"
        }
        $serverArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$ServerScript`" -WorldName $world -Seed $seed -ServerPort $seedMinecraftPort -Peaceful -ResetWorld"
        $server = Start-Process -FilePath "powershell.exe" -ArgumentList $serverArgs -WorkingDirectory $Root -RedirectStandardOutput $serverOut -RedirectStandardError $serverErr -PassThru -WindowStyle Hidden
        Wait-ServerReady $server $serverOut 360 | Out-Null
        if (-not (Wait-Port $seedMinecraftPort $true 10)) { throw "server ready marker appeared but port $seedMinecraftPort is not accepting connections" }

        @(
            '$ErrorActionPreference = "Stop"'
            "`$env:ADAPTER_LIFECYCLE_LOG=$(Quote-PowerShellLiteral $adapterLifecycleLog)"
            "`$env:MINECRAFT_PORT=$(Quote-PowerShellLiteral $seedMinecraftPort)"
            "`$env:DIRECT_GOAL=$(Quote-PowerShellLiteral $Goal)"
            "`$env:BRAIN_DATA_DIR=$(Quote-PowerShellLiteral $DataDir)"
            "`$env:PYTHON_EXE=$(Quote-PowerShellLiteral $Python)"
            "`$env:PYTHONPATH=$(Quote-PowerShellLiteral "$PythonSitePackages;$env:PYTHONPATH")"
            "Set-Location $(Quote-PowerShellLiteral $AdapterDir)"
            "& $(Quote-PowerShellLiteral $Node) index.js"
        ) | Set-Content -LiteralPath $adapterLaunch -Encoding ASCII
        $startedAfter = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd HH:mm:ss")
        $adapterArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$adapterLaunch`""
        $adapter = Start-Process -FilePath "powershell.exe" -ArgumentList $adapterArgs -WorkingDirectory $AdapterDir -RedirectStandardOutput $adapterOut -RedirectStandardError $adapterErr -PassThru -WindowStyle Hidden
        Start-Sleep -Seconds 8

        $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
        $run = $null
        while ((Get-Date) -lt $deadline) {
            Start-Sleep -Seconds 5
            $run = Read-RunStatus $startedAfter
            if ($null -ne $run -and $run.completed_at) { break }
        }
        $elapsed = [Math]::Round(((Get-Date) - $started).TotalSeconds, 2)
        $passedAndMissing = Test-Pass $run
        $passed = [bool]$passedAndMissing[0]
        $missing = @($passedAndMissing[1])
        $outcome = if ($null -eq $run) { "timeout" } elseif (-not $run.completed_at) { "timeout" } else { $run.outcome }
        $inventory = if ($run -and $run.final_inventory_json) { $run.final_inventory_json | ConvertFrom-Json } else { @{} }
        $failures = if ($run) { $run.failure_code_distribution } else { @{ timeout = 1 } }
        foreach ($prop in $failures.PSObject.Properties) {
            if ($prop.Name -notin @("Count","Length","LongLength","Rank","SyncRoot","IsReadOnly","IsFixedSize","IsSynchronized","Keys","Values")) {
                $allFailures[$prop.Name] = ([int]($allFailures[$prop.Name])) + ([int]$prop.Value)
            }
        }

        $results += [pscustomobject]@{
            seed = $seed
            outcome = $outcome
            passed = $passed
            missing_required_evidence = $missing
            completion_time_seconds = $elapsed
            deaths = if ($outcome -eq "death") { 1 } else { 0 }
            stuck_recoveries = if ($run) { [int]$run.stuck_recoveries } else { 0 }
            brain_unsafe_continuations = if ($run) { [int]$run.brain_unsafe_continuations } else { 0 }
            adapter_unsafe_continuations = if ($run) { [int]$run.adapter_unsafe_continuations } else { 0 }
            adapter_invalid_lifecycle_log = if ($run) { [int]$run.adapter_invalid_lifecycle_log } else { 1 }
            adapter_faults = if ($run) { [int]$run.adapter_faults } else { 0 }
            adapter_unresolved_execution = if ($run) { [int]$run.adapter_unresolved_execution } else { 0 }
            adapter_post_stop_activity = if ($run) { [int]$run.adapter_post_stop_activity } else { 0 }
            adapter_duplicate_terminal_events = if ($run) { [int]$run.adapter_duplicate_terminal_events } else { 0 }
            adapter_new_action_before_prior_settlement = if ($run) { [int]$run.adapter_new_action_before_prior_settlement } else { 0 }
            unsafe_continuations = if ($run) { [int]$run.unsafe_continuations } else { 0 }
            final_inventory = $inventory
            failure_code_distribution = $failures
            adapter_lifecycle = if ($run) { $run.adapter_lifecycle } else { @() }
            adapter_log_summary = if ($run) { $run.adapter_log_summary } else { @{} }
            critical_skill_failures = if ($run) { $run.critical_skill_failures } else { @{} }
            navigation_retries = if ($run) { [int]$run.navigation_retries } else { 0 }
            exploration_retries = if ($run) { [int]$run.exploration_retries } else { 0 }
            logs = @{
                server_stdout = $serverOut
                server_stderr = $serverErr
                brain_stdout = $brainOut
                brain_stderr = $brainErr
                adapter_stdout = $adapterOut
                adapter_stderr = $adapterErr
                adapter_lifecycle = $adapterLifecycleLog
            }
        }
    }
    catch {
        $results += [pscustomobject]@{
            seed = $seed
            outcome = "harness_error"
            passed = $false
            missing_required_evidence = @("harness_error")
            completion_time_seconds = [Math]::Round(((Get-Date) - $started).TotalSeconds, 2)
            deaths = 0
            stuck_recoveries = 0
            brain_unsafe_continuations = 0
            adapter_unsafe_continuations = 0
            adapter_invalid_lifecycle_log = 1
            adapter_faults = 0
            adapter_unresolved_execution = 0
            adapter_post_stop_activity = 0
            adapter_duplicate_terminal_events = 0
            adapter_new_action_before_prior_settlement = 0
            unsafe_continuations = 0
            final_inventory = @{}
            failure_code_distribution = @{ harness_error = 1 }
            adapter_lifecycle = @()
            adapter_log_summary = @{}
            critical_skill_failures = @{}
            navigation_retries = 0
            exploration_retries = 0
            error = $_.Exception.Message
            logs = @{
                server_stdout = $serverOut
                server_stderr = $serverErr
                brain_stdout = $brainOut
                brain_stderr = $brainErr
                adapter_stdout = $adapterOut
                adapter_stderr = $adapterErr
                adapter_lifecycle = $adapterLifecycleLog
            }
        }
        $allFailures["harness_error"] = ([int]($allFailures["harness_error"])) + 1
    }
    finally {
        Stop-Tree $adapter
        Stop-Tree $brain
        Stop-Tree $server
        Stop-ServerProcesses
        if (-not (Wait-Port $seedMinecraftPort $false 30)) {
            Write-Host "Warning: server port $seedMinecraftPort remained open after cleanup."
        }
        $leftoverServers = Get-ServerProcesses
        if (@($leftoverServers).Count -gt 0) {
            $pids = (@($leftoverServers) | ForEach-Object { $_.ProcessId }) -join ","
            Write-Host "Warning: server processes remained after cleanup: $pids"
        }
    }

    $passedCount = @($results | Where-Object { $_.passed }).Count
    $hungCount = @($results | Where-Object { $_.outcome -eq "timeout" }).Count
    $unsafeCount = ($results | Measure-Object -Property unsafe_continuations -Sum).Sum
    $adapterInvalidLogCount = ($results | Measure-Object -Property adapter_invalid_lifecycle_log -Sum).Sum
    $adapterFaultCount = ($results | Measure-Object -Property adapter_faults -Sum).Sum
    $adapterUnresolvedCount = ($results | Measure-Object -Property adapter_unresolved_execution -Sum).Sum
    $adapterPostStopCount = ($results | Measure-Object -Property adapter_post_stop_activity -Sum).Sum
    $adapterDuplicateTerminalCount = ($results | Measure-Object -Property adapter_duplicate_terminal_events -Sum).Sum
    $adapterNewBeforeSettleCount = ($results | Measure-Object -Property adapter_new_action_before_prior_settlement -Sum).Sum
    $deathCount = ($results | Measure-Object -Property deaths -Sum).Sum
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
        adapter_invalid_lifecycle_log = $adapterInvalidLogCount
        adapter_faults = $adapterFaultCount
        adapter_unresolved_execution = $adapterUnresolvedCount
        adapter_post_stop_activity = $adapterPostStopCount
        adapter_duplicate_terminal_events = $adapterDuplicateTerminalCount
        adapter_new_action_before_prior_settlement = $adapterNewBeforeSettleCount
        failure_code_distribution = $allFailures
        acceptance_gate_passed = ($passedCount -ge $requiredPasses -and $results.Count -eq $Seeds.Count -and $hungCount -eq 0 -and $deathCount -eq 0 -and $unsafeCount -eq 0 -and $adapterInvalidLogCount -eq 0 -and $adapterFaultCount -eq 0 -and $adapterUnresolvedCount -eq 0 -and $adapterPostStopCount -eq 0 -and $adapterDuplicateTerminalCount -eq 0 -and $adapterNewBeforeSettleCount -eq 0)
    }
    @{ summary = $summary; results = $results } | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $Output -Encoding UTF8
    Write-Host "Seed $seed => $($results[-1].outcome), passed=$($results[-1].passed)"
}

Get-Content -LiteralPath $Output
