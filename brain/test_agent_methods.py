#!/usr/bin/env python3
"""Test to check which SessionAgent methods are implemented vs required."""

import inspect
from agent import SessionAgent

# Methods called by main.py
required_methods = [
    'on_adapter_disconnect',
    'request_cancel_active',
    'set_goal',
    'set_paused',
    'status',
    'active_action_id',
    'next_action',
    'on_result',
    'on_cancel_ack',
    'on_death',
]

print("Checking SessionAgent implementation...")
print("=" * 50)

# Get all methods from SessionAgent class
agent_methods = [name for name, _ in inspect.getmembers(SessionAgent, predicate=inspect.isfunction)]

print(f"Total methods in SessionAgent: {len(agent_methods)}")
print(f"Required methods: {len(required_methods)}")
print()

missing_methods = []
for method in required_methods:
    if method in agent_methods:
        print(f"[OK] {method}() - IMPLEMENTED")
    else:
        print(f"[MISSING] {method}() - MISSING")
        missing_methods.append(method)

print()
print("=" * 50)
print(f"Missing methods: {len(missing_methods)}")
if missing_methods:
    print("Missing:")
    for method in missing_methods:
        print(f"  - {method}()")
else:
    print("All required methods are implemented!")

# Also check for memory attribute
print()
print("Checking for memory attribute...")
if hasattr(SessionAgent, 'memory'):
    print("[OK] SessionAgent has 'memory' attribute")
else:
    print("[MISSING] SessionAgent missing 'memory' attribute")

# Check if memory.add_protocol_error exists (called in main.py)
print()
print("Checking memory.add_protocol_error method...")
try:
    # Try to create an instance to check
    from goals import parse_goal
    default_goal = parse_goal("explore 100 blocks")
    test_agent = SessionAgent(default_goal)
    if hasattr(test_agent, 'memory') and hasattr(test_agent.memory, 'add_protocol_error'):
        print("[OK] memory.add_protocol_error() exists")
    else:
        print("[MISSING] memory.add_protocol_error() missing")
except Exception as e:
    print(f"[ERROR] Error checking memory: {e}")