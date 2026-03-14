"""
Transform provider tariffs JSON by:
1. Removing "Feed in specific" column
2. Adding "contract_name" field
3. Renaming "Contract type" to "contract_duration"
"""

import json
from pathlib import Path
from datetime import datetime


def transform_tariffs(input_json_path: str, output_json_path: str = None):
    """
    Transform provider tariffs JSON file.
    
    Args:
        input_json_path: Path to the input JSON file
        output_json_path: Path to save transformed JSON. If None, overwrites input
    """
    input_path = Path(input_json_path)
    
    if not input_path.exists():
        raise FileNotFoundError(f"JSON file not found: {input_path}")
    
    # Load the JSON
    print(f"Reading: {input_path}")
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Determine output path
    if output_json_path is None:
        output_path = input_path
    else:
        output_path = Path(output_json_path)
    
    # Transform metadata
    metadata = data['metadata']
    
    # Update columns list: remove "Feed in specific" and rename "Contract type"
    old_columns = metadata['columns'].copy()
    new_columns = []
    
    for col in old_columns:
        if col == 'Feed in specific':
            continue  # Skip this column
        elif col == 'Contract type':
            new_columns.append('contract_duration')  # Rename this
        else:
            new_columns.append(col)
    
    # Add contract_name if not already present
    if 'contract_name' not in new_columns:
        # Insert after Company name
        if 'Company name' in new_columns:
            idx = new_columns.index('Company name') + 1
            new_columns.insert(idx, 'contract_name')
        else:
            new_columns.insert(0, 'contract_name')
    
    metadata['columns'] = new_columns
    
    # Update column_types
    column_types = metadata['column_types'].copy()
    if 'Feed in specific' in column_types:
        del column_types['Feed in specific']
    if 'Contract type' in column_types:
        column_types['contract_duration'] = column_types.pop('Contract type')
    column_types['contract_name'] = 'object'
    
    metadata['column_types'] = column_types
    metadata['transformed_at'] = datetime.now().isoformat()
    
    # Transform records
    transformed_data = []
    
    for record in data['data']:
        new_record = {}
        
        # Copy and transform fields
        if 'Company name' in record:
            new_record['Company name'] = record['Company name']
            # Add contract_name (using company name as base)
            new_record['contract_name'] = record['Company name']
        
        # Copy other fields, excluding "Feed in specific" and renaming "Contract type"
        for key, value in record.items():
            if key == 'Feed in specific':
                continue  # Skip this field
            elif key == 'Contract type':
                new_record['contract_duration'] = value
            elif key == 'Company name':
                continue  # Already handled above
            else:
                new_record[key] = value
        
        transformed_data.append(new_record)
    
    # Create output structure
    output_data = {
        'metadata': metadata,
        'data': transformed_data
    }
    
    # Save transformed file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"Writing: {output_path}")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print()
    print("✓ Transformation completed successfully!")
    print()
    print("Changes made:")
    print(f"  ✗ Removed: 'Feed in specific'")
    print(f"  + Added: 'contract_name'")
    print(f"  ↻ Renamed: 'Contract type' → 'contract_duration'")
    print()
    print(f"Columns: {len(old_columns)} → {len(new_columns)}")
    print(f"Records: {len(data['data'])}")
    print()
    print(f"File size: {output_path.stat().st_size / 1024:.1f} KB")
    
    return output_data


def main():
    """Main function."""
    script_dir = Path(__file__).parent
    project_root = script_dir.parent.parent.parent
    
    dynamic_file = project_root / 'Attempt3' / 'Tariff_preprocesssing' / 'input' / 'provider_tariffs_dynamic.json'
    
    print("=" * 80)
    print("TRANSFORM PROVIDER TARIFFS")
    print("=" * 80)
    print()
    
    transform_tariffs(str(dynamic_file))


if __name__ == '__main__':
    main()
