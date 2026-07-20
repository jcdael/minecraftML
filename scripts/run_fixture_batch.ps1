param(
    [string]$OutputPath = "data\fixture-test-output.txt"
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$Python = "C:\Users\noahj\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$PythonSitePackages = Join-Path $Root "brain\.venv\Lib\site-packages"
$NodeBin = "C:\Users\noahj\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin"
$Output = if ([System.IO.Path]::IsPathRooted($OutputPath)) { $OutputPath } else { Join-Path $Root $OutputPath }

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Output) | Out-Null

Push-Location $Root
try {
    $env:PATH = "$NodeBin;$env:PATH"
    $env:PYTHONPATH = "$PythonSitePackages;$env:PYTHONPATH"
    $commands = @(
        @{ Name = "python-unit-fixture-trace"; Command = { & $Python -m unittest discover brain\tests } },
        @{ Name = "adapter-syntax"; Command = { Push-Location adapter; try { pnpm check } finally { Pop-Location } } },
        @{ Name = "adapter-fake-window-integration"; Command = { Push-Location adapter; try { pnpm test } finally { Pop-Location } } }
    )

    "" | Set-Content -LiteralPath $Output -Encoding UTF8
    foreach ($entry in $commands) {
        $header = "===== $($entry.Name) ====="
        Write-Host $header
        Add-Content -LiteralPath $Output -Value $header -Encoding UTF8
        $commandOutput = & $entry.Command *>&1
        $commandOutput | ForEach-Object {
            Write-Host $_
            Add-Content -LiteralPath $Output -Value $_ -Encoding UTF8
        }
        if ($LASTEXITCODE -ne 0) {
            throw "$($entry.Name) failed with exit code $LASTEXITCODE"
        }
    }
}
finally {
    Pop-Location
}
