#!/usr/bin/env python3
"""
Verification and inspection utility for tariff parquet files.

Provides post-ingestion validation and summary statistics.

Usage:
    python verify_output.py --output-root ./tariffs_curated

"""

import sys
from pathlib import Path
from typing import Dict, List
import argparse

import pandas as pd
import pyarrow.parquet as pq


def verify_file_exists(path: Path, name: str) -> bool:
    """Check if parquet file exists and log result."""
    if path.exists():
        print(f"✓ {name}: FOUND")
        return True
    else:
        print(f"✗ {name}: MISSING")
        return False


def get_parquet_stats(path: Path) -> Dict[str, any]:
    """Get statistics for a parquet file."""
    table = pq.read_table(path)
    df = pd.read_parquet(path)
    
    return {
        "rows": len(df),
        "columns": len(df.columns),
        "size_mb": path.stat().st_size / (1024 * 1024),
        "schema": [f.name for f in table.schema],
    }


def print_parquet_summary(path: Path, name: str) -> None:
    """Print detailed summary of a parquet file."""
    try:
        stats = get_parquet_stats(path)
        df = pd.read_parquet(path)
        
        print(f"\n{'=' * 70}")
        print(f"{name}")
        print(f"{'=' * 70}")
        print(f"Rows:        {stats['rows']:,}")
        print(f"Columns:     {stats['columns']}")
        print(f"Size:        {stats['size_mb']:.2f} MB")
        print(f"\nSchema:")
        for col in stats['schema']:
            print(f"  - {col}")
        
        if stats['rows'] > 0:
            print(f"\nFirst few rows:")
            print(df.head(3).to_string())
            
            # Print summary statistics for numeric columns
            numeric_cols = df.select_dtypes(include=['number']).columns
            if len(numeric_cols) > 0:
                print(f"\nNumeric summary:")
                print(df[numeric_cols].describe().to_string())
    
    except Exception as e:
        print(f"Error reading {name}: {e}")


def verify_referential_integrity(output_root: Path) -> None:
    """
    Check that contract_keys in usage/fee files reference existing contracts.
    """
    try:
        contracts_fixed = pd.read_parquet(output_root / "contracts_fixed.parquet")
        usage_fixed = pd.read_parquet(output_root / "fixed_usage.parquet")
        fees_fixed = pd.read_parquet(output_root / "fixed_fees.parquet")
        
        contract_keys_fixed = set(contracts_fixed["contract_key"])
        usage_keys = set(usage_fixed["contract_key"])
        fee_keys = set(fees_fixed["contract_key"])
        
        # Check usage references
        orphaned_usage = usage_keys - contract_keys_fixed
        if orphaned_usage:
            print(f"⚠ Fixed usage references non-existent contracts: {len(orphaned_usage)}")
        else:
            print("✓ Fixed usage references are valid")
        
        # Check fee references
        orphaned_fees = fee_keys - contract_keys_fixed
        if orphaned_fees:
            print(f"⚠ Fixed fee references non-existent contracts: {len(orphaned_fees)}")
        else:
            print("✓ Fixed fee references are valid")
        
        # Same for variable
        contracts_var = pd.read_parquet(output_root / "contracts_variable.parquet")
        usage_var = pd.read_parquet(output_root / "variable_usage.parquet")
        fees_var = pd.read_parquet(output_root / "variable_fees.parquet")
        
        contract_keys_var = set(contracts_var["contract_key"])
        usage_keys = set(usage_var["contract_key"])
        fee_keys = set(fees_var["contract_key"])
        
        orphaned_usage = usage_keys - contract_keys_var
        if orphaned_usage:
            print(f"⚠ Variable usage references non-existent contracts: {len(orphaned_usage)}")
        else:
            print("✓ Variable usage references are valid")
        
        orphaned_fees = fee_keys - contract_keys_var
        if orphaned_fees:
            print(f"⚠ Variable fee references non-existent contracts: {len(orphaned_fees)}")
        else:
            print("✓ Variable fee references are valid")
    
    except FileNotFoundError as e:
        print(f"⚠ Could not verify referential integrity: {e}")


def verify_no_duplicates(output_root: Path, dedup_keys: Dict[str, List[str]]) -> None:
    """
    Verify no duplicate rows by primary key.
    """
    print("\n" + "=" * 70)
    print("DUPLICATE CHECK")
    print("=" * 70)
    
    all_clean = True
    
    for filename, keys in dedup_keys.items():
        filepath = output_root / filename
        if not filepath.exists():
            continue
        
        try:
            df = pd.read_parquet(filepath)
            duplicates = df.duplicated(subset=keys, keep=False)
            dup_count = duplicates.sum()
            
            if dup_count > 0:
                print(f"✗ {filename}: {dup_count} duplicate rows")
                all_clean = False
            else:
                print(f"✓ {filename}: No duplicates")
        except Exception as e:
            print(f"⚠ Could not check {filename}: {e}")
    
    if all_clean:
        print("\n✓ All files are duplicate-free")


def verify_schema_consistency(output_root: Path) -> None:
    """
    Verify that fixed/variable versions have consistent schemas.
    """
    print("\n" + "=" * 70)
    print("SCHEMA CONSISTENCY")
    print("=" * 70)
    
    files_to_check = [
        ("contracts_fixed.parquet", "contracts_variable.parquet"),
        ("fixed_usage.parquet", "variable_usage.parquet"),
        ("fixed_fees.parquet", "variable_fees.parquet"),
        ("fixed_feedin_tiers.parquet", "variable_feedin_tiers.parquet"),
    ]
    
    for file1_name, file2_name in files_to_check:
        path1 = output_root / file1_name
        path2 = output_root / file2_name
        
        if not path1.exists() or not path2.exists():
            continue
        
        try:
            table1 = pq.read_table(path1)
            table2 = pq.read_table(path2)
            
            schema1_names = [f.name for f in table1.schema]
            schema2_names = [f.name for f in table2.schema]
            
            if schema1_names == schema2_names:
                print(f"✓ {file1_name} ↔ {file2_name}: Schemas match")
            else:
                print(f"✗ {file1_name} ↔ {file2_name}: Schema mismatch")
                print(f"  {file1_name}: {schema1_names}")
                print(f"  {file2_name}: {schema2_names}")
        except Exception as e:
            print(f"⚠ Could not compare {file1_name} and {file2_name}: {e}")


def verify_data_quality(output_root: Path) -> None:
    """
    Verify data quality: missing values, value ranges, etc.
    """
    print("\n" + "=" * 70)
    print("DATA QUALITY CHECK")
    print("=" * 70)
    
    try:
        # Check contracts
        for filename in ["contracts_fixed.parquet", "contracts_variable.parquet"]:
            filepath = output_root / filename
            if filepath.exists():
                df = pd.read_parquet(filepath)
                
                # Required columns should not be null
                required_cols = ["contract_key", "provider_id", "contract_type", "snapshot_month"]
                nulls = df[required_cols].isnull().sum()
                
                if nulls.sum() > 0:
                    print(f"✗ {filename}: Found null values in required columns")
                    print(f"  {nulls[nulls > 0].to_dict()}")
                else:
                    print(f"✓ {filename}: No null values in required columns")
        
        # Check rates are positive
        for filename in ["fixed_usage.parquet", "variable_usage.parquet"]:
            filepath = output_root / filename
            if filepath.exists():
                df = pd.read_parquet(filepath)
                negative_rates = (df["rate"] < 0).sum()
                
                if negative_rates > 0:
                    print(f"⚠ {filename}: {negative_rates} rows with negative rates")
                else:
                    print(f"✓ {filename}: All rates are non-negative")
        
        # Check fee amounts
        for filename in ["fixed_fees.parquet", "variable_fees.parquet"]:
            filepath = output_root / filename
            if filepath.exists():
                df = pd.read_parquet(filepath)
                negative_fees = (df["amount"] < 0).sum()
                
                if negative_fees > 0:
                    print(f"⚠ {filename}: {negative_fees} rows with negative amounts")
                else:
                    print(f"✓ {filename}: All amounts are non-negative")
    
    except Exception as e:
        print(f"⚠ Data quality check failed: {e}")


def main() -> int:
    """Main verification routine."""
    parser = argparse.ArgumentParser(
        description="Verify and inspect tariff ingestion output parquet files."
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
        help="Path to output parquet files",
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="Print detailed statistics for each file",
    )
    
    args = parser.parse_args()
    output_root = Path(args.output_root)
    
    if not output_root.exists():
        print(f"✗ Output directory does not exist: {output_root}")
        return 1
    
    print("=" * 70)
    print("TARIFF INGESTION OUTPUT VERIFICATION")
    print("=" * 70)
    print(f"Output root: {output_root.absolute()}\n")
    
    # Check file existence
    print("File Presence Check:")
    files_to_check = [
        ("contracts_fixed.parquet", "Fixed contracts"),
        ("contracts_variable.parquet", "Variable contracts"),
        ("fixed_usage.parquet", "Fixed usage tariffs"),
        ("variable_usage.parquet", "Variable usage tariffs"),
        ("fixed_fees.parquet", "Fixed fees"),
        ("variable_fees.parquet", "Variable fees"),
        ("fixed_feedin_tiers.parquet", "Fixed feed-in tiers"),
        ("variable_feedin_tiers.parquet", "Variable feed-in tiers"),
    ]
    
    all_files_exist = True
    for filename, description in files_to_check:
        filepath = output_root / filename
        if not verify_file_exists(filepath, description):
            all_files_exist = False
    
    if not all_files_exist:
        print("\n⚠ Some expected files are missing")
    
    # Print statistics
    if args.details:
        print("\nDetailed File Statistics:")
        for filename, description in files_to_check:
            filepath = output_root / filename
            if filepath.exists():
                print_parquet_summary(filepath, description)
    else:
        print("\nFile Sizes and Row Counts:")
        for filename, description in files_to_check:
            filepath = output_root / filename
            if filepath.exists():
                try:
                    stats = get_parquet_stats(filepath)
                    print(f"{description:30s} | {stats['rows']:8,} rows | {stats['size_mb']:7.2f} MB")
                except Exception as e:
                    print(f"{description:30s} | Error: {e}")
    
    # Verify referential integrity
    print("\n" + "=" * 70)
    print("REFERENTIAL INTEGRITY")
    print("=" * 70)
    verify_referential_integrity(output_root)
    
    # Check for duplicates
    dedup_keys = {
        "contracts_fixed.parquet": ["contract_key"],
        "contracts_variable.parquet": ["contract_key"],
        "fixed_usage.parquet": ["contract_key", "commodity", "direction", "tariff_band", "period"],
        "variable_usage.parquet": ["contract_key", "commodity", "direction", "tariff_band", "period"],
        "fixed_fees.parquet": ["contract_key", "fee_component"],
        "variable_fees.parquet": ["contract_key", "fee_component"],
        "fixed_feedin_tiers.parquet": ["contract_key", "tier_index", "settlement_period"],
        "variable_feedin_tiers.parquet": ["contract_key", "tier_index", "settlement_period"],
    }
    verify_no_duplicates(output_root, dedup_keys)
    
    # Check schema consistency
    verify_schema_consistency(output_root)
    
    # Check data quality
    verify_data_quality(output_root)
    
    print("\n" + "=" * 70)
    print("VERIFICATION COMPLETE")
    print("=" * 70)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
