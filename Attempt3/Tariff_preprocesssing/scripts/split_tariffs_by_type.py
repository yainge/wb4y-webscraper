"""
Split provider tariffs JSON into fixed and dynamic contracts.
"""

import json
from pathlib import Path
from datetime import datetime


def split_tariffs_by_type(input_json_path: str, output_dir: str = None):
    """
    Split provider tariffs JSON into fixed and dynamic contracts.
    
    Args:
        input_json_path: Path to the combined provider_tariffs.json
        output_dir: Output directory for split files. If None, uses same directory as input
    """
    input_path = Path(input_json_path)
    
    if not input_path.exists():
        raise FileNotFoundError(f"JSON file not found: {input_path}")
    
    # Load the combined JSON
    print(f"Reading: {input_path}")
    with open(input_path, 'r', encoding='utf-8') as f:
        combined_data = json.load(f)
    
    # Determine output directory
    if output_dir is None:
        output_dir = input_path.parent
    else:
        output_dir = Path(output_dir)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Split data by contract type
    fixed_records = []
    dynamic_records = []
    
    for record in combined_data['data']:
        contract_type = record.get('Contract type', '').strip().lower()
        
        if contract_type == 'vast':  # Dutch for "fixed"
            fixed_records.append(record)
        elif contract_type == 'dynamisch':  # Dutch for "dynamic"
            dynamic_records.append(record)
    
    # Create output structures
    fixed_output = {
        'metadata': {
            'source_file': str(input_path),
            'split_at': datetime.now().isoformat(),
            'contract_type': 'Vast (Fixed)',
            'total_records': len(fixed_records),
            'columns': combined_data['metadata']['columns'],
            'column_types': combined_data['metadata']['column_types']
        },
        'data': fixed_records
    }
    
    dynamic_output = {
        'metadata': {
            'source_file': str(input_path),
            'split_at': datetime.now().isoformat(),
            'contract_type': 'Dynamisch (Dynamic)',
            'total_records': len(dynamic_records),
            'columns': combined_data['metadata']['columns'],
            'column_types': combined_data['metadata']['column_types']
        },
        'data': dynamic_records
    }
    
    # Save split files
    fixed_file = output_dir / 'provider_tariffs_fixed.json'
    dynamic_file = output_dir / 'provider_tariffs_dynamic.json'
    
    print(f"\nWriting split files:")
    print(f"  Fixed contracts:   {len(fixed_records)} records → {fixed_file}")
    with open(fixed_file, 'w', encoding='utf-8') as f:
        json.dump(fixed_output, f, indent=2, ensure_ascii=False)
    
    print(f"  Dynamic contracts: {len(dynamic_records)} records → {dynamic_file}")
    with open(dynamic_file, 'w', encoding='utf-8') as f:
        json.dump(dynamic_output, f, indent=2, ensure_ascii=False)
    
    print()
    print("✓ Split completed successfully!")
    print()
    print("File sizes:")
    print(f"  Fixed:   {fixed_file.stat().st_size / 1024:.1f} KB")
    print(f"  Dynamic: {dynamic_file.stat().st_size / 1024:.1f} KB")
    print()
    
    return fixed_output, dynamic_output


def main():
    """Main function."""
    script_dir = Path(__file__).parent
    project_root = script_dir.parent.parent.parent
    
    input_file = project_root / 'Attempt3' / 'Tariff_preprocesssing' / 'input' / 'provider_tariffs.json'
    output_dir = project_root / 'Attempt3' / 'Tariff_preprocesssing' / 'input'
    
    print("=" * 80)
    print("SPLIT PROVIDER TARIFFS BY CONTRACT TYPE")
    print("=" * 80)
    print()
    
    fixed, dynamic = split_tariffs_by_type(str(input_file), str(output_dir))
    
    print("Contract type breakdown:")
    print(f"  Fixed (Vast):     {fixed['metadata']['total_records']} providers")
    print(f"  Dynamic (Dynamisch): {dynamic['metadata']['total_records']} providers")


if __name__ == '__main__':
    main()
