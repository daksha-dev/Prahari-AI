import json
with open('results.json') as f:
    r = json.load(f)

for dev_id, dev_data in r.get('devices', {}).items():
    if '10.0.5' in dev_id:
        print(f"{dev_id}: {len(dev_data.get('history', []))} windows")
