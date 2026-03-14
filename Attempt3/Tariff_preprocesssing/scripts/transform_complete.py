"""
Comprehensive transformation of provider tariffs:
1. Remove "Feed in specific" column
2. Add "contract_name" field
3. Rename "Contract type" to "contract_duration"
4. Map provider names to provider_id from providers.json
5. Rename "Client ID" → "provider_id"
6. Rename "Company name" → "provider_name"
7. Set contract_name to: "provider_name - contract_duration"
"""

import json
from pathlib import Path
from datetime import datetime


def comprehensive_transform(
    input_json_path: str,
    providers_json_path: str,
    output_json_path: str = None
):
    """
    Perform all transformations on provider tariffs.
    """
    input_path = Path(input_json_path)
    providers_path = Path(providers_json_path)
    
    if not input_path.exists():
        raise FileNotFoundError(f"Tariffs JSON not found: {input_path}")
    if not providers_path.exists():
        raise FileNotFoundError(f"Providers JSON not found: {providers_path}")
    
    # Load providers mapping
    print(f"Reading: {providers_path}")
    with open(providers_path, 'r', encoding='utf-8') as f:
        providers_map = json.load(f)
    print(f"  Found {len(providers_map)} providers")
    print()
    
    # Load tariffs JSON
    print(f"Reading: {input_path}")
    with open(input_path, 'r', encoding='utf-8') as f:
        tariffs_data = json.load(f)
    print(f"  Found {len(tariffs_data['data'])} records")
    print()
    
    # Determine output path
    if output_json_path is None:
        output_path = input_path
    else:
        output_path = Path(output_json_path)
    
    # Update metadata
    metadata = tariffs_data['metadata']
    old_columns = metadata['columns'].copy()
    
    # Build new columns list
    new_columns = []
    for col in old_columns:
        if col == 'Feed in specific':
            continue  # Skip
        elif col == 'Client ID':
            new_columns.append('provider_id')
        elif col == 'Company name':
            new_columns.append('provider_name')
        elif col == 'Contract type':
            new_columns.append('contract_duration')
        else:
            new_columns.append(col)
    
    # Ensure contract_name is after provider_name
    if 'contract_name' not in new_columns:
        idx = new_columns.index('provider_name') + 1
        new_columns.insert(idx, 'contract_name')
    
    metadata['columns'] = new_columns
    
    # Update column_types
    column_types = metadata['column_types'].copy()
    if 'Feed in specific' in column_types:
        del column_types['Feed in specific']
    if 'Client ID' in column_types:
        column_types['provider_id'] = column_types.pop('Client ID')
    if 'Company name' in column_types:
        column_types['provider_name'] = column_types.pop('Company name')
    if 'Contract type' in column_types:
        column_types['contract_duration'] = column_types.pop('Contract type')
    column_types['contract_name'] = 'object'
    
    metadata['column_types'] = column_types
    metadata['transformed_at'] = datetime.now().isoformat()
    
    # Transform records
    transformed_data = []
    unmatched = set()
    
    for record in tariffs_data['data']:
        # Get original values
        company_name = record.get('Company name', '')
        contract_duration = record.get('Contract type', '')
        
        # Find provider ID
        provider_id = None
        if company_name in providers_map:
            provider_id = providers_map[company_name]
        else:
            # Case-insensitive exact match
            for prov_name, prov_id in providers_map.items():
                if prov_name.lower() == company_name.lower():
                    provider_id = prov_id
                    break
            
            # Partial match: prioritize provider_name contains company_name
            if provider_id is None:
                for prov_name, prov_id in providers_map.items():
                    if company_name.lower() in prov_name.lower():
                        provider_id = prov_id
                        break
            
            # Fallback: company_name in provider_name
            if provider_id is None:
                for prov_name, prov_id in providers_map.items():
                    if prov_name.lower() in company_name.lower():
                        provider_id = prov_id
                        break
        
        if provider_id is None:
            unmatched.add(company_name)
            provider_id = -1
        
        # Build new record
        new_record = {}
        for key, value in record.items():
            if key == 'Feed in specific':
                continue  # Skip this field
            elif key == 'Client ID':
                new_record['provider_id'] = provider_id
            elif key == 'Company name':
                new_record['provider_name'] = value
            elif key == 'Contract type':
                new_record['contract_duration'] = value
            else:
                new_record[key] = value
        
        # Add contract_name: provider_name - contract_duration
        new_record['contract_name'] = f"{company_name} - {contract_duration}"
        
        transformed_data.append(new_record)
    
    # Create output
    output_data = {
        'metadata': metadata,
        'data': transformed_data
    }
    
    # Save
    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Writing: {output_path}")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print()
    print("✓ Comprehensive transformation completed!")
    print()
    print("Changes made:")
    print(f"  ✗ Removed: 'Feed in specific'")
    print(f"  ↻ Renamed: 'Client ID' → 'provider_id'")
    print(f"  ↻ Renamed: 'Company name' → 'provider_name'")
    print(f"  ↻ Renamed: 'Contract type' → 'contract_duration'")
    print(f"  + Added: 'contract_name' (format: provider_name - contract_duration)")
    print()
    print(f"Records: {len(transformed_data)}")
    print(f"Provider IDs matched: {len(transformed_data) - len(unmatched)}")
    
    if unmatched:
        print(f"⚠ Unmatched providers ({len(unmatched)}):")
        for prov in sorted(unmatched):
            print(f"    - {prov}")
    
    print()
    print(f"File size: {output_path.stat().st_size / 1024:.1f} KB")
    
    return output_data


def main():
    """Main function."""
    script_dir = Path(__file__).parent
    project_root = script_dir.parent.parent.parent
    
    tariffs_file = project_root / 'Attempt3' / 'Tariff_preprocesssing' / 'input' / 'provider_tariffs_dynamic.json'
    providers_file = project_root / 'Attempt3' / 'providers.json'
    
    print("=" * 80)
    print("COMPREHENSIVE PROVIDER TARIFFS TRANSFORMATION")
    print("=" * 80)
    print()
    
    comprehensive_transform(str(tariffs_file), str(providers_file))


if __name__ == '__main__':
    main()
