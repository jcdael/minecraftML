#!/usr/bin/env python3
"""
Test exploration reward formula as described in requirements.
The reward should be based on measurable game changes, not absolute distance from origin.
"""

def calculate_exploration_reward(before_state, after_state):
    """
    Calculate exploration reward based on requirements.
    
    Requirements say reward should be:
    + horizontal displacement, capped per action
    + new coarse navigation cells/chunks visited
    + small novelty for newly observed block/biome categories
    - attempted movement with negligible displacement
    - collision/stuck result
    - health loss
    - dangerous fall/fire/drowning state
    - death
    - action failure, cancellation, timeout, or unsafe continuation
    - excessive action duration
    
    For this test, we'll implement a simplified version.
    """
    reward = 0.0
    
    # Calculate horizontal displacement
    import math
    dx = after_state.get('x', 0) - before_state.get('x', 0)
    dz = after_state.get('z', 0) - before_state.get('z', 0)
    horizontal_displacement = math.sqrt(dx*dx + dz*dz)
    
    # Add horizontal displacement (capped)
    reward += min(horizontal_displacement, 5.0)  # Cap at 5 blocks
    
    # Penalize negligible displacement (if movement was attempted)
    if before_state.get('movement_attempted', False) and horizontal_displacement < 0.1:
        reward -= 1.0
    
    # Penalize health loss
    health_delta = after_state.get('health', 20) - before_state.get('health', 20)
    if health_delta < 0:
        reward += health_delta  # Negative delta reduces reward
    
    # Penalize death
    if after_state.get('health', 20) <= 0:
        reward -= 10.0
    
    # Penalize action failure
    if not after_state.get('action_success', True):
        reward -= 2.0
    
    return reward

def test_reward_formula():
    """Test the reward formula with example states."""
    print("Testing exploration reward formula...")
    
    # Test 1: Successful movement
    before = {'x': 0, 'z': 0, 'health': 20, 'movement_attempted': True}
    after = {'x': 3, 'z': 4, 'health': 20, 'action_success': True}  # 5 blocks displacement
    reward = calculate_exploration_reward(before, after)
    print(f"Test 1 - Movement 5 blocks: reward = {reward:.2f} (expected positive)")
    assert reward > 0, "Movement should give positive reward"
    
    # Test 2: No movement
    before = {'x': 0, 'z': 0, 'health': 20, 'movement_attempted': False}
    after = {'x': 0, 'z': 0, 'health': 20, 'action_success': True}
    reward = calculate_exploration_reward(before, after)
    print(f"Test 2 - No movement: reward = {reward:.2f} (expected ~0)")
    
    # Test 3: Health loss
    before = {'x': 0, 'z': 0, 'health': 20, 'movement_attempted': True}
    after = {'x': 1, 'z': 0, 'health': 15, 'action_success': True}  # 5 health loss
    reward = calculate_exploration_reward(before, after)
    print(f"Test 3 - Movement with health loss: reward = {reward:.2f} (expected lower)")
    assert reward < 1.0, "Health loss should reduce reward"
    
    # Test 4: Death
    before = {'x': 0, 'z': 0, 'health': 20, 'movement_attempted': True}
    after = {'x': 0, 'z': 0, 'health': 0, 'action_success': False}
    reward = calculate_exploration_reward(before, after)
    print(f"Test 4 - Death: reward = {reward:.2f} (expected very negative)")
    assert reward < -5.0, "Death should give large negative reward"
    
    # Test 5: Stuck (negligible displacement with movement attempted)
    before = {'x': 0, 'z': 0, 'health': 20, 'movement_attempted': True}
    after = {'x': 0.05, 'z': 0.05, 'health': 20, 'action_success': True}  # ~0.07 blocks
    reward = calculate_exploration_reward(before, after)
    print(f"Test 5 - Stuck/negligible movement: reward = {reward:.2f} (expected negative)")
    assert reward < 0, "Negligible movement should be penalized"
    
    print("\nAll reward formula tests passed!")
    return True

if __name__ == '__main__':
    try:
        test_reward_formula()
        print("\nSUCCESS: Reward formula test completed successfully.")
    except AssertionError as e:
        print(f"\nFAILED: {e}")
        exit(1)
    except Exception as e:
        print(f"\nERROR: {e}")
        exit(1)