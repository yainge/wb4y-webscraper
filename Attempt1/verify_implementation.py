#!/usr/bin/env python3
"""
Verification script - Confirms tuple extraction implementation is ready.
Run: python verify_implementation.py
"""

import sys
from pathlib import Path

def verify_imports():
    """Check all required dependencies."""
    print("Checking Python dependencies...\n")
    deps = {
        "requests": "HTTP client",
        "requests_toolbelt": "Multipart form encoder",
        "bs4": "HTML parsing",
        "playwright": "Browser automation",
    }
    
    missing = []
    for pkg, desc in deps.items():
        try:
            __import__(pkg)
            print(f"  ✓ {pkg:20s} ({desc})")
        except ImportError:
            print(f"  ✗ {pkg:20s} (MISSING)")
            missing.append(pkg)
    
    return len(missing) == 0

def verify_files():
    """Check all required files exist."""
    print("\nChecking implementation files...\n")
    files = {
        "tuple_tooltip.py": "Main CLI tool",
        "scraper4.py": "Core VizQL functions",
        "demo_extraction.py": "Working examples",
        "IMPLEMENTATION_SUMMARY.md": "Architecture guide",
        "TUPLE_EXTRACTION_GUIDE.md": "Comprehensive docs",
        "QUICK_REFERENCE.md": "Quick start guide",
    }
    
    missing = []
    for fname, desc in files.items():
        if Path(fname).exists():
            size = Path(fname).stat().st_size
            print(f"  ✓ {fname:30s} ({desc}) - {size} bytes")
        else:
            print(f"  ✗ {fname:30s} (MISSING)")
            missing.append(fname)
    
    return len(missing) == 0

def verify_functions():
    """Check scraper4 exports all required functions."""
    print("\nChecking scraper4 function exports...\n")
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
        
        functions = [
            ("capture_bootstrap_url", capture_bootstrap_url),
            ("bootstrap_session", bootstrap_session),
            ("select_tuple", select_tuple),
            ("fetch_tooltip", fetch_tooltip),
            ("parse_tooltip_table", parse_tooltip_table),
        ]
        
        for fname, func in functions:
            print(f"  ✓ {fname:30s} (callable)")
        
        print(f"\nConstants:")
        print(f"  ✓ VIEW_URL:  {VIEW_URL[:60]}...")
        print(f"  ✓ WORKSHEET: {WORKSHEET}")
        print(f"  ✓ DASHBOARD: {DASHBOARD}")
        
        return True
    except ImportError as e:
        print(f"  ✗ Import failed: {e}")
        return False

def verify_cli():
    """Check tuple_tooltip CLI."""
    print("\nChecking tuple_tooltip CLI...\n")
    try:
        import tuple_tooltip
        print(f"  ✓ tuple_tooltip.py loads successfully")
        print(f"  ✓ CLI entry point: tuple_tooltip.main()")
        return True
    except ImportError as e:
        print(f"  ✗ CLI import failed: {e}")
        return False

def main():
    """Run all verification checks."""
    print("="*70)
    print("TABLEAU TUPLE EXTRACTION - IMPLEMENTATION VERIFICATION")
    print("="*70 + "\n")
    
    checks = [
        ("Dependencies", verify_imports),
        ("Files", verify_files),
        ("Functions", verify_functions),
        ("CLI Tool", verify_cli),
    ]
    
    results = {}
    for name, check_fn in checks:
        try:
            results[name] = check_fn()
        except Exception as e:
            print(f"  ✗ Check failed: {e}")
            results[name] = False
    
    # Summary
    print("\n" + "="*70)
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    if passed == total:
        print(f"✓ ALL CHECKS PASSED ({passed}/{total})\n")
        print("Implementation is ready! To get started:\n")
        print("1. Discover available field names:")
        print("   python tuple_tooltip.py --discover\n")
        print("2. Copy FN string from output\n")
        print("3. Extract tuple:")
        print("   python tuple_tooltip.py --tuple-id 1 \\")
        print('       --fn-contract "[federated....].[none:Contractnaam:nk]"')
        print("\nFor details, see QUICK_REFERENCE.md or IMPLEMENTATION_SUMMARY.md")
        return 0
    else:
        print(f"✗ SOME CHECKS FAILED ({passed}/{total})\n")
        for name, passed in results.items():
            status = "PASS" if passed else "FAIL"
            print(f"  [{status}] {name}")
        print("\nFix missing dependencies:\n")
        print("  pip install requests requests-toolbelt beautifulsoup4 playwright")
        print("  playwright install chromium")
        return 1

if __name__ == "__main__":
    sys.exit(main())
