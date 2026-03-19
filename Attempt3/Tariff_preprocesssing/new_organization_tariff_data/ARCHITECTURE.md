"""
ARCHITECTURE GUIDE

Production-ready ingestion pipeline for Dutch energy contract tariff data.
"""

# =============================================================================
# HIGH-LEVEL DESIGN
# =============================================================================

## Flow Overview

    raw JSON (Attempt3/2025/*.json)
              ↓
        parse_json_file()
              ↓
        transform_contract() for each record
              ↓
        Splits into:
          ├─ ContractRow (metadata)
          ├─ UsageRow[] (volumetric tariffs)
          ├─ FeeRow[] (supplier fees)
          └─ FeedinTierRow[] (tier-based charges, empty for now)
              ↓
        Accumulate by contract_type (fixed/variable)
              ↓
        write_or_merge_parquet() with deduplication
              ↓
        Parquet files (append-safe, idempotent)


## Key Design Principles

### 1. Immutable Snapshots
Each parquet row includes snapshot_month, representing a point-in-time
capture of contracts. Running the pipeline twice on the same month will
produce identical results due to contract_key design and deduplication.

### 2. Separate Fixed/Variable Contracts
Fixed and variable contracts have fundamentally different semantics:
- Fixed: tariffs locked for contract duration → period="year"
- Variable: tariffs vary by month → period="YYYY-MM"

They are stored in separate parquet files (contracts_fixed.parquet,
contracts_variable.parquet) and linked usage tables, making it easier
for calculation engines to apply different rate logic.

### 3. Schema Alignment & Deduplication
The write_or_merge_parquet() function:
  1. Loads existing parquet (if any)
  2. Concatenates with new rows
  3. Deduplicates using natural keys (contract_key + commodity + direction, etc.)
  4. Overwrites file atomically

This ensures idempotent reruns without duplicate accumulation.

### 4. Extensible Structure for Feed-In
Contract rows include:
  - has_feed_in_tariff: boolean flag
  - has_feedin_tiers: boolean flag

Usage rows have direction="import" now, but can extend to "feed_in".
Feedin tier tables exist with full schema but may be empty initially.
Adding feed-in support later requires only new input data parsing,
not schema changes.


# =============================================================================
# MODULE BREAKDOWN
# =============================================================================

## Data Classes (Type Safety)

  ContractRow         → One row per contract snapshot
  UsageRow            → One row per tariff band (commodity + direction + band)
  FeeRow              → One row per fee component (supplier fee, etc.)
  FeedinTierRow       → One row per tier (extensible, empty for now)
  ParsedMonth         → Normalized YYYY-MM representation
  TransformationResult → Container for all rows from one raw contract


## Parsing Layer

  parse_json_file(filepath)
    Load and validate JSON structure

  infer_snapshot_month(raw_record, filepath)
    Extract month from _month_idx or filename
    Priority: _month_idx > filename > error

  parse_dutch_decimal(value_str)
    Handle Dutch locale: "108,9000" → Decimal(108.9)

  parse_dutch_month(month_str)
    "augustus 2025" → ParsedMonth(2025, 8)

  classify_contract_type(contract_duration)
    "Vast (3 jaar)" → "fixed"
    "Variabel (onbepaald)" → "variable"

  parse_duration_months(contract_duration)
    "Vast (3 jaar)" → 36
    "Variabel (onbepaald)" → None

  generate_contract_key(...)
    provider_id | contract_type | meter_type | contract_name_slug | snapshot_month
    Example: "anwb_energie|fixed|double|modelcontract|2025-08"


## Transformation Layer

  transform_contract(raw_record, filepath)
    Main orchestrator for one contract.
    
    Steps:
    1. Validate required fields
    2. Infer and normalize metadata
    3. Generate stable contract_key
    4. Create ContractRow (metadata)
    5. Parse electricity tariffs (if present)
       - Fixed yearly fee
       - Variable piek_per_kwh (single meter)
       - Variable piek_per_kwh + dal_per_kwh (double meter)
    6. Parse gas tariffs (if present)
       - Fixed yearly fee
       - Variable variable_per_m3
    7. Return TransformationResult with all rows


## I/O Layer

  parse_json_file(filepath)
    Load and validate JSON

  write_or_merge_parquet(output_path, new_rows, dedup_keys)
    1. Load existing parquet (if exists)
    2. Concatenate with new rows
    3. Deduplicate by keys
    4. Write atomically
    
    Ensures idempotent operation:
    - Run 1: Creates file with N rows
    - Run 2 (same input + 0 new rows): Produces identical file
    - Run 3 (new month): Appends without duplicating old months


## Main Orchestration

  scan_input_files(input_root)
    Recursive glob for contracts_*.json

  ingest_all_contracts(input_root, output_root)
    1. Scan all JSON files
    2. For each file and record, transform and accumulate
    3. Write all parquet files
    4. Return statistics


# =============================================================================
# PARQUET SCHEMA SUMMARY
# =============================================================================

contracts_fixed.parquet         (one per unique contract snapshot)
  contract_key, provider_id, provider_name, contract_name, contract_type,
  contract_duration_label, duration_months, meter_type, has_gas,
  has_feed_in_tariff, has_feedin_tiers, snapshot_month, source_file,
  source_session_id, source_tuple_id, estimated_annual_costs, is_active

contracts_variable.parquet      (one per unique contract snapshot)
  [same schema as fixed]

fixed_usage.parquet             (rows for each tariff band per contract)
  contract_key, provider_id, snapshot_month, commodity, direction,
  tariff_band, period, rate, unit

variable_usage.parquet          (rows for each tariff band per contract)
  [same schema as fixed_usage]
  Note: period = "YYYY-MM" (not "year")

fixed_fees.parquet              (supplier fees per contract)
  contract_key, provider_id, snapshot_month, fee_component,
  amount, billing_frequency, annual_amount, unit

variable_fees.parquet           (supplier fees per contract)
  [same schema as fixed_fees]

fixed_feedin_tiers.parquet      (tier-based charges, empty initially)
  contract_key, provider_id, snapshot_month, settlement_period, basis_type,
  tier_index, tier_min_kwh, tier_max_kwh, tier_amount, unit, vat_included

variable_feedin_tiers.parquet   (tier-based charges, empty initially)
  [same schema as fixed_feedin_tiers]


# =============================================================================
# ERROR HANDLING STRATEGY
# =============================================================================

## Levels of Resilience

  1. Parsing errors (invalid JSON)
     → Log error, skip file, continue with next file

  2. Missing/invalid fields in record
     → Raise ValueError in transform_contract()
     → Caught in main loop, logged as warning, continue

  3. Malformed tariffs (null/empty values)
     → Handled gracefully; missing tariffs simply produce
       fewer rows (e.g., no fee row if fixed_yearly missing)

  4. Decimal parsing failures
     → Try to parse, catch ValueError, log warning, skip that tariff

  5. Month inference failures
     → Raise ValueError if _month_idx and filename both fail
     → Contract marked as skipped


## Logging

  INFO:  File processing, summary counts, parquet writes
  WARNING: Skipped records, malformed fields, inference fallbacks
  ERROR: File parse failures, unexpected exceptions
  DEBUG: (with --verbose) Detailed field-by-field logs


# =============================================================================
# DEDUPLICATION STRATEGY
# =============================================================================

## Primary Keys (Dedup Keys)

  contracts_fixed.parquet
    (contract_key) - must be unique per month per contract

  fixed_usage.parquet
    (contract_key, commodity, direction, tariff_band, period)
    - Same contract may have multiple rows:
      * gas + electricity
      * double meter (peak + offpeak)
      * but only one row per unique combination

  fixed_fees.parquet
    (contract_key, fee_component)
    - Same contract may have multiple fees:
      * gas_supplier_fee + electricity_supplier_fee
      * but only one per component

  fixed_feedin_tiers.parquet
    (contract_key, tier_index, settlement_period)
    - Multiple tiers per contract


## Idempotency Guarantee

If you run the pipeline twice on the same input month:
1. First run: Creates parquet with N rows
2. Second run: Loads parquet, appends same N rows, deduplicates
   by primary key, produces identical file

If you add a new month:
1. Existing months unchanged (deduplicated out)
2. New month rows added


# =============================================================================
# COMMAND-LINE USAGE
# =============================================================================

python ingest_tariffs.py \
  --input-root ./Attempt3 \
  --output-root ./Attempt3/Tariff_preprocesssing/new_organization_tariff_data/output \
  [--verbose]

Scans recursively from input-root for all contracts_*.json files.
Creates output-root if needed.
Logs progress and summary.


# =============================================================================
# TESTING STRATEGY
# =============================================================================

Each function is isolated and testable:

  Unit tests:
    - parse_dutch_decimal("108,9000") → Decimal("108.9")
    - parse_dutch_month("augustus 2025") → ParsedMonth(2025, 8)
    - classify_contract_type("Vast (3 jaar)") → "fixed"
    - normalize_provider_id("ANWB Energie") → "anwb_energie"

  Integration tests:
    - Load sample JSON, transform contract, verify all rows
    - Run pipeline on test data, verify output parquets
    - Run twice on same data, verify deduplication

  End-to-end:
    - Full pipeline with all 12 months of 2025
    - Verify parquet contents, counts, schema


# =============================================================================
# FUTURE EXTENSIONS
# =============================================================================

See EXTENSIONS.md for detailed notes on adding feed-in tariffs and tiers.

Quick summary:
1. Feed-in tariffs (export): Extend transform_contract() to parse feedin
   fields, create usage rows with direction="feed_in"

2. Feed-in tiers: Parse tier JSON, create FeedinTierRow entries

3. New commodities: Add to commodity validation, create new usage/fee rows

4. VRE (variable renewable energy) tracks: Add new column to usage rows

5. Subscription models: Add new fee_component values


"""
