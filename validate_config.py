#!/usr/bin/env python3
"""
Validate MinecraftML build configuration consistency.
This script checks that all version numbers and references are consistent.
"""

import json
import os
import re
import sys

def read_gradle_properties(filepath):
    """Read gradle.properties file."""
    props = {}
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    props[key.strip()] = value.strip()
    return props

def read_json(filepath):
    """Read JSON file."""
    with open(filepath, 'r') as f:
        return json.load(f)

def check_versions():
    """Check version consistency across all files."""
    errors = []
    warnings = []
    
    # Read gradle.properties
    gradle_props = read_gradle_properties('client-mod/gradle.properties')
    
    # Read fabric.mod.json
    fabric_mod = read_json('client-mod/src/main/resources/fabric.mod.json')
    
    # Read mixin config
    mixin_config = read_json('client-mod/src/main/resources/minecraftml.mixins.json')
    
    # Check Minecraft version
    mc_version_gradle = gradle_props.get('minecraft_version', '')
    mc_version_fabric = fabric_mod.get('depends', {}).get('minecraft', '')
    
    if mc_version_gradle != '1.21.4':
        errors.append(f'gradle.properties minecraft_version is {mc_version_gradle}, expected 1.21.4')
    
    if mc_version_fabric != '1.21.4':
        errors.append(f'fabric.mod.json minecraft version is {mc_version_fabric}, expected 1.21.4')
    
    # Check Java version
    java_version_fabric = fabric_mod.get('depends', {}).get('java', '')
    java_version_mixin = mixin_config.get('compatibilityLevel', '')
    
    if java_version_fabric != '>=21':
        errors.append(f'fabric.mod.json java version is {java_version_fabric}, expected >=21')
    
    if java_version_mixin != 'JAVA_21':
        errors.append(f'minecraftml.mixins.json compatibilityLevel is {java_version_mixin}, expected JAVA_21')
    
    # Check Fabric loader version
    loader_version = gradle_props.get('loader_version', '')
    if loader_version != '0.16.9':
        warnings.append(f'loader_version is {loader_version}, expected 0.16.9')
    
    # Check Fabric API version
    fabric_version = gradle_props.get('fabric_version', '')
    if not fabric_version.startswith('0.116.0'):
        warnings.append(f'fabric_version is {fabric_version}, expected 0.116.0+...')
    
    # Check Yarn mappings
    yarn_mappings = gradle_props.get('yarn_mappings', '')
    if not yarn_mappings.startswith('1.21.4'):
        warnings.append(f'yarn_mappings is {yarn_mappings}, expected 1.21.4+...')
    
    return errors, warnings

def main():
    print("Validating MinecraftML build configuration...")
    print("=" * 50)
    
    errors, warnings = check_versions()
    
    if warnings:
        print("\nWarnings:")
        for warning in warnings:
            print(f"  WARNING: {warning}")
    
    if errors:
        print("\nErrors:")
        for error in errors:
            print(f"  ERROR: {error}")
        print(f"\nValidation FAILED with {len(errors)} error(s)")
        return 1
    else:
        print("\nSUCCESS: All version checks passed!")
        if warnings:
            print(f"  (with {len(warnings)} warning(s))")
        return 0

if __name__ == '__main__':
    sys.exit(main())