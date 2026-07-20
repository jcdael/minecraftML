# Phase 1 Protocol and Skill Contract

This project uses a localhost-only JSON protocol between the Python brain and the Mineflayer adapter.

## Protocol

- `protocol_version`: `1`
- Brain listens on `ws://127.0.0.1:8765`.
- Adapter connects to the brain, identifies itself with `hello.role="mineflayer_adapter"`, and sends observations/results.
- The brain tracks one active adapter websocket session by `adapter_id` and `session_id`.
- Goal/status/command clients are not adapter sessions; their disconnects must not affect pending adapter work.
- A second adapter hello while another adapter session is active is rejected. After the active adapter disconnects, a reconnect registers a new active session; stale results from old or non-active sessions are rejected before agent state changes.
- Brain sends one action at a time.
- Every action has an `action_id`.
- Every result must return the same `action_id`.
- Invalid messages fail closed and do not produce fallback actions.
- Adapter lifecycle logs must emit one `action_started` record with `seq: 0`, followed by one terminal result lifecycle for that same `action_id`.
- Every adapter `result` message must include a complete lifecycle object; malformed lifecycle results are rejected before agent state changes.
- Result lifecycle events use a per-action monotonic integer `seq` starting at `1`.
- Valid lifecycle event order is exactly:
  `abort_requested` (optional), `cleanup_started` (optional), `cleanup_completed` (optional), `execution_settled`, `post_stop_probe_completed`, `terminal_result`.
- `cleanup_completed` is only valid after `cleanup_started`; no unknown or duplicate lifecycle event names are valid.
- All lifecycle event timestamps must be within the outer `action_started` timestamp and the terminal result timestamp.
- The terminal result is not valid until after the post-stop probe has completed.

Supported brain-to-adapter messages:

```json
{"protocol_version":1,"type":"action","action_id":"act-...","action":{"kind":"stop"}}
{"protocol_version":1,"type":"cancel","action_id":"act-..."}
```

Supported adapter-to-brain messages:

```json
{"protocol_version":1,"type":"hello","client":"mineflayer-adapter","role":"mineflayer_adapter","adapter_id":"local-mineflayer-adapter","session_id":"..."}
{"protocol_version":1,"type":"goal","text":"gather 16 oak_log","requested_by":"player"}
{"protocol_version":1,"type":"command","command":"pause"}
{"protocol_version":1,"type":"observation","request_id":"obs-1","state":{}}
{"protocol_version":1,"type":"result","action_id":"act-...","ok":true,"before_state":{},"after_state":{}}
{"protocol_version":1,"type":"cancel_ack","action_id":"act-...","ok":true}
{"protocol_version":1,"type":"event","event":"death","action_id":"act-..."}
{"protocol_version":1,"type":"error","code":"invalid_json","message":"..."}
```

Supported action kinds:

- `noop`
- `stop`
- `control`
- `look_delta`
- `goto`
- `goto_relative`
- `mine_nearest`
- `equip`
- `eat`

Unsupported or unsafe surfaces:

- No nested `sequence` actions.
- No `chat` action.
- No server/admin commands.
- No filesystem, shell, JavaScript, or Python execution from goals.
- Unknown protocol versions, unsupported actions, invalid coordinates, excessive numeric values, and malformed payloads are rejected with machine-readable errors.
- Stale, missing, malformed, duplicate, or mismatched action IDs are persisted as protocol errors and must not alter another action.
- Stop success requires post-cleanup evidence that `action_running`, `movement_active`, `pathfinder_active`, and `digging_active` are all false.

## Skill Contract

Every skill in `brain/skills.py` has:

- typed constructor arguments,
- `can_start` preconditions,
- bounded `timeout_ms`,
- a concrete adapter action,
- stop/cancel behavior through `StopSkill`,
- `verify(before, after, result)`,
- structured `SkillResult`,
- a shared outcome vocabulary.

Outcome vocabulary:

- `success`
- `precondition_failed`
- `timeout`
- `unreachable`
- `unsafe`
- `interrupted`
- `verification_failed`
- `inventory_full`
- `unavailable`

Implemented Phase 1 skills:

- `Stop`
- `ExploreSearch`
- `GatherVisibleBlock`
- `EatWhenNeeded`
- `RecoverStuck`

Only this goal is implemented:

```text
gather <N> oak_log
```

The standard acceptance target is:

```text
gather 16 oak_log
```

Building, Nether, Ender Dragon, Fabric UI, LLM integration, and neural-network training are deliberately not implemented in Phase 1.
