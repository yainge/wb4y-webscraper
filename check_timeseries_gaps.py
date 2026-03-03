import json
import argparse
import logging
from pathlib import Path
from typing import Dict, Set, Tuple, List
from collections import defaultdict

# Try to import polars, fall back to pandas
try:
    import polars as pl
    USE_POLARS = True
except ImportError:
    import pandas as pd
    USE_POLARS = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def load_all_parquets(parquet_dir: str) -> Dict:
    """Load all parquet files from partitioned directory structure."""
    parquet_path = Path(parquet_dir)
    
    if not parquet_path.exists():
        logger.error(f"Parquet directory not found: {parquet_path}")
        return {}
    
    all_data = []
    provider_years = []
    
    # Find all provider_id=X/year=Y/part-0.parquet files
    for provider_dir in parquet_path.glob('provider_id=*'):
        provider_str = provider_dir.name
        try:
            provider_id = int(provider_str.split('=')[1])
        except (IndexError, ValueError):
            logger.warning(f"Skipping invalid provider directory: {provider_dir}")
            continue
        
        for year_dir in provider_dir.glob('year=*'):
            year_str = year_dir.name
            try:
                year = int(year_str.split('=')[1])
            except (IndexError, ValueError):
                logger.warning(f"Skipping invalid year directory: {year_dir}")
                continue
            
            parquet_file = year_dir / 'part-0.parquet'
            if parquet_file.exists():
                try:
                    if USE_POLARS:
                        df = pl.read_parquet(str(parquet_file))
                        all_data.append(df)
                    else:
                        df = pd.read_parquet(str(parquet_file))
                        all_data.append(df)
                    
                    logger.info(f"Loaded: provider_id={provider_id}, year={year}, rows={len(df)}")
                    provider_years.append((provider_id, year))
                
                except Exception as e:
                    logger.error(f"Failed to read {parquet_file}: {e}")
    
    if not all_data:
        logger.error("No parquet files loaded")
        return {}
    
    # Concatenate all dataframes
    try:
        if USE_POLARS:
            combined_df = pl.concat(all_data)
        else:
            combined_df = pd.concat(all_data, ignore_index=True)
        logger.info(f"Concatenated all parquets: total rows={len(combined_df)}")
        return combined_df
    except Exception as e:
        logger.error(f"Failed to concatenate dataframes: {e}")
        return {}

def analyze_timeseries_gaps(df) -> Dict:
    """Analyze time-series gaps in contract data."""
    
    if df is None or len(df) == 0:
        logger.error("No data to analyze")
        return {}
    
    # Convert to dict of records if using polars
    if USE_POLARS:
        records = df.to_dicts()
        columns = df.columns
    else:
        records = df.to_dict('records')
        columns = df.columns.tolist()
    
    # Group by contract_key
    contracts_by_key = defaultdict(list)
    for record in records:
        contract_key = record.get('contract_key')
        if contract_key:
            contracts_by_key[contract_key].append(record)
    
    logger.info(f"Analyzing {len(contracts_by_key)} unique contracts")
    
    # Build month-contract combinations
    month_contract_combinations = set()
    contract_info = {}  # contract_key -> {provider, name, etc.}
    
    for contract_key, records_for_key in contracts_by_key.items():
        # Get basic info from first record
        first_record = records_for_key[0]
        contract_info[contract_key] = {
            'provider': first_record.get('provider'),
            'provider_id': first_record.get('provider_id'),
            'contract_name': first_record.get('contract_name'),
            'contract_duration': first_record.get('contract_duration'),
            'meter_type': first_record.get('meter_type'),
        }
        
        # Collect all month-contract combinations present
        for record in records_for_key:
            month_label = record.get('month_label')
            year = record.get('year')
            month = record.get('month')
            if month_label and year and month:
                month_contract_combinations.add((contract_key, year, month, month_label))
    
    logger.info(f"Total month-contract combinations in data: {len(month_contract_combinations)}")
    
    # Find gaps: for each contract, identify missing months in its span
    gaps_by_contract = {}
    total_gaps = 0
    
    for contract_key, records_for_key in contracts_by_key.items():
        if not records_for_key:
            continue
        
        # Get year-month range for this contract
        present_months = set()
        min_year_month = None
        max_year_month = None
        
        for record in records_for_key:
            year = record.get('year')
            month = record.get('month')
            month_label = record.get('month_label')
            
            if year and month:
                present_months.add((year, month))
                year_month = (year, month)
                
                if min_year_month is None or year_month < min_year_month:
                    min_year_month = year_month
                if max_year_month is None or year_month > max_year_month:
                    max_year_month = year_month
        
        if min_year_month is None or max_year_month is None:
            continue
        
        # Find all months between min and max
        expected_months = set()
        year, month = min_year_month
        while (year, month) <= max_year_month:
            expected_months.add((year, month))
            month += 1
            if month > 12:
                month = 1
                year += 1
        
        # Find missing months
        missing_months = expected_months - present_months
        gap_count = len(missing_months)
        
        if gap_count > 0:
            gaps_by_contract[contract_key] = {
                'provider': contract_info[contract_key]['provider'],
                'provider_id': contract_info[contract_key]['provider_id'],
                'contract_name': contract_info[contract_key]['contract_name'],
                'meter_type': contract_info[contract_key]['meter_type'],
                'span_months': len(expected_months),
                'present_months': len(present_months),
                'missing_months': gap_count,
                'missing_month_labels': sorted(missing_months),
            }
            total_gaps += gap_count
    
    # Analyze null values in numeric columns
    numeric_columns = [
        'gas_fixed_yearly', 'gas_variable_per_m3',
        'elec_fixed_yearly', 'elec_piek_per_kwh', 'elec_dal_per_kwh',
        'estimated_annual_costs'
    ]
    
    null_counts = {}
    for col in numeric_columns:
        if col in columns:
            if USE_POLARS:
                null_count = df.select(pl.col(col).null_count()).item()
            else:
                null_count = df[col].isna().sum()
            
            null_counts[col] = {
                'null_count': int(null_count),
                'total': len(df),
                'null_percent': round(100 * int(null_count) / len(df), 2) if len(df) > 0 else 0
            }
    
    return {
        'total_records': len(records),
        'unique_contracts': len(contracts_by_key),
        'month_contract_combinations': len(month_contract_combinations),
        'contracts_with_gaps': len(gaps_by_contract),
        'total_missing_month_contract_combinations': total_gaps,
        'gaps_by_contract': gaps_by_contract,
        'null_values': null_counts,
    }

def print_analysis_report(analysis: Dict):
    """Print formatted analysis report."""
    if not analysis:
        logger.error("No analysis results")
        return
    
    print("\n" + "="*80)
    print("TIME-SERIES GAP ANALYSIS REPORT")
    print("="*80)
    
    print(f"\nOVERALL STATISTICS:")
    print(f"  Total records: {analysis['total_records']}")
    print(f"  Unique contracts: {analysis['unique_contracts']}")
    print(f"  Month-contract combinations present: {analysis['month_contract_combinations']}")
    print(f"  Contracts with gaps: {analysis['contracts_with_gaps']}")
    print(f"  Total missing month-contract combinations: {analysis['total_missing_month_contract_combinations']}")
    
    print(f"\nNULL VALUES IN NUMERIC COLUMNS:")
    for col, stats in analysis['null_values'].items():
        print(f"  {col}:")
        print(f"    Null count: {stats['null_count']} / {stats['total']} ({stats['null_percent']}%)")
    
    # Show details for contracts with gaps (top 20)
    gaps_by_contract = analysis['gaps_by_contract']
    if gaps_by_contract:
        print(f"\nCONTRACTS WITH TIME-SERIES GAPS (showing first 20):")
        for i, (contract_key, gap_info) in enumerate(sorted(
            gaps_by_contract.items(),
            key=lambda x: x[1]['missing_months'],
            reverse=True
        )[:20]):
            print(f"\n  Contract {i+1}: {contract_key}")
            print(f"    Provider: {gap_info['provider']} (ID: {gap_info['provider_id']})")
            print(f"    Name: {gap_info['contract_name']}")
            print(f"    Meter type: {gap_info['meter_type']}")
            print(f"    Span: {gap_info['present_months']} of {gap_info['span_months']} months present")
            print(f"    Missing: {gap_info['missing_months']} months")
            if gap_info['missing_month_labels']:
                print(f"    Missing months: {gap_info['missing_month_labels'][:5]}", end='')
                if len(gap_info['missing_month_labels']) > 5:
                    print(f" + {len(gap_info['missing_month_labels']) - 5} more")
                else:
                    print()
    
    print("\n" + "="*80 + "\n")

def main():
    parser = argparse.ArgumentParser(
        description='Check for missing values and time-series gaps in parquet tariff dataset'
    )
    parser.add_argument(
        '--parquet_dir',
        default='Attempt3/parquet_tariffs',
        help='Directory containing parquet files (default: Attempt3/parquet_tariffs)'
    )
    parser.add_argument(
        '--output_json',
        default=None,
        help='Optional: save analysis results to JSON file'
    )
    
    args = parser.parse_args()
    
    logger.info(f"Starting time-series gap analysis: parquet_dir={args.parquet_dir}")
    
    # Load all parquets
    df = load_all_parquets(args.parquet_dir)
    if df is None or (USE_POLARS and len(df) == 0) or (not USE_POLARS and len(df) == 0):
        logger.error("No data loaded, exiting")
        return
    
    # Analyze gaps
    analysis = analyze_timeseries_gaps(df)
    
    # Print report
    print_analysis_report(analysis)
    
    # Save to JSON if requested
    if args.output_json:
        try:
            # Convert sets to lists for JSON serialization
            json_safe_analysis = {
                'total_records': analysis['total_records'],
                'unique_contracts': analysis['unique_contracts'],
                'month_contract_combinations': analysis['month_contract_combinations'],
                'contracts_with_gaps': analysis['contracts_with_gaps'],
                'total_missing_month_contract_combinations': analysis['total_missing_month_contract_combinations'],
                'gaps_by_contract': {
                    k: {
                        **v,
                        'missing_month_labels': [
                            f"{y}-{m:02d}" for y, m in v['missing_month_labels']
                        ]
                    }
                    for k, v in analysis['gaps_by_contract'].items()
                },
                'null_values': analysis['null_values'],
            }
            
            with open(args.output_json, 'w', encoding='utf-8') as f:
                json.dump(json_safe_analysis, f, indent=2)
            logger.info(f"Analysis saved to {args.output_json}")
        except Exception as e:
            logger.error(f"Failed to save analysis to JSON: {e}")

if __name__ == '__main__':
    main()
