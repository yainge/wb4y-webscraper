import json

with open('Attempt3/Tariff_preprocesssing/input/provider_tariffs.json', 'r') as f:
    data = json.load(f)

print('JSON File Summary:')
print(f'  Total records: {data["metadata"]["total_records"]}')
print(f'  Columns: {data["metadata"]["columns"]}')
print()
print('First record example:')
print(json.dumps(data['data'][0], indent=2))
