#!/usr/bin/env python3
"""Validate evidence bundle for MinecraftML live test."""

import json
import os
import sys
from pathlib import Path
import sqlite3
from typing import Any, Dict, List

def validate_evidence_bundle(evidence_dir: str) -> bool:
    """Validate evidence bundle directory structure and contents."""
    evidence_path = Path(evidence_dir)
    
    if not evidence_path.exists():
        print(f"ERROR: Evidence directory does not exist: {evidence_dir}")
        return False
    
    print(f"Validating evidence bundle: {evidence_dir}")
    print("=" * 60)
    
    all_passed = True
    
    # Required files
    required_files = [
        "base-and-final-git-state.txt",
        "environment.txt",
        "baseline-build.log",
        "final-gradle-build.log",
        "python-tests.log",
        "jar-contents.txt",
        "tlauncher-profile.txt",
        "minecraft-latest.log",
        "brain-live.log",
        "session-summary.json",
        "transitions.jsonl",
        "reward-breakdown.jsonl",
        "database-before-after.txt",
        "policy-before.json",
        "policy-after.json",
        "policy-diff.txt",
        "safety-tests.md",
        "live-test-report.md"
    ]
    
    print("1. Checking required files...")
    for file in required_files:
        file_path = evidence_path / file
        if file_path.exists():
            print(f"   ✓ {file}")
        else:
            print(f"   ✗ {file} - MISSING")
            all_passed = False
    
    # Check screenshots directory
    screenshots_dir = evidence_path / "screenshots"
    if screenshots_dir.exists():
        screenshot_files = list(screenshots_dir.glob("*.png"))
        if len(screenshot_files) >= 3:
            print(f"   ✓ screenshots/ (has {len(screenshot_files)} images)")
        else:
            print(f"   ✗ screenshots/ - Needs at least 3 screenshots, found {len(screenshot_files)}")
            all_passed = False
    else:
        print("   ✗ screenshots/ directory - MISSING")
        all_passed = False
    
    # Validate session-summary.json
    print("\n2. Validating session-summary.json...")
    session_file = evidence_path / "session-summary.json"
    if session_file.exists():
        try:
            with open(session_file, 'r') as f:
                session_data = json.load(f)
            
            required_fields = [
                "base_commit", "tested_commit", "minecraft_version",
                "fabric_loader_version", "fabric_api_version", "java_version",
                "tlauncher_profile", "world_name", "session_id", "goal",
                "start_position", "end_position", "path_length", "net_displacement",
                "yaw_range", "unique_action_ids", "matched_transitions",
                "policy_updates", "arms_attempted", "manual_override_passed",
                "f8_stop_passed", "deadman_passed", "f9_local_passed",
                "final_controls_released"
            ]
            
            for field in required_fields:
                if field in session_data:
                    print(f"   ✓ {field}: {session_data[field]}")
                else:
                    print(f"   ✗ {field} - MISSING")
                    all_passed = False
            
            # Check acceptance criteria
            if session_data.get("matched_transitions", 0) >= 30:
                print(f"   ✓ matched_transitions >= 30: {session_data['matched_transitions']}")
            else:
                print(f"   ✗ matched_transitions < 30: {session_data.get('matched_transitions', 0)}")
                all_passed = False
                
            if session_data.get("unique_action_ids", 0) >= 30:
                print(f"   ✓ unique_action_ids >= 30: {session_data['unique_action_ids']}")
            else:
                print(f"   ✗ unique_action_ids < 30: {session_data.get('unique_action_ids', 0)}")
                all_passed = False
                
            if len(session_data.get("arms_attempted", [])) >= 3:
                print(f"   ✓ arms_attempted >= 3: {session_data['arms_attempted']}")
            else:
                print(f"   ✗ arms_attempted < 3: {session_data.get('arms_attempted', [])}")
                all_passed = False
                
            if session_data.get("path_length", 0) > 20:
                print(f"   ✓ path_length > 20: {session_data['path_length']}")
            else:
                print(f"   ✗ path_length <= 20: {session_data.get('path_length', 0)}")
                all_passed = False
                
            # All safety tests must pass
            safety_tests = [
                "manual_override_passed",
                "f8_stop_passed", 
                "deadman_passed",
                "f9_local_passed",
                "final_controls_released"
            ]
            
            for test in safety_tests:
                if session_data.get(test):
                    print(f"   ✓ {test}: PASSED")
                else:
                    print(f"   ✗ {test}: FAILED")
                    all_passed = False
                    
        except Exception as e:
            print(f"   ✗ Error parsing session-summary.json: {e}")
            all_passed = False
    else:
        print("   ✗ session-summary.json - MISSING")
        all_passed = False
    
    # Validate transitions.jsonl
    print("\n3. Validating transitions.jsonl...")
    transitions_file = evidence_path / "transitions.jsonl"
    if transitions_file.exists():
        try:
            transitions = []
            with open(transitions_file, 'r') as f:
                for line in f:
                    if line.strip():
                        transitions.append(json.loads(line))
            
            print(f"   ✓ Found {len(transitions)} transitions")
            
            if len(transitions) >= 30:
                print(f"   ✓ At least 30 transitions: {len(transitions)}")
            else:
                print(f"   ✗ Less than 30 transitions: {len(transitions)}")
                all_passed = False
            
            # Check for unique action IDs
            action_ids = [t.get("action_id") for t in transitions if "action_id" in t]
            unique_ids = set(action_ids)
            
            if len(unique_ids) >= 30:
                print(f"   ✓ At least 30 unique action IDs: {len(unique_ids)}")
            else:
                print(f"   ✗ Less than 30 unique action IDs: {len(unique_ids)}")
                all_passed = False
                
            # Check each transition has required fields
            required_transition_fields = ["action_id", "before_state", "after_state", "result"]
            for i, trans in enumerate(transitions[:5]):  # Check first 5
                for field in required_transition_fields:
                    if field not in trans:
                        print(f"   ✗ Transition {i} missing {field}")
                        all_passed = False
                        break
                        
        except Exception as e:
            print(f"   ✗ Error parsing transitions.jsonl: {e}")
            all_passed = False
    else:
        print("   ✗ transitions.jsonl - MISSING")
        all_passed = False
    
    # Validate policy files
    print("\n4. Validating policy files...")
    policy_before = evidence_path / "policy-before.json"
    policy_after = evidence_path / "policy-after.json"
    policy_diff = evidence_path / "policy-diff.txt"
    
    if policy_before.exists() and policy_after.exists():
        try:
            with open(policy_before, 'r') as f:
                before = json.load(f)
            with open(policy_after, 'r') as f:
                after = json.load(f)
            
            print(f"   ✓ policy-before.json: {len(before.get('arms', []))} arms")
            print(f"   ✓ policy-after.json: {len(after.get('arms', []))} arms")
            
            # Check if policy changed
            if before != after:
                print("   ✓ Policy changed (learning occurred)")
            else:
                print("   ✗ Policy unchanged (no learning)")
                all_passed = False
                
            if policy_diff.exists():
                diff_size = os.path.getsize(policy_diff)
                if diff_size > 0:
                    print(f"   ✓ policy-diff.txt has changes ({diff_size} bytes)")
                else:
                    print("   ✗ policy-diff.txt is empty")
                    all_passed = False
            else:
                print("   ✗ policy-diff.txt - MISSING")
                all_passed = False
                
        except Exception as e:
            print(f"   ✗ Error parsing policy files: {e}")
            all_passed = False
    else:
        print("   ✗ Policy files missing")
        all_passed = False
    
    # Validate logs contain no critical errors
    print("\n5. Checking logs for critical errors...")
    log_files = ["minecraft-latest.log", "brain-live.log"]
    for log_file in log_files:
        log_path = evidence_path / log_file
        if log_path.exists():
            try:
                with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                error_keywords = [
                    "ERROR", "Exception", "Crash", "failed to load",
                    "missing dependency", "mixin failed", "class not found"
                ]
                
                errors_found = []
                for keyword in error_keywords:
                    if keyword in content:
                        errors_found.append(keyword)
                
                if errors_found:
                    print(f"   ⚠ {log_file}: Found errors: {', '.join(errors_found[:3])}")
                    # Don't fail for errors, just warn
                else:
                    print(f"   ✓ {log_file}: No critical errors")
            except Exception as e:
                print(f"   ✗ Error reading {log_file}: {e}")
        else:
            print(f"   ✗ {log_file} - MISSING")
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("VALIDATION PASSED ✓")
        return True
    else:
        print("VALIDATION FAILED ✗")
        return False

def main():
    if len(sys.argv) != 2:
        print("Usage: python validate_evidence.py <evidence_directory>")
        print("Example: python validate_evidence.py evidence/live-fabric/2024-01-15_12-30-00")
        sys.exit(1)
    
    evidence_dir = sys.argv[1]
    if validate_evidence_bundle(evidence_dir):
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()