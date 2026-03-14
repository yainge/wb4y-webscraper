"""
Convert Excel files to JSON format.

This script reads an Excel file and converts it to structured JSON format,
preserving all data and handling various data types appropriately.
"""

import pandas as pd
import json
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Union


def convert_value_to_json_compatible(value: Any) -> Any:
    """
    Convert pandas/numpy types to JSON-compatible types.
    
    Args:
        value: Value to convert
    
    Returns:
        JSON-compatible value
    """
    if pd.isna(value):
        return None
    elif isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    elif isinstance(value, bool):
        return value
    elif isinstance(value, (int, float, str)):
        return value
    else:
        # Handle any other pandas/numpy types by converting to native Python types
        try:
            if hasattr(value, 'item'):  # numpy types have item() method
                return value.item()
            else:
                return str(value)
        except:
            return str(value)


def excel_to_json(
    excel_path: Union[str, Path],
    output_path: Union[str, Path] = None,
    sheet_name: int = 0,
    orient: str = 'records'
) -> Dict:
    """
    Convert Excel file to JSON format.
    
    Args:
        excel_path: Path to the Excel file
        output_path: Path to save JSON file. If None, saves in same directory with .json extension
        sheet_name: Sheet name or index to read (default: 0 for first sheet)
        orient: JSON orientation - 'records' (list of dicts) or 'index' (dict with index as keys)
    
    Returns:
        Dictionary containing the converted data and metadata
    """
    excel_path = Path(excel_path)
    
    if not excel_path.exists():
        raise FileNotFoundError(f"Excel file not found: {excel_path}")
    
    # Read Excel file
    print(f"Reading Excel file: {excel_path}")
    df = pd.read_excel(excel_path, sheet_name=sheet_name)
    
    print(f"  Shape: {df.shape} (rows: {len(df)}, columns: {len(df.columns)})")
    print(f"  Columns: {list(df.columns)}")
    
    # Convert DataFrame to list of records
    if orient == 'records':
        # Convert to list of dictionaries
        data = []
        for _, row in df.iterrows():
            record = {}
            for col in df.columns:
                value = row[col]
                record[col] = convert_value_to_json_compatible(value)
            data.append(record)
    else:
        # Convert to dictionary with index as keys
        data = {}
        for idx, row in df.iterrows():
            record = {}
            for col in df.columns:
                value = row[col]
                record[col] = convert_value_to_json_compatible(value)
            data[str(idx)] = record
    
    # Create output structure with metadata
    output_data = {
        'metadata': {
            'source_file': str(excel_path),
            'converted_at': datetime.now().isoformat(),
            'sheet_name': str(sheet_name),
            'total_records': len(df),
            'columns': list(df.columns),
            'column_types': {col: str(df[col].dtype) for col in df.columns}
        },
        'data': data
    }
    
    # Determine output path if not provided
    if output_path is None:
        output_path = excel_path.with_suffix('.json')
    
    output_path = Path(output_path)
    
    # Create output directory if it doesn't exist
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write JSON file
    print(f"\nWriting JSON file: {output_path}")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"✓ Successfully converted! JSON file has {len(data)} records")
    print()
    
    return output_data


def main():
    """Main function with default paths for provider tariffs conversion."""
    script_dir = Path(__file__).parent
    project_root = script_dir.parent.parent.parent
    
    # Default: Convert provider_tariffs.xlsx
    excel_file = project_root / 'Attempt3' / 'Tariff_preprocesssing' / 'input' / 'provider_tariffs.xlsx'
    output_file = project_root / 'Attempt3' / 'Tariff_preprocesssing' / 'input' / 'provider_tariffs.json'
    
    print("=" * 80)
    print("EXCEL TO JSON CONVERTER")
    print("=" * 80)
    print()
    
    try:
        excel_to_json(excel_file, output_file)
        print(f"Output file: {output_file}")
        print(f"File size: {output_file.stat().st_size / 1024:.1f} KB")
        print()
        print("✓ Conversion completed successfully!")
    except Exception as e:
        print(f"✗ Error: {e}")
        raise


if __name__ == '__main__':
    main()
