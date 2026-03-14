"""
Generate timeseries of dynamic contracts costs per kWh.

Formula: (market_price + energy_tax + margin) * VAT

Where:
- market_price: ENTSOE electricity market price (EUR/MWh)
- energy_tax: Energy tax rate (EUR/kWh)
- margin: Provider margin (EUR/kWh) from provider_tariffs.xlsx
- VAT: Value Added Tax (21% for Netherlands)
"""

import pandas as pd
import json
import os
from pathlib import Path
from datetime import datetime

# Configuration
VAT_RATE = 1.21  # 21% VAT for Netherlands
ENERGY_TAX = 0.088  # EUR/kWh (approximate energy tax in Netherlands)

def load_provider_tariffs(xlsx_path):
    """Load provider tariffs and return dynamic contracts."""
    df = pd.read_excel(xlsx_path)
    # Filter for dynamic contracts only
    dynamic = df[df['Contract type'] == 'Dynamisch'].copy()
    
    providers = {}
    for _, row in dynamic.iterrows():
        provider_name = row['Company name']
        margin = row['Electricity price']  # in EUR/kWh
        
        if provider_name not in providers:
            providers[provider_name] = {
                'margin': margin,
                'client_id': row['Client ID'],
                'contract_type': row['Contract type']
            }
    
    return providers

def load_market_prices(parquet_path):
    """Load ENTSOE market prices and return as DataFrame with datetime index."""
    prices_df = pd.read_parquet(parquet_path)
    # Convert ts_utc to datetime if not already
    prices_df['ts_utc'] = pd.to_datetime(prices_df['ts_utc'])
    prices_df.set_index('ts_utc', inplace=True)
    # Convert price from EUR/MWh to EUR/kWh
    prices_df['price_kwh'] = prices_df['price'] # EUR/kWh (already in correct unit)
    return prices_df

def calculate_dynamic_costs(market_price_kwh, energy_tax, margin, vat_rate):
    """
    Calculate dynamic contract cost per kWh.
    
    Formula: (market_price + energy_tax + margin) * VAT
    
    Returns:
        Total cost per kWh (EUR/kWh)
    """
    return (market_price_kwh + energy_tax + margin) * vat_rate

def generate_timeseries_for_provider(prices_df, provider_name, provider_info, output_dir):
    """Generate and save timeseries for a single provider."""
    margin = provider_info['margin']
    
    # Calculate costs using vectorized operations
    costs = (prices_df['price_kwh'] + ENERGY_TAX + margin) * VAT_RATE
    
    # Create output DataFrame
    timeseries_df = pd.DataFrame({
        'timestamp': prices_df.index,
        'market_price_kwh': prices_df['price_kwh'].values,
        'energy_tax': ENERGY_TAX,
        'margin': margin,
        'total_cost_kwh': costs.values
    })
    
    # Create provider directory if it doesn't exist
    provider_dir = Path(output_dir) / provider_name
    provider_dir.mkdir(parents=True, exist_ok=True)
    
    # Save as Parquet for efficient storage
    parquet_file = provider_dir / 'timeseries_2025.parquet'
    timeseries_df.to_parquet(parquet_file, index=False)
    
    # Save as JSON (convert to dictionary format for efficient storage)
    json_file = provider_dir / 'timeseries_2025.json'
    json_data = {
        'provider': provider_name,
        'margin': float(margin),
        'energy_tax': float(ENERGY_TAX),
        'vat_rate': float(VAT_RATE - 1),
        'data': {
            'timestamp': [ts.isoformat() for ts in timeseries_df['timestamp']],
            'market_price_kwh': timeseries_df['market_price_kwh'].tolist(),
            'total_cost_kwh': timeseries_df['total_cost_kwh'].tolist()
        },
        'metadata': {
            'records': len(timeseries_df),
            'unit': 'EUR/kWh',
            'generated_at': datetime.now().isoformat()
        }
    }
    
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)
    
    print(f"✓ {provider_name}: {len(timeseries_df)} records | "
          f"Margin: {margin:.6f} EUR/kWh | "
          f"Avg cost: {costs.mean():.4f} EUR/kWh")
    
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
    
    # Create output directory
    output_base.mkdir(parents=True, exist_ok=True)
    
    print(f"Loading data...")
    print(f"Provider tariffs: {provider_tariffs}")
    print(f"Market prices: {prices_parquet}")
    print(f"Output directory: {output_base}")
    print()
    
    # Load data
    providers = load_provider_tariffs(str(provider_tariffs))
    prices_df = load_market_prices(str(prices_parquet))
    
    # Filter prices for 2025 only
    prices_2025 = prices_df[prices_df.index.year == 2025].copy()
    
    print(f"Found {len(providers)} dynamic providers")
    print(f"Market price data: {len(prices_2025)} records for 2025")
    print(f"Time range: {prices_2025.index.min()} to {prices_2025.index.max()}")
    print()
    print(f"Configuration:")
    print(f"  VAT Rate: {(VAT_RATE - 1) * 100:.0f}%")
    print(f"  Energy Tax: {ENERGY_TAX:.4f} EUR/kWh")
    print()
    print(f"Generating timeseries for {len(providers)} providers:")
    print()
    
    # Generate timeseries for each provider
    total_records = 0
    for provider_name in sorted(providers.keys()):
        provider_info = providers[provider_name]
        records = generate_timeseries_for_provider(
            prices_2025, 
            provider_name, 
            provider_info, 
            output_base
        )
        total_records += records
    
    print()
    print(f"✓ Completed! Generated {total_records} total records across {len(providers)} providers")
    print(f"Output saved to: {output_base}")

if __name__ == '__main__':
    main()
