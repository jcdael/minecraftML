@echo off
REM Batch script to build MinecraftML with Java 21

set JAVA_HOME=C:\Users\noahj\AppData\Local\Temp\jdk-21\jdk-21.0.12
set PATH=%JAVA_HOME%\bin;%PATH%

echo Using Java from: %JAVA_HOME%
java -version

cd client-mod
call gradlew.bat --no-daemon clean build

pause