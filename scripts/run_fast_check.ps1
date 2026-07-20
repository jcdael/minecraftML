param(
    [string]$ManifestPath = "fixtures\bootstrap\manifest.json"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$BundledPython = "C:\Users\noahj\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$Python = if (Test-Path $BundledPython) { $BundledPython } else { "python" }
$PythonSitePackages = Join-Path $Root "brain\.venv\Lib\site-packages"
$NodeBin = "C:\Users\noahj\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin"
$ResolvedManifest = if ([System.IO.Path]::IsPathRooted($ManifestPath)) { $ManifestPath } else { Join-Path $Root $ManifestPath }
$Failures = @()

function Invoke-FastCheckStep {
    param(
        [string]$Name,
        [scriptblock]$Command
    )

    $stepTimer = [System.Diagnostics.Stopwatch]::StartNew()
    $global:LASTEXITCODE = 0
    $script:FastCheckExitCode = 0
    try {
        $output = & $Command *>&1
        $exitCode = $script:FastCheckExitCode
    }
    catch {
        $output = @($_)
        $exitCode = 1
    }
    finally {
        $stepTimer.Stop()
    }

    if ($exitCode -ne 0) {
        Write-Host ("fail {0:n2}s {1}" -f $stepTimer.Elapsed.TotalSeconds, $Name)
        $output | ForEach-Object { Write-Host $_ }
        $script:Failures += "$Name($exitCode)"
        return
    }

    Write-Host ("ok   {0:n2}s {1}" -f $stepTimer.Elapsed.TotalSeconds, $Name)
}

function Set-FastCheckExitCode {
    param(
        [bool]$Succeeded,
        [int]$NativeExitCode
    )

    $script:FastCheckExitCode = if ($NativeExitCode -eq 0 -or $Succeeded) { 0 } else { $NativeExitCode }
}

Push-Location $Root
try {
    if (Test-Path $NodeBin) {
        $env:PATH = "$NodeBin;$env:PATH"
    }
    if (Test-Path $PythonSitePackages) {
        $env:PYTHONPATH = "$PythonSitePackages;$env:PYTHONPATH"
    }

    Write-Host "fast-check offline=true live-minecraft=false"
    $totalTimer = [System.Diagnostics.Stopwatch]::StartNew()

    Invoke-FastCheckStep "python-compile" {
        $global:LASTEXITCODE = 0
        & $Python -m compileall -q brain
        $ok = $?
        Set-FastCheckExitCode $ok $LASTEXITCODE
    }
    Invoke-FastCheckStep "python-unit-trace" {
        $global:LASTEXITCODE = 0
        $pythonOutput = New-TemporaryFile
        cmd /c "`"$Python`" -m unittest discover brain\tests > `"$pythonOutput`" 2>&1"
        $script:FastCheckExitCode = $LASTEXITCODE
        if ($script:FastCheckExitCode -ne 0) {
            Get-Content -LiteralPath $pythonOutput
        }
        Remove-Item -LiteralPath $pythonOutput -Force
    }
    Invoke-FastCheckStep "adapter-syntax" {
        Push-Location adapter
        try {
            $global:LASTEXITCODE = 0
            $adapterOutput = New-TemporaryFile
            cmd /c "pnpm check > `"$adapterOutput`" 2>&1"
            $script:FastCheckExitCode = $LASTEXITCODE
            if ($script:FastCheckExitCode -ne 0) {
                Get-Content -LiteralPath $adapterOutput
            }
            Remove-Item -LiteralPath $adapterOutput -Force
        }
        finally {
            Pop-Location
        }
    }
    Invoke-FastCheckStep "adapter-fake-window-tests" {
        Push-Location adapter
        try {
            $global:LASTEXITCODE = 0
            $adapterOutput = New-TemporaryFile
            cmd /c "pnpm test > `"$adapterOutput`" 2>&1"
            $script:FastCheckExitCode = $LASTEXITCODE
            if ($script:FastCheckExitCode -ne 0) {
                Get-Content -LiteralPath $adapterOutput
            }
            Remove-Item -LiteralPath $adapterOutput -Force
        }
        finally {
            Pop-Location
        }
    }
    Invoke-FastCheckStep "fixture-manifest" {
        $global:LASTEXITCODE = 0
        & $Python brain\fixture_manifest.py $ResolvedManifest
        $ok = $?
        Set-FastCheckExitCode $ok $LASTEXITCODE
    }
    Invoke-FastCheckStep "fixture-trace-replay" {
        $global:LASTEXITCODE = 0
        & $Python brain\bootstrap_trace_fixtures.py --replay
        $ok = $?
        Set-FastCheckExitCode $ok $LASTEXITCODE
    }
    Invoke-FastCheckStep "fixture-world-batch" {
        $global:LASTEXITCODE = 0
        powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_fixture_world_batch.ps1 -ManifestPath $ResolvedManifest -OutputPath data\fixture-world-batch-results.json -ResetWorlds
        $ok = $?
        Set-FastCheckExitCode $ok $LASTEXITCODE
    }

    $totalTimer.Stop()
    Write-Host ("done {0:n2}s" -f $totalTimer.Elapsed.TotalSeconds)
    if ($Failures.Count -gt 0) {
        Write-Host ("failed: {0}" -f ($Failures -join ", "))
        exit 1
    }
}
finally {
    Pop-Location
}
