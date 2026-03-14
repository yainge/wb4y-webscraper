"""
Generate timeseries of dynamic contracts combining import and feed-in tariffs.

Merges functionality from:
- generate_dynamic_contracts_timeseries.py (import tariffs based on market prices)
- generate_feedin_timeseries.py (feed-in tariffs)

Formula for import cost: (market_price + energy_tax + margin) * VAT
Feed-in tariff: Fixed rate per contract from provider tariffs

Output: One parquet file per contract with columns: timestamp, import_tariff, feedin_tariff
"""

import pandas as pd
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple

# Configuration
VAT_RATE = 1.21  # 21% VAT for Netherlands
ENERGY_TAX = 0.088  # EUR/kWh (approximate energy tax in Netherlands)


def load_contract_tariffs_from_json(json_path: str) -> Dict:
    """
    Load contract tariffs from Frank Energie tariffs JSON.
    
    Returns:
        Dictionary with contract scenarios:
        {
            'scenario_id': {
                'name': str,
                'description': str,
                'import_margin': float (EUR/kWh),
                'feedin_rate': float (EUR/kWh),
                'fixed_costs_monthly': float (EUR/month)
            }
        }
    """
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    contracts = {}
    
    for scenario in data.get('scenarios', []):
        scenario_id = scenario.get('scenario_id')
        import_rate = scenario.get('electricity_purchase', {}).get('rate_per_kwh', 0)
        feedin_rate = scenario.get('electricity_feedin', {}).get('rate_per_kwh', 0)
        
        contracts[scenario_id] = {
            'name': scenario.get('name', scenario_id),
            'description': scenario.get('description', ''),
            'import_margin': import_rate,  # Base import margin (will be added to market price)
            'feedin_rate': feedin_rate,  # Fixed feed-in rate
            'fixed_costs_monthly': scenario.get('fixed_costs_monthly', 0)
        }
    
    return contracts


def load_market_prices(parquet_path: str) -> pd.DataFrame:
    """
    Load ENTSOE market prices and return as DataFrame with datetime index.
    
    Returns:
        DataFrame with columns: price (EUR/MWh or EUR/kWh depending on source)
    """
    prices_df = pd.read_parquet(parquet_path)
    
    # Convert ts_utc to datetime if not already
    if 'ts_utc' in prices_df.columns:
        prices_df['ts_utc'] = pd.to_datetime(prices_df['ts_utc'])
        prices_df.set_index('ts_utc', inplace=True)
    elif 'timestamp' in prices_df.columns:
        prices_df['timestamp'] = pd.to_datetime(prices_df['timestamp'])
        prices_df.set_index('timestamp', inplace=True)
    
    # Normalize price to EUR/kWh if it's in EUR/MWh
    if 'price' in prices_df.columns:
        # Check if prices are in MWh range (typically > 100)
        if prices_df['price'].max() > 100:
            prices_df['price_kwh'] = prices_df['price'] / 1000  # Convert MWh to kWh
        else:
            prices_df['price_kwh'] = prices_df['price']
    elif 'price_kwh' in prices_df.columns:
        prices_df['price_kwh'] = prices_df['price_kwh']
    else:
        raise ValueError("No price column found in market prices parquet")
    
    return prices_df


def calculate_import_tariff(market_price_kwh: float, import_margin: float, 
                            energy_tax: float, vat_rate: float) -> float:
    """
    Calculate import tariff cost per kWh.
    
    Formula: (market_price + energy_tax + import_margin) * VAT
    
    Args:
        market_price_kwh: Market price in EUR/kWh
        import_margin: Provider margin in EUR/kWh
        energy_tax: Energy tax in EUR/kWh
        vat_rate: VAT multiplier (e.g., 1.21 for 21%)
    
    Returns:
        Total import cost per kWh (EUR/kWh)
    """
    return (market_price_kwh + energy_tax + import_margin) * vat_rate


def generate_timeseries_for_contract(
    prices_df: pd.DataFrame,
    contract_id: str,
    contract_info: Dict,
    output_dir: Path,
    provider_name: str = "Frank Energie"
) -> Tuple[int, float, float]:
    """
    Generate and save combined timeseries for a single contract.
    
    Args:
        prices_df: DataFrame with market prices indexed by timestamp
        contract_id: Scenario ID (e.g., 'without_solar', 'with_solar')
        contract_info: Dictionary with contract parameters
        output_dir: Directory to save output files
        provider_name: Provider name for subdirectory
    
    Returns:
        Tuple of (num_records, avg_import_tariff, feedin_rate)
    """
    import_margin = contract_info['import_margin']
    feedin_rate = contract_info['feedin_rate']
    
    # Calculate import tariffs using vectorized operations
    import_tariffs = prices_df['price_kwh'].apply(
        lambda price: calculate_import_tariff(price, import_margin, ENERGY_TAX, VAT_RATE)
    )
    
    # Create output DataFrame
    timeseries_df = pd.DataFrame({
        'timestamp': prices_df.index,
        'import_tariff': import_tariffs.values,
        'feedin_tariff': feedin_rate
    })
    
    # Create output directory structure
    output_path = Path(output_dir) / provider_name
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Generate filename based on contract
    filename = f'timeseries_{contract_id}_2025.parquet'
    parquet_file = output_path / filename
    
    # Save as Parquet (efficient for timeseries data)
    timeseries_df.to_parquet(parquet_file, index=False)
    
    # Also save metadata as JSON
    json_file = output_path / f'timeseries_{contract_id}_2025.json'
    json_data = {
        'provider': provider_name,
        'contract': contract_id,
        'name': contract_info['name'],
        'description': contract_info['description'],
        'tariff_parameters': {
            'import_margin': float(import_margin),
            'feedin_rate': float(feedin_rate),
            'energy_tax': float(ENERGY_TAX),
            'vat_rate': float(VAT_RATE - 1),
            'fixed_costs_monthly': float(contract_info['fixed_costs_monthly'])
        },
        'data_summary': {
            'records': len(timeseries_df),
            'timestamp_range': {
                'start': timeseries_df['timestamp'].min().isoformat(),
                'end': timeseries_df['timestamp'].max().isoformat()
            },
            'import_tariff_stats': {
                'min': float(timeseries_df['import_tariff'].min()),
                'max': float(timeseries_df['import_tariff'].max()),
                'mean': float(timeseries_df['import_tariff'].mean()),
                'unit': 'EUR/kWh'
            },
            'feedin_tariff': float(feedin_rate),
            'unit': 'EUR/kWh'
        },
        'metadata': {
            'generated_at': datetime.now().isoformat(),
            'source': 'merged script: generate_contract_timeseries.py'
        }
    }
    
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)
    
    avg_import = timeseries_df['import_tariff'].mean()
    
    status = "✓" if feedin_rate > 0 else "✓" if feedin_rate == 0 else "⚠"
    print(f"{status} {contract_id:20s} | Records: {len(timeseries_df):6d} | "
          f"Import avg: {avg_import:7.4f} EUR/kWh | Feed-in: {feedin_rate:7.4f} EUR/kWh | "
          f"File: {filename}")
    
    return len(timeseries_df), avg_import, feedin_rate


def main(json_tariffs_path: str = None, 
         prices_parquet_path: str = None,
         output_dir: str = None):
    """
    Main function to generate timeseries for all contracts from JSON tariff file.
    
    Args:
        json_tariffs_path: Path to Frank Energie tariffs JSON file
        prices_parquet_path: Path to ENTSOE market prices parquet file
        output_dir: Output directory for generated files
    """
    # Define default paths if not provided
    script_dir = Path(__file__).parent
    project_root = script_dir.parent.parent.parent
    
    if json_tariffs_path is None:
        json_tariffs_path = (
            project_root / 'Attempt3' / 'Tariff_preprocesssing' / 'Dynamic_contracts' / 
            '2025' / 'Frank Energie' / 'frank_energie_tariffs.json'
        )
    
    if prices_parquet_path is None:
        prices_parquet_path = (
            project_root / 'Attempt3' / 'Tariff_preprocesssing' / 'input' / 
            'entsoe_prices_NL_2025_2026_combined.parquet'
        )
    
    if output_dir is None:
        output_dir = project_root / 'Attempt3' / 'Tariff_preprocesssing' / 'Dynamic_contracts'
    
    # Convert to string paths
    json_tariffs_path = str(json_tariffs_path)
    prices_parquet_path = str(prices_parquet_path)
    output_dir = Path(output_dir)
    
    # Validate input files
    if not Path(json_tariffs_path).exists():
        raise FileNotFoundError(f"Tariffs JSON not found: {json_tariffs_path}")
    if not Path(prices_parquet_path).exists():
        raise FileNotFoundError(f"Market prices not found: {prices_parquet_path}")
    
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("=" * 100)
    print("DYNAMIC CONTRACT TIMESERIES GENERATOR (Merged Script)")
    print("=" * 100)
    print()
    print(f"Loading data...")
    print(f"  Tariffs JSON:   {json_tariffs_path}")
    print(f"  Market prices:  {prices_parquet_path}")
    print(f"  Output dir:     {output_dir}")
    print()
    
    # Load data
    contracts = load_contract_tariffs_from_json(json_tariffs_path)
    prices_df = load_market_prices(prices_parquet_path)
    
    # Filter prices for 2025 only
    prices_2025 = prices_df[prices_df.index.year == 2025].copy()
    
    print(f"Data Summary:")
    print(f"  Found {len(contracts)} contracts/scenarios")
    print(f"  Market price data: {len(prices_2025)} records for 2025")
    print(f"  Time range: {prices_2025.index.min()} to {prices_2025.index.max()}")
    print()
    print(f"Configuration:")
    print(f"  VAT Rate:       {(VAT_RATE - 1) * 100:.0f}%")
    print(f"  Energy Tax:     {ENERGY_TAX:.4f} EUR/kWh")
    print()
    print(f"Generating timeseries for {len(contracts)} contracts:")
    print()
    
    # Generate timeseries for each contract
    total_records = 0
    contract_stats = []
    
    for contract_id in sorted(contracts.keys()):
        contract_info = contracts[contract_id]
        num_records, avg_import, feedin_rate = generate_timeseries_for_contract(
            prices_2025,
            contract_id,
            contract_info,
            output_dir,
            provider_name="Frank Energie"
        )
        total_records += num_records
        contract_stats.append({
            'contract_id': contract_id,
            'records': num_records,
            'avg_import': avg_import,
            'feedin_rate': feedin_rate
        })
    
    print()
    print("=" * 100)
    print(f"✓ COMPLETED! Generated {total_records} total records across {len(contracts)} contracts")
    print("=" * 100)
    print()
    print("Output Summary:")
    for stat in contract_stats:
        print(f"  {stat['contract_id']:20s}: {stat['records']:6d} records | "
              f"Avg import: {stat['avg_import']:7.4f} EUR/kWh | "
              f"Feed-in: {stat['feedin_rate']:7.4f} EUR/kWh")
    print()
    print(f"Output saved to: {output_dir / 'Frank Energie'}")
    print()
    print("Files generated (per contract):")
    print(f"  - timeseries_<contract_id>_2025.parquet (columns: timestamp, import_tariff, feedin_tariff)")
    print(f"  - timeseries_<contract_id>_2025.json (metadata and summary statistics)")
    print()


if __name__ == '__main__':
    main()
