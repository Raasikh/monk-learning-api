import re
import json

s = '{"board": "\\Delta U = q + w"}'
print("RAW STRING IN PYTHON:", repr(s))

pat = re.compile(r'\\(?!["\\/bfnrt]|u[0-9a-fA-F]{4})')

res1 = pat.sub(lambda m: '\\\\' + m.group(0), s)
print("\nRES1 (\\\\\\\\ + m.group(0)):", repr(res1))

res2 = pat.sub(lambda m: '\\\\' + m.group(0)[1:], s)
print("RES2 (\\\\\\\\ + m.group(0)[1:]):", repr(res2))

try:
    json.loads(res1)
    print("\nRES1 LOAD: SUCCESS")
except Exception as e:
    print("RES1 LOAD FAILED:", e)

try:
    parsed = json.loads(res2)
    print("RES2 LOAD: SUCCESS!")
    print("PARSED:", parsed)
except Exception as e:
    print("RES2 LOAD FAILED:", e)
