import json

with open('Attempt3/Tariff_preprocesssing/input/provider_tariffs_dynamic.json', 'r') as f:
    data = json.load(f)

print('Updated Columns:')
print('  ', data['metadata']['columns'])
print()
print('Sample records (showing provider_id, provider_name, contract_name):')
for i, record in enumerate(data['data'][:3], 1):
    print(f'  {i}. ID: {record["provider_id"]}, Name: {record["provider_name"]}, Contract: {record["contract_name"]}')
print()
print('All provider IDs:')
ids = [r['provider_id'] for r in data['data']]
print(f'  {sorted(set(ids))}')
