# Phase 2 Bootstrap Iron Final Report

Date: 2026-07-13

## Commands And Evidence

Fixture/unit/trace/adapter batch:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_fixture_batch.ps1 -OutputPath data\fixture-test-output-latest.txt
```

Exact output saved at:

```text
data\fixture-test-output-latest.txt
```

Two-seed smoke:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_two_seed_smoke.ps1 -Goal 'bootstrap 1 iron_ingot' -TimeoutSeconds 900 -BrainPort 8770 -MinecraftPort 25574
```

Result file:

```text
data\smoke-evaluation-results.json
```

Summary: 2/2 passed, zero deaths, zero hung runs, zero unsafe continuations, zero adapter lifecycle violations, zero critical craft/place/smelt failures.

Final three-seed gate:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "& { .\scripts\run_ten_seed_evaluation.ps1 -Seeds @(12001,12002,12003) -TimeoutSeconds 900 -DataDir 'data\bootstrap-final-three-seed' -Goal 'bootstrap 1 iron_ingot' -BrainPort 8770 -MinecraftPort 25579 }"
```

Result file:

```text
data\bootstrap-final-three-seed\evaluation-results.json
```

Summary: 2/3 passed, acceptance gate passed, zero deaths, zero hung runs, zero unsafe continuations, zero adapter lifecycle violations, median completion 664.92s, p95 completion 701.57s, navigation retries 43, exploration retries 42.

Passed final seeds: 12002 and 12003. Both have verified iron ingot, verified final Stop, and structured furnace transition evidence tied to the successful smelt action.

Process cleanup check:

```powershell
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and ($_.CommandLine -like '*server.jar*' -or $_.CommandLine -like '*adapter*index.js*' -or $_.CommandLine -like '*stdio_worker.py*' -or $_.CommandLine -like '*brain\\main.py*') }
netstat -ano | findstr /C:'127.0.0.1:25579' /C:'127.0.0.1:25580' /C:'127.0.0.1:25581'
```

Result: no live server, adapter, brain worker, or final-gate listener remained.
