import json
import re
from collections import defaultdict

# Load contracts
with open('contracts.json') as f:
    data = json.load(f)

budget_contracts = data['Budget Energie']

# Parse contracts into base_name + variant
parsed = defaultdict(list)

for contract in budget_contracts:
    match = re.match(r'^(.+?)\s+([A-Z]|BAT)$', contract)
    
    if match:
        base_name = match.group(1)
        variant = match.group(2)
        parsed[base_name].append((variant, contract))
    else:
        parsed[contract].append(("", contract))

# Analyze slug collisions
print("CONTRACT KEY STRUCTURE (provider|type|meter_type|name_slug|variant)")
print("=" * 90)
print()

# Group by slug to find collisions
by_slug = defaultdict(list)

for base_name in sorted(parsed.keys()):
    slug = base_name.lower().replace(" ", "_").replace("(", "").replace(")", "")
    
    for variant_letter, full_contract in sorted(parsed[base_name]):
        contract_key = f"budget_energie|fixed|electricity|{slug}|{variant_letter}"
        by_slug[slug].append({
            'original_name': base_name,
            'variant': variant_letter,
            'full_contract': full_contract,
            'contract_key': contract_key
        })

# Show collisions
print("SLUG COLLISIONS (Same slug from different base names):\n")
for slug in sorted(by_slug.keys()):
    contracts = by_slug[slug]
    if len(set(c['original_name'] for c in contracts)) > 1:
        print(f"Slug: {slug}")
        for contract in contracts:
            print(f"  Original: {contract['original_name']}")
            print(f"  Contract Key: {contract['contract_key']}")
        print()

print("\nUNIQUE SLUG MAPPING:\n")
slug_map = defaultdict(list)
for base_name in sorted(parsed.keys()):
    slug = base_name.lower().replace(" ", "_").replace("(", "").replace(")", "")
    slug_map[slug].append(base_name)

for slug in sorted(slug_map.keys()):
    names = slug_map[slug]
    print(f"Slug: {slug}")
    if len(names) == 1:
        for variant_letter, _ in sorted(parsed[names[0]]):
            print(f"  + {names[0]} [{variant_letter}]")
    else:
        print(f"  ⚠️  COLLISION - Multiple original names map to same slug:")
        for name in names:
            for variant_letter, _ in sorted(parsed[name]):
                print(f"     • {name} [{variant_letter}]")
    print()
