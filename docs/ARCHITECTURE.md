# Architecture

## Recommended system

```text
Minecraft Java local server
        |
        | Minecraft protocol
        v
Mineflayer adapter (Node.js)
  - observes inventory, nearby blocks, entities, health, position
  - executes safe, typed actions
  - never executes arbitrary shell commands
        |
        | localhost WebSocket JSON
        v
Agent brain (Python)
  - safety/reflex layer
  - goal parser
  - symbolic planner
  - skill selector
  - online learner
  - persistent memory
        |
        +--> SQLite experience replay
        +--> model checkpoints
        +--> fixed-seed evaluator
        +--> optional local LLM for typed goal decomposition
```

## Control rates

- Reflexes: frequent checks for hunger, drowning, falling, fire, and hostile mobs.
- Skills: multi-step actions such as navigating, mining, crafting, smelting, or fighting.
- Planner: selects subgoals only when the world state changes or a skill ends.
- Trainer: learns from replay without changing the active policy mid-action.

## Important separation

The local language model, if used, should only produce schema-validated goals and plans. It should not generate or execute arbitrary JavaScript, Python, shell commands, or Minecraft server commands.

## Observation modes

1. **Structured mode**: inventory, nearby voxel IDs, entities, recipes, health, and position. Best for building a capable agent on one computer.
2. **Human-like mode**: pixels, keyboard, and mouse only. Best for research, but far more expensive and slower to learn.
3. **Hybrid mode**: structured state for planning, pixels for visual details and aesthetic building.

## Production policy promotion

```text
active policy v42 plays
        |
        +--> experience replay
                    |
                    v
              trainer creates v43
                    |
                    v
        evaluator runs fixed worlds
                    |
          promote only if v43 improves
```

This prevents a new online update from suddenly destroying a previously reliable skill.
