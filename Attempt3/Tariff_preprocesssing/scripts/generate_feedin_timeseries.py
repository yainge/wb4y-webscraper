"""
Generate timeseries of feed-in tariffs for dynamic contracts.

Feed-in tariffs are the rates paid to consumers when they feed electricity back
into the grid (e.g., from solar panels).
"""

import pandas as pd
import json
import os
from pathlib import Path
from datetime import datetime

def load_provider_feedin_tariffs(xlsx_path):
    """Load provider feed-in tariffs and return dynamic contracts."""
    df = pd.read_excel(xlsx_path)
    # Filter for dynamic contracts only
    dynamic = df[df['Contract type'] == 'Dynamisch'].copy()
    
    providers = {}
    for _, row in dynamic.iterrows():
        provider_name = row['Company name']
        feedin_rate = row['Feed-in']  # in EUR/kWh
        feedin_specific = row['Feed in specific']  # Yes/No
        
        if provider_name not in providers:
            providers[provider_name] = {
                'feedin_rate': feedin_rate,
                'feedin_specific': feedin_specific,
                'client_id': row['Client ID'],
                'contract_type': row['Contract type']
            }
    
    return providers

def load_market_prices(parquet_path):
    """Load ENTSOE market prices to get the timestamp structure."""
    prices_df = pd.read_parquet(parquet_path)
    prices_df['ts_utc'] = pd.to_datetime(prices_df['ts_utc'])
    prices_df.set_index('ts_utc', inplace=True)
    return prices_df

def generate_feedin_timeseries_for_provider(prices_df, provider_name, provider_info, output_dir):
    """Generate and save feed-in timeseries for a single provider."""
    feedin_rate = provider_info['feedin_rate']
    
    # Create timeseries with fixed feed-in rate for all timestamps
    timeseries_df = pd.DataFrame({
        'timestamp': prices_df.index,
        'feedin_rate_kwh': feedin_rate
    })
    
    # Create provider directory if it doesn't exist
    provider_dir = Path(output_dir) / provider_name
    provider_dir.mkdir(parents=True, exist_ok=True)
    
    # Save as Parquet for efficient storage
    parquet_file = provider_dir / 'feedin_timeseries_2025.parquet'
    timeseries_df.to_parquet(parquet_file, index=False)
    
    # Save as JSON
    json_file = provider_dir / 'feedin_timeseries_2025.json'
    json_data = {
        'provider': provider_name,
        'feedin_rate_kwh': float(feedin_rate),
        'feedin_specific': provider_info['feedin_specific'],
        'data': {
            'timestamp': [ts.isoformat() for ts in timeseries_df['timestamp']],
            'feedin_rate_kwh': [float(feedin_rate)] * len(timeseries_df)
        },
        'metadata': {
            'records': len(timeseries_df),
            'unit': 'EUR/kWh',
            'type': 'feed-in (electricity fed back to grid)',
            'generated_at': datetime.now().isoformat()
        }
    }
    
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)
    
    status = "✓" if feedin_rate > 0 else "⚠"
    print(f"{status} {provider_name}: {len(timeseries_df)} records | "
          f"Feed-in rate: {feedin_rate:.6f} EUR/kWh")
    
    return len(timeseries_df)

def main():
    # Define paths
    script_dir = Path(__file__).parent
    project_root = script_dir.parent.parent.parent
    
    provider_tariffs = project_root / 'Attempt3' / 'Tariff_preprocesssing' / 'input' / 'provider_tariffs.xlsx'
    prices_parquet = project_root / 'Attempt3' / 'Tariff_preprocesssing' / 'input' / 'entsoe_prices_NL_2025_2026_combined.parquet'
    output_base = project_root / 'Attempt3' / 'Tariff_preprocesssing' / 'Dynamic_contracts' / '2025'
    
    # Validate input files
    if not provider_tariffs.exists():
        raise FileNotFoundError(f"Provider tariffs not found: {provider_tariffs}")
    if not prices_parquet.exists():
        raise FileNotFoundError(f"Market prices not found: {prices_parquet}")
    
    print(f"Loading data...")
    print(f"Provider tariffs: {provider_tariffs}")
    print(f"Output directory: {output_base}")
    print()
    
    # Load data
    providers = load_provider_feedin_tariffs(str(provider_tariffs))
    prices_df = load_market_prices(str(prices_parquet))
    
    # Filter prices for 2025 only
    prices_2025 = prices_df[prices_df.index.year == 2025].copy()
    
    print(f"Found {len(providers)} dynamic providers with feed-in tariffs")
    print(f"Timestamp records: {len(prices_2025)} for 2025")
    print()
    print(f"Generating feed-in timeseries for {len(providers)} providers:")
    print()
    
    # Generate timeseries for each provider
    total_records = 0
    zero_feedin = 0
    for provider_name in sorted(providers.keys()):
        provider_info = providers[provider_name]
        if provider_info['feedin_rate'] == 0:
            zero_feedin += 1
        records = generate_feedin_timeseries_for_provider(
            prices_2025, 
            provider_name, 
            provider_info, 
            output_base
        )
        total_records += records
    
    print()
    print(f"✓ Completed! Generated {total_records} total records across {len(providers)} providers")
    if zero_feedin > 0:
        print(f"⚠ {zero_feedin} provider(s) have zero feed-in rates (no feed-in compensation)")
    print(f"Output saved to: {output_base}")
    print()
    print("Files saved show:")
    print("  - feedin_timeseries_2025.json (JSON format with timestamps)")
    print("  - feedin_timeseries_2025.parquet (Parquet format for efficient storage)")

if __name__ == '__main__':
    main()
