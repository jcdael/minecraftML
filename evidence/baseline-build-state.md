Baseline Build State - Current Broken State
=============================================
Timestamp: 2024-01-01 00:00:00 UTC
Command: cd client-mod; ./gradlew.bat --no-daemon clean build 2>&1
Exit Code: 1

Build Output (truncated):
-----------
To honour the JVM settings for this build a single-use Daemon process will be forked. For more on this, please refer to https://docs.gradle.org/8.8/userguide/gradle_daemon.html#sec:disabling_the_daemon in the Gradle documentation.
Daemon will be stopped at the end of the build 

> Configure project :
Fabric Loom: 1.6.6
"Lock for cache='C:\Users\noahj\.gradle\caches\fabric-loom', project=':'" is currently held by pid '21768'.
Locking process does not exist, assuming abrupt termination and deleting lock file.
Found existing cache lock file (ACQUIRED_PREVIOUS_OWNER_MISSING), rebuilding loom cache. This may have been caused by a failed or canceled build.

unknown invokedynamic bsm: java/lang/runtime/SwitchBootstraps/typeSwitch(Ljava/lang/invoke/MethodHandles$Lookup;Ljava/lang/String;Ljava/lang/invoke/MethodType;[Ljava/lang/Object;)Ljava/lang/invoke/CallSite; (tag=6 iif=false)
unknown invokedynamic bsm: java/lang/runtime/SwitchBootstraps/typeSwitch(Ljava/lang/invoke/MethodHandles$Lookup;Ljava/lang/String;Ljava/lang/invoke/MethodType;[Ljava/lang/Object;)Ljava/lang/invoke/CallSite; (tag=6 iif=false)
unknown invokedynamic bsm: java/lang/runtime/SwitchBootstraps/typeSwitch(Ljava/lang/invoke/MethodHandles$Lookup;Ljava/lang/String;Ljava/lang/invoke/MethodType;[Ljava/lang/Object;)Ljava/lang/invoke/CallSite; (tag=6 iif=false)
(Repeated many times...)

Deprecated Gradle features were used in this build, making it incompatible with Gradle 9.0.

FAILURE: Build failed with an exception.
* What went wrong:
A problem occurred configuring root project 'minecraftml-fabric'.
> Failed to setup Minecraft, java.lang.IllegalStateException: Javadoc provided by mod (fabric-content-registries-v0) 
must be have an intermediary source namespace
* Try:
> Run with --stacktrace option to get the stack trace.
> Run with --info or --debug option to get more log output.
> Run with --scan to get full insights.
> Get more help at https://help.gradle.org.
BUILD FAILED in 12s

Analysis:
---------
The build is currently broken with two related issues:

1. Java Version Incompatibility: "unknown invokedynamic bsm" errors indicate that the build process is trying to process Java 21 bytecode features (specifically, switch expressions introduced in Java 14 and enhanced in Java 21) with a Java 8 JVM. This is the primary blocker.

2. Fabric Loom Configuration Error: "Javadoc provided by mod (fabric-content-registries-v0) must have an intermediary source namespace" suggests version incompatibility between Fabric Loom, Fabric API, and Minecraft versions.

Root Cause:
- System has Java 8 installed (java version "1.8.0_431")
- Project requires Java 21 for Minecraft 1.21.4 compatibility
- Gradle is configured to use Java 21 (org.gradle.java.home in gradle.properties)
- However, some part of the build process is still using the system Java 8

This baseline evidence shows the current broken state that needs to be fixed.