#!/usr/bin/env python3
"""
Analyze unique contract names per provider in raw JSON files.

Scans all contract JSON files in a directory and groups contract names by provider.
Useful for understanding data structure and identifying data quality issues.

Usage:
    python analyze_contract_names.py --input-dir ../../2025
    python analyze_contract_names.py --input-dir ../../2025 --output csv
"""

import json
import sys
from pathlib import Path
from typing import Dict, Set
from collections import defaultdict
import argparse


def scan_contracts(input_dir: Path) -> Dict[str, Set[str]]:
    """
    Scan all contract JSON files and collect unique contract names per provider.
    
    Args:
        input_dir: Directory containing JSON files
    
    Returns:
        Dict mapping provider name to set of unique contract names
    """
    provider_contracts = defaultdict(set)
    file_count = 0
    record_count = 0
    
    # Find all JSON files matching pattern
    json_files = sorted(input_dir.glob("contracts_*.json"))
    
    if not json_files:
        print(f"No contract JSON files found in {input_dir}")
        return {}
    
    print(f"Found {len(json_files)} JSON files")
    print()
    
    for json_file in json_files:
        file_count += 1
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                records = json.load(f)
            
            if not isinstance(records, list):
                print(f"⚠ {json_file.name}: Expected list, got {type(records).__name__}")
                continue
            
            for record in records:
                record_count += 1
                provider = record.get("provider", "").strip()
                contract_name = record.get("contract_name", "").strip()
                
                if provider and contract_name:
                    provider_contracts[provider].add(contract_name)
        
        except json.JSONDecodeError as e:
            print(f"✗ {json_file.name}: Invalid JSON - {e}")
        except Exception as e:
            print(f"✗ {json_file.name}: Error - {e}")
    
    print(f"Processed {file_count} files with {record_count} total records")
    print()
    
    return provider_contracts


def print_summary(provider_contracts: Dict[str, Set[str]]) -> None:
    """Print formatted summary of contract names per provider."""
    if not provider_contracts:
        print("No data to display")
        return
    
    # Sort providers alphabetically
    providers = sorted(provider_contracts.keys())
    
    print("=" * 80)
    print("UNIQUE CONTRACT NAMES PER PROVIDER")
    print("=" * 80)
    print()
    
    total_providers = len(providers)
    total_unique_contracts = sum(len(names) for names in provider_contracts.values())
    
    print(f"Total providers: {total_providers}")
    print(f"Total unique contract name combinations: {total_unique_contracts}")
    print()
    
    for provider in providers:
        contract_names = sorted(provider_contracts[provider])
        count = len(contract_names)
        
        print(f"{provider} ({count} unique contracts)")
        print("-" * 80)
        for i, name in enumerate(contract_names, 1):
            print(f"  {i:2d}. {name}")
        print()


def export_csv(provider_contracts: Dict[str, Set[str]], output_file: Path) -> None:
    """Export results to CSV format."""
    import csv
    
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["provider", "contract_name"])
        
        for provider in sorted(provider_contracts.keys()):
            for contract_name in sorted(provider_contracts[provider]):
                writer.writerow([provider, contract_name])
    
    print(f"Exported to {output_file}")


def export_json(provider_contracts: Dict[str, Set[str]], output_file: Path) -> None:
    """Export results to JSON format."""
    # Convert sets to lists for JSON serialization
    data = {
        provider: sorted(list(names))
        for provider, names in provider_contracts.items()
    }
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"Exported to {output_file}")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Analyze unique contract names per provider in raw JSON files."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        required=True,
        help="Directory containing contract JSON files",
    )
    parser.add_argument(
        "--output",
        choices=["text", "csv", "json"],
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        help="Output file path (for csv/json formats)",
    )
    
    args = parser.parse_args()
    
    # Verify input directory exists
    if not args.input_dir.exists():
        print(f"✗ Input directory does not exist: {args.input_dir}")
        return 1
    
    print(f"Input directory: {args.input_dir.absolute()}")
    print()
    
    # Scan contracts
    provider_contracts = scan_contracts(args.input_dir)
    
    if not provider_contracts:
        return 1
    
    # Output results
    if args.output == "text":
        print_summary(provider_contracts)
    
    elif args.output == "csv":
        output_file = args.output_file or Path("contract_names.csv")
        export_csv(provider_contracts, output_file)
    
    elif args.output == "json":
        output_file = args.output_file or Path("contract_names.json")
        export_json(provider_contracts, output_file)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
