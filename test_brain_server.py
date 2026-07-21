#!/usr/bin/env python3
"""
MinecraftML Fabric Local-Player MVP - Integration Test Script
This script simulates the Python brain server side to test the Fabric mod.
"""

import asyncio
import websockets
import json
import time

class MockBrainServer:
    def __init__(self, host='localhost', port=8765):
        self.host = host
        self.port = port
        self.clients = set()
        self.handshake_received = False
        
    async def handle_client(self, websocket, path):
        """Handle a WebSocket client connection."""
        self.clients.add(websocket)
        print(f"Client connected: {websocket.remote_address}")
        
        try:
            async for message in websocket:
                await self.handle_message(websocket, message)
                
        except websockets.exceptions.ConnectionClosed:
            print(f"Client disconnected: {websocket.remote_address}")
        finally:
            self.clients.remove(websocket)
    
    async def handle_message(self, websocket, message):
        """Handle incoming messages from the client."""
        try:
            data = json.loads(message)
            message_type = data.get('type', 'unknown')
            
            print(f"Received message type: {message_type}")
            
            if message_type == 'handshake':
                await self.handle_handshake(websocket, data)
            elif message_type == 'observation':
                await self.handle_observation(websocket, data)
            else:
                print(f"Unknown message type: {message_type}")
                
        except json.JSONDecodeError as e:
            print(f"Invalid JSON received: {e}")
    
    async def handle_handshake(self, websocket, handshake):
        """Handle handshake from client."""
        print(f"Handshake received:")
        print(f"  Version: {handshake.get('version')}")
        print(f"  Role: {handshake.get('role')}")
        print(f"  Capabilities: {handshake.get('capabilities')}")
        
        # Send handshake response
        response = {
            'type': 'handshake',
            'version': '2.0',
            'role': 'brain',
            'capabilities': ['control', 'look_delta', 'sequence', 'stop', 'noop']
        }
        
        await websocket.send(json.dumps(response))
        print("Handshake response sent")
        self.handshake_received = True
    
    async def handle_observation(self, websocket, observation):
        """Handle observation from client."""
        tick = observation.get('tick', 0)
        data = observation.get('data', {})
        
        print(f"Observation received (tick: {tick}):")
        
        # Extract and display key information
        if 'player' in data:
            player = data['player']
            print(f"  Player: x={player.get('x', 0):.2f}, y={player.get('y', 0):.2f}, z={player.get('z', 0):.2f}")
            print(f"  Health: {player.get('health', 0)}/{player.get('max_health', 20)}")
        
        # Send a simple action back
        if self.handshake_received:
            await self.send_test_action(websocket)
    
    async def send_test_action(self, websocket):
        """Send a test action to the client."""
        # Send a simple movement action
        action = {
            'type': 'control',
            'data': {
                'key': 'forward',
                'pressed': True,
                'duration': 10  # 10 ticks
            }
        }
        
        await websocket.send(json.dumps(action))
        print("Test action sent: forward for 10 ticks")
        
        # After 2 seconds, send stop
        await asyncio.sleep(2)
        
        stop_action = {
            'type': 'stop',
            'data': {
                'immediate': True
            }
        }
        
        await websocket.send(json.dumps(stop_action))
        print("Stop action sent")
    
    async def run(self):
        """Run the WebSocket server."""
        print(f"Starting Mock Brain Server on {self.host}:{self.port}")
        print("Waiting for Fabric mod connection...")
        print("Make sure Minecraft is running with the Fabric mod installed")
        print("Press F8 in Minecraft to activate AI control")
        
        async with websockets.serve(self.handle_client, self.host, self.port):
            await asyncio.Future()  # Run forever

def main():
    """Main entry point."""
    print("=" * 60)
    print("MinecraftML Fabric Local-Player MVP - Integration Test")
    print("=" * 60)
    print()
    print("This script simulates a Python brain server to test the Fabric mod.")
    print("Prerequisites:")
    print("  1. Minecraft with Fabric loader installed")
    print("  2. MinecraftML Fabric mod installed")
    print("  3. Python 3.7+ with websockets library")
    print()
    print("To install websockets library:")
    print("  pip install websockets")
    print()
    
    server = MockBrainServer()
    
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        print("\nServer stopped by user")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()