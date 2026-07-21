#!/usr/bin/env python3
"""
Protocol v2 fixture validation script.
Validates that all fixtures conform to the expected schema.
"""

import json
import os
import sys
from pathlib import Path

def validate_handshake(data):
    """Validate handshake fixture."""
    required = ["version", "role", "capabilities", "metadata"]
    for field in required:
        if field not in data:
            return False, f"Missing required field: {field}"
    
    if data["version"] != 2:
        return False, f"Version must be 2, got {data['version']}"
    
    if data["role"] != "fabric_local_player":
        return False, f"Role must be 'fabric_local_player', got {data['role']}"
    
    return True, "Valid handshake"

def validate_observation(data):
    """Validate observation fixture."""
    if data["type"] != "observation":
        return False, f"Type must be 'observation', got {data['type']}"
    
    if "data" not in data:
        return False, "Missing 'data' field"
    
    data_fields = data["data"]
    required_sections = ["player", "world"]
    for section in required_sections:
        if section not in data_fields:
            return False, f"Missing section in data: {section}"
    
    return True, "Valid observation"

def validate_action(data, action_type):
    """Validate action fixture."""
    if data["type"] != "action":
        return False, f"Type must be 'action', got {data['type']}"
    
    if "data" not in data:
        return False, "Missing 'data' field"
    
    action_data = data["data"]
    if action_data.get("action_type") != action_type:
        return False, f"Action type mismatch: expected {action_type}, got {action_data.get('action_type')}"
    
    return True, f"Valid {action_type} action"

def main():
    """Main validation function."""
    fixtures_dir = Path("fixtures")
    if not fixtures_dir.exists():
        print("Error: fixtures directory not found")
        return 1
    
    fixtures = [
        ("protocol_v2_handshake.json", validate_handshake),
        ("protocol_v2_observation.json", validate_observation),
        ("protocol_v2_action_control.json", lambda d: validate_action(d, "control")),
        ("protocol_v2_action_look_delta.json", lambda d: validate_action(d, "look_delta")),
        ("protocol_v2_action_sequence.json", lambda d: validate_action(d, "sequence")),
        ("protocol_v2_action_stop.json", lambda d: validate_action(d, "stop")),
        ("protocol_v2_action_noop.json", lambda d: validate_action(d, "noop")),
    ]
    
    all_valid = True
    
    for filename, validator in fixtures:
        filepath = fixtures_dir / filename
        if not filepath.exists():
            print(f"FAIL: Missing fixture: {filename}")
            all_valid = False
            continue
        
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            is_valid, message = validator(data)
            if is_valid:
                print(f"PASS: {filename}: {message}")
            else:
                print(f"FAIL: {filename}: {message}")
                all_valid = False
                
        except json.JSONDecodeError as e:
            print(f"FAIL: {filename}: Invalid JSON - {e}")
            all_valid = False
        except Exception as e:
            print(f"FAIL: {filename}: Error - {e}")
            all_valid = False
    
    if all_valid:
        print("\nSUCCESS: All fixtures are valid!")
        return 0
    else:
        print("\nWARNING: Some fixtures failed validation")
        return 1

if __name__ == "__main__":
    sys.exit(main())