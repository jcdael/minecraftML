param(
    [switch]$IUnderstandDisposableWorld,
    [string]$Goal = "gather 16 oak_log"
)

if (-not $IUnderstandDisposableWorld) {
    throw "Refusing to run. Re-run with -IUnderstandDisposableWorld after starting a disposable local Minecraft world bound to 127.0.0.1."
}

$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root "brain\.venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Missing brain virtualenv. Follow README install commands first."
}

Write-Host "Smoke runner expects: local server on 127.0.0.1:25565, brain on 127.0.0.1:8765, adapter connected."
Write-Host "Submitting one goal: $Goal"

& $Python (Join-Path $Root "brain\evaluate_seeds.py") `
    --i-understand-disposable-world `
    --goal $Goal `
    --seeds 12001 `
    --timeout-seconds 900
