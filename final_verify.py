import json

with open('Attempt3/Tariff_preprocesssing/input/provider_tariffs_dynamic.json', 'r') as f:
    data = json.load(f)

print('=== FINAL VERIFICATION ===')
print()
print('Columns:')
for i, col in enumerate(data['metadata']['columns'], 1):
    print(f'  {i:2d}. {col}')
print()
print(f'Total Records: {data["metadata"]["total_records"]}')
print()
print('Sample records:')
for i, record in enumerate(data['data'][:5], 1):
    print(f'\n  {i}. Provider: {record["provider_name"]} (ID: {record["provider_id"]})')
    print(f'     Contract: {record["contract_name"]}')
    print(f'     Electricity: {record["Electricity price"]:.4f} EUR/kWh')
    print(f'     Feed-in: {record["Feed-in"]:.4f} EUR/kWh')
