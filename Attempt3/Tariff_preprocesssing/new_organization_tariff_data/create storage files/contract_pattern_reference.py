#!/usr/bin/env python3
"""
Contract Pattern Recognition Helper

Demonstrates how to use the duration and variant reference files
to parse contract names across providers.
"""

import json
from pathlib import Path

def load_references():
    """Load duration and variant reference files."""
    durations_file = Path(__file__).parent / "contract_durations.json"
    variants_file = Path(__file__).parent / "contract_variants.json"
    
    with open(durations_file) as f:
        durations = json.load(f)
    
    with open(variants_file) as f:
        variants = json.load(f)
    
    return durations, variants


def build_duration_patterns(durations_ref):
    """Build a list of all duration indicators for regex matching."""
    all_indicators = []
    for duration_key, duration_info in durations_ref["duration_patterns"].items():
        all_indicators.extend(duration_info["indicators"])
    return all_indicators


def build_variant_patterns(variants_ref):
    """Build a flat list of all known variant labels."""
    all_variants = set()
    for category, info in variants_ref["variant_categories"].items():
        if "variants" in info:
            all_variants.update(info["variants"])
    return sorted(all_variants)


def demonstrate_coolblue():
    """Show how Coolblue Energie contracts are decomposed."""
    durations, variants = load_references()
    
    coolblue_contracts = [
        "1 jaar Zeker",
        "1 jaar Zeker Actie",
        "1 jaar Zeker Bespaarpakket",
        "2 jaar Zeker",
        "3 jaar Zeker",
        "5 jaar zeker",
        "Halfjaar Zeker",
        "Halfjaar Zeker Bespaarpakket",
        "Halfjaar Zeker actie",
        "Kwartaal Zeker",
        "Direct voordeel",
        "Minder energie - variabel",
        "Ziggo 1 jaar Zeker",
        "ING Puntenaanbod"
    ]
    
    print("=" * 80)
    print("COOLBLUE ENERGIE - CONTRACT PATTERN ANALYSIS")
    print("=" * 80)
    print()
    
    print("Reference Data:")
    print(f"  Base: Zeker (or specific service like 'Direct voordeel', 'Minder energie')")
    print(f"  Durations: 1 jaar, 2 jaar, 3 jaar, 5 jaar, Halfjaar, Kwartaal")
    print(f"  Variants: Actie, Bespaarpakket, Ziggo, ING Puntenaanbod")
    print()
    
    print("Contract Decomposition:")
    print()
    
    for contract in coolblue_contracts:
        parts = {
            "original": contract,
            "duration": "--",
            "base": "--",
            "variant": "--"
        }
        
        # Find time indication
        for duration_key, duration_info in durations["duration_patterns"].items():
            for indicator in duration_info["indicators"]:
                if indicator.lower() in contract.lower():
                    parts["duration"] = indicator
                    break
        
        # Find variant
        all_variants = build_variant_patterns(variants)
        for variant in all_variants:
            if variant.lower() in contract.lower():
                parts["variant"] = variant
                break
        
        # Extract base (what's left after removing duration and variant)
        base = contract
        if parts["duration"] != "--":
            base = base.replace(parts["duration"], "").strip()
        if parts["variant"] != "--":
            base = base.replace(parts["variant"], "").strip()
        
        # Clean up separators
        base = base.replace(" -", "").replace("- ", "").strip()
        
        if base:
            parts["base"] = base
        
        print(f"  Contract: {parts['original']}")
        print(f"    -> Base: {parts['base']}")
        print(f"    -> Duration: {parts['duration']}")
        print(f"    -> Variant: {parts['variant']}")
        print()


def demonstrate_delta():
    """Show how DELTA energie contracts are decomposed."""
    durations, variants = load_references()
    
    delta_contracts = [
        "DELTA Groene Stroom en/of DELTA Gas, variabele leveringsprijs",
        "DELTA Groene Stroom en/of DELTA Gas, variabele leveringsprijs (a)",
        "DELTA Groene Stroom en/of DELTA Gas, variabele leveringsprijs (b)",
        "DELTA Groene Stroom en/of DELTA Gas, variabele leveringsprijs (c)",
        "DELTA Groene Stroom en/of DELTA Gas, variabele leveringsprijs (e)",
        "DELTA Groene Stroom, vaste leveringsprijs (1 jaar) en/of DELTA Gas, vaste leveringsprijs (1 jaar)",
        "DELTA Groene Stroom, vaste leveringsprijs (3 jaar) en/of DELTA Gas, vaste leveringsprijs (3 jaar)",
        "DELTA Puur Zeeuws Groen en/of DELTA MixGroen Gas, variabele leveringsprijs",
        "DELTA Puur Zeeuws Groen, vaste leveringsprijs (1 jaar) en/of DELTA MixGroen Gas, vaste leveringsprijs (1 jaar)",
        "DELTA Puur Zeeuws Groen, vaste leveringsprijs (3 jaar) en/of DELTA MixGroen Gas, vaste leveringsprijs (3 jaar)",
        "DELTA Groene Actiestroom en/of DELTA Actiegas, variabele leveringsprijs",
    ]
    
    print("=" * 80)
    print("DELTA ENERGIE - CONTRACT PATTERN ANALYSIS")
    print("=" * 80)
    print()
    
    print("Reference Data:")
    print("  Bases:")
    print("    - DELTA Groene Stroom en/of DELTA Gas")
    print("    - DELTA Groene Actiestroom en/of DELTA Actiegas")
    print("    - DELTA Puur Zeeuws Groen en/of DELTA MixGroen Gas")
    print("  Time Indications:")
    print("    - variabele leveringsprijs")
    print("    - vaste leveringsprijs (1 jaar)")
    print("    - vaste leveringsprijs (3 jaar)")
    print("  Variants: (a), (b), (c), (e)")
    print()
    
    print("Contract Decomposition:")
    print()
    
    # DELTA-specific time indicators (check these first for accuracy)
    delta_time_indicators = [
        "vaste leveringsprijs (3 jaar)",
        "vaste leveringsprijs (1 jaar)",
        "variabele leveringsprijs"
    ]
    
    for contract in delta_contracts:
        parts = {
            "original": contract,
            "base": "--",
            "time_indication": "--",
            "variant": "--"
        }
        
        # Find time indication (DELTA-specific first)
        for indicator in delta_time_indicators:
            if indicator in contract:
                parts["time_indication"] = indicator
                break
        
        # Find variant (parenthetical codes)
        for variant in ["(a)", "(b)", "(c)", "(e)"]:
            if variant in contract:
                parts["variant"] = variant
                break
        
        # Extract base (what's left after removing time indication and variant)
        base = contract
        if parts["time_indication"] != "--":
            base = base.replace(parts["time_indication"], "").strip()
        if parts["variant"] != "--":
            base = base.replace(parts["variant"], "").strip()
        
        # Clean up separators and extra whitespace
        base = base.replace(" -", "").replace("- ", "").replace("  ", " ").strip()
        base = base.rstrip(",")
        
        if base:
            parts["base"] = base
        
        print(f"  Contract: {parts['original']}")
        print(f"    -> Base: {parts['base']}")
        print(f"    -> Time Indication: {parts['time_indication']}")
        print(f"    -> Variant: {parts['variant']}")
        print()


def demonstrate_energiedirect():
    """Show how Energiedirect.nl contracts are decomposed."""
    durations, variants = load_references()
    
    energiedirect_contracts = [
        "Groene Stroom en Gas variabel",
        "Groene Stroom en Gas variabel ACQ",
        "Groene Stroom en Gas variabel AFL",
        "Vast Groene Stroom en Gas AltijdVoordeel Vaste Prijs 1 jaar",
        "Vast Groene Stroom en Gas AltijdVoordeel A Vaste Prijs 1 jaar",
        "Vast Groene Stroom en Gas AltijdVoordeel Energiecollectief Vaste Prijs 1 jaar",
        "Vast Groene Stroom en Gas AltijdVoordeel Klant Vaste Prijs 2 jaar",
        "Vast Groene Stroom en Gas AltijdVoordeel P Vaste Prijs 3 jaar",
        "Vast Groene Stroom en Gas AltijdVoordeel Plus Vaste Prijs 1 jaar",
        "Vast Groene Stroom en Gas DirectVoordeel Actie Vaste Prijs 1 jaar"
    ]
    
    print("=" * 80)
    print("ENERGIEDIRECT.NL - CONTRACT PATTERN ANALYSIS")
    print("=" * 80)
    print()
    
    print("Reference Data:")
    print("  Bases:")
    print("    - Groene Stroom en Gas")
    print("    - Vast Groene Stroom en Gas AltijdVoordeel")
    print("    - Vast Groene Stroom en Gas DirectVoordeel")
    print("  Contract Types:")
    print("    - variabel (indefinite variable)")
    print("    - Vaste Prijs 1 jaar, 2 jaar, 3 jaar")
    print("  Variants: ACQ, AFL, A, Energiecollectief, Klant, P, Plus, Actie")
    print()
    
    print("Contract Decomposition:")
    print()
    
    energiedirect_time_indicators = [
        "Vaste Prijs 3 jaar",
        "Vaste Prijs 2 jaar",
        "Vaste Prijs 1 jaar",
        "variabel"
    ]
    
    for contract in energiedirect_contracts:
        parts = {
            "original": contract,
            "base": "--",
            "type_duration": "--",
            "variant": "--"
        }
        
        # Find type/duration (check longer patterns first to avoid substring issues)
        for indicator in energiedirect_time_indicators:
            if indicator in contract:
                parts["type_duration"] = indicator
                break
        
        # Find variant (be careful not to match within base names)
        energiedirect_variants = ["ACQ", "AFL", "Energiecollectief", "Klant", "Plus", "Actie", "A", "P"]
        for variant in energiedirect_variants:
            if variant in contract:
                # Check if variant is a standalone word (surrounded by spaces or at boundaries)
                import re
                pattern = r'\b' + re.escape(variant) + r'\b'
                if re.search(pattern, contract):
                    if variant == "A":
                        # Only match "A" as variant if it's not part of "AltijdVoordeel"
                        if re.search(r'\bA\b', contract):
                            parts["variant"] = variant
                            break
                    else:
                        parts["variant"] = variant
                        break
        
        # Extract base
        base = contract
        if parts["type_duration"] != "--":
            base = base.replace(parts["type_duration"], "").strip()
        if parts["variant"] != "--":
            # Only remove variant if it's a standalone word
            if parts["variant"] == "A" and " A " in base:
                base = base.replace(" A ", " ").strip()
            elif parts["variant"] != "A":
                base = base.replace(parts["variant"], "").strip()
        
        base = base.replace("  ", " ").strip().rstrip(",")
        
        if base:
            parts["base"] = base
        
        print(f"  Contract: {parts['original']}")
        print(f"    -> Base: {parts['base']}")
        print(f"    -> Type/Duration: {parts['type_duration']}")
        print(f"    -> Variant: {parts['variant']}")
        print()


def demonstrate_essent():
    """Show how Essent contracts are decomposed."""
    durations, variants = load_references()
    
    essent_contracts = [
        "Groene Stroom (NL) en Gas Variabel",
        "Groene Stroom (NL) en Gas Variabel ACQ",
        "Groene Stroom (NL) en Gas Variabel AFL",
        "ZekerheidsGarantie Groene Stroom (NL) en Gas 1 jaar",
        "ZekerheidsGarantie A Groene Stroom (NL) en Gas 1 jaar",
        "ZekerheidsGarantie A Groene Stroom (NL) en Gas 3 jaar",
        "ZekerheidsGarantie B Groene Stroom (NL) en Gas 1 jaar",
        "ZekerheidsGarantie B Groene Stroom (NL) en Gas 3 jaar",
        "ZekerheidsGarantie C Groene Stroom (NL) en Gas 1 jaar",
        "ZekerheidsGarantie F Groene Stroom (NL) en Gas 3 jaar",
        "ZekerheidsGarantie Plus Groene Stroom (NL) en Gas 1 jaar",
        "ZekerheidsGarantie Compleet Klant Groene Stroom (NL) en Gas 3 jaar",
        "ZekerheidsGarantie Voordeel Groene Stroom (NL) en Gas 1 jaar",
        "ZekerheidsGarantie Actie Groene Stroom (NL) en Gas 1 jaar"
    ]
    
    print("=" * 80)
    print("ESSENT - CONTRACT PATTERN ANALYSIS")
    print("=" * 80)
    print()
    
    print("Reference Data:")
    print("  Base: Groene Stroom (NL) en Gas")
    print("  Contract Types:")
    print("    - Variabel (variable)")
    print("    - ZekerheidsGarantie (certainty guarantee with fixed price)")
    print("  Specific Duration: 1 jaar, 3 jaar")
    print("  Variants: ACQ, AFL, A, B, C, F, P, RB, Plus, Compleet, Voordeel, Actie, Klant")
    print()
    
    print("Contract Decomposition:")
    print()
    
    essent_prefixes = ["ZekerheidsGarantie"]
    essent_durations = ["3 jaar", "1 jaar"]
    
    for contract in essent_contracts:
        parts = {
            "original": contract,
            "base": "--",
            "type": "--",
            "duration": "--",
            "variant": "--"
        }
        
        # Determine contract type
        if "Variabel" in contract:
            parts["type"] = "Variabel"
        elif any(prefix in contract for prefix in essent_prefixes):
            parts["type"] = "ZekerheidsGarantie"
        
        # Find duration
        for duration in essent_durations:
            if duration in contract:
                parts["duration"] = duration
                break
        
        # Find variant
        for variant in ["ACQ", "AFL", "A", "B", "C", "F", "P", "RB", "Plus", "Compleet", "Voordeel", "Actie", "Klant"]:
            if variant in contract:
                parts["variant"] = variant
                break
        
        # Extract base (always "Groene Stroom (NL) en Gas")
        parts["base"] = "Groene Stroom (NL) en Gas"
        
        print(f"  Contract: {parts['original']}")
        print(f"    -> Base: {parts['base']}")
        print(f"    -> Type: {parts['type']}")
        print(f"    -> Duration: {parts['duration']}")
        print(f"    -> Variant: {parts['variant']}")
        print()


def demonstrate_frank_energie():
    """Show how Frank Energie contracts are decomposed."""
    durations, variants = load_references()
    
    frank_contracts = [
        "Frank Energie 1 jaar vast Jan 2025",
        "Frank Energie 1 jaar vast Apr 2025",
        "Frank Energie 1 jaar vast December 2025",
        "Frank Energie Variabel Jan 2025",
        "Frank Energie Variabel Mar 2025",
        "Frank Energie Variabel September 2025"
    ]
    
    print("=" * 80)
    print("FRANK ENERGIE - CONTRACT PATTERN ANALYSIS")
    print("=" * 80)
    print()
    
    print("Reference Data:")
    print("  Base: Frank Energie")
    print("  Contract Types: 1 jaar vast, Variabel")
    print("  Month Indicators: Jan, Feb, Mar, Apr, Mei, Jun, Jul, Aug, Sep, Oct, Nov, Dec")
    print("  Year: 2024, 2025, 2026, etc. (stored in snapshot_month)")
    print("  Variants: None (month+year indicators are dropped)")
    print()
    
    print("Contract Decomposition:")
    print("  Note: Month+year are removed from contract_name and stored in snapshot_month")
    print()
    
    month_indicators = ["January", "February", "March", "April", "May", "June", 
                        "July", "August", "September", "October", "November", "December",
                        "Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    
    for contract in frank_contracts:
        parts = {
            "original": contract,
            "base": "--",
            "type": "--",
            "month_year": "--"
        }
        
        # Base is always "Frank Energie"
        parts["base"] = "Frank Energie"
        
        # Find contract type
        if "1 jaar vast" in contract:
            parts["type"] = "1 jaar vast"
        elif "Variabel" in contract:
            parts["type"] = "Variabel"
        
        # Extract month+year (to be dropped from contract_name)
        import re
        # Pattern: [Month] [4-digit year]
        match = re.search(r'\b([A-Z][a-z]+)\s+(\d{4})\b', contract)
        if match:
            parts["month_year"] = f"{match.group(1)} {match.group(2)}"
        
        # Final contract_name would be: "Frank Energie [type]" (without month+year)
        final_name = f"{parts['base']} {parts['type']}"
        
        print(f"  Contract (raw): {parts['original']}")
        print(f"    -> Base: {parts['base']}")
        print(f"    -> Type: {parts['type']}")
        print(f"    -> Month+Year (to drop): {parts['month_year']}")
        print(f"    -> Final contract_name: {final_name}")
        print()


def demonstrate_greenchoice():
    """Show how Greenchoice contracts are decomposed."""
    durations, variants = load_references()
    
    greenchoice_contracts = [
        "1 jaar vast",
        "1 jaar vast met korting",
        "100% Nederlandse Wind 1 jaar",
        "100% Nederlandse Wind 3 jaar",
        "Groenbezig 1 jaar",
        "Groenbezig 2 jaar",
        "Groen&Vrij Wind en Zon",
        "Groen&Vrij Wind en Zon Start",
        "Nederlandse Windstroom 1 jaar",
        "Nederlandse Windstroom 3 jaar",
        "Nederlandse Windstroom Variabel",
        "Slimgroen 1 jaar",
        "Zonnestroom via Univé 2 jaar met Korting",
        "Zorgeloos Energie tot 1-1-2027",
        "Collectief 1 jaar",
        "Collectief Variabel",
        "Collectief Variabel Start",
        "211",
        "250"
    ]
    
    print("=" * 80)
    print("GREENCHOICE - CONTRACT PATTERN ANALYSIS")
    print("=" * 80)
    print()
    
    print("Reference Data:")
    print("  Bases:")
    print("    - (empty/implicit - standard fixed contracts)")
    print("    - 100% Nederlandse Wind")
    print("    - Groenbezig")
    print("    - Groen&Vrij Wind en Zon")
    print("    - Nederlandse Windstroom")
    print("    - Slimgroen")
    print("    - Zonnestroom")
    print("    - Zorgeloos Energie")
    print("    - Collectief")
    print("  Time Indications: 1 jaar, 2 jaar, 3 jaar, variabel, flexibel, tot [date]")
    print("  Variants: 150-500 (pricing tiers), met Korting, Start, Collectief, via Univé")
    print()
    
    print("Contract Decomposition:")
    print()
    
    greenchoice_bases = ["100% Nederlandse Wind", "Groenbezig", "Groen&Vrij Wind en Zon", 
                         "Nederlandse Windstroom", "Slimgroen", "Zonnestroom", 
                         "Zorgeloos Energie", "Collectief"]
    greenchoice_durations = ["3 jaar", "2 jaar", "1 jaar", "Variabel", "variabel"]
    pricing_tiers = ["150", "200", "210", "250", "300", "350", "400", "500"]
    greenchoice_variants = ["met Korting", "met korting", "Start", "Collectief", "via Univé"]
    
    for contract in greenchoice_contracts:
        parts = {
            "original": contract,
            "base": "--",
            "duration": "--",
            "variant": "--"
        }
        
        # Try to find base
        for base in greenchoice_bases:
            if base in contract:
                parts["base"] = base
                break
        
        # Check if it's a pricing tier number
        if contract.isdigit() and contract in pricing_tiers:
            parts["base"] = "--"
            parts["duration"] = "--"
            parts["variant"] = contract
            print(f"  Contract: {parts['original']}")
            print(f"    -> Base: {parts['base']}")
            print(f"    -> Duration: {parts['duration']}")
            print(f"    -> Variant (pricing tier): {parts['variant']}")
            print()
            continue
        
        # Find duration
        for duration in greenchoice_durations:
            if duration in contract:
                parts["duration"] = duration
                break
        
        # Check for specific date pattern (Zorgeloos)
        if "tot " in contract:
            import re
            match = re.search(r'tot\s+(\d+-\d+-\d+)', contract)
            if match:
                parts["duration"] = f"tot {match.group(1)}"
        
        # Find variant
        for variant_candidate in greenchoice_variants + pricing_tiers:
            if variant_candidate in contract:
                parts["variant"] = variant_candidate
                break
        
        # Extract base from remaining text if not found
        if parts["base"] == "--":
            base_text = contract
            if parts["duration"] != "--":
                base_text = base_text.replace(parts["duration"], "").strip()
            if parts["variant"] != "--":
                base_text = base_text.replace(parts["variant"], "").strip()
            base_text = base_text.replace("  ", " ").strip()
            
            if base_text:
                parts["base"] = base_text
        
        print(f"  Contract: {parts['original']}")
        print(f"    -> Base: {parts['base']}")
        print(f"    -> Duration: {parts['duration']}")
        print(f"    -> Variant: {parts['variant']}")
        print()
    
    print()
    print("=" * 80)
    print("REFERENCE FILES CREATED")
    print("=" * 80)
    print()
    print("1. contract_durations.json")
    print("   - Time indicators (1 jaar, 2 jaar, vaste leveringsprijs, etc.)")
    print("   - Status modifiers (vast, variabel, zeker)")
    print("   - Months conversion for each duration")
    print("   - Provider annotations")
    print()
    print("2. contract_variants.json")
    print("   - 9+ variant categories (promotional, welcome, loyalty, pricing tiers, etc.)")
    print("   - Specific variants for each category")
    print("   - Provider summary showing common variants")
    print("   - Examples for pattern matching")
    print()
    print("3. contract_types.json")
    print("   - Contract type categorization (vast, variabel, zeker, etc.)")
    print("   - Separation of contract_type from contract_duration")
    print("   - Provider-specific pattern examples")
    print()


def demonstrate_mega():
    """Show how Mega contracts are decomposed."""
    durations, variants = load_references()
    
    mega_contracts = [
        "194",
        "200",
        "266",
        "484",
        "496",
        "532",
        "540",
        "589,70",
        "592",
        "680",
        "698",
        "84",
        "85",
        "VEH 1 jaar vast",
        "VEH 2 jaar vast",
        "Variabel maandelijks December",
        "Variabel maandelijks November",
        "Variabel maandelijks October",
        "Variabel maandelijks September",
        "Variabel maandelijks januari"
    ]
    
    print("=" * 80)
    print("MEGA - CONTRACT PATTERN ANALYSIS")
    print("=" * 80)
    print()
    
    print("Reference Data:")
    print("  Base: Mega")
    print("  Contract Types: VEH, Variabel")
    print("  Numeric Codes (variants): 194, 200, 266, 484, 496, 532, 540, 589,70, 592, 680, 698, 84, 85")
    print("  Durations: 1 jaar, 2 jaar")
    print("  Note: Monthly modifiers (December, November, etc.) are removed from contract_name")
    print()
    
    print("Contract Decomposition:")
    print()
    
    months = ["December", "November", "October", "September", "August", 
              "juli", "juni", "maart", "januari", "april"]
    
    for contract in mega_contracts:
        parts = {
            "original": contract,
            "base": "--",
            "type": "--",
            "variant": "--",
            "month_to_drop": "--"
        }
        
        # Handle pure numeric codes as variants
        if contract.replace(",", "").isdigit():
            parts["variant"] = contract
            print(f"  Contract: {parts['original']}")
            print(f"    -> Variant (pricing code): {parts['variant']}")
            print()
            continue
        
        # Check for month to drop from "Variabel maandelijks [Month]"
        for month in months:
            if month in contract:
                parts["month_to_drop"] = month
                parts["type"] = "Variabel"
                final_name = "Variabel"
                print(f"  Contract (raw): {parts['original']}")
                print(f"    -> Type: {parts['type']}")
                print(f"    -> Month (to drop): {parts['month_to_drop']}")
                print(f"    -> Final contract_name: {final_name}")
                print()
                break
        else:
            # Handle VEH contracts
            if "VEH" in contract:
                parts["base"] = "Mega"
                parts["type"] = "VEH"
                
                # Find duration
                if "1 jaar" in contract:
                    duration = "1 jaar"
                elif "2 jaar" in contract:
                    duration = "2 jaar"
                else:
                    duration = "--"
                
                print(f"  Contract: {parts['original']}")
                print(f"    -> Base: {parts['base']}")
                print(f"    -> Type: {parts['type']}")
                print(f"    -> Duration: {duration}")
                print()


def demonstrate_noord_energie():
    """Show how Noord Energie group contracts are decomposed."""
    durations, variants = load_references()
    
    noord_contracts = [
        "Noord Energie 1 jaar vast",
        "Noord Energie 2 jaar vast",
        "Noord Energie 3 jaar vast",
        "Noord Energie Actie 1 jaar vast",
        "Noord Energie Actie 3 jaar vast",
        "Noord Energie Variabel",
        "Noord Energie vast Online 3 jaar",
        "Yebbo 1 jaar vast",
        "Yebbo Variabel",
        "Zuid Energie 1 jaar vast particulier",
        "Zuid Energie 3 jaar vast particulier"
    ]
    
    print("=" * 80)
    print("NOORD ENERGIE GROUP - CONTRACT PATTERN ANALYSIS")
    print("=" * 80)
    print()
    
    print("Reference Data:")
    print("  Bases: Noord Energie, Yebbo, Zuid Energie")
    print("  Contract Types: vast (fixed), variabel (variable)")
    print("  Durations: 1 jaar, 2 jaar, 3 jaar")
    print("  Variants: Actie, Online, particulier")
    print()
    
    print("Contract Decomposition:")
    print()
    
    bases = ["Noord Energie", "Yebbo", "Zuid Energie"]
    durations_list = ["3 jaar", "2 jaar", "1 jaar"]  # Check longer first
    
    for contract in noord_contracts:
        parts = {
            "original": contract,
            "base": "--",
            "type": "--",
            "duration": "--",
            "variant": "--"
        }
        
        # Find base
        for base in bases:
            if base in contract:
                parts["base"] = base
                break
        
        # Find contract type
        if "Variabel" in contract:
            parts["type"] = "Variabel"
        elif "vast" in contract.lower():
            parts["type"] = "vast"
        
        # Find duration
        for duration in durations_list:
            if duration in contract:
                parts["duration"] = duration
                break
        
        # Find variant
        if "Actie" in contract:
            parts["variant"] = "Actie"
        elif "Online" in contract:
            parts["variant"] = "Online"
        elif "particulier" in contract:
            parts["variant"] = "particulier"
        
        print(f"  Contract: {parts['original']}")
        print(f"    -> Base: {parts['base']}")
        print(f"    -> Type: {parts['type']}")
        print(f"    -> Duration: {parts['duration']}")
        print(f"    -> Variant: {parts['variant']}")
        print()


def demonstrate_om_nieuwe_energie():
    """Show how Om | nieuwe energie contracts are decomposed."""
    durations, variants = load_references()
    
    om_contracts = [
        "1 jaar vast",
        "Flex",
        "Flex 202506",
        "Flex 202507",
        "Flex 202508",
        "Flex 202509",
        "Flex 202510",
        "Flex 202511",
        "Flex 202512",
        "Variabel",
        "Variabel 202507"
    ]
    
    print("=" * 80)
    print("OM | NIEUWE ENERGIE - CONTRACT PATTERN ANALYSIS")
    print("=" * 80)
    print()
    
    print("Reference Data:")
    print("  Bases: Flex, Variabel")
    print("  Contract Types: 1 jaar vast, flexibel")
    print("  Month Codes: 202506, 202507, 202508, 202509, 202510, 202511, 202512")
    print("  Note: Date codes (YYYYMM format) should be removed from contract_name")
    print()
    
    print("Contract Decomposition:")
    print()
    
    import re
    month_code_pattern = r'\b20\d{4}\b'
    
    for contract in om_contracts:
        parts = {
            "original": contract,
            "base": "--",
            "type": "--",
            "month_code": "--"
        }
        
        # Find base
        if "1 jaar vast" in contract:
            parts["type"] = "1 jaar vast"
            parts["base"] = "1 jaar vast"
        elif "Flex" in contract:
            parts["base"] = "Flex"
        elif "Variabel" in contract:
            parts["base"] = "Variabel"
        
        # Extract month code
        match = re.search(month_code_pattern, contract)
        if match:
            parts["month_code"] = match.group(0)
        
        # Final contract_name (without month code)
        final_name = contract
        if parts["month_code"] != "--":
            final_name = re.sub(month_code_pattern, "", contract).strip()
        
        print(f"  Contract (raw): {parts['original']}")
        print(f"    -> Base: {parts['base']}")
        print(f"    -> Month Code (to drop): {parts['month_code']}")
        print(f"    -> Final contract_name: {final_name}")
        print()


def demonstrate_powerpeers():
    """Show how Powerpeers contracts are decomposed."""
    durations, variants = load_references()
    
    powerpeers_contracts = [
        "Maandelijks Wisselend",
        "Samen Groen VP1",
        "Samen Groen VP2",
        "Samen Groen VP2-B",
        "Samen Groen VP3",
        "Variabel",
        "Variabel & 100% Groen Gas",
        "Variabel & 25% Groen Gas"
    ]
    
    print("=" * 80)
    print("POWERPEERS - CONTRACT PATTERN ANALYSIS")
    print("=" * 80)
    print()
    
    print("Reference Data:")
    print("  Bases: Samen Groen, 100% Groen Gas, 25% Groen Gas")
    print("  Time Indication: maandelijks wisselend (monthly variable)")
    print("  Variants: VP1, VP2, VP2-B, VP3 (pricing/contract tiers)")
    print()
    
    print("Contract Decomposition:")
    print()
    
    bases = ["Samen Groen", "100% Groen Gas", "25% Groen Gas"]
    vp_variants = ["VP1", "VP2-B", "VP2", "VP3"]  # Check longer variants first
    
    for contract in powerpeers_contracts:
        parts = {
            "original": contract,
            "base": "--",
            "time_indication": "--",
            "variant": "--"
        }
        
        # Special case: pure "Maandelijks Wisselend"
        if contract == "Maandelijks Wisselend":
            parts["time_indication"] = "Maandelijks Wisselend"
            print(f"  Contract: {parts['original']}")
            print(f"    -> Time Indication: {parts['time_indication']}")
            print()
            continue
        
        # Find time indication
        if "Variabel" in contract:
            parts["time_indication"] = "Variabel"
        
        # Find base
        for base in bases:
            if base in contract:
                parts["base"] = base
                break
        
        # Find variant (VP code)
        for vp in vp_variants:
            if vp in contract:
                parts["variant"] = vp
                break
        
        print(f"  Contract: {parts['original']}")
        print(f"    -> Base: {parts['base']}")
        print(f"    -> Time Indication: {parts['time_indication']}")
        print(f"    -> Variant: {parts['variant']}")
        print()


def demonstrate_pure_energie():
    """Show how Pure Energie contracts are decomposed."""
    durations, variants = load_references()
    
    pure_contracts = [
        "Pure Energie Plus",
        "Pure Energie Variabel",
        "Pure Energie Variabel Netto Terugleveren",
        "Vast Consument",
        "Vast Consument 100% groen gas",
        "Vast Consument 25% groen gas",
        "Verlenging Consument",
        "Verlenging Pure Energie Plus"
    ]
    
    print("=" * 80)
    print("PURE ENERGIE - CONTRACT PATTERN ANALYSIS")
    print("=" * 80)
    print()
    
    print("Reference Data:")
    print("  Bases: Pure Energie, Vast Consument, Verlenging")
    print("  Contract Types: vast (fixed), variabel (variable)")
    print("  Variants: Plus, Netto Terugleveren, Consument")
    print()
    
    print("Contract Decomposition:")
    print()
    
    bases = ["Pure Energie", "Vast Consument", "Verlenging"]
    
    for contract in pure_contracts:
        parts = {
            "original": contract,
            "base": "--",
            "type": "--",
            "variant": "--"
        }
        
        # Find base
        for base in bases:
            if base in contract:
                parts["base"] = base
                break
        
        # Find type
        if "Vast" in contract:
            parts["type"] = "Vast"
        elif "Variabel" in contract:
            parts["type"] = "Variabel"
        
        # Find variant
        if "Plus" in contract:
            parts["variant"] = "Plus"
        elif "Netto Terugleveren" in contract:
            parts["variant"] = "Netto Terugleveren"
        elif "Consument" in contract:
            parts["variant"] = "Consument"
        
        print(f"  Contract: {parts['original']}")
        print(f"    -> Base: {parts['base']}")
        print(f"    -> Type: {parts['type']}")
        print(f"    -> Variant: {parts['variant']}")
        print()


def demonstrate_unitedconsumers():
    """Show how UnitedConsumers contracts are decomposed."""
    durations, variants = load_references()
    
    uc_contracts = [
        "1 jaar vaste prijs",
        "1 jaar wind mee",
        "3 jaar vaste prijs",
        "3 jaar wind mee",
        "Regiokorting Delta",
        "Regiokorting ENGIE",
        "Regiokorting Eneco",
        "Regiokorting Essent",
        "Regiokorting Vattenfall",
        "Stapelkorting Delta",
        "Stapelkorting ENGIE",
        "Stapelkorting Eneco",
        "Stapelkorting Essent",
        "Stapelkorting Vattenfall",
        "Variabel onbepaalde tijd"
    ]
    
    print("=" * 80)
    print("UNITEDCONSUMERS - CONTRACT PATTERN ANALYSIS")
    print("=" * 80)
    print()
    
    print("Reference Data:")
    print("  Base: Wind mee")
    print("  Contract Types: vaste prijs (fixed), variabel (variable)")
    print("  Durations: 1 jaar, 3 jaar, onbepaalde tijd")
    print("  Discount Variants: Regiokorting, Stapelkorting")
    print("  Discount Modifiers: Delta, ENGIE, Eneco, Essent, Vattenfall")
    print()
    
    print("Contract Decomposition:")
    print()
    
    for contract in uc_contracts:
        parts = {
            "original": contract,
            "base": "--",
            "type": "--",
            "duration": "--",
            "variant": "--",
            "modifier": "--"
        }
        
        # Find type/duration
        if "vaste prijs" in contract:
            parts["type"] = "vaste prijs"
            if "1 jaar" in contract:
                parts["duration"] = "1 jaar"
            elif "3 jaar" in contract:
                parts["duration"] = "3 jaar"
        elif "wind mee" in contract:
            parts["base"] = "Wind mee"
            if "1 jaar" in contract:
                parts["duration"] = "1 jaar"
            elif "3 jaar" in contract:
                parts["duration"] = "3 jaar"
        elif "Variabel" in contract:
            parts["type"] = "Variabel"
            parts["duration"] = "onbepaalde tijd"
        
        # Find discount variant
        if "Regiokorting" in contract:
            parts["variant"] = "Regiokorting"
        elif "Stapelkorting" in contract:
            parts["variant"] = "Stapelkorting"
        
        # Find discount modifier
        for provider in ["Delta", "ENGIE", "Eneco", "Essent", "Vattenfall"]:
            if provider in contract:
                parts["modifier"] = provider
                break
        
        # Set base for Wind mee contracts
        if parts["base"] == "--" and "wind mee" in contract.lower():
            parts["base"] = "Wind mee"
        
        print(f"  Contract: {parts['original']}")
        print(f"    -> Base: {parts['base']}")
        print(f"    -> Type: {parts['type']}")
        print(f"    -> Duration: {parts['duration']}")
        print(f"    -> Discount: {parts['variant']} {parts['modifier']}")
        print()


def demonstrate_eneco():
    """Show how Eneco bundle contracts (electricity + gas) are decomposed."""
    durations, variants = load_references()
    
    eneco_contracts = [
        "Eneco HollandseWind & Zon 1 jaar VastePrijs & Eneco CO2-GecompenseerdGas 1 jaar VastePrijs",
        "Eneco HollandseWind & Zon 1 jaar VasteLooptijd & Eneco Gas 1 jaar VasteLooptijd",
        "Eneco HollandseWind & Zon 3 jaar Zeker & Eneco CO2-GecompenseerdGas 3 jaar Zeker",
        "Eneco HollandseWind & Zon 3 jaar Variabel & Eneco Gas 3 jaar Variabel",
        "Eneco HollandseWind & Zon 1 jaar Actie & Eneco CO2-GecompenseerdGas 1 jaar Actie",
        "Eneco HollandseWind & Zon 1 jaar MKB & Eneco Gas 1 jaar MKB",
        "Eneco HollandseWind & Zon 1 jaar VastePrijs & Eneco CO2-GecompenseerdGas 1 jaar VastePrijs VoordeelMomenten",
        "Eneco HollandseWind & Zon 3 jaar Zeker & Eneco Gas 3 jaar Zeker",
        "Eneco HollandseWind & Zon 1 jaar Variabel & Eneco CO2-GecompenseerdGas 1 jaar Variabel",
        "Eneco HollandseWind & Zon 1 jaar VastePrijs & Eneco Gas 1 jaar VastePrijs"
    ]
    
    print("=" * 80)
    print("ENECO - BUNDLE CONTRACT PATTERN ANALYSIS (ELECTRICITY + GAS)")
    print("=" * 80)
    print()
    
    print("Reference Data:")
    print("  Bundle Format: Eneco [elec_base] [duration] [type] & Eneco [gas_base] [duration] [type]")
    print("  Electricity Base: HollandseWind & Zon")
    print("  Gas Bases: CO2-GecompenseerdGas, Gas")
    print("  Contract Types: VastePrijs, VasteLooptijd, Zeker, Variabel, Actie, MKB")
    print("  Durations: 1 jaar, 3 jaar")
    print("  Variants: VoordeelMomenten (special promotional)")
    print()
    
    print("Contract Decomposition (Bundle = Electricity & Gas):")
    print()
    
    for contract in eneco_contracts:
        parts = {
            "original": contract,
            "electricity_base": "--",
            "electricity_type": "--",
            "electricity_duration": "--",
            "electricity_variant": "--",
            "gas_base": "--",
            "gas_type": "--",
            "gas_duration": "--",
            "gas_variant": "--"
        }
        
        # Split bundle on " & Eneco " (to avoid splitting "HollandseWind & Zon")
        components = contract.split(" & Eneco ")
        
        # Parse electricity component
        if len(components) >= 1:
            elec = components[0].replace("Eneco ", "").strip()
            if "HollandseWind" in elec and "Zon" in elec:
                parts["electricity_base"] = "HollandseWind & Zon"
            
            # Extract type and duration
            for type_val in ["VastePrijs", "VasteLooptijd", "Zeker", "Variabel", "Actie", "MKB"]:
                if type_val in elec:
                    parts["electricity_type"] = type_val
            
            for dur in ["1 jaar", "3 jaar"]:
                if dur in elec:
                    parts["electricity_duration"] = dur
            
            # Check for special variant
            if "VoordeelMomenten" in elec:
                parts["electricity_variant"] = "VoordeelMomenten"
        
        # Parse gas component
        if len(components) >= 2:
            gas = components[1].strip()
            
            # Determine gas base (NOT variant)
            if "CO2-GecompenseerdGas" in gas:
                parts["gas_base"] = "CO2-GecompenseerdGas"
            elif "Gas" in gas and "CO2" not in gas:
                parts["gas_base"] = "Gas"
            
            # Extract gas type (usually matches electricity)
            for type_val in ["VastePrijs", "VasteLooptijd", "Zeker", "Variabel", "Actie", "MKB"]:
                if type_val in gas:
                    parts["gas_type"] = type_val
            
            # Extract gas duration
            for dur in ["1 jaar", "3 jaar"]:
                if dur in gas:
                    parts["gas_duration"] = dur
        
        print(f"  Contract: {parts['original']}")
        print(f"    Electricity:")
        print(f"      -> Base: {parts['electricity_base']}")
        print(f"      -> Type: {parts['electricity_type']}")
        print(f"      -> Duration: {parts['electricity_duration']}")
        print(f"      -> Variant: {parts['electricity_variant']}")
        print(f"    Gas:")
        print(f"      -> Base: {parts['gas_base']}")
        print(f"      -> Type: {parts['gas_type']}")
        print(f"      -> Duration: {parts['gas_duration']}")
        print(f"      -> Variant: {parts['gas_variant']}")
        print()


def demonstrate_oxxio():
    """Show how OXXIO bundle contracts (electricity + gas) are decomposed."""
    durations, variants = load_references()
    
    oxxio_contracts = [
        "Oxxio Nederlandse Windstroom Zeker 1 jaar & Oxxio Gas Zeker 1 jaar",
        "Oxxio Europese Windstroom Variabel 1 jaar & Oxxio CO2-gecompenseerd Gas Variabel 1 jaar",
        "Oxxio LosVast Zeker 3 jaar & Oxxio Gas Zeker 3 jaar",
        "Oxxio Nederlandse Windstroom Variabel 3 jaar & Oxxio Gas Variabel 3 jaar",
        "Oxxio Sales Oxxio.nl Zeker 1 jaar & Oxxio Gas Zeker 1 jaar",
        "Oxxio Nederlandse Windstroom Zeker LosVast & Oxxio Gas Zeker",
        "Oxxio Europese Windstroom Variabel 1 jaar & Oxxio CO2-gecompenseerd Gas Variabel 1 jaar",
        "Oxxio LosVast Variabel Flexibel & Oxxio LosVast Variabel",
        "Oxxio Nederlandse Windstroom Zeker 1 jaar & Oxxio Gas Zeker 1 jaar",
        "Oxxio Sales Oxxio.nl Variabel 3 jaar & Oxxio Gas Variabel 3 jaar"
    ]
    
    print("=" * 80)
    print("OXXIO - BUNDLE CONTRACT PATTERN ANALYSIS (ELECTRICITY + GAS)")
    print("=" * 80)
    print()
    
    print("Reference Data:")
    print("  Bundle Format: Oxxio [elec_base] [contract_type] [duration] & Oxxio [gas_base] [contract_type] [duration]")
    print("  Electricity Bases: Nederlandse Windstroom, Europese Windstroom, LosVast, Sales Oxxio.nl")
    print("  Gas Bases: Gas, CO2-gecompenseerd Gas")
    print("  Contract Types: Zeker, Variabel, LosVast")
    print("  Durations: 1 jaar, 3 jaar, Flexibel")
    print()
    
    print("Contract Decomposition (Bundle = Electricity & Gas):")
    print()
    
    for contract in oxxio_contracts:
        parts = {
            "original": contract,
            "electricity_base": "--",
            "electricity_contract_type": "--",
            "electricity_duration": "--",
            "gas_base": "--",
            "gas_contract_type": "--",
            "gas_duration": "--"
        }
        
        # Split bundle on "&"
        components = [c.strip() for c in contract.split("&")]
        
        # Parse electricity component
        if len(components) >= 1:
            elec = components[0]
            
            # Extract electricity base (check longer names first for "Sales Oxxio.nl")
            for elec_base in ["Sales Oxxio.nl", "Nederlandse Windstroom", "Europese Windstroom", "LosVast"]:
                if elec_base in elec:
                    parts["electricity_base"] = elec_base
                    break
            
            # Extract contract type
            for ctype in ["Zeker", "Variabel", "LosVast"]:
                if ctype in elec:
                    parts["electricity_contract_type"] = ctype
                    break
            
            # Extract duration
            for dur in ["Flexibel", "1 jaar", "3 jaar"]:
                if dur in elec:
                    parts["electricity_duration"] = dur
        
        # Parse gas component
        if len(components) >= 2:
            gas = components[1]
            
            # Extract gas base (NOT variant)
            if "CO2-gecompenseerd Gas" in gas:
                parts["gas_base"] = "CO2-gecompenseerd Gas"
            elif "Gas" in gas and "CO2" not in gas:
                parts["gas_base"] = "Gas"
            
            # Extract gas contract type
            for ctype in ["Zeker", "Variabel", "LosVast"]:
                if ctype in gas:
                    parts["gas_contract_type"] = ctype
                    break
            
            # Extract gas duration
            for dur in ["Flexibel", "1 jaar", "3 jaar"]:
                if dur in gas:
                    parts["gas_duration"] = dur
        
        print(f"  Contract: {parts['original']}")
        print(f"    Electricity:")
        print(f"      -> Base: {parts['electricity_base']}")
        print(f"      -> Contract Type: {parts['electricity_contract_type']}")
        print(f"      -> Duration: {parts['electricity_duration']}")
        print(f"    Gas:")
        print(f"      -> Base: {parts['gas_base']}")
        print(f"      -> Contract Type: {parts['gas_contract_type']}")
        print(f"      -> Duration: {parts['gas_duration']}")
        print()



if __name__ == "__main__":
    demonstrate_coolblue()
    print()
    demonstrate_delta()
    print()
    demonstrate_energiedirect()
    print()
    demonstrate_essent()
    print()
    demonstrate_frank_energie()
    print()
    demonstrate_greenchoice()
    print()
    demonstrate_mega()
    print()
    demonstrate_noord_energie()
    print()
    demonstrate_om_nieuwe_energie()
    print()
    demonstrate_powerpeers()
    print()
    demonstrate_pure_energie()
    print()
    demonstrate_unitedconsumers()
    print()
    demonstrate_eneco()
    print()
    demonstrate_oxxio()
    
    print()
    print("=" * 80)
    print("REFERENCE FILES UPDATED")
    print("=" * 80)
    print()
    print("1. contract_durations.json")
    print("   - Time indicators (1 jaar, 2 jaar, vaste leveringsprijs, etc.)")
    print("   - Status modifiers (vast, variabel, zeker)")
    print("   - Months conversion for each duration")
    print("   - Provider annotations")
    print("   - Frank Energie month indicators")
    print()
    print("2. contract_variants.json")
    print("   - 10+ variant categories (pricing tiers NEW for Greenchoice)")
    print("   - Specific variants for each category")
    print("   - Provider summary showing common variants")
    print()
    print("3. contract_types.json")
    print("   - Contract type categorization (vast, variabel, zeker, VEH, etc.)")
    print("   - Separation of contract_type from contract_duration")
    print("   - Provider-specific pattern examples")
    print("   - 8 providers documented: DELTA, Energiedirect, Essent, Frank, Greenchoice, Hezelaer, Mega, Noord")
    print()
