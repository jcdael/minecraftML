param(
    [string]$ManifestPath = "fixtures\bootstrap\manifest.json",
    [string]$OutputPath = "data\fixture-world-batch-results.json",
    [switch]$ResetWorlds
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$BundledPython = "C:\Users\noahj\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$Python = if (Test-Path $BundledPython) { $BundledPython } else { "python" }
$Manifest = if ([System.IO.Path]::IsPathRooted($ManifestPath)) { $ManifestPath } else { Join-Path $Root $ManifestPath }
$Output = if ([System.IO.Path]::IsPathRooted($OutputPath)) { $OutputPath } else { Join-Path $Root $OutputPath }
$ServerDir = Join-Path $Root "server"

function Resolve-ChildPath {
    param(
        [string]$Parent,
        [string]$Child
    )
    $combined = Join-Path $Parent $Child
    $resolvedParent = (Resolve-Path -LiteralPath $Parent).Path
    if (Test-Path $combined) {
        $resolved = (Resolve-Path -LiteralPath $combined).Path
    } else {
        $resolved = [System.IO.Path]::GetFullPath($combined)
    }
    if (-not $resolved.StartsWith($resolvedParent, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing path outside parent: $resolved"
    }
    return $resolved
}

Push-Location $Root
try {
    & $Python brain\fixture_manifest.py $Manifest | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "fixture manifest validation failed"
    }

    $manifestDir = Split-Path -Parent (Resolve-Path -LiteralPath $Manifest).Path
    $manifestData = Get-Content -LiteralPath $Manifest -Raw | ConvertFrom-Json
    $results = @()
    foreach ($fixture in $manifestData.fixtures) {
        $fixtureId = [string]$fixture.id
        $templatePath = Resolve-ChildPath $manifestDir ([string]$fixture.seed_template.path)
        $worldName = "fixture-$fixtureId"
        $worldPath = Resolve-ChildPath $ServerDir $worldName
        if ($ResetWorlds -and (Test-Path $worldPath)) {
            Remove-Item -LiteralPath $worldPath -Recurse -Force
        }
        if (Test-Path $worldPath) {
            Remove-Item -LiteralPath $worldPath -Recurse -Force
        }
        Copy-Item -LiteralPath $templatePath -Destination $worldPath -Recurse -Force
        $levelDat = Join-Path $worldPath "level.dat"
        if (-not (Test-Path $levelDat)) {
            throw "copied fixture world is missing level.dat: $worldPath"
        }
        $results += [pscustomobject]@{
            id = $fixtureId
            world_name = $worldName
            world_path = $worldPath
            template_path = $templatePath
            expected_outcome = [string]$fixture.expected_terminal.outcome
            expected_failure_code = [string]$fixture.expected_terminal.failure_code
            level_dat_present = $true
        }
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Output) | Out-Null
    [pscustomobject]@{
        ok = $true
        fixture_count = @($results).Count
        results = $results
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Output -Encoding UTF8
    Write-Host "fixture-world-batch ok fixtures=$(@($results).Count) output=$Output"
}
finally {
    Pop-Location
}
