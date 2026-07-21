import sqlite3

conn = sqlite3.connect('experience.db')
cursor = conn.cursor()
cursor.execute('SELECT name, sql FROM sqlite_master WHERE type="table"')
tables = cursor.fetchall()

print("Tables in experience.db:")
for name, sql in tables:
    print(f"\n=== {name} ===")
    if sql:
        print(sql)
    else:
        print("(no SQL definition)")
    
    # Show column info
    cursor.execute(f'PRAGMA table_info("{name}")')
    columns = cursor.fetchall()
    print("Columns:")
    for col in columns:
        print(f"  {col[1]} ({col[2]})")

conn.close()