#!/usr/bin/env python3
"""
Inspect Budget Energie key generation with the current snapshot/base-key model.
"""

from collections import defaultdict
from pathlib import Path
import importlib.util
import json
import sys


def load_ingest_module():
    script_path = Path(__file__).parent / "ingest_tariffs.py"
    spec = importlib.util.spec_from_file_location("budget_key_ingest", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.load_contract_reference_data()
    return module


INGEST = load_ingest_module()


with open(Path(__file__).parent / "contracts.json", "r", encoding="utf-8") as handle:
    data = json.load(handle)

budget_contracts = data["Budget Energie"]
grouped = defaultdict(list)

for contract_name in budget_contracts:
    normalized = INGEST.normalize_contract_name("Budget Energie", contract_name)
    grouped[normalized.contract_base_key].append(
        {
            "raw_contract_name": contract_name,
            "contract_name_no_variant": normalized.contract_name_no_variant,
            "contract_base_name": normalized.contract_base_name,
            "variant": normalized.variant,
        }
    )

print("BUDGET ENERGIE BASE KEY GROUPS")
print("=" * 80)
print()

for contract_base_key in sorted(grouped.keys()):
    print(f"Base key: {contract_base_key}")
    for row in sorted(grouped[contract_base_key], key=lambda item: item["raw_contract_name"]):
        print(f"  Raw:      {row['raw_contract_name']}")
        print(f"  NoVariant:{row['contract_name_no_variant']}")
        print(f"  Base:     {row['contract_base_name']}")
        print(f"  Variant:  {row['variant']}")
    print()
