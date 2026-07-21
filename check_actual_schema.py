import sqlite3
from pathlib import Path

# Check the actual experience.db
db_path = Path("experience.db")
if not db_path.exists():
    print("experience.db does not exist")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Check schema version
cursor.execute("SELECT value FROM schema_meta WHERE key='schema_version'")
version_row = cursor.fetchone()
schema_version = int(version_row[0]) if version_row else 0
print(f"Schema version: {schema_version}")

# Check if policy_updates table exists
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='policy_updates'")
table_exists = cursor.fetchone()
print(f"policy_updates table exists: {bool(table_exists)}")

if table_exists:
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
        print("\nSUCCESS: action_id has PRIMARY KEY constraint (implies UNIQUE)")
    else:
        print("\nFAILURE: action_id does not have PRIMARY KEY constraint")

conn.close()