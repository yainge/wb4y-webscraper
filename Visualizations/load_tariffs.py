from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Any, Tuple
import pandas as pd
import re
from functools import lru_cache


@dataclass
class Tariff:
    provider: str
    contract_type: str
    price_eur_per_kwh: float
    monthly_cost_eur: float
    feed_in_specific: Optional[str] = None
    feed_in_eur_per_kwh: float = 0.0
    gas_price_eur_per_m3: float = 0.0
    monthly_gas_cost_eur: float = 0.0
    duration: Optional[str] = None
    deeplink: Optional[str] = None


@dataclass
class TariffBook:
    providers: Dict[str, Dict[str, Tariff]] = field(default_factory=dict)

    def get(self, provider: str, contract_type: str) -> Optional[Tariff]:
        pkey = normalize_name(provider)
        ckey = normalize_contract(contract_type)
        return self.providers.get(pkey, {}).get(ckey)


REQUIRED_COLS = [
    "Company name",
    "Contract type",
    "Electricity price",
    "Monthly Cost",
]


def normalize_name(name: str) -> str:
    return (name or "").strip().lower()


def normalize_contract(contract: str) -> str:
    val = (contract or "").strip().lower()
    mapping = {
        "vast": "fixed",
        "fixed": "fixed",
        "dynamisch": "dynamic",
        "dynamic": "dynamic",
        "variable": "variable",
        "variabel": "variable",
    }
    return mapping.get(val, val)


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if parent.name == "backend":
            # Use backend folder so relative paths hit backend/data/*
            return parent
    return here.parents[3]


# -------------------- Grid tariffs (CSV) --------------------
GRID_DEFAULT_COST = 476.25  # fallback when DSO unknown or value missing
GRID_DEFAULT_COST_GAS_1 = 160.00  # fallback gas grid cost
GRID_DEFAULT_COST_GAS_2 = 280.00
GRID_DEFAULT_COST_GAS_3 = 400.00
GRID_CSV_RELATIVE = Path("data") / "grid" / "grid_tariffs.csv"


def _clean_postal_code(pc: str) -> Optional[str]:
    if not pc:
        return None
    match = re.match(r"^\s*([0-9]{4})", str(pc))
    return match.group(1) if match else None


def _clean_grid_fee(val: Any) -> Optional[float]:
    if val is None:
        return None
    txt = str(val).strip()
    if not txt or txt == "#N/A":
        return None
    # remove currency symbols and thousand separators, use dot decimal
    txt = txt.replace("€", "").replace(" ", "").replace(",", ".")
    try:
        return float(txt)
    except Exception:
        return None


@lru_cache(maxsize=1)
def load_grid_tariffs(csv_path: Optional[Path] = None) -> Dict[str, float]:
    """
    Load grid tariffs keyed by 4-digit postal code.
    Rows with DSO == 'Onbekend' or fee == '#N/A' are ignored.
    """
    if csv_path is None:
        csv_path = _repo_root() / GRID_CSV_RELATIVE
    if not csv_path.exists():
        # Return empty to fall back to default
        return {}
    try:
        df = pd.read_csv(csv_path, encoding="latin1")
    except UnicodeDecodeError:
        df = pd.read_csv(csv_path, encoding="utf-8", errors="ignore")
    needed = {"Postcode", "DSO", "Electricity fee"}
    if not needed.issubset(set(df.columns)):
        return {}
    mapping: Dict[str, float] = {}
    for _, row in df.iterrows():
        dso = str(row.get("DSO", "")).strip()
        elec_fee = _clean_grid_fee(row.get("Electricity fee"))
        pc = _clean_postal_code(str(row.get("Postcode", "")))
        if not pc:
            continue
        if dso.lower() == "onbekend" or elec_fee is None:
            continue
        mapping[pc] = elec_fee
    return mapping



@lru_cache(maxsize=1)
def load_grid_gas_tiers(csv_path: Optional[Path] = None) -> Dict[str, Tuple[float, float, float]]:
    """Load gas-tier prices keyed by 4-digit postal code.

    Returns mapping: {postcode4: (tier1_price, tier2_price, tier3_price)}.
    Tier columns are detected by looking for any column with 'gas' in the header
    (case-insensitive). If multiple found, the first three are used. Missing
    tier values fall back to the GRID_DEFAULT_COST_GAS_* constants.
    """
    if csv_path is None:
        csv_path = _repo_root() / GRID_CSV_RELATIVE
    if not csv_path.exists():
        return {}
    try:
        df = pd.read_csv(csv_path, encoding="latin1")
    except UnicodeDecodeError:
        df = pd.read_csv(csv_path, encoding="utf-8", errors="ignore")

    cols = list(df.columns)
    if not {"Postcode", "DSO", "Electricity fee"}.issubset(set(cols)):
        return {}

    # find gas-related columns (in order)
    gas_cols = [c for c in cols if "gas" in str(c).lower()]

    mapping: Dict[str, Tuple[float, float, float]] = {}
    for _, row in df.iterrows():
        dso = str(row.get("DSO", "")).strip()
        pc = _clean_postal_code(str(row.get("Postcode", "")))
        if not pc:
            continue
        # skip rows invalid for electricity as before
        elec_fee = _clean_grid_fee(row.get("Electricity fee"))
        if dso.lower() == "onbekend" or elec_fee is None:
            continue

        # collect up to three tier values
        tiers = []
        for i in range(3):
            if i < len(gas_cols):
                val = _clean_grid_fee(row.get(gas_cols[i]))
                if val is None:
                    # fallback to default per-tier
                    val = [GRID_DEFAULT_COST_GAS_1, GRID_DEFAULT_COST_GAS_2, GRID_DEFAULT_COST_GAS_3][i]
            else:
                val = [GRID_DEFAULT_COST_GAS_1, GRID_DEFAULT_COST_GAS_2, GRID_DEFAULT_COST_GAS_3][i]
            tiers.append(float(val))

        mapping[pc] = (tiers[0], tiers[1], tiers[2])

    return mapping


def grid_cost_for_postal(postal_code: str, table: Optional[Dict[str, float]] = None) -> float:
    """Return electricity grid cost (single float) for a postal code.

    Backwards-compatible: if `table` contains tuples/lists, the first element
    is used as the electricity fee.
    """
    table = table or load_grid_tariffs()
    pc = _clean_postal_code(postal_code or "")
    if not pc:
        return GRID_DEFAULT_COST
    val = table.get(pc, GRID_DEFAULT_COST)
    if isinstance(val, (list, tuple)):
        # defensive: use first entry as electricity fee
        val = val[0] if val else GRID_DEFAULT_COST
    try:
        return float(val)
    except Exception:
        return GRID_DEFAULT_COST


def grid_gas_tiers_for_postal(postal_code: str, table: Optional[Dict[str, Tuple[float, float, float]]] = None) -> Tuple[float, float, float]:
    """Return gas tier prices (tier1,tier2,tier3) for a postal code.

    Falls back to `GRID_DEFAULT_COST_GAS_*` when missing.
    """
    table = table or load_grid_gas_tiers()
    pc = _clean_postal_code(postal_code or "")
    if not pc:
        return (GRID_DEFAULT_COST_GAS_1, GRID_DEFAULT_COST_GAS_2, GRID_DEFAULT_COST_GAS_3)
    vals = table.get(pc)
    if not vals:
        return (GRID_DEFAULT_COST_GAS_1, GRID_DEFAULT_COST_GAS_2, GRID_DEFAULT_COST_GAS_3)
    try:
        return (float(vals[0]), float(vals[1]), float(vals[2]))
    except Exception:
        return (GRID_DEFAULT_COST_GAS_1, GRID_DEFAULT_COST_GAS_2, GRID_DEFAULT_COST_GAS_3)


def load_provider_tariffs(xlsx_path: Optional[Path] = None) -> TariffBook:
    """
    Load provider tariffs from the Excel sheet backend/data/provider_tariffs/provider_tariffs.xlsx.

    Expected columns (case-sensitive):
      - Company name
      - Contract type
      - Electricity price
      - Monthly Cost
      - Feed in specific (optional)
      - Feed-in (optional)
      - Gas price (optional)
      - Monthly gas cost (optional)
      - Duration (optional)
    """
    if xlsx_path is None:
        xlsx_path = _repo_root() / "data" / "provider_tariffs" / "provider_tariffs.xlsx"
    if not xlsx_path.exists():
        raise FileNotFoundError(f"Tariff file not found at {xlsx_path}")

    df = pd.read_excel(xlsx_path)
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"Tariff file missing columns: {missing}")

    book = TariffBook()
    for _, row in df.iterrows():
        provider = str(row.get("Company name", "")).strip()
        if not provider:
            continue
        contract_type = normalize_contract(row.get("Contract type", ""))
        price = _safe_float(row.get("Electricity price"))
        monthly = _safe_float(row.get("Monthly Cost"))
        feed_in = _safe_float(row.get("Feed-in"))
        gas_price = _safe_float(row.get("Gas price"))
        monthly_gas_cost = _safe_float(row.get("Monthly gas cost"))
        deeplink = _safe_str(row.get("Deeplink"))
        tariff = Tariff(
            provider=provider,
            contract_type=contract_type,
            price_eur_per_kwh=price,
            monthly_cost_eur=monthly,
            feed_in_eur_per_kwh=feed_in,
            feed_in_specific=_safe_str(row.get("Feed in specific")),
            duration=_safe_str(row.get("Duration")),
            gas_price_eur_per_m3=gas_price,
            monthly_gas_cost_eur=monthly_gas_cost,
            deeplink=deeplink,
        )
        pkey = normalize_name(provider)
        ckey = contract_type
        book.providers.setdefault(pkey, {})[ckey] = tariff
    return book


def _safe_float(val: Any) -> float:
    try:
        if pd.isna(val):
            return 0.0
    except Exception:
        pass
    try:
        return float(str(val).replace("€", "").strip())
    except Exception:
        return 0.0


def _safe_str(val: Any) -> Optional[str]:
    if val is None:
        return None
    text = str(val).strip()
    return text or None
