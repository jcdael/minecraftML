import re

with open('tests/test_phase1.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the test_trace_replay method
match = re.search(r'def test_trace_replay.*?(?=def test_|$)', content, re.DOTALL)
if match:
    print("Found test_trace_replay method:")
    print(match.group(0))
    print("\nLength:", len(match.group(0)))
else:
    print("Could not find test_trace_replay method")
    
# Also check where the file ends
print("\nLast 100 characters of file:")
print(content[-100:])