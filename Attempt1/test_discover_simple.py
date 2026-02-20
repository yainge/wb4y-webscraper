#!/usr/bin/env python3
"""Test the discover function."""
import sys
from scraper4 import discover_available_fields

try:
    print("Starting field discovery...")
    fields = discover_available_fields()
    print(f"\n✓ Discovery complete! Found {len(fields)} fields")
except KeyboardInterrupt:
    print("\n⚠ Interrupted by user")
    sys.exit(130)
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
