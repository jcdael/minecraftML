# Protocol v2 Specification

## Overview
Protocol v2 is a WebSocket-based communication protocol between the Minecraft Fabric client mod and the Python brain. It supports structured observations, actions, and control state management.

## Message Types

### 1. Hello Message (Client → Server)
Sent when connection is established to negotiate capabilities.

```json
{
  "type": "hello",
  "protocol_version": "2.0",
  "capabilities": {
    "observation_fields": ["position", "velocity", "health", "inventory", "nearby_blocks", "nearby_entities"],
    "action_types": ["control", "look_delta", "sequence", "noop", "stop"],
    "control_states": ["OFF", "READY", "ACTIVE", "PAUSED", "MANUAL_OVERRIDE", "EMERGENCY_LATCHED", "FAULTED"]
  }
}
```

### 2. Observation Message (Client → Server)
Sent periodically or on state change.

```json
{
  "type": "observation",
  "timestamp": 1234567890.123,
  "player": {
    "position": {"x": 0.0, "y": 64.0, "z": 0.0},
    "velocity": {"x": 0.0, "y": 0.0, "z": 0.0},
    "health": 20.0,
    "food_level": 20,
    "saturation": 5.0,
    "experience_level": 0,
    "experience_progress": 0.0,
    "game_mode": "survival"
  },
  "inventory": [
    {"slot": 0, "item": "minecraft:dirt", "count": 64, "max_stack_size": 64},
    {"slot": 1, "item": "minecraft:stone_pickaxe", "count": 1, "damage": 0}
  ],
  "nearby_blocks": [
    {"position": {"x": 1, "y": 64, "z": 0}, "block": "minecraft:grass_block"},
    {"position": {"x": -1, "y": 64, "z": 0}, "block": "minecraft:oak_log"}
  ],
  "nearby_entities": [
    {"type": "minecraft:zombie", "position": {"x": 5.0, "y": 64.0, "z": 5.0}, "distance": 7.07}
  ],
  "control_state": "READY"
}
```

### 3. Action Message (Server → Client)
Sent to control the player.

```json
{
  "type": "action",
  "action_id": "action_123456",
  "skill_name": "explore",
  "skill_args": {"radius": 10},
  "action": {
    "type": "control",
    "forward": 1.0,
    "strafe": 0.0,
    "jump": false,
    "sneak": false,
    "sprint": false,
    "attack": false,
    "use": false
  }
}
```

### 4. Look Delta Action (Server → Client)
```json
{
  "type": "action",
  "action_id": "action_123457",
  "skill_name": "look_around",
  "skill_args": {},
  "action": {
    "type": "look_delta",
    "yaw": 45.0,
    "pitch": -10.0
  }
}
```

### 5. Sequence Action (Server → Client)
```json
{
  "type": "action",
  "action_id": "action_123458",
  "skill_name": "mine_block",
  "skill_args": {"block_type": "minecraft:stone"},
  "action": {
    "type": "sequence",
    "steps": [
      {"type": "control", "forward": 1.0, "strafe": 0.0, "jump": false, "sneak": false, "sprint": false, "attack": false, "use": false},
      {"type": "look_delta", "yaw": 90.0, "pitch": 0.0},
      {"type": "control", "forward": 0.0, "strafe": 0.0, "jump": false, "sneak": false, "sprint": false, "attack": true, "use": false}
    ],
    "step_duration_ms": 100
  }
}
```

### 6. Noop Action (Server → Client)
```json
{
  "type": "action",
  "action_id": "action_123459",
  "skill_name": "wait",
  "skill_args": {},
  "action": {
    "type": "noop",
    "duration_ms": 1000
  }
}
```

### 7. Stop Action (Server → Client)
```json
{
  "type": "action",
  "action_id": "action_123460",
  "skill_name": "emergency_stop",
  "skill_args": {},
  "action": {
    "type": "stop"
  }
}
```

### 8. Control State Update (Client → Server)
```json
{
  "type": "control_state",
  "state": "ACTIVE",
  "reason": "manual_override_detected"
}
```

### 9. Error Message (Either direction)
```json
{
  "type": "error",
  "code": "invalid_action",
  "message": "Action type 'invalid_type' is not supported",
  "details": {"received_action_type": "invalid_type"}
}
```

### 10. Policy Update (Server → Client)
```json
{
  "type": "policy_update",
  "action_id": "action_123456",
  "reward": 0.5,
  "agent_policy_version": "v1.0",
  "exploration_bandit": "UCB",
  "exploration_parameters": {"c": 2.0}
}
```

## Constraints

1. **Same-player control**: Only controls the local player, never other entities
2. **Client-only**: Runs entirely in the Fabric client mod
3. **Localhost only**: WebSocket server runs on localhost only
4. **Fail-closed safety**: Emergency stop latches until manually cleared
5. **One action at a time**: ActionExecutor processes one action completely before accepting another
6. **Lifecycle evidence**: All state transitions are logged and verifiable