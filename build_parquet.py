import json
import argparse
import logging
import hashlib
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import sys

# Try to import polars, fall back to pandas
try:
    import polars as pl
    USE_POLARS = True
except ImportError:
    import pandas as pd
    USE_POLARS = False

import pyarrow.parquet as pq

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Dutch month mapping
DUTCH_MONTHS = {
    'januari': 1,
    'februari': 2,
    'maart': 3,
    'april': 4,
    'mei': 5,
    'juni': 6,
    'juli': 7,
    'augustus': 8,
    'september': 9,
    'oktober': 10,
    'november': 11,
    'december': 12
}

def load_months(input_dir: str) -> List[str]:
    """Load month labels from months.json."""
    months_file = Path(input_dir) / 'months.json'
    try:
        with open(months_file, 'r', encoding='utf-8') as f:
            months = json.load(f)
        logger.info(f"Loaded {len(months)} months from {months_file}")
        return months
    except Exception as e:
        logger.error(f"Failed to load months.json: {e}")
        return []

def load_providers(input_dir: str) -> Dict[str, int]:
    """Load provider mapping from providers.json."""
    providers_file = Path(input_dir) / 'providers.json'
    provider_map = {}
    try:
        with open(providers_file, 'r', encoding='utf-8') as f:
            providers = json.load(f)
        
        # Handle both list of dicts and dict format
        if isinstance(providers, list):
            for item in providers:
                if isinstance(item, dict) and 'providerName' in item and 'provider_id_ACM' in item:
                    provider_map[item['providerName']] = item['provider_id_ACM']
        elif isinstance(providers, dict):
            provider_map = providers
        
        logger.info(f"Loaded {len(provider_map)} providers from {providers_file}")
        return provider_map
    except Exception as e:
        logger.error(f"Failed to load providers.json: {e}")
        return {}

def parse_dutch_month_label(month_label: str) -> Optional[Tuple[str, int, int]]:
    """Parse Dutch month label like 'februari 2026' into (label, month, year)."""
    try:
        parts = month_label.strip().lower().split()
        if len(parts) != 2:
            logger.warning(f"Invalid month label format: {month_label}")
            return None
        
        month_name, year_str = parts
        if month_name not in DUTCH_MONTHS:
            logger.warning(f"Unknown Dutch month: {month_name}")
            return None
        
        year = int(year_str)
        month = DUTCH_MONTHS[month_name]
        return (month_label, month, year)
    except Exception as e:
        logger.warning(f"Failed to parse month label '{month_label}': {e}")
        return None

def parse_euro_float(value: Optional[str]) -> Optional[float]:
    """Parse European decimal format (comma as separator) to float."""
    if value is None or value == '' or value == 'null':
        return None
    try:
        if isinstance(value, (int, float)):
            return float(value)
        # Replace comma with dot
        value_str = str(value).strip().replace(',', '.')
        return float(value_str)
    except Exception as e:
        logger.warning(f"Failed to parse float value '{value}': {e}")
        return None

def make_contract_key(provider_id: int, contract_name: str, contract_duration: str, meter_type: str) -> str:
    """Create a deterministic contract key as SHA1 hash (first 16 chars)."""
    key_str = f"{provider_id}|{contract_name}|{contract_duration}|{meter_type}"
    hash_obj = hashlib.sha1(key_str.encode('utf-8'))
    return hash_obj.hexdigest()[:16]

def find_contract_file(month_label: str, input_dir: str) -> Optional[Path]:
    """Find the contracts JSON file for a given month label."""
    input_path = Path(input_dir)
    month_filename = f"contracts_{month_label}.json"
    
    # Check in root input_dir
    file_path = input_path / month_filename
    if file_path.exists():
        return file_path
    
    # Check in year subdirectories (2023, 2024, 2025, 2026, etc.)
    month_parts = month_label.strip().split()
    if len(month_parts) == 2:
        year = month_parts[1]
        year_dir = input_path / year
        file_path = year_dir / month_filename
        if file_path.exists():
            return file_path
    
    return None

def process_all_months(months: List[str], input_dir: str, provider_map: Dict[str, int]) -> Tuple[List[Dict], int]:
    """Load and process all monthly contract files."""
    all_records = []
    missing_provider_count = 0
    
    for month_idx, month_label in enumerate(months):
        # Parse month label
        parsed = parse_dutch_month_label(month_label)
        if parsed is None:
            logger.warning(f"Skipping month {month_label} due to parse error")
            continue
        
        label, month, year = parsed
        period_start = f"{year:04d}-{month:02d}-01"
        
        # Find contracts file for this month
        contracts_file = find_contract_file(month_label, input_dir)
        if contracts_file is None:
            logger.warning(f"Contracts file not found for {month_label}")
            continue
        
        # Load contracts
        try:
            with open(contracts_file, 'r', encoding='utf-8') as f:
                contracts = json.load(f)
            
            if not isinstance(contracts, list):
                logger.warning(f"Expected list in {contracts_file}, got {type(contracts)}")
                continue
            
            # Process each contract
            records_this_month = 0
            for record in contracts:
                try:
                    # Get provider and lookup ID
                    provider_name = record.get('provider', '').strip()
                    
                    # Try exact match first, then case-insensitive
                    provider_id = provider_map.get(provider_name)
                    if provider_id is None:
                        # Try case-insensitive match
                        for prov_key, prov_id in provider_map.items():
                            if prov_key.lower() == provider_name.lower():
                                provider_id = prov_id
                                break
                    
                    if provider_id is None:
                        provider_id = -1
                        missing_provider_count += 1
                        logger.warning(f"Provider '{provider_name}' not found in mapping")
                    
                    # Parse tariffs
                    tariffs = record.get('tariffs', {})
                    gas_tariffs = tariffs.get('gas', {})
                    elec_tariffs = tariffs.get('electricity', {})
                    
                    # Parse costs
                    estimated_costs_str = record.get('estimated_annual_costs', '')
                    estimated_costs = parse_euro_float(estimated_costs_str)
                    
                    # Parse tuple_id
                    tuple_id_str = record.get('_tupleId', '')
                    try:
                        tuple_id = int(tuple_id_str) if tuple_id_str else None
                    except ValueError:
                        tuple_id = None
                    
                    # Create contract key
                    contract_name = record.get('contract_name', '')
                    contract_duration = record.get('contract_duration', '')
                    meter_type = record.get('meter_type', '')
                    contract_key = make_contract_key(provider_id, contract_name, contract_duration, meter_type)
                    
                    # Build row
                    row = {
                        'month_label': label,
                        'month_idx': month_idx,
                        'year': year,
                        'month': month,
                        'period_start': period_start,
                        'provider': provider_name,
                        'provider_id': provider_id,
                        'contract_name': contract_name,
                        'contract_duration': contract_duration,
                        'meter_type': meter_type,
                        'contract_key': contract_key,
                        'gas_fixed_yearly': parse_euro_float(gas_tariffs.get('fixed_yearly')),
                        'gas_variable_per_m3': parse_euro_float(gas_tariffs.get('variable_per_m3')),
                        'elec_fixed_yearly': parse_euro_float(elec_tariffs.get('fixed_yearly')),
                        'elec_piek_per_kwh': parse_euro_float(elec_tariffs.get('piek_per_kwh')),
                        'elec_dal_per_kwh': parse_euro_float(elec_tariffs.get('dal_per_kwh')),
                        'estimated_annual_costs': estimated_costs,
                        'tuple_id': tuple_id,
                        'session_id': record.get('_session_id', ''),
                    }
                    all_records.append(row)
                    records_this_month += 1
                
                except Exception as e:
                    logger.warning(f"Error processing record in {label}: {e}")
                    continue
            
            logger.info(f"Month {label}: {records_this_month} records loaded")
        
        except Exception as e:
            logger.error(f"Failed to load contracts from {contracts_file}: {e}")
            continue
    
    return all_records, missing_provider_count

def write_provider_year_parquets(all_records: List[Dict], output_dir: str, force: bool = False):
    """Group records by provider_id/year and write parquet files."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Group records by (provider_id, year)
    groups = defaultdict(list)
    for record in all_records:
        key = (record['provider_id'], record['year'])
        groups[key].append(record)
    
    # Write each group to parquet
    written_count = 0
    skipped_count = 0
    
    for (provider_id, year), records in sorted(groups.items()):
        partition_dir = output_path / f"provider_id={provider_id}" / f"year={year}"
        partition_dir.mkdir(parents=True, exist_ok=True)
        
        parquet_file = partition_dir / "part-0.parquet"
        
        # Check if file exists and force flag
        if parquet_file.exists() and not force:
            logger.info(f"Skipped: provider_id={provider_id}, year={year} (already exists, use --force to rebuild)")
            skipped_count += 1
            continue
        
        try:
            # Convert to dataframe and write
            if USE_POLARS:
                df = pl.DataFrame(records)
                df.write_parquet(str(parquet_file), compression='snappy')
            else:
                df = pd.DataFrame(records)
                df.to_parquet(str(parquet_file), compression='snappy', index=False)
            
            unique_contracts = len(set(r['contract_key'] for r in records))
            months_covered = sorted(set(r['month_label'] for r in records))
            missing_ids = sum(1 for r in records if r['provider_id'] == -1)
            
            logger.info(
                f"Written: provider_id={provider_id}, year={year}, rows={len(records)}, "
                f"unique_contracts={unique_contracts}, months_covered={len(months_covered)}, "
                f"missing_provider_id_rows={missing_ids}"
            )
            
            written_count += 1
        
        except Exception as e:
            logger.error(f"Failed to write {parquet_file}: {e}")
    
    logger.info(f"Parquet files written: {written_count}, skipped: {skipped_count}")
    
    # Overall summary
    total_rows = len(all_records)
    total_unique_contracts = len(set(r['contract_key'] for r in all_records))
    total_missing = sum(1 for r in all_records if r['provider_id'] == -1)
    
    logger.info(
        f"Overall totals: rows={total_rows}, unique_contracts={total_unique_contracts}, "
        f"missing_provider_mappings={total_missing}"
    )

def main():
    parser = argparse.ArgumentParser(
        description='Convert monthly contracts JSON to Parquet time-series dataset'
    )
    parser.add_argument(
        '--input_dir',
        default='Attempt3',
        help='Input directory containing months.json and contracts files (default: Attempt3)'
    )
    parser.add_argument(
        '--output_dir',
        default='Attempt3/parquet_tariffs',
        help='Output directory for parquet files (default: Attempt3/parquet_tariffs)'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Force rebuild even if output parquet already exists'
    )
    
    args = parser.parse_args()
    
    logger.info(f"Starting build_parquet: input_dir={args.input_dir}, output_dir={args.output_dir}, force={args.force}")
    
    # Load metadata
    months = load_months(args.input_dir)
    if not months:
        logger.error("No months loaded, exiting")
        sys.exit(1)
    
    provider_map = load_providers(args.input_dir)
    if not provider_map:
        logger.warning("No providers loaded, will use -1 for all unknown providers")
    
    # Process all months
    all_records, missing_provider_count = process_all_months(months, args.input_dir, provider_map)
    logger.info(f"Total records processed: {len(all_records)}")
    
    if not all_records:
        logger.error("No records processed, exiting")
        sys.exit(1)
    
    # Write parquet files
    write_provider_year_parquets(all_records, args.output_dir, args.force)
    
    logger.info("Build completed successfully")

if __name__ == '__main__':
    main()
