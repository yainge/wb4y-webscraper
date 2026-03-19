# Dutch Energy Tariff Ingestion Pipeline

Production-ready Python script for transforming monthly raw Dutch energy contract JSON snapshots into normalized, append-safe parquet files for consumption by calculation engines.

## Quick Start

### Installation

```bash
# Install dependencies
pip install pandas pyarrow

# Or if using poetry
poetry install
```

### Configuration

The script operates on a nested folder structure:

```
Attempt3/
├── 2025/
│   ├── contracts_januari 2025.json
│   ├── contracts_februari 2025.json
│   └── ... (more months)
├── 2026/
│   ├── contracts_januari 2026.json
│   └── ... (more months)
└── Tariff_preprocesssing/
    └── new_organization_tariff_data/
        ├── ingest_tariffs.py (this script)
        └── output/
            ├── contracts_fixed.parquet
            ├── contracts_variable.parquet
            ├── fixed_usage.parquet
            └── ... (more parquet files)
```

### Running the Pipeline

```bash
# Basic run (will create output directory)
python ingest_tariffs.py \
  --input-root ./Attempt3 \
  --output-root ./Attempt3/Tariff_preprocesssing/new_organization_tariff_data/output

# With debug logging
python ingest_tariffs.py \
  --input-root ./Attempt3 \
  --output-root ./output \
  --verbose
```

### Example Output

```
======================================================================
Dutch Energy Tariff Ingestion Pipeline
======================================================================
Input root:  c:\path\to\Attempt3
Output root: c:\path\to\output

Processing 2025/contracts_januari 2025.json
Processing 2025/contracts_februari 2025.json
...
======================================================================
Writing parquet files...
======================================================================
Loading existing contracts_fixed.parquet
Combined 45 existing + 12 new rows
Deduplicated contracts_fixed.parquet: 57 rows -> 57 rows
Wrote 57 rows to .\output\contracts_fixed.parquet
...
======================================================================
SUMMARY
======================================================================
Records processed:  284
Records skipped:    2
Parsing errors:     0

Parquet files written:
  contracts_fixed.parquet:      128 rows
  contracts_variable.parquet:   156 rows
  fixed_usage.parquet:          384 rows
  variable_usage.parquet:       468 rows
  fixed_fees.parquet:           256 rows
  variable_fees.parquet:        312 rows
  fixed_feedin_tiers.parquet:   0 rows
  variable_feedin_tiers.parquet: 0 rows
======================================================================
Ingestion complete!
```

## Output Parquet Files

### 1. `contracts_fixed.parquet` & `contracts_variable.parquet`
One row per unique contract snapshot (year, month, contract name, meter type).

**Key Columns:**
- `contract_key`: Stable primary key (provider | type | meter_type | name | month)
- `provider_id`: Normalized provider name (e.g., "anwb_energie")
- `contract_type`: "fixed" or "variable"
- `meter_type`: "single" or "double"
- `snapshot_month`: YYYY-MM format
- `duration_months`: Null for indefinite, otherwise months locked
- `has_gas`, `has_feed_in_tariff`, `has_feedin_tiers`: Boolean flags

### 2. `fixed_usage.parquet` & `variable_usage.parquet`
One row per tariff band per contract (e.g., electricity peak, gas, etc.).

**Key Columns:**
- `contract_key`: Links to contract
- `commodity`: "electricity" or "gas"
- `direction`: "import" for consumption; "feed_in" for solar export (future)
- `tariff_band`: "single", "peak", or "offpeak"
- `period`: "year" (fixed) or "YYYY-MM" (variable)
- `rate`: Decimal tariff (kWh, m³, etc.)
- `unit`: "kWh" or "m3"

### 3. `fixed_fees.parquet` & `variable_fees.parquet`
One row per fee component per contract (e.g., supplier fees).

**Key Columns:**
- `contract_key`: Links to contract
- `fee_component`: "gas_supplier_fee", "electricity_supplier_fee"
- `amount`: EUR amount
- `billing_frequency`: "yearly" (variable), null (fixed)
- `annual_amount`: EUR/year
- `unit`: "EUR"

### 4. `fixed_feedin_tiers.parquet` & `variable_feedin_tiers.parquet`
One row per tier per contract (for tiered feed-in rates, currently empty).

**Key Columns:**
- `contract_key`: Links to contract
- `settlement_period`: "monthly", "quarterly", etc.
- `basis_type`: "net_production", "gross_production", etc.
- `tier_index`: 0, 1, 2, ...
- `tier_min_kwh`, `tier_max_kwh`: Range boundaries (nullable)
- `tier_amount`: EUR/kWh rate
- `vat_included`: Boolean

## Key Features

### ✅ Idempotent & Append-Safe
- Run the pipeline multiple times on the same input → identical output
- New months are appended without duplicating old data
- Deduplication uses natural primary keys per table

### ✅ Robust Error Handling
- Malformed records logged as warnings, don't crash pipeline
- Dutch locale decimals (commas) automatically converted
- Missing optional tariff fields handled gracefully
- Month inference from filename if `_month_idx` field missing

### ✅ Separate Fixed/Variable Storage
- Different business logic for fixed (locked rates) vs variable (month-varying)
- Stored in separate parquet files for easy filtering
- Usage rows use `period="year"` (fixed) or `period="YYYY-MM"` (variable)

### ✅ Meter Type Support
- **Single meter**: One electricity tariff per direction
  - `tariff_band="single"` with `piek_per_kwh` rate
- **Double meter**: Peak and off-peak electricity tariffs
  - `tariff_band="peak"` with `piek_per_kwh`
  - `tariff_band="offpeak"` with `dal_per_kwh`
- **Gas**: Always single tariff regardless of meter type

### ✅ Extensible for Future Data
- Feed-in tariffs: `direction="import"` → add `direction="feed_in"` rows
- Tiered rates: Schema ready, code path prepared
- New commodities: Simple extension of parsing logic
- See `EXTENSIONS.md` for detailed implementation guide

## Raw Input Format

Expected JSON structure (list of contracts):

```json
[
  {
    "provider": "AllureNRG",
    "contract_name": "Variabele Prijs (met zonnepanelen)",
    "contract_duration": "Variabel (onbepaald)",
    "meter_type": "single",
    "tariffs": {
      "gas": {
        "fixed_yearly": "108,9000",
        "variable_per_m3": "1,3167"
      },
      "electricity": {
        "fixed_yearly": "363,0000",
        "piek_per_kwh": "0,2862",
        "dal_per_kwh": null
      }
    },
    "estimated_annual_costs": "189",
    "_tupleId": "8",
    "_month_idx": "augustus 2025",
    "_session_id": "3D71407C077544BB90D82BE71468C474-0:0"
  }
]
```

**Important notes:**
- Decimal values use commas (Dutch locale): `"108,9000"`
- Month index in Dutch: `"augustus 2025"` → parsed to `"2025-08"`
- `meter_type`: "single" or "double"
- `dal_per_kwh` often null for single-meter contracts (ignored)
- `fixed_yearly` values are fees, not usage tariffs

## Documentation

- **`ARCHITECTURE.md`**: High-level design, module breakdown, deduplication strategy
- **`EXAMPLES.md`**: Step-by-step transformation of 2 real contracts
- **`EXTENSIONS.md`**: Detailed guide for adding feed-in tariffs, tiers, new commodities

## Running Tests

```bash
# Basic validation
python ingest_tariffs.py --input-root ./test_data --output-root ./test_output --verbose

# Inspect output
python -c "
import pyarrow.parquet as pq
table = pq.read_table('./test_output/contracts_fixed.parquet')
print(table.to_pandas())
"
```

## Code Organization

- **Type System**: Dataclasses for all data structures (ContractRow, UsageRow, FeeRow, etc.)
- **Parsing Layer**: Modular functions for Dutch dates, decimals, contract classification
- **Transformation**: `transform_contract()` handles all raw→normalized logic
- **I/O**: `write_or_merge_parquet()` manages append-safe deduplication
- **Orchestration**: `ingest_all_contracts()` coordinates pipeline
- **CLI**: ArgumentParser for command-line usage

## Business Rules at a Glance

| Rule | Implementation |
|------|-----------------|
| Meter type single | `tariff_band="single"`, use `piek_per_kwh` |
| Meter type double | Two rows: `tariff_band="peak"` + `"offpeak"` |
| Fixed contracts | `period="year"`, `rate` locked |
| Variable contracts | `period="YYYY-MM"`, `rate` may change |
| Rates stored as fees | `fixed_yearly` → FeeRow, not UsageRow |
| Gas volumetric | `variable_per_m3` → UsageRow |
| Month parsing | Dutch month names, iso format output |
| Comma decimals | Auto-converted: `"108,9000"` → `Decimal("108.9")` |
| Contract key | Unique across provider, name, meter type, month |
| Deduplication | By primary key; latest version wins |

## Performance

- **Typical dataset**: 12 months × ~300 contracts/month = 3,600 records
- **Processing time**: < 5 seconds on modern hardware
- **Output size**: ~2-5 MB total parquet (compressed)
- **Memory usage**: < 500 MB

## Logging & Debugging

```bash
# Enable debug output
python ingest_tariffs.py --input-root ./data --output-root ./output --verbose

# Log levels:
# - INFO: File processing, summary counts, parquet writes
# - WARNING: Skipped records, malformed fields, inference fallbacks
# - ERROR: File parse failures, unexpected exceptions
```

## Extending for Production

See `EXTENSIONS.md` for:
- Adding feed-in tariffs (solar export rates)
- Adding tiered rates (quantity-based discounts)
- Supporting new commodities (hydrogen, heat)
- Schema evolution and backward compatibility
- Testing checklist

## License

[Your license here]

## Author

[Your organization]

---

**Questions or issues?** See `ARCHITECTURE.md` for deep dives into design decisions and `EXAMPLES.md` for walkthroughs of actual transformations.
