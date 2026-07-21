# # Coding-Agent Prompt: Migrate `jcdael/minecraftML` from Mineflayer to a Fabric Local-Player Training MVP

## Current Status: Git Audit Completed - Ready for Implementation

**Repository:** `https://github.com/jcdael/minecraftML`
**Source Branch:** `master` (contains actual project, not `main`)
**Working Branch:** `feature/fabric-local-player-mvp` (created from latest `origin/master`)
**Audit Date:** 2026-07-21T00:42:07.856Z

---

## 1. Git Audit Results

### Repository Configuration
- **Remote:** `origin https://github.com/jcdael/minecraftML.git`
- **Current Branch:** `feature/fabric-local-player-mvp` (created successfully)
- **Previous Branch:** `master` (up to date with origin/master)
- **Working Tree:** Clean (no uncommitted changes affecting migration)

### Branch Structure
- `master` - Main development branch with full project
- `main` - Contains only README (not used for development)
- `feature/fabric-local-player-mvp` - New branch for Fabric migration

---

## 2. Baseline Architecture Assessment

### Current Mineflayer Architecture (Pre-Migration)
```
Mineflayer Bot Client (Node.js)
    ↓ WebSocket (ws://127.0.0.1:8765)
Python Brain (Learning Agent)
    ↓ SQLite Memory
Goal Execution Engine
```

### Key Components Identified:
1. **Adapter (`adapter/`)** - Mineflayer-based bot client
   - `index.js` - Main Mineflayer bot implementation
   - `safety.js` - Critical action lifecycle and fail-closed semantics
   - `bootstrap_actions.js` - Verified smelting behavior
   - `package.json` - Dependencies: mineflayer@4.37.1, ws@8.18.3

2. **Brain (`brain/`)** - Python learning system
   - `protocol.py` - Strict WebSocket protocol validation
   - `skills.py` - Deterministic skills and verification logic
   - `supervisor.py` - Safety monitoring (health, food, hazards)
   - `agent.py` - Single-pending-action state machine
   - `memory.py` - SQLite experience storage

3. **Configuration (`config.example.json`)**
   - Minecraft 1.21.4, offline auth, localhost:25565
   - Username: "Learner" (separate bot account)

---

## 3. Migration Requirements

### Non-Negotiable Constraints
1. **Same-player control** - Must control `MinecraftClient.player`, not spawn separate account
2. **Client-only mod** - No server installation required
3. **Target:** Minecraft Java 1.21.4, Java 21, Fabric Loader
4. **TLauncher proof** - Final validation must use actual TLauncher Fabric profile
5. **Localhost only** - Reject non-loopback WebSocket connections
6. **No credential handling** - Use already authorized profile
7. **Offline/private use** - Disposable single-player world only
8. **Fail closed** - Automatic input release on errors
9. **One action at a time** - Preserve action IDs and lifecycle evidence
10. **No fake evidence** - Real local-player training required

---

## 4. Implementation Plan

### Phase 1: Fabric Mod Foundation
1. **Create `client-mod/` directory** with Fabric mod structure
2. **Set up Gradle build** with Fabric Loom for 1.21.4
3. **Implement basic mod class** with client-side initialization
4. **Add configuration system** for brain connection settings

### Phase 2: Local Player Integration
1. **Hook into player entity** - Access `MinecraftClient.player`
2. **Implement input control** - Movement, camera, interactions
3. **Add HUD overlay** - AI status, goals, controls
4. **Create control toggles** - F8 (AI on/off), F9 (emergency stop), G (goal screen)

### Phase 3: WebSocket Bridge
1. **Port protocol from Python** - Maintain exact message format
2. **Implement WebSocket client** - Localhost-only connections
3. **Add action lifecycle** - Preserve safety.js semantics
4. **Create observation system** - Player state, inventory, world data

### Phase 4: Integration & Testing
1. **Maintain brain compatibility** - No changes to Python protocol
2. **Add unit tests** - Mod functionality verification
3. **Create integration tests** - End-to-end with Python brain
4. **Document setup** - TLauncher profile configuration

### Phase 5: Live Validation
1. **Build mod JAR** - Production-ready artifact
2. **Install in TLauncher** - Fabric 1.21.4 profile
3. **Execute training proof** - AI controls local player
4. **Capture evidence** - SQLite records, screenshots, logs

---

## 5. Files in Scope

### To Create (New Fabric Mod):
- `client-mod/build.gradle` - Fabric mod build configuration
- `client-mod/src/main/java/` - Java source code
- `client-mod/src/main/resources/fabric.mod.json` - Mod metadata
- `client-mod/README.md` - Mod-specific documentation

### To Modify (Migration Adaptations):
- `.agent/GOAL.md` - This file (tracking progress)
- `.agent/CURRENT_STATE.md` - Milestone tracking
- `README.md` - Update architecture description
- `config.example.json` - Add Fabric-specific settings

### To Preserve (Unchanged):
- `brain/` - Entire Python learning system
- `adapter/` - Legacy Mineflayer reference (keep for regression)
- `fixtures/`, `scripts/`, `docs/` - Existing assets

---

## 6. Acceptance Criteria

The milestone is reached when:
1. ✅ **Git audit completed** - Feature branch created from master
2. ⬜ **Fabric mod compiles** - Successful Gradle build
3. ⬜ **Mod loads in Minecraft** - Title screen with mod active
4. ⬜ **Local player accessible** - Can read player entity state
5. ⬜ **Input control functional** - AI can move player/camera
6. ⬜ **WebSocket connection** - Communicates with Python brain
7. ⬜ **Safety controls work** - F8 toggle, F9 emergency stop
8. ⬜ **HUD displays** - AI status and goal information
9. ⬜ **Training loop starts** - AI begins learning in disposable world
10. ⬜ **Evidence captured** - SQLite records of training session
11. ⬜ **Safe shutdown** - Controls released, world preserved

---

## 7. Current Progress

### Completed:
- ✅ Git repository located and verified
- ✅ Feature branch created: `feature/fabric-local-player-mvp`
- ✅ Baseline architecture documented
- ✅ Key files identified and analyzed
- ✅ Baseline test report captured

### Next Steps:
1. Create Fabric mod directory structure
2. Set up Gradle build for Minecraft 1.21.4
3. Implement basic mod initialization

---

## 8. Commands for Development

```powershell
# Build and test mod
cd client-mod
./gradlew build
./gradlew runClient

# Run Python brain (unchanged)
cd brain
.\.venv\Scripts\python.exe main.py

# Run baseline tests
node baseline-test-report.js
```

---

## 9. Live Stop Condition

**STOP WORK WHEN:**
- AI controls the same local player shown on screen
- Genuine persisted learning loop begins in disposable TLauncher world
- Verifiable matched transitions captured in SQLite
- Safety controls tested and functional
- AI safely stopped and all controls released

**DO NOT CONTINUE INTO:**
- Mining automation
- Baritone integration  
- Crafting/building systems
- Combat or Nether progression
- Computer vision or neural RL
- Ender Dragon work

---

*This document updated as the primary tracking mechanism for the Fabric migration MVP. Keep CURRENT_STATE.md updated with specific implementation milestones.*