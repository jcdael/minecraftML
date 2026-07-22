# MinecraftML Protocol Documentation
# Version 2.0 - Phase 2: Fabric Local Player

## Overview

This document describes the WebSocket protocol used between the Minecraft Fabric mod (client) and the Python brain (server). The protocol enables real-time control of a local Minecraft player for AI training.

## Connection Details

- **Endpoint**: `ws://127.0.0.1:8765`
- **Protocol Version**: 2
- **Role**: `fabric_local_player` (not `mineflayer_adapter`)
- **Session**: Unique session ID per connection

## Message Types

### 1. Hello (Client → Brain)
```json
{
  "protocol_version": 2,
  "type": "hello",
  "client": "minecraft_fabric",
  "client_version": "0.2.0",
  "minecraft_version": "1.21.4",
  "role": "fabric_local_player",
  "adapter_id": "<stable local id>",
  "session_id": "<new UUID per connection>",
  "capabilities": [
    "observation",
    "control",
    "look_delta",
    "sequence",
    "cancel",
    "result_lifecycle",
    "same_player_control",
    "tick_based",
    "manual_override",
    "emergency_stop"
  ]
}
```

### 2. Hello Ack (Brain → Client)
```json
{
  "protocol_version": 2,
  "type": "hello_ack",
  "session_id": "<same session id>",
  "accepted": true,
  "brain_version": "0.2.0"
}
```

### 3. Observation (Client → Brain)
```json
{
  "protocol_version": 2,
  "type": "observation",
  "session_id": "<session id>",
  "request_id": "<unique observation id>",
  "timestamp_ms": 0,
  "client_tick": 0,
  "state": {
    "position": {"x": 0.0, "y": 0.0, "z": 0.0},
    "velocity": {"x": 0.0, "y": 0.0, "z": 0.0},
    "yaw": 0.0,
    "pitch": 0.0,
    "health": 20.0,
    "food": 20,
    "inventory": [],
    "nearby_blocks": {"counts": {}, "samples": []},
    "nearby_entities": [],
    "dimension": "overworld",
    "biome": "plains",
    "on_ground": true,
    "action_running": false,
    "movement_active": false,
    "screen": "none"
  }
}
```

### 4. Action (Brain → Client)
```json
{
  "protocol_version": 2,
  "type": "action",
  "session_id": "<session id>",
  "action_id": "<UUID>",
  "based_on_request_id": "<observation id>",
  "action": {
    "kind": "control",
    "key": "forward",
    "pressed": true,
    "duration_ticks": 12
  }
}
```

### 5. Result (Client → Brain)
```json
{
  "protocol_version": 2,
  "type": "result",
  "session_id": "<session id>",
  "action_id": "<same action id>",
  "ok": true,
  "code": "completed",
  "elapsed_ticks": 12,
  "elapsed_ms": 600,
  "before_state": {},
  "after_state": {},
  "metrics": {
    "horizontal_displacement": 2.4,
    "vertical_displacement": 0.0,
    "yaw_change": 0.0,
    "health_delta": 0.0,
    "new_cells": 2,
    "collision_or_stuck": false
  },
  "lifecycle": {
    "started_tick": 100,
    "input_released_tick": 112,
    "result_sent_tick": 113
  }
}
```

### 6. Cancel (Brain → Client)
```json
{
  "protocol_version": 2,
  "type": "cancel",
  "session_id": "<session id>",
  "action_id": "<action id to cancel>"
}
```

### 7. Cancel Ack (Client → Brain)
```json
{
  "protocol_version": 2,
  "type": "cancel_ack",
  "session_id": "<session id>",
  "action_id": "<action id>",
  "ok": true
}
```

### 8. Goal (Client → Brain)
```json
{
  "protocol_version": 2,
  "type": "goal",
  "session_id": "<session id>",
  "text": "explore 64 blocks",
  "requested_by": "goal_screen"
}
```

### 9. Command (Client → Brain)
```json
{
  "protocol_version": 2,
  "type": "command",
  "session_id": "<session id>",
  "command": "pause|resume|status"
}
```

### 10. Event (Client → Brain)
```json
{
  "protocol_version": 2,
  "type": "event",
  "session_id": "<session id>",
  "event": "death",
  "action_id": "<optional action id>"
}
```

## Supported Actions (Phase 2)

Only these action kinds are supported in Phase 2:

1. **noop**: No operation
2. **stop**: Stop all actions
3. **control**: Control a key (forward, back, left, right, jump, sneak, sprint, attack, use)
4. **look_delta**: Change yaw/pitch
5. **sequence**: Sequence of actions

## Control Keys

Valid keys for `control` actions:
- `forward`
- `back`
- `left`
- `right`
- `jump`
- `sneak`
- `sprint`
- `attack`
- `use`

## Safety Features

1. **Manual Override**: First physical user input returns control
2. **Emergency Stop (F9)**: Unconditional local stop
3. **Deadman Switch**: Timeout on brain disconnect
4. **Action Timeout**: Maximum duration per action
5. **World/Menu Safety**: Release controls on menu/world change

## Learning Protocol

1. Brain receives observation
2. Brain selects action using bandit algorithm
3. Client executes action
4. Client sends result with metrics
5. Brain updates policy based on reward
6. Repeat for at least 30 transitions

## Reward Calculation

Reward based on:
- Horizontal displacement (capped)
- New navigation cells visited
- Novelty for new block/biome categories
- Penalties for:
  - Negligible displacement
  - Collision/stuck
  - Health loss
  - Dangerous states
  - Action failure
  - Excessive duration

## Data Persistence

- **SQLite Database**: `data/experience.db`
- **Policy Files**: `data/bandit/policy_*.json`
- **Atomic Updates**: Temporary file + replace pattern
- **Backups**: Last valid policy kept

## Current Status

**BLOCKED**: Java version incompatibility
- System: Java 8
- Required: Java 21
- Build fails with "unknown invokedynamic bsm" errors

## Next Steps After Unblocking

1. Complete build with Java 21
2. Implement real input control
3. Test safety features
4. Perform TLauncher live test
5. Collect 30+ learning transitions
6. Validate policy updates