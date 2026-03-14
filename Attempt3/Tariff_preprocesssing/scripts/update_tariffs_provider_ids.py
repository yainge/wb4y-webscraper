"""
Update provider tariffs JSON with correct provider IDs and naming conventions.

Changes:
1. Map provider names to provider_id from providers.json
2. Rename "Client ID" → "provider_id"
3. Rename "Company name" → "provider_name"
4. Update "contract_name" to be: provider_name + contract_duration
"""

import json
from pathlib import Path
from datetime import datetime


def update_tariffs_with_provider_ids(
    tariffs_json_path: str,
    providers_json_path: str,
    output_json_path: str = None
):
    """
    Update tariffs JSON with proper provider IDs and naming.
    
    Args:
        tariffs_json_path: Path to provider_tariffs_dynamic.json
        providers_json_path: Path to providers.json
        output_json_path: Path to save updated JSON. If None, overwrites input
    """
    tariffs_path = Path(tariffs_json_path)
    providers_path = Path(providers_json_path)
    
    if not tariffs_path.exists():
        raise FileNotFoundError(f"Tariffs JSON not found: {tariffs_path}")
    if not providers_path.exists():
        raise FileNotFoundError(f"Providers JSON not found: {providers_path}")
    
    # Load providers mapping
    print(f"Reading: {providers_path}")
    with open(providers_path, 'r', encoding='utf-8') as f:
        providers_map = json.load(f)
    
    print(f"  Found {len(providers_map)} providers")
    print()
    
    # Load tariffs JSON
    print(f"Reading: {tariffs_path}")
    with open(tariffs_path, 'r', encoding='utf-8') as f:
        tariffs_data = json.load(f)
    
    print(f"  Found {len(tariffs_data['data'])} records")
    print()
    
    # Determine output path
    if output_json_path is None:
        output_path = tariffs_path
    else:
        output_path = Path(output_json_path)
    
    # Update metadata columns
    metadata = tariffs_data['metadata']
    old_columns = metadata['columns'].copy()
    
    # Transform columns
    new_columns = []
    for col in old_columns:
        if col == 'Client ID':
            new_columns.append('provider_id')
        elif col == 'Company name':
            new_columns.append('provider_name')
        else:
            new_columns.append(col)
    
    metadata['columns'] = new_columns
    
    # Update column_types
    column_types = metadata['column_types'].copy()
    if 'Client ID' in column_types:
        column_types['provider_id'] = column_types.pop('Client ID')
    if 'Company name' in column_types:
        column_types['provider_name'] = column_types.pop('Company name')
    
    metadata['column_types'] = column_types
    metadata['updated_at'] = datetime.now().isoformat()
    
    # Transform records
    transformed_data = []
    unmatched_providers = set()
    
    for record in tariffs_data['data']:
        new_record = {}
        company_name = record.get('Company name', '')
        contract_duration = record.get('contract_duration', '')
        
        # Try to find provider ID in the providers map
        # 1. Try exact match
        # 2. Try case-insensitive match
        # 3. Try partial match (prioritize matches where company_name is in prov_name)
        provider_id = None
        
        if company_name in providers_map:
            provider_id = providers_map[company_name]
        else:
            # Try case-insensitive exact match
            for prov_name, prov_id in providers_map.items():
                if prov_name.lower() == company_name.lower():
                    provider_id = prov_id
                    break
            
            # Try partial match if not found (prioritize provider name contains company name)
            if provider_id is None:
                best_match = None
                for prov_name, prov_id in providers_map.items():
                    if company_name.lower() in prov_name.lower():
                        best_match = prov_id
                        break
                if best_match is None:
                    for prov_name, prov_id in providers_map.items():
                        if prov_name.lower() in company_name.lower():
                            best_match = prov_id
                            break
                provider_id = best_match
        
        if provider_id is None:
            unmatched_providers.add(company_name)
            provider_id = -1  # Use -1 for unmatched
        
        # Transform fields
        for key, value in record.items():
            if key == 'Client ID':
                new_record['provider_id'] = provider_id
            elif key == 'Company name':
                new_record['provider_name'] = value
            elif key == 'contract_name':
                # Update contract_name to be: provider_name - contract_duration
                new_record['contract_name'] = f"{company_name} - {contract_duration}"
            else:
                new_record[key] = value
        
        transformed_data.append(new_record)
    
    # Create output structure
    output_data = {
        'metadata': metadata,
        'data': transformed_data
    }
    
    # Save updated file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"Writing: {output_path}")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print()
    print("✓ Update completed successfully!")
    print()
    print("Changes made:")
    print(f"  ↻ Renamed: 'Client ID' → 'provider_id'")
    print(f"  ↻ Renamed: 'Company name' → 'provider_name'")
    print(f"  ↻ Updated: 'contract_name' to 'provider_name - contract_duration'")
    print()
    print(f"Records: {len(transformed_data)}")
    print(f"Provider IDs matched: {len(transformed_data) - len(unmatched_providers)}")
    
    if unmatched_providers:
        print(f"⚠ Unmatched providers ({len(unmatched_providers)}):")
        for prov in sorted(unmatched_providers):
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
    print("UPDATE PROVIDER TARIFFS WITH PROVIDER IDs")
    print("=" * 80)
    print()
    
    update_tariffs_with_provider_ids(str(tariffs_file), str(providers_file))


if __name__ == '__main__':
    main()
