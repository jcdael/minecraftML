# Minecraft ML Phase 2

This repository is a local, offline-at-runtime foundation for safe autonomous Minecraft skills. Supported goals:

```text
gather 16 oak_log
bootstrap 1 iron_ingot
```

It is not a full game-playing AI yet. Phase 2 adds a deterministic survival bootstrap chain: logs -> planks/table/sticks/wood pickaxe -> cobblestone -> stone pickaxe/furnace -> coal/raw iron -> smelted iron ingot. Every skill is bounded, verified from fresh observations, persisted to SQLite, and stopped safely.

## Pinned Runtime

Use one pinned target while developing:

- Minecraft Java dedicated server: `1.21.4`
- Java: Eclipse Temurin `21.0.11+10` project-local JRE under `server\java21`, or another Java 21 runtime compatible with Minecraft `1.21.4`
- Node.js: `24.14.0`
- pnpm: `11.7.0`
- Python: `3.12.13`
- Mineflayer: `4.37.1`
- mineflayer-pathfinder: `2.4.5`
- vec3: `0.1.10`
- ws: `8.18.3`
- websockets: `15.0.1`

Runtime services bind to `127.0.0.1`. The agent does not require cloud services or external APIs after dependencies and the Minecraft server jar are installed.

This workspace has been prepared with:

- official Minecraft Java `1.21.4` server jar at `server\server.jar`,
- project-local Temurin Java 21 at `server\java21\...\bin\java.exe`.

## Install

Copy the local config:

```powershell
Copy-Item config.example.json config.json
```

Install the adapter with the checked-in lockfile:

```powershell
cd adapter
pnpm install --frozen-lockfile
pnpm run check
cd ..
```

Install the brain:

```powershell
cd brain
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
cd ..
```

Run the fast fixture, trace, and adapter integration batch before any live-world debugging:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_fixture_batch.ps1
```

If an interrupted Windows process keeps `data\fixture-test-output.txt` locked, write the same batch output to a fresh path:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_fixture_batch.ps1 -OutputPath data\fixture-test-output-latest.txt
```

## Disposable Worlds Only

Do not run automated mining against a personal world.

Recommended workflow:

1. Keep valuable worlds outside this project.
2. Create disposable server worlds named like `ai-eval-seed-12001`.
3. Before a run, delete or archive only that disposable world folder.
4. Keep backups in `server\backups\`.
5. Use `server\server.properties.example` as the baseline and keep `server-ip=127.0.0.1`.
6. Never port-forward this server.

Example backup commands:

```powershell
New-Item -ItemType Directory -Force server\backups
Compress-Archive -Path server\world -DestinationPath server\backups\world-before-ai-run.zip -Force
Remove-Item -Recurse -Force server\world
```

Only run those commands for a disposable world you are willing to lose.

## Run

Start the Minecraft `1.21.4` server first with `server-ip=127.0.0.1`. The helper script refuses to run until you personally accept Mojang's EULA in `server\eula.txt`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_disposable_server.ps1 -WorldName ai-eval-seed-12001 -Seed 12001 -ResetWorld
```

Terminal 1:

```powershell
cd brain
.\.venv\Scripts\python.exe main.py
```

Terminal 2:

```powershell
cd adapter
pnpm start
```

In Minecraft chat:

```text
!goal gather 16 oak_log
!goal bootstrap 1 iron_ingot
!pause
!resume
!status
```

Unsupported goals such as building a house or beating the Ender Dragon return an unsupported response instead of pretending to work.

## Fixture And Trace Workflow

Use fixtures first. The fixture batch runs:

- Python unit tests, including deterministic bootstrap, missing material, full inventory, low food, death/respawn, and normalized trace replay tests.
- Adapter syntax checks.
- Adapter fake Mineflayer/window integration tests covering delayed furnace output transfer, cancel during output transfer, transfer failure, craft/place/smelt timeout and cancellation, post-stop container side effects, and quarantined adapter behavior.

Output is saved to:

```text
data\fixture-test-output.txt
```

## Legacy Manual Smoke Test

The legacy manual smoke runner is opt-in and refuses to run unless you confirm a disposable world:

```powershell
.\scripts\run_real_server_smoke.ps1 -IUnderstandDisposableWorld
```

It expects the local server, brain, and adapter to already be running. Prefer the bootstrap smoke/evaluation commands below for Phase 2; they create disposable worlds automatically and write per-seed evidence.

## Bootstrap Smoke And Evaluation

Run the two-seed smoke only after fixtures pass:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_two_seed_smoke.ps1 -Goal 'bootstrap 1 iron_ingot' -TimeoutSeconds 900 -MinecraftPort 25570
```

If Windows still shows stale Minecraft listeners from interrupted runs, use a fresh base Minecraft port. The smoke wrapper increments the port per seed.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_two_seed_smoke.ps1 -Goal 'bootstrap 1 iron_ingot' -TimeoutSeconds 900 -MinecraftPort 25574
```

After smoke passes, run the fresh three-seed bootstrap gate:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
& .\scripts\run_ten_seed_evaluation.ps1 -Seeds @(12001,12002,12003) -TimeoutSeconds 900 -DataDir data\bootstrap-final-three-seed -Goal 'bootstrap 1 iron_ingot' -MinecraftPort 25579
```

The evaluator starts one disposable server world per seed and an adapter-local stdio brain worker, submits the goal through the adapter, captures logs, and tears the processes down. A bootstrap run passes only when:

- final inventory contains at least `1 iron_ingot`,
- SQLite evidence says the run began with an empty inventory,
- SQLite evidence says the bootstrap goal was verified complete,
- final Stop verifies action, movement, pathfinding, digging, and container activity are inactive,
- smelt evidence includes raw iron and coal/fuel before smelting, furnace input/fuel/output transition evidence, fresh iron ingot inventory increase, and no pending container operation,
- no craft/place/smelt timeout or verification-failure events occurred,
- no skill attempt continues after the verified stop.

Bootstrap acceptance gate:

- normal fixtures pass 100% and negative fixtures fail safely,
- two-seed smoke passes `2/2`,
- three-seed gate passes at least `2/3`,
- zero hung runs,
- zero deaths,
- zero unsafe action continuations after stop,
- zero adapter lifecycle violations or unresolved executions.

The evaluator writes JSON with completion rate, median and p95 completion time, total navigation/exploration retries, deaths, stuck recoveries, hung runs, unsafe continuations, critical craft/place/smelt failures, and failure-code distribution. Missing evidence fails the gate.

## Architecture Notes

- `brain/protocol.py` defines versioned message/action validation.
- `brain/skills.py` defines the skill contract and deterministic Phase 1 skills.
- `brain/supervisor.py` independently handles low food, low health, and danger stops.
- `brain/agent.py` parses supported goals, selects skills, verifies results, records furnace transition evidence, and records runs.
- `brain/memory.py` owns idempotent SQLite initialization and durable skill-attempt persistence.
- `adapter/index.js` executes one validated action at a time with timeouts, cancellation, cleanup, container activity tracking, and before/after observations.
- `docs/PHASE1_PROTOCOL.md` documents the protocol and skill contract.

This foundation is intentionally small. Later planner, building, and learning phases can add more goals by composing new verified skills into the same protocol, persistence, and safety supervisor instead of replacing them with an unreliable black box.
