from __future__ import annotations

import re

import structlog

logger = structlog.get_logger()

# ── Dutch column name → canonical field ──────────────────────────────────────
# Multiple Dutch names can map to the same canonical field.
COLUMN_MAP: dict[str, str] = {
    # Provider
    "leverancier": "provider_name",
    "aanbieder": "provider_name",
    "energieleverancier": "provider_name",
    # Contract name
    "contractnaam": "contract_name",
    "product": "contract_name",
    "productnaam": "contract_name",
    "naam product": "contract_name",
    # Contract type
    "contracttype": "contract_type",
    "contractsoort": "contract_type",
    "type contract": "contract_type",
    "soort contract": "contract_type",
    # Tariff / price value
    "tarief": "value",
    "prijs": "value",
    "variabel leveringstarief": "value",
    "leveringstarief": "value",
    "tarief (eur/kwh)": "value",
    "tarief (eur/m3)": "value",
    "tarief (€/kwh)": "value",
    "tarief (€/m3)": "value",
    # Commodity
    "energiesoort": "commodity",
    "commodity": "commodity",
    "product type": "commodity",
    # Date / validity
    "peildatum": "valid_from",
    "datum": "valid_from",
    "ingangsdatum": "valid_from",
    "maand": "valid_from",
    "startdatum": "valid_from",
    # Fixed costs
    "vaste kosten": "fixed_cost_value",
    "vastrecht": "fixed_cost_value",
    "vaste leveringskosten": "fixed_cost_value",
    "vaste kosten (eur/maand)": "fixed_cost_value",
    "vaste kosten (€/maand)": "fixed_cost_value",
    # Unit
    "eenheid": "unit_raw",
}

# ── Contract type normalization (Dutch → canonical) ──────────────────────────
CONTRACT_TYPE_MAP: dict[str, str] = {
    "variabel": "variable",
    "vast": "fixed",
    "dynamisch": "dynamic",
    "modelcontract": "model",
    "model": "model",
    "hybride": "hybrid",
    "hybrid": "hybrid",
}

# ── Commodity normalization ──────────────────────────────────────────────────
COMMODITY_MAP: dict[str, str] = {
    "elektriciteit": "electricity",
    "stroom": "electricity",
    "electricity": "electricity",
    "gas": "gas",
    "aardgas": "gas",
    "stadswarmte": "district_heating",
    "warmte": "district_heating",
    "district_heating": "district_heating",
}


def map_columns(raw_columns: list[str]) -> dict[str, str]:
    """Map raw DataFrame column names → canonical fields. Unmapped columns are skipped."""
    result: dict[str, str] = {}
    for col in raw_columns:
        key = col.strip().lower()
        canonical = COLUMN_MAP.get(key)
        if canonical:
            result[col] = canonical
        else:
            cleaned = _strip_tableau_wrappers(key)
            canonical = COLUMN_MAP.get(cleaned)
            if canonical:
                result[col] = canonical
            else:
                logger.debug("unmapped_column", raw=col, cleaned=cleaned)
    return result


def normalize_contract_type(raw: str) -> str:
    key = raw.strip().lower()
    return CONTRACT_TYPE_MAP.get(key, "unknown")


def normalize_commodity(raw: str) -> str:
    key = raw.strip().lower()
    return COMMODITY_MAP.get(key, key)


def infer_tou_from_columns(col_name: str) -> str:
    """Infer time-of-use (peak/off-peak) from column naming patterns."""
    lower = col_name.lower()
    if any(k in lower for k in ("hoog", "piek", "normaal", "enkel")):
        return "on_peak"
    if any(k in lower for k in ("laag", "dal", "nacht")):
        return "off_peak"
    return "flat"


def infer_meter_direction(col_name: str, value_context: str = "") -> str:
    """Infer meter direction from column/context."""
    lower = (col_name + " " + value_context).lower()
    if any(k in lower for k in ("teruglevering", "teruglever", "feed-in", "saldering", "terugleveren")):
        return "feed_in"
    return "consumption"


def _strip_tableau_wrappers(s: str) -> str:
    """Remove ATTR(...), SUM(...), AGG(...) wrappers from Tableau field names."""
    match = re.match(r"^(?:attr|sum|agg|avg|min|max)\((.+)\)$", s, re.IGNORECASE)
    return match.group(1).strip() if match else s
