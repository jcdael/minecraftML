# Roadmap to a Fully Autonomous Agent

## Stage 1: reliable interface

Implement and test these typed actions independently:

- observe state
- walk to coordinates
- look at a block or entity
- mine a block
- pick up dropped items
- equip tools and armor
- craft from inventory and crafting table
- place blocks
- open containers, deposit, and withdraw
- smelt and refuel furnaces
- eat, sleep, flee, and recover from being stuck
- attack melee targets and use ranged weapons
- enter and exit Nether and End portals

Each skill needs explicit preconditions, a timeout, a success verifier, and machine-readable failure codes.

## Stage 2: symbolic Minecraft knowledge

Build a recipe and prerequisite graph. Represent the world as facts such as:

- `has(oak_log, 8)`
- `near(crafting_table)`
- `equipped(iron_pickaxe)`
- `dimension(overworld)`
- `knows_location(nether_portal)`

Use an HTN or GOAP planner to transform goals into skill calls.

## Stage 3: persistent learning

Record every transition:

- goal and subgoal
- observation before action
- selected skill and arguments
- result and failure code
- reward
- observation after action
- elapsed ticks

Start with contextual bandits for strategy selection. Add behavior cloning from successful trajectories, then recurrent PPO or another suitable RL algorithm for navigation, combat, and recovery.

## Stage 4: automatic curriculum

Generate tasks just beyond the agent's current competence. Examples:

1. survive one night
2. collect logs
3. craft wooden tools
4. obtain stone tools
5. cook food
6. obtain iron and a shield
7. make and relight a Nether portal
8. find a fortress and obtain blaze rods
9. obtain ender pearls
10. locate and fill a stronghold portal
11. defeat the dragon and return

Use novelty rewards only once per discovery and combine them with concrete goal progress to reduce reward hacking.

## Stage 5: building

Represent structures as blueprints rather than free-form block actions. A house goal becomes:

1. choose and flatten a safe site
2. generate a blueprint
3. calculate a bill of materials
4. gather materials
5. place foundation, frame, walls, roof, doors, windows, lights, bed, and storage
6. walk around the structure and verify every expected block
7. repair missing or misplaced blocks

## Stage 6: Fabric mod shell

After the agent works as a local bot, add a Fabric client/server mod that provides:

- goal entry screen
- pause, resume, and emergency stop
- current plan and subgoal display
- skill success rates and learning curves
- policy checkpoint selection and rollback
- world-backup button
- optional structured telemetry unavailable through normal packets

Keep the Python brain separate so ML dependencies do not have to run inside Minecraft's Java process.
