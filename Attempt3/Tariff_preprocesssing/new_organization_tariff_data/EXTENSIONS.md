"""
EXTENSIONS: FEED-IN TARIFFS AND TIER CHARGES

Detailed guide for adding production support for feed-in tariffs and
tiered rates when raw data becomes available.

"""

# =============================================================================
# OVERVIEW
# =============================================================================

Current state (as of deployment):
  - Import-only tariffs (consumption)
  - No feed-in tariff rates
  - No tiered rate structures

Future state (when data arrives):
  - Add feed_in_tariff field to electricity tariffs
  - Add feedin_tiers array with tier-based rates
  - Possibly add gas feed-in (unlikely for residential)


Design principle:
  The existing code is architected to support these extensions with
  MINIMAL changes. The dataclasses, schemas, and transformation logic
  are extensible by design.


# =============================================================================
# ADDING FEED-IN TARIFF (LEVEL 1: SIMPLE RATE)
# =============================================================================

When raw JSON begins to include:

{
  "tariffs": {
    "electricity": {
      ...,
      "feed_in_tariff": "0,085"   ← NEW FIELD
    }
  }
}


Changes required:

### Step 1: Update raw record parsing in transform_contract()

  In the "Process electricity tariffs" section, add:

    # Feed-in rate (opposite direction of import)
    feed_in_rate = elec_tariffs.get("feed_in_tariff")
    if feed_in_rate is not None and feed_in_rate != "":
        try:
            rate = parse_dutch_decimal(feed_in_rate)
            period = snapshot_month.yyyy_mm if contract_type == "variable" else "year"
            usage_rows.append(UsageRow(
                contract_key=contract_key,
                provider_id=provider_id,
                snapshot_month=snapshot_month.yyyy_mm,
                commodity="electricity",
                direction="feed_in",        ← KEY: different direction
                tariff_band="single",       ← or peak/offpeak if double meter
                period=period,
                rate=rate,
                unit="kWh",
            ))
        except ValueError as e:
            logger.warning(f"Could not parse electricity feed_in_tariff '{feed_in_rate}': {e}")


### Step 2: Update deduplication logic in write_or_merge_parquet()

  The existing usage row dedup key is already extensible:
    (contract_key, commodity, direction, tariff_band, period)

  Adding direction="feed_in" rows will naturally deduplicate
  separately from direction="import" rows. No changes needed.


### Step 3: Update contract row has_feed_in_tariff flag

  In transform_contract(), after parsing all tariffs:

    # Determine if contract has feed-in capability
    has_feed_in = False
    if has_electricity:
        elec_tariffs = tariffs["electricity"]
        if elec_tariffs.get("feed_in_tariff"):
            has_feed_in = True

    ... then use has_feed_in when creating contract_row:

    contract_row = ContractRow(
        ...,
        has_feed_in_tariff=has_feed_in,
        ...
    )


### Step 4: Testing

  Run ingest_tariffs.py on test JSON with feed_in_tariff fields.
  Verify:
    - variable_usage.parquet includes direction="feed_in" rows
    - Deduplication works correctly
    - contract_row.has_feed_in_tariff = true


Full code diff (pseudo):

  # in transform_contract(), electricity section:
  
  # Fixed component (fee)
  fixed_yearly = ...
  
  # Import usage
  if meter_type == "single":
      piek = ...
      
  # >> NEW: Feed-in usage
  # >> Feed-in is exported energy (household to grid)
  feed_in_rate = elec_tariffs.get("feed_in_tariff")
  if feed_in_rate is not None and feed_in_rate != "":
      try:
          rate = parse_dutch_decimal(feed_in_rate)
          period = snapshot_month.yyyy_mm if contract_type == "variable" else "year"
          usage_rows.append(UsageRow(
              contract_key=contract_key,
              provider_id=provider_id,
              snapshot_month=snapshot_month.yyyy_mm,
              commodity="electricity",
              direction="feed_in",
              tariff_band="single",  # or peak/offpeak for double meter
              period=period,
              rate=rate,
              unit="kWh",
          ))
      except ValueError as e:
          logger.warning(f"Could not parse electricity feed_in_tariff '{feed_in_rate}': {e}")



# =============================================================================
# ADDING FEED-IN TIERS (LEVEL 2: TIERED RATES)
# =============================================================================

When raw JSON includes:

{
  "feedin_tiers": {
    "monthly": [
      {
        "tier_min_kwh": 0,
        "tier_max_kwh": 100,
        "tier_amount": "0,10",
        "settlement_period": "monthly",
        "basis_type": "net_production"
      },
      {
        "tier_min_kwh": 100,
        "tier_max_kwh": null,
        "tier_amount": "0,08",
        "settlement_period": "monthly",
        "basis_type": "net_production"
      }
    ]
  }
}


Changes required:

### Step 1: Add helper function to parse tiers

  def parse_feedin_tiers(
      raw_tiers: Dict[str, List[Dict[str, Any]]],
      contract_key: str,
      provider_id: str,
      snapshot_month: str,
  ) -> List[FeedinTierRow]:
      """
      Parse nested tier structure into FeedinTierRow instances.
      
      Handles multiple tier definitions (monthly, quarterly, etc.).
      """
      result = []
      
      for period_key, tiers_list in raw_tiers.items():
          if not isinstance(tiers_list, list):
              logger.warning(f"Expected tier list, got {type(tiers_list).__name__}")
              continue
          
          for tier_index, tier_obj in enumerate(tiers_list):
              try:
                  tier_min = tier_obj.get("tier_min_kwh")
                  tier_max = tier_obj.get("tier_max_kwh")
                  tier_amount_str = tier_obj.get("tier_amount")
                  
                  if tier_amount_str is None or tier_amount_str == "":
                      logger.warning(f"Skipping tier {tier_index}: no tier_amount")
                      continue
                  
                  tier_amount = parse_dutch_decimal(tier_amount_str)
                  
                  # Parse min/max if present
                  tier_min_decimal = None
                  if tier_min is not None:
                      tier_min_decimal = Decimal(str(tier_min))
                  
                  tier_max_decimal = None
                  if tier_max is not None:
                      tier_max_decimal = Decimal(str(tier_max))
                  
                  row = FeedinTierRow(
                      contract_key=contract_key,
                      provider_id=provider_id,
                      snapshot_month=snapshot_month,
                      settlement_period=period_key,  # "monthly", "quarterly", etc.
                      basis_type=tier_obj.get("basis_type", "net_production"),
                      tier_index=tier_index,
                      tier_min_kwh=tier_min_decimal,
                      tier_max_kwh=tier_max_decimal,
                      tier_amount=tier_amount,
                      unit="EUR/kWh",
                      vat_included=tier_obj.get("vat_included", False),
                  )
                  result.append(row)
              
              except (ValueError, KeyError) as e:
                  logger.warning(f"Could not parse tier {tier_index}: {e}")
                  continue
      
      return result


### Step 2: Integrate into transform_contract()

  In the main function, after parsing electricity tariffs:

    # Parse feed-in tiers if present
    feedin_tier_rows = []
    raw_feedin_tiers = raw_record.get("feedin_tiers", {})
    if raw_feedin_tiers and isinstance(raw_feedin_tiers, dict):
        feedin_tier_rows = parse_feedin_tiers(
            raw_feedin_tiers,
            contract_key,
            provider_id,
            snapshot_month.yyyy_mm,
        )


### Step 3: Update contract row flag

    has_feedin_tiers = len(feedin_tier_rows) > 0
    
    ... pass to contract_row:
    
    contract_row = ContractRow(
        ...,
        has_feedin_tiers=has_feedin_tiers,
        ...
    )


### Step 4: Return feedin_tier_rows via TransformationResult

    return TransformationResult(
        contract_row=contract_row,
        usage_rows=usage_rows,
        fee_rows=fee_rows,
        feedin_tier_rows=feedin_tier_rows,  ← Already in the dataclass
    )


### Step 5: Accumulate and write in main pipeline

  In ingest_all_contracts(), the feedin_tier_rows are already
  accumulated. Just ensure write_or_merge_parquet is called:

    # Variable feedin tiers
    write_or_merge_parquet(
        output_root / "variable_feedin_tiers.parquet",
        variable_feedin_tiers,  ← Already accumulated
        FeedinTierRow,
        get_feedin_tiers_schema(),
        dedup_keys=["contract_key", "tier_index", "settlement_period"],
    )


### Output Example

After parsing ANWB contract with tiers, variable_feedin_tiers.parquet:

  {
    contract_key: "anwb_energie|variable|single|with_solar|2025-08",
    provider_id: "anwb_energie",
    snapshot_month: "2025-08",
    settlement_period: "monthly",
    basis_type: "net_production",
    tier_index: 0,
    tier_min_kwh: 0,
    tier_max_kwh: 100,
    tier_amount: 0.10,
    unit: "EUR/kWh",
    vat_included: false,
  },
  {
    contract_key: "anwb_energie|variable|single|with_solar|2025-08",
    provider_id: "anwb_energie",
    snapshot_month: "2025-08",
    settlement_period: "monthly",
    basis_type: "net_production",
    tier_index: 1,
    tier_min_kwh: 100,
    tier_max_kwh: null,
    tier_amount: 0.08,
    unit: "EUR/kWh",
    vat_included: false,
  }




# =============================================================================
# ADDING GAS FEED-IN (LEVEL 3: BIO-METHANE, UNLIKELY)
# =============================================================================

If residential contracts ever support gas feed-in (bio-methane injection),
follow the same pattern:

1. Extend parse for tariffs.gas.feed_in_rate
2. Create usage rows with:
   - commodity="gas"
   - direction="feed_in"
   - tariff_band="single"
3. Update contract_row.has_feed_in_tariff if gas feed-in present
4. Parsing logic is identical to electricity feed-in


# =============================================================================
# ADDING NEW COMMODITIES (e.g., HYDROGEN, HEAT)
# =============================================================================

To support additional commodities:

1. Update validate section in transform_contract():
   - Add new commodity to validation
   - Example: "hydrogen" in tariffs and isinstance(..., dict)

2. Create parsing block for new commodity:
   - Follow same pattern as electricity/gas
   - Extract fixed_yearly as fee
   - Extract variable_per_unit as usage rate
   - Determine appropriate unit ("kg", "MWh", etc.)

3. Update schemas (if new unit types:
   - get_usage_schema() unit field is already string-typed
   - get_fees_schema() unit field is already string-typed

4. No changes to main orchestration


Example for Hydrogen:

    if has_hydrogen:
        hydrogen_tariffs = tariffs["hydrogen"]
        
        fixed_yearly = hydrogen_tariffs.get("fixed_yearly")
        if fixed_yearly is not None and fixed_yearly != "":
            try:
                rate = parse_dutch_decimal(fixed_yearly)
                fee_rows.append(FeeRow(..., fee_component="hydrogen_supplier_fee", ...))
            except ValueError as e:
                logger.warning(f"Could not parse hydrogen fixed_yearly: {e}")
        
        variable_per_kg = hydrogen_tariffs.get("variable_per_kg")
        if variable_per_kg is not None and variable_per_kg != "":
            try:
                rate = parse_dutch_decimal(variable_per_kg)
                period = snapshot_month.yyyy_mm if contract_type == "variable" else "year"
                usage_rows.append(UsageRow(
                    ...,
                    commodity="hydrogen",
                    tariff_band="single",
                    period=period,
                    rate=rate,
                    unit="kg",
                ))
            except ValueError as e:
                logger.warning(f"Could not parse hydrogen variable_per_kg: {e}")


# =============================================================================
# ADDING CONTRACT VARIANT METADATA
# =============================================================================

If contracts later include subscription models (e.g., "Pro", "Plus"):

1. Extend raw record to include variant field
2. Add to contract_key generation (already possible, extend slug)
3. Add to contracts.parquet schema:
   - contract_variant: optional string
4. Parse and store in ContractRow


# =============================================================================
# ERROR RECOVERY STRATEGIES
# =============================================================================

When adding new fields, ensure backward compatibility:

1. Existing fields are optional (use .get() with defaults)
2. Missing feed-in data doesn't break pipeline
3. Malformed tier structures are logged, not fatal
4. Unknown tier settlement periods are parsed verbatim

Forward-looking changes:

1. New schema columns should always be nullable
2. Default values should be sensible (False, 0, null, empty string)
3. Document the default behavior clearly
4. Write integration tests for backward compatibility


# =============================================================================
# RECOMMENDATION: INCREMENTAL ROLLOUT
# =============================================================================

When feed-in data first arrives:

Phase 1 (Day 1):
  1. Add feed_in_tariff parsing (Level 1)
  2. Test on sample data
  3. Deploy write-only (don't change existing files)

Phase 2 (Week 1):
  1. Full ingestion with feed-in rows
  2. Validate calculation engine can handle new direction="feed_in" rows
  3. Monitor for issues

Phase 3 (Month 1):
  1. Add feed-in tiers parsing (Level 2)
  2. Repeat test/deploy cycle

Phase 4 (Ongoing):
  1. Monitor for new fields or structures
  2. Adjust parsing as needed
  3. Maintain backward compatibility


# =============================================================================
# TESTING CHECKLIST FOR EXTENSIONS
# =============================================================================

[] Parse unit tests for new fields
[] Transform test: single contract with new data → all rows generated
[] Schema test: parquet columns match expected types
[] Deduplication test: run twice, verify no duplicates
[] Integration test: full pipeline with mixed old/new contracts
[] Edge cases: null/empty values, missing optional fields
[] Migration test: ingestion with old data, then new data, mixed month
[] Logging test: warnings logged for malformed new data, no crashes


"""
