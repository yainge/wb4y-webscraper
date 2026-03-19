"""Extract and parse contract variants from Budget Energie and similar contracts.

Budget Energie contracts follow this pattern:
  "Groene Stroom en Aardgas 1 Jaar Vast A"
  └─ Base name: "Groene Stroom en Aardgas 1 Jaar Vast"
  └─ Variant: "A"

This module provides utilities to:
  1. Extract trailing variant codes (letters, special codes)
  2. Generate slugs from base contract names
  3. Keep variant separate for deduplication/grouping
"""

import re
from typing import Optional, Tuple
from dataclasses import dataclass


@dataclass
class ParsedContractName:
    """Result of parsing a contract name."""
    base_name: str
    """The contract name without the variant."""
    slug: str
    """URL-safe slug of the base name."""
    variant: Optional[str]
    """Extracted variant (letter, code, etc.), or None if not found."""
    original: str
    """Original input contract name."""


def extract_variant(contract_name: str) -> Tuple[str, Optional[str]]:
    """Extract trailing variant from contract name.
    
    Variants are typically:
      - Single letters: A, B, C, ... Z
      - Special codes: BAT, ACQ, AFL
      - Numbers with units: 1 jaar, 2 jaar, 3 jaar (preserved as part of name, not variant)
    
    Args:
        contract_name: Full contract name (e.g., "Groene Stroom en Aardgas 1 Jaar Vast A")
    
    Returns:
        Tuple of (base_name, variant):
          - base_name: Contract name without variant
          - variant: Extracted variant, or None if no variant found
    
    Examples:
        >>> extract_variant("Groene Stroom en Aardgas 1 Jaar Vast A")
        ("Groene Stroom en Aardgas 1 Jaar Vast", "A")
        
        >>> extract_variant("Groene Stroom en Aardgas 1 Jaar Vast BAT")
        ("Groene Stroom en Aardgas 1 Jaar Vast", "BAT")
        
        >>> extract_variant("Nederlandse Wind Stroom Variabel ACQ Flexibele looptijd")
        ("Nederlandse Wind Stroom Variabel Flexibele looptijd", "ACQ")
        
        >>> extract_variant("Modelcontract")
        ("Modelcontract", None)
    
    Note:
        Duration (1 jaar, 2 jaar, etc.) is NOT treated as a variant.
        Only trailing single-letter or special code variants are extracted.
    """
    contract_name = contract_name.strip()
    
    # Pattern: optional spaces + variant (1-3 letters) at the end
    # Variants: A-Z or special codes like BAT, ACQ, AFL
    match = re.match(r'^(.+?)\s+([A-Z]{1,3})$', contract_name)
    
    if match:
        base = match.group(1).strip()
        variant = match.group(2)
        return base, variant
    
    return contract_name, None


def contract_name_slug(name: str) -> str:
    """Generate URL-safe slug from contract name.
    
    Transformations:
      1. Convert to lowercase
      2. Replace spaces with underscores
      3. Remove parentheses
    
    Args:
        name: Contract name (typically the base name without variant)
    
    Returns:
        URL-safe slug
    
    Examples:
        "Groene Stroom en Aardgas 1 Jaar Vast" → "groene_stroom_en_aardgas_1_jaar_vast"
        "Nederlandse Wind Stroom en CO2-gecompenseerd Gas" → "nederlandse_wind_stroom_en_co2-gecompenseerd_gas"
    """
    return name.lower().replace(" ", "_").replace("(", "").replace(")", "")


def parse_contract_name(contract_name: str) -> ParsedContractName:
    """Parse a contract name into base, slug, and variant.
    
    Args:
        contract_name: Full contract name
    
    Returns:
        ParsedContractName with separate base, slug, variant fields
    
    Example:
        >>> result = parse_contract_name("Groene Stroom en Aardgas 1 Jaar Vast A")
        >>> result.base_name
        'Groene Stroom en Aardgas 1 Jaar Vast'
        >>> result.slug
        'groene_stroom_en_aardgas_1_jaar_vast'
        >>> result.variant
        'A'
    """
    base_name, variant = extract_variant(contract_name)
    slug = contract_name_slug(base_name)
    
    return ParsedContractName(
        base_name=base_name,
        slug=slug,
        variant=variant,
        original=contract_name
    )


# Example: Budget Energie contracts
BUDGET_ENERGIE_CONTRACTS = [
    "Groene Stroom en Aardgas 1 Jaar Vast A",
    "Groene Stroom en Aardgas 1 Jaar Vast B",
    "Groene Stroom en Aardgas 1 Jaar Vast BAT",
    "Groene Stroom en Aardgas 1 Jaar Vast E",
    "Groene Stroom en Aardgas 1 Jaar Verlenging A",
    "Groene Stroom en Aardgas 1 Jaar Verlenging B",
    "Groene Stroom en Aardgas 1 Jaar Verlenging C",
    "Groene Stroom en Aardgas 1 Jaar Verlenging D",
    "Groene Stroom en Aardgas 1 Jaar Verlenging E",
    "Groene Stroom en Aardgas 2 Jaar Vast A",
    "Groene Stroom en Aardgas 2 Jaar Vast B",
    "Groene Stroom en Aardgas 2 Jaar Vast E",
    "Groene Stroom en Aardgas 2 Jaar Verlenging A",
    "Groene Stroom en Aardgas 2 Jaar Verlenging B",
    "Groene Stroom en Aardgas 3 Jaar Vast A",
    "Groene Stroom en Aardgas 3 Jaar Vast B",
    "Groene Stroom en Aardgas 3 Jaar Vast C",
    "Groene Stroom en Aardgas 3 Jaar Vast D",
    "Groene Stroom en Aardgas 3 Jaar Vast E",
    "Groene Stroom en Aardgas 3 Jaar Verlenging A",
    "Groene Stroom en Aardgas 3 Jaar Verlenging B",
    "Groene Stroom en Aardgas Variabel A",
    "Groene Stroom en Aardgas Variabel C",
    "Groene Stroom en Aardgas Variabel E",
    "Groene stroom en Aardgas 1 jaar Vast C",
    "Groene stroom en Aardgas 1 jaar Vast D",
    "Groene stroom en Aardgas 1 jaar Vast G",
    "Groene stroom en Aardgas 2 jaar Vast C",
    "Groene stroom en Aardgas 2 jaar Vast G",
    "Groene stroom en Aardgas 3 jaar Vast C",
    "Groene stroom en Aardgas 3 jaar Vast G",
    "Modelcontract",
    "Nederlandse Wind Stroom en CO2-gecompenseerd Gas Vast 1 Jaar A",
    "Nederlandse Wind Stroom en CO2-gecompenseerd Gas Vast 1 Jaar B",
]


if __name__ == "__main__":
    print("=" * 80)
    print("Budget Energie Contract Variant Extraction")
    print("=" * 80)
    print()
    
    # Group by base name to show unique contracts with their variants
    contract_groups = {}
    for contract in BUDGET_ENERGIE_CONTRACTS:
        parsed = parse_contract_name(contract)
        if parsed.base_name not in contract_groups:
            contract_groups[parsed.base_name] = {
                "slug": parsed.slug,
                "variants": []
            }
        if parsed.variant:
            contract_groups[parsed.base_name]["variants"].append(parsed.variant)
    
    # Print grouped view
    for i, (base_name, info) in enumerate(contract_groups.items(), 1):
        variants_str = ", ".join(sorted(info["variants"])) if info["variants"] else "—"
        print(f"{i:2d}. {base_name}")
        print(f"    slug: {info['slug']}")
        print(f"    variants: {variants_str}")
        print()
    
    print("=" * 80)
    print(f"Total unique base contracts: {len(contract_groups)}")
    print(f"Total contract entries: {len(BUDGET_ENERGIE_CONTRACTS)}")
    print("=" * 80)
