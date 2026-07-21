#!/usr/bin/env python3
"""Validate protocol v2 fixtures against expected schema."""

import json
import os
from pathlib import Path
from typing import Dict, Any, List
import sys

class ProtocolValidator:
    """Validate protocol v2 messages against expected structure."""
    
    def __init__(self):
        self.required_fields = {
            "hello": ["type", "protocol_version", "capabilities"],
            "observation": ["type", "timestamp", "player", "inventory", "nearby_blocks", "nearby_entities", "control_state"],
            "action": ["type", "action_id", "skill_name", "skill_args", "action"],
            "control_state": ["type", "state", "reason"],
            "error": ["type", "code", "message"],
            "policy_update": ["type", "action_id", "reward", "agent_policy_version", "exploration_bandit", "exploration_parameters"]
        }
        
        self.action_types = ["control", "look_delta", "sequence", "noop", "stop"]
        self.control_states = ["OFF", "READY", "ACTIVE", "PAUSED", "MANUAL_OVERRIDE", "EMERGENCY_LATCHED", "FAULTED"]
    
    def validate_message(self, message: Dict[str, Any]) -> List[str]:
        """Validate a message and return list of errors."""
        errors = []
        
        # Check required type field
        if "type" not in message:
            return ["Missing required field: type"]
        
        msg_type = message["type"]
        
        # Check if type is known
        if msg_type not in self.required_fields:
            errors.append(f"Unknown message type: {msg_type}")
            return errors
        
        # Check required fields
        for field in self.required_fields[msg_type]:
            if field not in message:
                errors.append(f"Missing required field: {field}")
        
        # Type-specific validation
        if msg_type == "hello":
            errors.extend(self._validate_hello(message))
        elif msg_type == "observation":
            errors.extend(self._validate_observation(message))
        elif msg_type == "action":
            errors.extend(self._validate_action(message))
        elif msg_type == "control_state":
            errors.extend(self._validate_control_state(message))
        elif msg_type == "policy_update":
            errors.extend(self._validate_policy_update(message))
        
        return errors
    
    def _validate_hello(self, message: Dict[str, Any]) -> List[str]:
        errors = []
        if message.get("protocol_version") != "2.0":
            errors.append("protocol_version must be '2.0'")
        
        capabilities = message.get("capabilities", {})
        if not isinstance(capabilities, dict):
            errors.append("capabilities must be an object")
        else:
            required_caps = ["observation_fields", "action_types", "control_states"]
            for cap in required_caps:
                if cap not in capabilities:
                    errors.append(f"Missing capability: {cap}")
        
        return errors
    
    def _validate_observation(self, message: Dict[str, Any]) -> List[str]:
        errors = []
        
        # Check player structure
        player = message.get("player", {})
        required_player_fields = ["position", "velocity", "health"]
        for field in required_player_fields:
            if field not in player:
                errors.append(f"Missing player field: {field}")
        
        # Check control state
        state = message.get("control_state")
        if state not in self.control_states:
            errors.append(f"Invalid control_state: {state}")
        
        # Check arrays
        for array_field in ["inventory", "nearby_blocks", "nearby_entities"]:
            value = message.get(array_field)
            if not isinstance(value, list):
                errors.append(f"{array_field} must be an array")
        
        return errors
    
    def _validate_action(self, message: Dict[str, Any]) -> List[str]:
        errors = []
        
        action = message.get("action", {})
        action_type = action.get("type")
        
        if action_type not in self.action_types:
            errors.append(f"Invalid action type: {action_type}")
        else:
            # Type-specific validation
            if action_type == "control":
                errors.extend(self._validate_control_action(action))
            elif action_type == "look_delta":
                errors.extend(self._validate_look_delta_action(action))
            elif action_type == "sequence":
                errors.extend(self._validate_sequence_action(action))
            elif action_type == "noop":
                errors.extend(self._validate_noop_action(action))
            # stop action has no additional fields
        
        return errors
    
    def _validate_control_action(self, action: Dict[str, Any]) -> List[str]:
        errors = []
        required_fields = ["forward", "strafe", "jump", "sneak", "sprint", "attack", "use"]
        for field in required_fields:
            if field not in action:
                errors.append(f"Missing control field: {field}")
        return errors
    
    def _validate_look_delta_action(self, action: Dict[str, Any]) -> List[str]:
        errors = []
        required_fields = ["yaw", "pitch"]
        for field in required_fields:
            if field not in action:
                errors.append(f"Missing look_delta field: {field}")
        return errors
    
    def _validate_sequence_action(self, action: Dict[str, Any]) -> List[str]:
        errors = []
        if "steps" not in action:
            errors.append("Missing sequence steps")
        elif not isinstance(action["steps"], list):
            errors.append("steps must be an array")
        elif len(action["steps"]) == 0:
            errors.append("steps array cannot be empty")
        
        if "step_duration_ms" not in action:
            errors.append("Missing step_duration_ms")
        elif not isinstance(action["step_duration_ms"], (int, float)):
            errors.append("step_duration_ms must be a number")
        
        return errors
    
    def _validate_noop_action(self, action: Dict[str, Any]) -> List[str]:
        errors = []
        if "duration_ms" not in action:
            errors.append("Missing duration_ms")
        elif not isinstance(action["duration_ms"], (int, float)):
            errors.append("duration_ms must be a number")
        return errors
    
    def _validate_control_state(self, message: Dict[str, Any]) -> List[str]:
        errors = []
        state = message.get("state")
        if state not in self.control_states:
            errors.append(f"Invalid control state: {state}")
        return errors
    
    def _validate_policy_update(self, message: Dict[str, Any]) -> List[str]:
        errors = []
        reward = message.get("reward")
        if not isinstance(reward, (int, float)):
            errors.append("reward must be a number")
        
        exploration_parameters = message.get("exploration_parameters")
        if not isinstance(exploration_parameters, dict):
            errors.append("exploration_parameters must be an object")
        
        return errors

def validate_fixtures() -> bool:
    """Validate all fixture files."""
    validator = ProtocolValidator()
    fixtures_dir = Path("protocol_fixtures")
    
    all_valid = True
    
    for fixture_file in fixtures_dir.glob("*.json"):
        if fixture_file.name == "all_fixtures.json":
            continue
            
        print(f"\nValidating {fixture_file.name}:")
        
        try:
            with open(fixture_file, 'r') as f:
                data = json.load(f)
            
            errors = validator.validate_message(data)
            
            if errors:
                all_valid = False
                for error in errors:
                    print(f"  [ERROR] {error}")
            else:
                print(f"  [OK] Valid")
                
        except json.JSONDecodeError as e:
            all_valid = False
            print(f"  [ERROR] Invalid JSON: {e}")
        except Exception as e:
            all_valid = False
            print(f"  [ERROR] Error reading file: {e}")
    
    return all_valid

def create_all_fixtures_file():
    """Create a single file with all fixtures for easy reference."""
    fixtures_dir = Path("protocol_fixtures")
    all_fixtures = {}
    
    for fixture_file in fixtures_dir.glob("*.json"):
        if fixture_file.name == "all_fixtures.json":
            continue
            
        try:
            with open(fixture_file, 'r') as f:
                data = json.load(f)
            
            # Use filename without extension as key
            key = fixture_file.stem
            all_fixtures[key] = data
            
        except Exception as e:
            print(f"Warning: Could not read {fixture_file}: {e}")
    
    output_file = fixtures_dir / "all_fixtures.json"
    with open(output_file, 'w') as f:
        json.dump(all_fixtures, f, indent=2)
    
    print(f"\nCreated {output_file} with {len(all_fixtures)} fixtures")

if __name__ == "__main__":
    print("Protocol v2 Fixture Validation")
    print("=" * 40)
    
    # Validate all fixtures
    if validate_fixtures():
        print("\n[SUCCESS] All fixtures are valid!")
    else:
        print("\n[FAILURE] Some fixtures have validation errors")
        sys.exit(1)
    
    # Create combined fixtures file
    create_all_fixtures_file()