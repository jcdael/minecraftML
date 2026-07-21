import sqlite3
import os
from pathlib import Path

# Create a test database
test_db = Path('test_experience.db')
if test_db.exists():
    test_db.unlink()

# Import and test the memory module
import sys
sys.path.insert(0, '.')

from brain.memory import ExperienceStore

# Create the store
store = ExperienceStore(test_db)

# Check the schema
conn = sqlite3.connect(test_db)
cursor = conn.cursor()

print('Schema meta:')
cursor.execute('SELECT * FROM schema_meta')
for row in cursor.fetchall():
    print(f'  {row}')

print('\npolicy_updates table schema:')
cursor.execute('PRAGMA table_info(policy_updates)')
columns = cursor.fetchall()
if columns:
    for row in columns:
        print(f'  {row}')
else:
    print('  Table does not exist')

print('\npolicy_updates table constraints:')
cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='policy_updates'")
result = cursor.fetchone()
if result:
    print(result[0])

# Test adding a policy update
store.add_policy_update(
    action_id='test-action-123',
    skill_name='test_skill',
    skill_args={'param': 'value'},
    state_before={'state': 'before'},
    selected_action={'action': 'test'},
    reward=1.0,
    agent_policy_version='v1',
    exploration_bandit='UCB',
    exploration_parameters={'c': 2.0}
)

print('\nPolicy update added successfully')

# Try to add duplicate
try:
    store.add_policy_update(
        action_id='test-action-123',
        skill_name='test_skill',
        skill_args={'param': 'value2'},
        state_before={'state': 'before2'},
        selected_action={'action': 'test2'},
        reward=2.0,
        agent_policy_version='v1',
        exploration_bandit='UCB',
        exploration_parameters={'c': 2.0}
    )
    print('Duplicate action_id replaced (as expected with PRIMARY KEY)')
except Exception as e:
    print(f'Error with duplicate: {e}')

conn.close()
store.close()

# Clean up
test_db.unlink()
print('\nTest completed successfully')