import sqlite3
from pathlib import Path

# Create a test database
test_db = Path("test_experience.db")
if test_db.exists():
    test_db.unlink()

# Import memory to trigger migration
from brain.memory import ExperienceStore

store = ExperienceStore(test_db)

# Check if policy_updates table exists
conn = sqlite3.connect(test_db)
cursor = conn.cursor()

# Check table exists
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='policy_updates'")
table_exists = cursor.fetchone()
print(f"policy_updates table exists: {bool(table_exists)}")

# Check schema
cursor.execute("PRAGMA table_info(policy_updates)")
columns = cursor.fetchall()
print("\npolicy_updates columns:")
for col in columns:
    print(f"  {col[1]} ({col[2]}) - PK: {col[5]}")

# Check UNIQUE constraint
cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='policy_updates'")
sql = cursor.fetchone()[0]
print(f"\nTable SQL:\n{sql}")

# Check if action_id is PRIMARY KEY (which implies UNIQUE)
if "PRIMARY KEY" in sql and "action_id" in sql:
    print("\n✓ action_id has PRIMARY KEY constraint (implies UNIQUE)")
else:
    print("\n✗ action_id does not have PRIMARY KEY constraint")

conn.close()
store.close()
test_db.unlink()