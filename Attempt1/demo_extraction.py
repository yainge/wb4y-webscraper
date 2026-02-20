#!/usr/bin/env python3
"""
Demo script showing how to use scraper4 functions programmatically.

This demonstrates the complete workflow without using the CLI tool,
useful for integration into larger Python applications.
"""

import sys
from pathlib import Path

try:
    from scraper4 import (
        capture_bootstrap_url,
        bootstrap_session,
        select_tuple,
        fetch_tooltip,
        parse_tooltip_table,
        VIEW_URL,
        WORKSHEET,
        DASHBOARD,
    )
except ImportError as e:
    print(f"Error: Could not import scraper4: {e}", file=sys.stderr)
    sys.exit(1)


def demo_basic_extraction():
    """
    Demo 1: Basic single-field extraction
    
    Shows the minimal workflow to extract a tooltip.
    """
    print("\n" + "="*70)
    print("DEMO 1: Basic Single-Field Extraction")
    print("="*70 + "\n")
    
    # Step 1: Get fresh bootstrap session
    print("Step 1: Capturing bootstrap session...")
    bootstrap_url = capture_bootstrap_url(VIEW_URL)
    print(f"  Success! URL: {bootstrap_url[:60]}...")
    
    # Step 2: Initialize VizQL session
    print("\nStep 2: Initializing VizQL session...")
    session, session_id = bootstrap_session(bootstrap_url)
    print(f"  Success! Session ID: {session_id[:16]}...")
    
    # Step 3: Select a tuple (mark)
    print("\nStep 3: Selecting tuple #1...")
    # NOTE: Replace with actual FN string from your dashboard
    fn_example = "[federated.0oi1j4o10smp321c0zq3g038kx3b].[none:Contractnaam:nk]"
    print(f"  (Using example FN: {fn_example})")
    try:
        select_tuple(session, session_id, tuple_id=1, fn=fn_example)
        print("  Success!")
    except Exception as e:
        print(f"  Note: Select may fail with invalid FN string (expected): {e}")
        return
    
    # Step 4: Fetch tooltip
    print("\nStep 4: Fetching tooltip HTML...")
    tooltip_html = fetch_tooltip(session, session_id)
    print(f"  Success! Received {len(tooltip_html)} bytes of HTML")
    
    # Step 5: Parse tooltip
    print("\nStep 5: Parsing tooltip...")
    data = parse_tooltip_table(tooltip_html)
    print(f"  Success! Extracted {len(data)} fields")
    
    # Display results
    print("\n" + "-"*70)
    print("EXTRACTED DATA:")
    print("-"*70)
    for key, value in data.items():
        if value:
            print(f"  {key:40s} : {value}")
    print("-"*70)


def demo_multi_field_extraction():
    """
    Demo 2: Multi-field extraction (multiple selectors)
    
    Shows how to select multiple related fields before fetching tooltip.
    Useful when tooltip data depends on multiple selections.
    """
    print("\n" + "="*70)
    print("DEMO 2: Multi-Field Extraction")
    print("="*70 + "\n")
    
    print("This demo shows selecting multiple tuple fields...")
    print("Step 1: Capture bootstrap + init session")
    
    bootstrap_url = capture_bootstrap_url(VIEW_URL)
    session, session_id = bootstrap_session(bootstrap_url)
    print(f"  Session ID: {session_id[:16]}...\n")
    
    # Select CONTRACT field
    fn_contract = "[federated.0oi1j4o10smp321c0zq3g038kx3b].[none:Contractnaam:nk]"
    print(f"Step 2: Select contract field")
    print(f"  FN: {fn_contract}")
    try:
        select_tuple(session, session_id, tuple_id=2, fn=fn_contract)
    except:
        print("  (Skipped - would fail with example FN)")
        return
    
    # Select SUPPLIER field (if available)
    fn_supplier = "[federated.0oi1j4o10smp321c0zq3g038kx3b].[none:Energie leveranciers:nk]"
    print(f"\nStep 3: Select supplier field")
    print(f"  FN: {fn_supplier}")
    try:
        select_tuple(session, session_id, tuple_id=2, fn=fn_supplier)
    except:
        print("  (Skipped - would fail with example FN)")
        return
    
    print("\nStep 4: Fetch combined tooltip")
    print("  (Both selections are now scoped in the tooltip)")
    tooltip_html = fetch_tooltip(session, session_id)
    data = parse_tooltip_table(tooltip_html)
    
    print(f"\nExtracted {len(data)} fields for tuple #2:")
    print(f"  Contract : {data.get('contract_name', 'N/A')}")
    print(f"  Supplier : {data.get('supplier', 'N/A')}")


def demo_batch_extraction():
    """
    Demo 3: Batch extraction pattern
    
    Shows how to extract multiple tuples efficiently.
    """
    print("\n" + "="*70)
    print("DEMO 3: Batch Extraction Pattern")
    print("="*70 + "\n")
    
    results = []
    tuple_ids = [1, 2, 3]  # Extract first 3 tuples
    fn = "[federated.0oi1j4o10smp321c0zq3g038kx3b].[none:Contractnaam:nk]"
    
    print(f"Extracting {len(tuple_ids)} tuples...\n")
    
    # Option A: Reuse single bootstrap session (faster)
    print("Approach A: Reuse bootstrap session for all tuples")
    print("-"*70)
    bootstrap_url = capture_bootstrap_url(VIEW_URL)
    session, session_id = bootstrap_session(bootstrap_url)
    
    for i, tuple_id in enumerate(tuple_ids, 1):
        print(f"Extracting tuple #{tuple_id} ({i}/{len(tuple_ids)})...", end=" ")
        try:
            select_tuple(session, session_id, tuple_id, fn)
            tooltip_html = fetch_tooltip(session, session_id)
            data = parse_tooltip_table(tooltip_html)
            results.append({
                "tuple_id": tuple_id,
                "contract_name": data.get("contract_name"),
                "supplier": data.get("supplier"),
            })
            print("OK")
        except Exception as e:
            print(f"ERROR: {e}")
            if "410" in str(e):
                print("  Note: Session expired. In production, recapture bootstrap and retry.")
    
    print(f"\nCollected {len(results)} results")
    print("\nSummary:")
    for r in results:
        print(f"  Tuple {r['tuple_id']:2d} : {r['contract_name']} / {r['supplier']}")


def demo_error_handling():
    """
    Demo 4: Error handling and recovery
    
    Shows common error scenarios and recovery patterns.
    """
    print("\n" + "="*70)
    print("DEMO 4: Error Handling & Recovery")
    print("="*70 + "\n")
    
    print("Common scenarios:\n")
    
    # Scenario 1: Invalid FN string
    print("1. Invalid FN string → HTTP 400")
    print("   Recovery: Get correct FN from browser DevTools Network tab")
    print("   Details: Open https://public.tableau.com/views/...dashboard...")
    print("             F12 → Network → triggerVizQL → Request")
    print("             Copy the 'fn' parameter\n")
    
    # Scenario 2: Session timeout
    print("2. Session timeout → HTTP 410")
    print("   Recovery: Recapture bootstrap_url and reinit session")
    print("   Code:\n")
    print("        try:")
    print("            # make VizQL call")
    print("        except requests.HTTPError as e:")
    print("            if e.response.status_code == 410:")
    print("                bootstrap_url = capture_bootstrap_url()")
    print("                session, session_id = bootstrap_session(bootstrap_url)")
    print("                # retry the call\n")
    
    # Scenario 3: Network timeout
    print("3. Network timeout")
    print("   Recovery: Increase timeout (default 30s is usually sufficient)")
    print("   Note: All functions accept timeout parameter for requests calls\n")
    
    # Scenario 4: Empty tooltip
    print("4. Empty tooltip HTML")
    print("   Cause: Tuple not found or tooltip rendering failed")
    print("   Check: Verify tuple_id exists in worksheet")
    print("          Try manual interaction in browser\n")


def main():
    """Run all demos."""
    print("\n" + "="*70)
    print("SCRAPER4 FUNCTION DEMOS")
    print("="*70)
    print("\nThis script demonstrates how to use scraper4 functions")
    print("programmatically for Tableau tooltip extraction.\n")
    print("NOTE: These demos use example FN strings that will likely not work")
    print("      with the actual dashboard. Before running, get real FN strings")
    print("      from browser DevTools → Network tab.\n")
    
    try:
        demo_basic_extraction()
        demo_multi_field_extraction()
        demo_batch_extraction()
        demo_error_handling()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        sys.exit(130)
    except Exception as e:
        print(f"\n\nDemo failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    print("\n" + "="*70)
    print("For production use, see tuple_tooltip.py CLI tool")
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
