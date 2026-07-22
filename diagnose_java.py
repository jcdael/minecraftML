#!/usr/bin/env python3
"""Diagnose Java version issues for MinecraftML."""

import os
import subprocess
import sys

def check_java_version():
    """Check Java version and configuration."""
    print("Java Version Diagnostic")
    print("=" * 60)
    
    # Check system Java
    try:
        result = subprocess.run(["java", "-version"], capture_output=True, text=True, shell=True)
        print(f"System Java version:\n{result.stderr}")
    except Exception as e:
        print(f"Error checking system Java: {e}")
    
    # Check if Java 21 is installed at expected location
    java_21_path = r"C:\Users\noahj\AppData\Local\Temp\jdk-21\jdk-21.0.12\bin\java.exe"
    if os.path.exists(java_21_path):
        print(f"\n✓ Java 21 found at: {java_21_path}")
    else:
        print(f"\n✗ Java 21 not found at: {java_21_path}")
    
    # Check gradle.properties
    gradle_props_path = "client-mod/gradle.properties"
    if os.path.exists(gradle_props_path):
        with open(gradle_props_path, 'r') as f:
            content = f.read()
            if "org.gradle.java.home" in content:
                print("\n✓ gradle.properties contains org.gradle.java.home setting")
                # Extract the path
                for line in content.split('\n'):
                    if "org.gradle.java.home" in line:
                        print(f"  Setting: {line.strip()}")
            else:
                print("\n✗ gradle.properties missing org.gradle.java.home setting")
    else:
        print(f"\n✗ gradle.properties not found at: {gradle_props_path}")
    
    # Check environment variables
    print("\nEnvironment Variables:")
    env_vars = ["JAVA_HOME", "PATH"]
    for var in env_vars:
        value = os.environ.get(var, "Not set")
        print(f"  {var}: {value[:100]}{'...' if len(value) > 100 else ''}")
    
    # Try to run a simple Java 21 feature test
    print("\nJava 21 Feature Test:")
    test_code = """
public class TestJava21 {
    public static void main(String[] args) {
        System.out.println("Java version: " + System.getProperty("java.version"));
        System.out.println("Java vendor: " + System.getProperty("java.vendor"));
        // Java 21 feature: record patterns (preview in Java 21)
        record Point(int x, int y) {}
        Point p = new Point(10, 20);
        if (p instanceof Point(int x, int y)) {
            System.out.println("Java 21 record pattern test: x=" + x + ", y=" + y);
        }
    }
}
"""
    
    # Write test file
    with open("TestJava21.java", "w") as f:
        f.write(test_code)
    
    try:
        # Try to compile with system Java
        compile_result = subprocess.run(["javac", "TestJava21.java"], capture_output=True, text=True, shell=True)
        if compile_result.returncode == 0:
            print("  ✓ TestJava21.java compiled successfully")
            # Try to run
            run_result = subprocess.run(["java", "TestJava21"], capture_output=True, text=True, shell=True)
            print(f"  Output:\n{run_result.stdout}")
            if "Java 21" in run_result.stdout or "21." in run_result.stdout:
                print("  ✓ Running Java 21 or later")
            else:
                print("  ✗ Not running Java 21")
        else:
            print(f"  ✗ Compilation failed: {compile_result.stderr}")
    except Exception as e:
        print(f"  Error running test: {e}")
    finally:
        # Clean up
        for file in ["TestJava21.java", "TestJava21.class"]:
            if os.path.exists(file):
                os.remove(file)
    
    print("\n" + "=" * 60)
    print("Recommendations:")
    print("1. Set JAVA_HOME environment variable to Java 21 installation")
    print("2. Add %JAVA_HOME%\\bin to PATH")
    print("3. Restart terminal/IDE to pick up changes")
    print("4. Run: cd client-mod && gradlew.bat --no-daemon clean build")

if __name__ == "__main__":
    check_java_version()