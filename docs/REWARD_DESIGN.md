# Reward Design

A long Minecraft objective needs dense progress signals without teaching shortcuts that violate the real goal.

## Base reward example

```text
+ terminal goal completion
+ increase in required item count
+ prerequisite milestone completed
+ new safe location mapped
+ successful skill verification
- damage taken
- death
- lost required items
- time and unnecessary movement
- repeated identical failure
- being stuck
```

## Potential-based progress

Define a progress score `Phi(state)` from completed prerequisites, useful inventory, known locations, and distance to the current target. Give the learner:

```text
reward = Phi(next_state) - Phi(state) + terminal_reward
```

## Preventing reward hacking

- Verify actual inventory and world changes instead of trusting an action return value.
- Reward a discovery only the first time or with diminishing returns.
- Cap rewards for repeatedly placing and breaking the same block.
- Separate training worlds from the valued long-term survival world.
- Evaluate on held-out world seeds before promoting a policy.
