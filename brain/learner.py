from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class BanditArm:
    """Represents an arm in the multi-armed bandit."""
    name: str
    attempts: int = 0
    successes: int = 0
    total_reward: float = 0.0
    last_selected: float = 0.0  # timestamp
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate (avoid division by zero)."""
        if self.attempts == 0:
            return 0.0
        return self.successes / self.attempts
    
    @property
    def average_reward(self) -> float:
        """Calculate average reward per attempt."""
        if self.attempts == 0:
            return 0.0
        return self.total_reward / self.attempts
    
    def record_attempt(self, reward: float = 0.0) -> None:
        """Record an attempt with optional reward."""
        self.attempts += 1
        self.total_reward += reward
        if reward > 0:
            self.successes += 1
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "attempts": self.attempts,
            "successes": self.successes,
            "total_reward": self.total_reward,
            "last_selected": self.last_selected
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> BanditArm:
        """Create from dictionary."""
        return cls(
            name=data["name"],
            attempts=data["attempts"],
            successes=data["successes"],
            total_reward=data["total_reward"],
            last_selected=data["last_selected"]
        )


class PersistentUCBBandit:
    """Upper Confidence Bound bandit with persistence.
    
    Implements UCB1 algorithm with exploration-exploitation tradeoff.
    Persists state to disk for learning across sessions.
    """
    
    def __init__(
        self,
        data_dir: Path,
        exploration_weight: float = 2.0,
        min_attempts_for_exploitation: int = 5
    ) -> None:
        """
        Args:
            data_dir: Directory to store bandit state
            exploration_weight: Weight for exploration term (higher = more exploration)
            min_attempts_for_exploitation: Minimum attempts before using UCB
        """
        self.data_dir = Path(data_dir)
        self.exploration_weight = exploration_weight
        self.min_attempts = min_attempts_for_exploitation
        
        # Create data directory if it doesn't exist
        os.makedirs(self.data_dir, exist_ok=True)
        
        # Load existing arms or initialize empty
        self.arms: Dict[str, BanditArm] = {}
        self.total_attempts: int = 0
        self._load_state()
    
    def select_arm(self, arm_names: List[str]) -> int:
        """Select an arm using UCB1 algorithm.
        
        Args:
            arm_names: List of arm names to choose from
            
        Returns:
            Index of selected arm in arm_names list
        """
        import time
        
        # Ensure all arms exist
        for name in arm_names:
            if name not in self.arms:
                self.arms[name] = BanditArm(name=name)
        
        current_time = time.time()
        
        # If we don't have enough data, select randomly among under-explored arms
        if self.total_attempts < self.min_attempts * len(arm_names):
            # Find arms with fewer than min_attempts
            under_explored = [
                idx for idx, name in enumerate(arm_names)
                if self.arms[name].attempts < self.min_attempts
            ]
            if under_explored:
                import random
                selected_idx = random.choice(under_explored)
                selected_name = arm_names[selected_idx]
                self.arms[selected_name].last_selected = current_time
                return selected_idx
        
        # Calculate UCB scores
        scores = []
        for name in arm_names:
            arm = self.arms[name]
            
            if arm.attempts == 0:
                # Never tried this arm - high exploration value
                score = float('inf')
            else:
                # UCB1 formula: average_reward + exploration_weight * sqrt(ln(total_attempts) / attempts)
                exploitation = arm.average_reward
                exploration = self.exploration_weight * math.sqrt(
                    math.log(self.total_attempts) / arm.attempts
                )
                score = exploitation + exploration
            
            scores.append(score)
        
        # Select arm with highest score
        selected_idx = scores.index(max(scores))
        selected_name = arm_names[selected_idx]
        
        # Update last selected time
        self.arms[selected_name].last_selected = current_time
        
        return selected_idx
    
    def record_attempt(self, arm_name: str, reward: float = 0.0) -> None:
        """Record an attempt for an arm.
        
        Args:
            arm_name: Name of the arm
            reward: Reward received from this attempt
        """
        if arm_name not in self.arms:
            self.arms[arm_name] = BanditArm(name=arm_name)
        
        self.arms[arm_name].record_attempt(reward)
        self.total_attempts += 1
        
        # Auto-save periodically
        if self.total_attempts % 10 == 0:
            self.save()
    
    def record_result(self, arm_name: str, reward: float) -> None:
        """Record a result for an arm (alias for record_attempt).
        
        Args:
            arm_name: Name of the arm
            reward: Reward received
        """
        self.record_attempt(arm_name, reward)
    
    def get_arm_stats(self, arm_name: str) -> Optional[Dict]:
        """Get statistics for a specific arm.
        
        Returns:
            Dictionary with arm statistics or None if arm doesn't exist
        """
        if arm_name not in self.arms:
            return None
        
        arm = self.arms[arm_name]
        return {
            "name": arm.name,
            "attempts": arm.attempts,
            "successes": arm.successes,
            "success_rate": arm.success_rate,
            "total_reward": arm.total_reward,
            "average_reward": arm.average_reward,
            "last_selected": arm.last_selected
        }
    
    def get_all_stats(self) -> Dict[str, Dict]:
        """Get statistics for all arms."""
        return {
            name: self.get_arm_stats(name)
            for name in self.arms
        }
    
    def should_save(self) -> bool:
        """Check if we should save state (based on number of attempts)."""
        return self.total_attempts % 20 == 0
    
    def save(self) -> None:
        """Save bandit state to disk."""
        state = {
            "exploration_weight": self.exploration_weight,
            "min_attempts": self.min_attempts,
            "total_attempts": self.total_attempts,
            "arms": {
                name: arm.to_dict()
                for name, arm in self.arms.items()
            }
        }
        
        state_file = self.data_dir / "bandit_state.json"
        with open(state_file, 'w') as f:
            json.dump(state, f, indent=2)
    
    def load(self) -> None:
        """Load bandit state from disk."""
        state_file = self.data_dir / "bandit_state.json"
        if not os.path.exists(state_file):
            return
        
        with open(state_file, 'r') as f:
            state = json.load(f)
        
        self.exploration_weight = state.get("exploration_weight", self.exploration_weight)
        self.min_attempts = state.get("min_attempts", self.min_attempts)
        self.total_attempts = state.get("total_attempts", 0)
        
        self.arms = {}
        arms_data = state.get("arms", {})
        for name, arm_data in arms_data.items():
            self.arms[name] = BanditArm.from_dict(arm_data)
    
    def _load_state(self) -> None:
        """Load state (alias for load)."""
        self.load()
    
    def reset(self) -> None:
        """Reset bandit state (clear all learning)."""
        self.arms = {}
        self.total_attempts = 0
        
        # Remove state file
        state_file = self.data_dir / "bandit_state.json"
        if os.path.exists(state_file):
            os.remove(state_file)