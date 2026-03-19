# Quick Start Guide

Get the tariff ingestion pipeline running in 5 minutes.

## 1. Install Dependencies

```bash
cd Attempt3/Tariff_preprocesssing/new_organization_tariff_data

# Install required packages
pip install -r requirements.txt

# Or install just the essentials
pip install pandas pyarrow
```

## 2. Run the Pipeline

```bash
# From the script directory, or with full path
python ingest_tariffs.py \
  --input-root ../../ \
  --output-root ./output

# With verbose logging (see details)
python ingest_tariffs.py \
  --input-root ../../ \
  --output-root ./output \
  --verbose
```

**Expected output:**

```
======================================================================
Dutch Energy Tariff Ingestion Pipeline
======================================================================
Input root:  /path/to/Attempt3
Output root: /path/to/output

Processing 2025/contracts_januari 2025.json
Processing 2025/contracts_februari 2025.json
...
Processing 2026/contracts_februari 2026.json
======================================================================
Writing parquet files...
======================================================================
Loading existing contracts_fixed.parquet
Combined 0 existing + 284 new rows
Deduplicated contracts_fixed.parquet: 284 rows -> 284 rows
Wrote 284 rows to ./output\contracts_fixed.parquet
...
======================================================================
SUMMARY
======================================================================
Records processed:  2824
Records skipped:    12
Parsing errors:     0

Parquet files written:
  contracts_fixed.parquet:      456 rows
  contracts_variable.parquet:   568 rows
  fixed_usage.parquet:         1,368 rows
  variable_usage.parquet:      1,704 rows
  fixed_fees.parquet:            912 rows
  variable_fees.parquet:        1,136 rows
  fixed_feedin_tiers.parquet:      0 rows
  variable_feedin_tiers.parquet:   0 rows
======================================================================
Ingestion complete!
```

## 3. Verify Output

```bash
# Check that all output files were created
python verify_output.py --output-root ./output

# View detailed statistics
python verify_output.py --output-root ./output --details
```

## 4. Inspect the Data

### View contracts

```bash
python -c "
import pandas as pd
df = pd.read_parquet('./output/contracts_fixed.parquet')
print(f'Fixed contracts: {len(df)} rows')
print(df[['provider_id', 'contract_name', 'meter_type', 'snapshot_month']].head())
"
```

### View tariffs

```bash
python -c "
import pandas as pd
df = pd.read_parquet('./output/fixed_usage.parquet')
print(f'Fixed usage tariffs: {len(df)} rows')
print(df[['commodity', 'tariff_band', 'rate', 'unit']].head())
"
```

### View fees

```bash
python -c "
import pandas as pd
df = pd.read_parquet('./output/fixed_fees.parquet')
print(f'Fixed fees: {len(df)} rows')
print(df[['provider_id', 'fee_component', 'amount']].head())
"
```

## 5. Rerun on Updated Data (Append New Month)

When a new month arrives (e.g., March 2026):

1. Place the JSON file in `Attempt3/2026/contracts_maart 2026.json`
2. Rerun the pipeline:

```bash
python ingest_tariffs.py \
  --input-root ../../ \
  --output-root ./output
```

The pipeline will:
- Read the new month file
- Append to existing parquet files
- Automatically deduplicate (no duplicates even if you rerun on the same data)
- Produce updated output with both old and new months

## 6. Run Tests (Optional)

```bash
# Install test dependencies
pip install pytest pytest-cov

# Run unit tests
pytest test_ingest_tariffs.py -v

# Run with coverage
pytest test_ingest_tariffs.py --cov=ingest_tariffs
```

## What Each Output File Contains

| File | Purpose | Primary Key |
|------|---------|-------------|
| `contracts_fixed.parquet` | Fixed contract metadata | contract_key |
| `contracts_variable.parquet` | Variable contract metadata | contract_key |
| `fixed_usage.parquet` | Fixed tariff rates by band | contract_key + commodity + direction + band + period |
| `variable_usage.parquet` | Variable tariff rates by month | contract_key + commodity + direction + band + period |
| `fixed_fees.parquet` | Fixed supplier fees | contract_key + fee_component |
| `variable_fees.parquet` | Variable supplier fees | contract_key + fee_component |
| `fixed_feedin_tiers.parquet` | Feed-in tier rates (empty currently) | contract_key + tier_index |
| `variable_feedin_tiers.parquet` | Feed-in tier rates (empty currently) | contract_key + tier_index |

## Common Commands

```bash
# Count records per provider
python -c "
import pandas as pd
contracts = pd.read_parquet('./output/contracts_fixed.parquet')
print(contracts['provider_name'].value_counts())
"

# Find all double-meter contracts
python -c "
import pandas as pd
contracts = pd.read_parquet('./output/contracts_fixed.parquet')
double = contracts[contracts['meter_type'] == 'double']
print(f'Double-meter contracts: {len(double)}')
"

# Get average rates by commodity
python -c "
import pandas as pd
usage = pd.read_parquet('./output/fixed_usage.parquet')
print(usage.groupby('commodity')['rate'].agg(['mean', 'min', 'max']))
"

# Total fees by provider
python -c "
import pandas as pd
fees = pd.read_parquet('./output/fixed_fees.parquet')
print(fees.groupby('provider_id')['amount'].sum())
"
```

## Troubleshooting

### "No contract JSON files found"

Check that your input directory structure is correct:

```
Attempt3/
├── 2025/
│   └── contracts_*.json files here
├── 2026/
│   └── contracts_*.json files here
```

The script looks for `contracts_*.json` files recursively.

### "Could not parse month from record"

If a contract record is missing `_month_idx`, the script tries to infer from the filename. Ensure JSON files are named like:

- `contracts_januari 2025.json`
- `contracts_februari 2025.json`
- `contracts_maart 2025.json`
- etc.

### Decimal parsing errors

Raw data uses Dutch locale (comma separator). The script converts automatically:
- Input: `"108,9000"` → Output: `108.9`

If you see warnings about decimal parsing, check the raw JSON for valid formats.

### Permission denied on output files

If you get permission errors writing parquet:
- Ensure `--output-root` directory is writable
- Close any open Excel/Power BI files that reference the parquets
- Verify disk space is available

## Next Steps

See the full documentation:
- **`README.md`** — Overview and detailed reference
- **`ARCHITECTURE.md`** — Design decisions and module structure
- **`EXAMPLES.md`** — Walkthrough of 2 real contracts
- **`EXTENSIONS.md`** — How to add feed-in tariffs and tiers later

## Integration with Calculation Engine

The output parquet files are ready to use:

```python
import pandas as pd

# Load contracts and usage tariffs
contracts = pd.read_parquet('output/contracts_fixed.parquet')
usage = pd.read_parquet('output/fixed_usage.parquet')
fees = pd.read_parquet('output/fixed_fees.parquet')

# Join to calculate bills
merged = contracts.merge(usage, on='contract_key')
merged = merged.merge(fees, on='contract_key')

# Your calculation logic here
...
```

The data is normalized and ready for further processing.
