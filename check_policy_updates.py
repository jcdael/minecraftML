import sqlite3
import os

db_path = 'brain/experience.db'

if not os.path.exists(db_path):
    print(f"Database file {db_path} does not exist")
    exit(0)

conn = sqlite3.connect(db_path)
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

print('\nAll tables:')
cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name")
for name, sql in cursor.fetchall():
    print(f'\n{name}:')
    print(f'  {sql}')

conn.close()