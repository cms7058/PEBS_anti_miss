"""A disposable real backend for the mini program contract tests. No network or user database."""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.server import Store, APIError
offset = 0
store = Store(':memory:', lambda: time.time() + offset)
for line in sys.stdin:
    call = json.loads(line)
    if 'advance' in call:
        offset += call['advance']
        store.tick()
        print(json.dumps({'statusCode': 200, 'data': {'ok': True}}), flush=True)
        continue
    try:
        result = store.dispatch(call['method'], call['path'], call.get('data') or {}, call.get('token', ''))
        output = {'statusCode': 200, 'data': result}
    except APIError as error:
        output = {'statusCode': error.status, 'data': {'error': error.message}}
    print(json.dumps(output), flush=True)
store.db.close()
