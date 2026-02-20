#!/usr/bin/env python3
"""
Tuple-ID Based Tooltip Extraction for Tableau Public Dashboard.

Retrieves tariff data deterministically for a given tuple_id by calling
Tableau VizQL endpoints in sequence:
  1) bootstrapSession (fresh session each run)
  2) tabdoc/select-by-tuple-value (select mark by tuple-id)
  3) tabsrv/render-tooltip-server (fetch tooltip HTML)
  4) parse tooltip HTML into dict/CSV row

Dependencies: requests, requests-toolbelt, beautifulsoup4, playwright
Installation: pip install requests requests-toolbelt beautifulsoup4 playwright

Usage:
  python tuple_tooltip.py --tuple-id 2 \
    --fn-contract "[federated....].[none:Contractnaam:nk]" \
    --fn-supplier "[federated....].[none:Energie leveranciers:nk]" \
    --out tariffs.csv
"""

import argparse
import csv
import sys
import time
from pathlib import Path

try:
    from scraper4 import (
        capture_bootstrap_url,
        bootstrap_session,
        select_tuple,
        fetch_tooltip,
        parse_tooltip_table,
        extract_fn_strings_from_tooltip_response,
        discover_available_fields,
        VIEW_URL,
    )
except ImportError:
    print("Error: scraper4.py not found or import failed.", file=sys.stderr)
    print("Ensure scraper4.py is in the same directory.", file=sys.stderr)
    sys.exit(1)


def extract_tooltip_for_tuple(
    tuple_id: int,
    fn_contract: str,
    fn_supplier: str = None,
    retry_on_410: bool = True
) -> dict:
    """
    Workflow:
      a) bootstrap_url = capture_bootstrap_url()
      b) session, session_id = bootstrap_session(bootstrap_url)
      c) select_tuple(session, session_id, tuple_id, fn_contract)
         If fn_supplier provided, also call select_tuple with fn_supplier.
      d) tooltip_text = fetch_tooltip(session, session_id)
      e) return parse_tooltip_table(tooltip_text)
    
    Returns: dict with parsed tooltip fields + standardized keys.
    Raises: RuntimeError on unrecoverable failure.
    """
    try:
        print(f"\n{'='*70}")
        print(f"Extracting tooltip for tuple_id={tuple_id}")
        print(f"{'='*70}")
        
        # Step a: Capture fresh bootstrap session
        print("\n[1/5] Capturing bootstrap session...")
        bootstrap_url = capture_bootstrap_url(VIEW_URL)
        print(f"  [OK] Bootstrap URL: {bootstrap_url[:80]}...")
        
        # Step b: Initialize session
        print("\n[2/5] Initializing VizQL session...")
        session, session_id = bootstrap_session(bootstrap_url)
        print(f"  [OK] Session ID: {session_id}")
        
        # Step c: Select tuple by contract field
        print(f"\n[3/5] Selecting tuple {tuple_id} by Contractnaam...")
        select_tuple(session, session_id, tuple_id, fn_contract)
        
        # If supplier field provided, also select it
        if fn_supplier:
            print(f"\n[3b/5] Selecting tuple {tuple_id} by Energie leveranciers...")
            select_tuple(session, session_id, tuple_id, fn_supplier)
        
        # Step d: Fetch tooltip
        print(f"\n[4/5] Fetching tooltip HTML...")
        tooltip_html = fetch_tooltip(session, session_id)
        if not tooltip_html:
            raise RuntimeError("render-tooltip-server returned empty response.")
        print(f"  [OK] Tooltip Length: {len(tooltip_html)} chars")
        
        # Step e: Parse tooltip
        print(f"\n[5/5] Parsing tooltip...")
        parsed = parse_tooltip_table(tooltip_html)
        print(f"  [OK] Extracted {len(parsed)} fields")
        
        print(f"\n{'='*70}")
        print("SUCCESS\n")
        
        return parsed
        
    except Exception as e:
        if "410" in str(e) and retry_on_410:
            print(f"\n⚠ Session expired (410). Retrying once...")
            time.sleep(1)
            return extract_tooltip_for_tuple(
                tuple_id, fn_contract, fn_supplier, retry_on_410=False
            )
        raise RuntimeError(f"Failed to extract tooltip: {e}") from e


def print_result(row: dict):
    """Pretty-print tooltip result."""
    print("\nExtracted Fields:")
    print("-" * 70)
    for key, value in row.items():
        if value:
            print(f"  {key:40s} : {value}")
    print("-" * 70)


def append_to_csv(filepath: Path, row: dict, mode: str = "a"):
    """
    Append row to CSV file. If file doesn't exist or is empty, write header.
    Union all keys from all rows.
    """
    filepath = Path(filepath)
    fieldnames = list(row.keys())
    
    # Determine if we need to write header
    write_header = not filepath.exists() or filepath.stat().st_size == 0
    
    # Read existing fieldnames if file exists
    if filepath.exists() and filepath.stat().st_size > 0:
        with open(filepath, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames:
                # Union old and new fieldnames, preserving order
                fieldnames = list(dict.fromkeys(list(reader.fieldnames) + fieldnames))
    
    with open(filepath, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, restval="")
        if write_header:
            writer.writeheader()
        writer.writerow(row)
    
    print(f"[OK] Appended to {filepath}")


def main():
    parser = argparse.ArgumentParser(
        description="Extract tooltip data for a Tableau dashboard tuple by ID.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Discover available fields from the dashboard
  python tuple_tooltip.py --discover

  # Extract tuple 2 using single field selector
  python tuple_tooltip.py --tuple-id 2 \\
    --fn-contract "[federated....].[none:Contractnaam:nk]"

  # Extract tuple 2 with multiple selectors and save to CSV
  python tuple_tooltip.py --tuple-id 2 \\
    --fn-contract "[federated....].[none:Contractnaam:nk]" \\
    --fn-supplier "[federated....].[none:Energie leveranciers:nk]" \\
    --out tariffs.csv

  # Extract multiple tuples
  for i in 1 2 3; do
    python tuple_tooltip.py --tuple-id $i \\
      --fn-contract "[federated....].[none:Contractnaam:nk]" \\
      --out tariffs.csv
  done
        """
    )
    
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Discover available field names (FN strings) from the dashboard"
    )
    parser.add_argument(
        "--tuple-id",
        type=int,
        default=None,
        help="Tuple ID to extract (e.g., 2)"
    )
    parser.add_argument(
        "--fn-contract",
        type=str,
        default=None,
        help='Field name for contract selection, e.g., "[federated....].[none:Contractnaam:nk]"'
    )
    parser.add_argument(
        "--fn-supplier",
        type=str,
        default=None,
        help='(Optional) Field name for supplier selection, e.g., "[federated....].[none:Energie leveranciers:nk]"'
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="(Optional) CSV output file path. If exists, append; else create."
    )
    
    args = parser.parse_args()
    
    try:
        # Discover mode
        if args.discover:
            discover_available_fields()
            return
        
        # Normal extraction mode
        if not args.tuple_id or not args.fn_contract:
            parser.print_help()
            print("\n❌ Error: --tuple-id and --fn-contract are required (or use --discover)")
            sys.exit(1)
        # Extract tooltip
        result = extract_tooltip_for_tuple(
            tuple_id=args.tuple_id,
            fn_contract=args.fn_contract,
            fn_supplier=args.fn_supplier
        )
        
        # Display result
        print_result(result)
        
        # Optionally save to CSV
        if args.out:
            append_to_csv(Path(args.out), result)
        
        # Print key fields
        print("\nKey Fields:")
        print(f"  Contract Name    : {result.get('contract_name', 'N/A')}")
        print(f"  Supplier         : {result.get('supplier', 'N/A')}")
        print(f"  Contract Duration: {result.get('contract_duration', 'N/A')}")
        
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
