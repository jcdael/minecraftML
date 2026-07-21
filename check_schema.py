#!/usr/bin/env python3
"""Check database schema and version."""

import sqlite3
import sys

def main() -> None:
    conn = sqlite3.connect("experience.db")
    cursor = conn.cursor()
    
    # List all tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row[0] for row in cursor.fetchall()]
    print(f"Existing tables: {tables}")
    
    # Check schema version
    try:
        cursor.execute("SELECT value FROM schema_meta WHERE key='schema_version'")
        row = cursor.fetchone()
        if row:
            print(f"Schema version: {row[0]}")
        else:
            print("Schema version: unknown (no schema_meta entry)")
    except sqlite3.OperationalError:
        print("Schema version: unknown (schema_meta table doesn't exist)")
    
    # Check policy_updates table
    if 'policy_updates' in tables:
        print("policy_updates table exists")
        # Check its columns
        cursor.execute("PRAGMA table_info(policy_updates)")
        columns = cursor.fetchall()
        print("policy_updates columns:")
        for col in columns:
            print(f"  {col[1]} ({col[2]}) - {'PRIMARY KEY' if col[5] else ''}")
    else:
        print("policy_updates table does NOT exist")
    
    conn.close()

if __name__ == "__main__":
    main()