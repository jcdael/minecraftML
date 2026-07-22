#!/usr/bin/env python3
"""
Test Python protocol implementation for issues identified in audit.
"""

import sys
import os

# Add brain directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'brain'))

try:
    import protocol
    print("SUCCESS: Successfully imported protocol module")
    
    # Check protocol version
    print(f"Protocol version: {protocol.PROTOCOL_VERSION}")
    if protocol.PROTOCOL_VERSION != 2:
        print(f"ERROR: PROTOCOL_VERSION should be 2, but is {protocol.PROTOCOL_VERSION}")
    else:
        print("OK: PROTOCOL_VERSION is correct (2)")
    
    # Check adapter role
    print(f"Adapter role: {protocol.ADAPTER_ROLE}")
    if protocol.ADAPTER_ROLE != "fabric_local_player":
        print(f"ERROR: ADAPTER_ROLE should be 'fabric_local_player', but is '{protocol.ADAPTER_ROLE}'")
    else:
        print("OK: ADAPTER_ROLE is correct ('fabric_local_player')")
    
    # Check supported actions
    print(f"\nSupported actions: {protocol.SUPPORTED_ACTIONS}")
    
    # Check for problematic actions that shouldn't be in phase 2
    phase2_actions = {"noop", "stop", "control", "look_delta", "sequence"}
    extra_actions = protocol.SUPPORTED_ACTIONS - phase2_actions
    if extra_actions:
        print(f"WARNING: Protocol supports actions not in phase 2: {extra_actions}")
    
    print("\nProtocol import test completed.")
    
except ImportError as e:
    print(f"ERROR: Failed to import protocol: {e}")
    sys.exit(1)
except Exception as e:
    print(f"ERROR: Error during test: {e}")
    sys.exit(1)