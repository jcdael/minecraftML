# TLauncher Setup Guide for MinecraftML Testing

## Overview

This guide explains how to set up TLauncher for testing the MinecraftML Fabric mod. TLauncher is required for the live validation phase because it's the user's intended launcher.

## Prerequisites

1. **TLauncher**: Installed and working
2. **Java 21**: Required for Minecraft 1.21.4
3. **Fabric Loader**: Version compatible with Minecraft 1.21.4
4. **Fabric API**: Version compatible with Minecraft 1.21.4
5. **MinecraftML Mod**: Built JAR file

## Step 1: Install Java 21

**Windows:**
1. Download Java 21 JDK from [Adoptium](https://adoptium.net/temurin/releases/?version=21)
2. Install to `C:\Program Files\Java\jdk-21`
3. Set `JAVA_HOME` environment variable:
   ```
   JAVA_HOME=C:\Program Files\Java\jdk-21
   ```
4. Add to PATH: `%JAVA_HOME%\bin`

**Verify:**
```bash
java -version
# Should show: java version "21.x.x"
```

## Step 2: Configure TLauncher Profile

1. Open TLauncher
2. Go to **Settings** → **Java/Minecraft**
3. Set Java executable path to Java 21:
   ```
   C:\Program Files\Java\jdk-21\bin\javaw.exe
   ```

4. Create new profile:
   - Click **Add New Profile**
   - Name: `MinecraftML Test`
   - Version: `fabric-loader-0.16.9-1.21.4`
   - Game Directory: `C:\Users\<user>\AppData\Roaming\.minecraft-ml-test`
   - Java Arguments: Keep default
   - Resolution: 1280x720 (recommended for testing)

## Step 3: Install Fabric Loader and API

1. In TLauncher, select the `MinecraftML Test` profile
2. Click **Install Fabric**
3. Select version: `1.21.4`
4. Select loader: `0.16.9` (or latest compatible)
5. Click **Install**

6. Download Fabric API for 1.21.4 from:
   - https://modrinth.com/mod/fabric-api/versions

7. Place Fabric API JAR in mods folder:
   ```
   C:\Users\<user>\AppData\Roaming\.minecraft-ml-test\mods\
   ```

## Step 4: Install MinecraftML Mod

1. Build the mod (when Java 21 is available):
   ```bash
   cd client-mod
   .\gradlew.bat --no-daemon clean build
   ```

2. Find the built JAR:
   ```
   client-mod\build\libs\minecraftml-*.jar
   ```

3. Copy to mods folder:
   ```
   C:\Users\<user>\AppData\Roaming\.minecraft-ml-test\mods\
   ```

## Step 5: Create Disposable World

1. Launch TLauncher with `MinecraftML Test` profile
2. Create new world:
   - **World Name**: `ML-Test-World`
   - **Game Mode**: Creative (for control testing)
   - **Difficulty**: Peaceful
   - **World Type**: Superflat (recommended)
   - **Allow Cheats**: ON
   - **Generate Structures**: OFF

3. Save world location for reference:
   ```
   C:\Users\<user>\AppData\Roaming\.minecraft-ml-test\saves\ML-Test-World\
   ```

## Step 6: Start Python Brain

1. Open terminal in project root
2. Start brain server:
   ```bash
   cd brain
   python main.py
   ```

3. Should show:
   ```
   Minecraft AI brain listening on ws://127.0.0.1:8765
   ```

## Step 7: Launch and Test

1. Launch Minecraft with TLauncher profile
2. Load the `ML-Test-World`
3. Verify mod loads (check `latest.log`):
   ```
   [INFO] [minecraftml]: MinecraftML loaded
   [INFO] [minecraftml]: WebSocket server started on port 8765
   ```

4. Test controls:
   - **F8**: Toggle AI control
   - **F9**: Emergency stop
   - **G**: Goal screen

## Safety Notes

1. **Isolated Profile**: Uses separate `.minecraft-ml-test` directory
2. **Disposable World**: Test world can be deleted after testing
3. **Local Only**: Brain binds to `127.0.0.1:8765`
4. **No Credentials**: Never modify or access Microsoft/TLauncher credentials
5. **Backup**: Regular worlds are not touched

## Troubleshooting

**Java Version Issues:**
- Error: "unknown invokedynamic bsm"
- Solution: Ensure Java 21 is installed and TLauncher uses it

**Fabric Loader Issues:**
- Error: "Fabric Loader not found"
- Solution: Reinstall Fabric through TLauncher

**Mod Not Loading:**
- Check `latest.log` for errors
- Verify JAR is in correct `mods` folder
- Check Fabric API compatibility

**Brain Connection Issues:**
- Verify Python brain is running
- Check port 8765 is not blocked
- Verify `ws://127.0.0.1:8765` in mod config

## Evidence Collection

After successful test, collect:
1. `latest.log` from game directory
2. Brain server logs
3. Screenshots of HUD and goal screen
4. Database files from `brain/data/`
5. Policy files from `brain/data/bandit/`

## Current Blockers

**PRIMARY BLOCKER**: Java version mismatch
- System has Java 8
- Project requires Java 21
- Build fails with bytecode compatibility errors

**Workaround**: Install Java 21 and configure TLauncher to use it.