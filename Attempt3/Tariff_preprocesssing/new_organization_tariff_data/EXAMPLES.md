"""
EXAMPLES: RAW DATA TRANSFORMATION

Detailed walkthrough of how raw JSON contracts become parquet rows.

"""

# =============================================================================
# EXAMPLE 1: VARIABLE SINGLE-METER CONTRACT (ALLURENERGE)
# =============================================================================

## Input: Raw JSON Record

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


## Transformation Steps

### Step 1: Parse Metadata
  provider_name = "AllureNRG"
  contract_name = "Variabele Prijs (met zonnepanelen)"
  contract_duration = "Variabel (onbepaald)"
  meter_type = "single"
  snapshot_month_raw = "augustus 2025" → ParsedMonth(2025, 8) → "2025-08"
  contract_type = "variable" (from "Variabel")
  duration_months = None (from "onbepaald")
  provider_id = "allurenerge" (normalized)

### Step 2: Generate Contract Key
  contract_key = "allurenerge|variable|single|variabele_prijs_met_zonnepanelen|2025-08"

### Step 3: Create Rows

→ contracts_variable.parquet ROW:
  {
    contract_key: "allurenerge|variable|single|variabele_prijs_met_zonnepanelen|2025-08",
    provider_id: "allurenerge",
    provider_name: "AllureNRG",
    contract_name: "Variabele Prijs (met zonnepanelen)",
    contract_type: "variable",
    contract_duration_label: "Variabel (onbepaald)",
    duration_months: null,
    meter_type: "single",
    has_gas: true,
    has_feed_in_tariff: false,
    has_feedin_tiers: false,
    snapshot_month: "2025-08",
    source_file: "contracts_augustus 2025.json",
    source_session_id: "3D71407C077544BB90D82BE71468C474-0:0",
    source_tuple_id: "8",
    estimated_annual_costs: "189",
    is_active: true,
  }

→ variable_usage.parquet ROWS (3 rows):

  Row 1 - Electricity Single Tariff:
  {
    contract_key: "allurenerge|variable|single|variabele_prijs_met_zonnepanelen|2025-08",
    provider_id: "allurenerge",
    snapshot_month: "2025-08",
    commodity: "electricity",
    direction: "import",
    tariff_band: "single",       ← single meter → single band
    period: "2025-08",           ← variable → snapshot month YYYY-MM
    rate: 0.2862,                ← piek_per_kwh parsed
    unit: "kWh",
  }

  Row 2 - Gas Tariff:
  {
    contract_key: "allurenerge|variable|single|variabele_prijs_met_zonnepanelen|2025-08",
    provider_id: "allurenerge",
    snapshot_month: "2025-08",
    commodity: "gas",
    direction: "import",
    tariff_band: "single",       ← gas always single
    period: "2025-08",           ← variable → snapshot month YYYY-MM
    rate: 1.3167,                ← variable_per_m3 parsed
    unit: "m3",
  }

→ variable_fees.parquet ROWS (2 rows):

  Row 1 - Electricity Supplier Fee:
  {
    contract_key: "allurenerge|variable|single|variabele_prijs_met_zonnepanelen|2025-08",
    provider_id: "allurenerge",
    snapshot_month: "2025-08",
    fee_component: "electricity_supplier_fee",
    amount: 363.0,               ← fixed_yearly parsed
    billing_frequency: "yearly",
    annual_amount: 363.0,
    unit: "EUR",
  }

  Row 2 - Gas Supplier Fee:
  {
    contract_key: "allurenerge|variable|single|variabele_prijs_met_zonnepanelen|2025-08",
    provider_id: "allurenerge",
    snapshot_month: "2025-08",
    fee_component: "gas_supplier_fee",
    amount: 108.9,               ← fixed_yearly parsed
    billing_frequency: "yearly",
    annual_amount: 108.9,
    unit: "EUR",
  }

→ variable_feedin_tiers.parquet ROWS:
  [empty - no feedin tier data in input]


SUMMARY for Example 1:
  - 1 contract row
  - 2 usage rows (electricity + gas)
  - 2 fee rows (electricity supplier + gas supplier)
  - 0 feedin tier rows


# =============================================================================
# EXAMPLE 2: FIXED DOUBLE-METER CONTRACT (ANWB ENERGIE)
# =============================================================================

## Input: Raw JSON Record

{
  "provider": "ANWB Energie",
  "contract_name": "Modelcontract",
  "contract_duration": "Vast (3 jaar)",
  "meter_type": "double",
  "tariffs": {
    "gas": {
      "fixed_yearly": "186,0012",
      "variable_per_m3": "6,0955"
    },
    "electricity": {
      "fixed_yearly": "186,0012",
      "piek_per_kwh": "1,5770",
      "dal_per_kwh": "1,2135"
    }
  },
  "estimated_annual_costs": "930",
  "_tupleId": "1",
  "_month_idx": "augustus 2025",
  "_session_id": "3D71407C077544BB90D82BE71468C474-0:0"
}


## Transformation Steps

### Step 1: Parse Metadata
  provider_name = "ANWB Energie"
  contract_name = "Modelcontract"
  contract_duration = "Vast (3 jaar)"
  meter_type = "double"
  snapshot_month_raw = "augustus 2025" → "2025-08"
  contract_type = "fixed" (from "Vast")
  duration_months = 36 (3 years × 12 months)
  provider_id = "anwb_energie"

### Step 2: Generate Contract Key
  contract_key = "anwb_energie|fixed|double|modelcontract|2025-08"

### Step 3: Create Rows

→ contracts_fixed.parquet ROW:
  {
    contract_key: "anwb_energie|fixed|double|modelcontract|2025-08",
    provider_id: "anwb_energie",
    provider_name: "ANWB Energie",
    contract_name: "Modelcontract",
    contract_type: "fixed",        ← fixed
    contract_duration_label: "Vast (3 jaar)",
    duration_months: 36,           ← parsed from "Vast (3 jaar)"
    meter_type: "double",
    has_gas: true,
    has_feed_in_tariff: false,
    has_feedin_tiers: false,
    snapshot_month: "2025-08",
    source_file: "contracts_augustus 2025.json",
    source_session_id: "3D71407C077544BB90D82BE71468C474-0:0",
    source_tuple_id: "1",
    estimated_annual_costs: "930",
    is_active: true,
  }

→ fixed_usage.parquet ROWS (4 rows):

  Row 1 - Electricity Peak (Piek):
  {
    contract_key: "anwb_energie|fixed|double|modelcontract|2025-08",
    provider_id: "anwb_energie",
    snapshot_month: "2025-08",
    commodity: "electricity",
    direction: "import",
    tariff_band: "peak",         ← double meter → peak band
    period: "year",              ← fixed → always "year"
    rate: 1.5770,                ← piek_per_kwh
    unit: "kWh",
  }

  Row 2 - Electricity Off-peak (Dal):
  {
    contract_key: "anwb_energie|fixed|double|modelcontract|2025-08",
    provider_id: "anwb_energie",
    snapshot_month: "2025-08",
    commodity: "electricity",
    direction: "import",
    tariff_band: "offpeak",      ← double meter → offpeak band
    period: "year",              ← fixed → always "year"
    rate: 1.2135,                ← dal_per_kwh
    unit: "kWh",
  }

  Row 3 - Gas:
  {
    contract_key: "anwb_energie|fixed|double|modelcontract|2025-08",
    provider_id: "anwb_energie",
    snapshot_month: "2025-08",
    commodity: "gas",
    direction: "import",
    tariff_band: "single",
    period: "year",              ← fixed → "year" for all
    rate: 6.0955,                ← variable_per_m3 (note: named "variable"
                                    but still stored when contract is fixed)
    unit: "m3",
  }

→ fixed_fees.parquet ROWS (2 rows):

  Row 1 - Electricity Supplier Fee:
  {
    contract_key: "anwb_energie|fixed|double|modelcontract|2025-08",
    provider_id: "anwb_energie",
    snapshot_month: "2025-08",
    fee_component: "electricity_supplier_fee",
    amount: 186.0012,            ← fixed_yearly for electricity
    billing_frequency: null,     ← null for fixed contracts
    annual_amount: null,
    unit: "EUR",
  }

  Row 2 - Gas Supplier Fee:
  {
    contract_key: "anwb_energie|fixed|double|modelcontract|2025-08",
    provider_id: "anwb_energie",
    snapshot_month: "2025-08",
    fee_component: "gas_supplier_fee",
    amount: 186.0012,            ← fixed_yearly for gas
    billing_frequency: null,     ← null for fixed contracts
    annual_amount: null,
    unit: "EUR",
  }

→ fixed_feedin_tiers.parquet ROWS:
  [empty - no feedin tier data]


SUMMARY for Example 2:
  - 1 contract row
  - 3 usage rows (electricity peak + offpeak + gas)
  - 2 fee rows (electricity supplier + gas supplier)
  - 0 feedin tier rows


# =============================================================================
# KEY OBSERVATIONS
# =============================================================================

## Meter Type Handling

  Single Meter:
    - Electricity stored as 1 row with tariff_band="single"
    - Use piek_per_kwh (column dal_per_kwh is null, ignored)

  Double Meter:
    - Electricity stored as 2 rows:
      * tariff_band="peak" with piek_per_kwh
      * tariff_band="offpeak" with dal_per_kwh

  Gas:
    - Always 1 row with tariff_band="single"
    - Uses variable_per_m3 regardless of single/double meter


## Fixed vs Variable Period Semantics

  Fixed Contracts:
    period = "year"
    → Tariffs are locked for entire contract duration
    → Calculation engine applies same rates for all months during contract

  Variable Contracts:
    period = "2025-08" (snapshot month)
    → Tariffs may change month-to-month
    → Calculation engine looks up tariff by month
    → Ingesting September 2025 will add new rows with period="2025-09"


## Deduplication Keys

  Contract-level dedup:
    contract_key = "allurenerge|variable|single|variabele_prijs_met_zonnepanelen|2025-08"
    → Unique per provider, contract name, meter type, and snapshot month
    → Re-ingesting same month produces identical key, cleaned by dedup

  Usage-level dedup (in fixed_usage.parquet):
    (contract_key, commodity, direction, tariff_band, period)
    → ANWB January 2026 peak tariff at 1.5770 (fixed, still "year")
    → If ingested twice, same primary key dedupes to 1 row

  Fee-level dedup (in fixed_fees.parquet):
    (contract_key, fee_component)
    → ANWB electricity_supplier_fee
    → If re-ingested, same key dedupes to 1 row


## NULL Handling

  dal_per_kwh = null (single meter contracts):
    → Parsed as null
    → No row created (check before parse_dutch_decimal)

  fixed_yearly = missing key (if contract has only variable):
    → Parsed as None
    → No fee row created
    → Usage row still created normally

  _month_idx = missing from record:
    → Falls back to filename extraction
    → If both fail, contract skipped with warning


# =============================================================================
# EXTENDING TO FEED-IN TARIFFS (FUTURE)
# =============================================================================

When feed-in data arrives, expected raw input:

{
  "provider": "AllureNRG",
  "contract_name": "With Solar Feed-In",
  "contract_duration": "Variable",
  "meter_type": "single",
  "tariffs": {
    "electricity": {
      "fixed_yearly": "120,00",
      "piek_per_kwh": "0,28",
      "dal_per_kwh": null,
      "feed_in_tariff": "0,085"     ← NEW
    },
    "gas": { ... }
  },
  "feedin_tiers": {                  ← NEW
    "monthly": [
      {
        "tier_min_kwh": 0,
        "tier_max_kwh": 100,
        "tier_amount": "0,10"
      },
      {
        "tier_min_kwh": 100,
        "tier_max_kwh": null,
        "tier_amount": "0,08"
      }
    ]
  },
  ...
}

Transformation:
  1. Check for feed_in_tariff in tariffs.electricity
  2. If present, create UsageRow with direction="feed_in"
  3. Parse feedin_tiers array (if present)
  4. Create FeedinTierRow entries
  5. Set has_feed_in_tariff=true, has_feedin_tiers=true in contracts row


"""
