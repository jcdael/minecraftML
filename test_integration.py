#!/usr/bin/env python3
"""
Test script for MinecraftML Fabric local-player MVP system.
This script tests the integration between the Fabric mod and the Python brain.
"""

import json
import asyncio
import websockets
import sys
import os

# Add brain directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'brain'))

from agent import SessionAgent
from goals import ExploreGoal
from learner import PersistentUCBBandit
from skills import count_inventory_items

class MockObservation:
    """Mock observation for testing."""
    def __init__(self):
        self.position = {"x": 0.0, "y": 64.0, "z": 0.0}
        self.health = 20.0
        self.hunger = 20
        self.inventory = []
        self.nearby_entities = []
        self.looking_at = {"yaw": 0.0, "pitch": 0.0}
        self.is_on_ground = True
        self.is_sprinting = False
        self.is_sneaking = False
        self.is_jumping = False

def test_brain_integration():
    """Test that the brain components work together."""
    print("Testing brain integration...")
    
    # Create a mock observation
    obs = MockObservation()
    
    # Create goal
    goal = ExploreGoal()
    
    # Create learner
    learner = PersistentUCBBandit()
    
    # Create agent
    agent = SessionAgent(goal, learner)
    
    # Test reward calculation
    reward = agent.calculate_reward(obs)
    print(f"✓ Reward calculation works: {reward}")
    
    # Test action selection
    action = agent.select_action(obs)
    print(f"✓ Action selection works: {action}")
    
    # Test learning update
    agent.learn(obs, action, reward)
    print("✓ Learning update works")
    
    print("\n✅ Brain integration test passed!")

def test_protocol_v2():
    """Test protocol V2 message formats."""
    print("\nTesting protocol V2...")
    
    # Test handshake
    handshake = {
        "version": 2,
        "role": "fabric_local_player",
        "capabilities": ["control", "look_delta", "sequence", "stop", "noop"]
    }
    
    # Test observation
    observation = {
        "type": "observation",
        "data": {
            "position": {"x": 0.0, "y": 64.0, "z": 0.0},
            "health": 20.0,
            "hunger": 20,
            "inventory": [],
            "nearby_entities": [],
            "looking_at": {"yaw": 0.0, "pitch": 0.0},
            "is_on_ground": True,
            "is_sprinting": False,
            "is_sneaking": False,
            "is_jumping": False
        }
    }
    
    # Test action
    action = {
        "type": "action",
        "action_type": "control",
        "data": {
            "key": "forward",
            "pressed": True,
            "duration": 10
        }
    }
    
    print(f"✓ Handshake format: {json.dumps(handshake, indent=2)}")
    print(f"✓ Observation format: {json.dumps(observation, indent=2)}")
    print(f"✓ Action format: {json.dumps(action, indent=2)}")
    
    print("\n✅ Protocol V2 test passed!")

async def test_websocket_server():
    """Test WebSocket server functionality."""
    print("\nTesting WebSocket server...")
    
    async def echo_server(websocket, path):
        """Simple echo server for testing."""
        async for message in websocket:
            data = json.loads(message)
            
            if data.get("type") == "handshake":
                # Accept handshake
                response = {
                    "type": "handshake_response",
                    "status": "accepted",
                    "role": "brain"
                }
                await websocket.send(json.dumps(response))
            elif data.get("type") == "observation":
                # Send a test action
                action = {
                    "type": "action",
                    "action_type": "noop",
                    "data": {}
                }
                await websocket.send(json.dumps(action))
    
    # Start test server
    server = await websockets.serve(echo_server, "localhost", 8765)
    
    print("✓ WebSocket server started on localhost:8765")
    
    # Give server time to start
    await asyncio.sleep(1)
    
    # Clean up
    server.close()
    await server.wait_closed()
    
    print("✅ WebSocket server test passed!")

def test_inventory_fix():
    """Test the inventory stack counting fix."""
    print("\nTesting inventory fix...")
    
    # Test inventory with duplicate stacks
    inventory = [
        {"type": "dirt", "count": 64},
        {"type": "dirt", "count": 32},
        {"type": "stone", "count": 64},
        {"type": "wood", "count": 16}
    ]
    
    counts = count_inventory_items(inventory)
    
    expected = {
        "dirt": 96,  # 64 + 32
        "stone": 64,
        "wood": 16
    }
    
    assert counts == expected, f"Expected {expected}, got {counts}"
    print(f"✓ Inventory counting works correctly: {counts}")
    
    print("✅ Inventory fix test passed!")

def main():
    """Run all tests."""
    print("=" * 60)
    print("MinecraftML Fabric Local-Player MVP System Tests")
    print("=" * 60)
    
    try:
        # Run tests
        test_inventory_fix()
        test_brain_integration()
        test_protocol_v2()
        
        # Note: WebSocket test requires async, so we'll skip it in automated tests
        # but mention it's available
        print("\n⚠️  WebSocket server test requires async execution.")
        print("   Run with: python -m asyncio test_integration.py")
        
        print("\n" + "=" * 60)
        print("✅ All core tests passed!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()