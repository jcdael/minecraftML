#!/usr/bin/env python3
"""Test the migration to schema version 5."""

import sqlite3
from pathlib import Path
import sys

# Add the brain module to path
sys.path.insert(0, '.')

from brain.memory import ExperienceStore

def main() -> None:
    # Use a test database
    test_db = Path("test_experience.db")
    if test_db.exists():
        test_db.unlink()
    
    store = None
    try:
        # Create store - this should run migrations
        store = ExperienceStore(test_db)
        
        # Check schema version
        cursor = store.connection.cursor()
        cursor.execute("SELECT value FROM schema_meta WHERE key='schema_version'")
        row = cursor.fetchone()
        print(f"Schema version after initialization: {row[0] if row else 'unknown'}")
        
        # Check tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]
        print(f"Tables: {tables}")
        
        # Verify policy_updates table exists and has correct columns
        if 'policy_updates' in tables:
            print("OK: policy_updates table exists")
            cursor.execute("PRAGMA table_info(policy_updates)")
            columns = cursor.fetchall()
            column_names = [col[1] for col in columns]
            expected_columns = [
                'action_id', 'timestamp', 'skill_name', 'skill_args_json',
                'state_before_json', 'selected_action_json', 'reward',
                'agent_policy_version', 'exploration_bandit', 'exploration_parameters_json'
            ]
            
            for col in expected_columns:
                if col in column_names:
                    print(f"  OK: Column '{col}' exists")
                else:
                    print(f"  ERROR: Column '{col}' missing")
            
            # Check primary key constraint
            cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='policy_updates'")
            table_sql = cursor.fetchone()[0]
            if "PRIMARY KEY" in table_sql and "action_id" in table_sql:
                print("OK: action_id is PRIMARY KEY")
            else:
                print("ERROR: action_id is not PRIMARY KEY")
        else:
            print("ERROR: policy_updates table missing")
        
        # Test adding a policy update
        store.add_policy_update(
            action_id="test_action_123",
            skill_name="explore",
            skill_args={"radius": 10},
            state_before={"position": [0, 0, 0]},
            selected_action={"type": "move", "direction": "north"},
            reward=0.5,
            agent_policy_version="v1.0",
            exploration_bandit="UCB",
            exploration_parameters={"c": 2.0}
        )
        print("OK: Successfully added policy update")
        
        # Verify it was inserted
        cursor.execute("SELECT COUNT(*) FROM policy_updates")
        count = cursor.fetchone()[0]
        print(f"OK: policy_updates count: {count}")
        
    finally:
        # Clean up
        if store:
            store.close()
        if test_db.exists():
            try:
                test_db.unlink()
            except PermissionError:
                print(f"Warning: Could not delete {test_db} - it may still be in use")
    
    print("\nMigration test completed!")

if __name__ == "__main__":
    main()