"""Fetch energy contract tariffs from the Daisycon energy-nl API.

This calls the same JSON endpoint the embedded widget uses
(https://daisycon.tools/api/energy/netherlands/nl-NL/products). The widget's
own defaults (media_id=300811, publisher_id=19111) are required; the affiliate
mediaId from the embed snippet only goes into `placeholder_media_id`.

Usage:  py fetch_tariffs.py [--peak 1500] [--off-peak 1000] [--gas 1200] [--out tariffs.csv]
"""
import argparse
import csv
import json
import sys

import requests

API = "https://daisycon.tools/api/energy/netherlands/nl-NL/products"


def fetch_products(peak=1500, off_peak=1000, gas=1200, postal_code=None,
                   house_number=None, placeholder_media_id=415069,
                   tariff_types=("fixed", "variable", "dynamic")):
    params = {
        "placeholder_media_id": placeholder_media_id,
        "page": 1,
        "per_page": 100,
        "media_id": 300811,
        "publisher_id": 19111,
        "discount": "true",
        "electricity_usage_single": 0,
        "electricity_usage_peak": peak,
        "electricity_usage_off_peak": off_peak,
        "electricity_feed_in_single": 0,
        "electricity_feed_in_peak": 0,
        "electricity_feed_in_off_peak": 0,
        "energy_meter": "smart_double",
        "gas_usage": gas,
        "product_type": "electricity+gas" if gas else "electricity",
        "tariff_type[]": list(tariff_types),
        "tariff_sort": "lowest_total_price",
    }
    if postal_code and house_number:
        params["postal_code"] = postal_code
        params["house_number"] = house_number
    r = requests.get(API, params=params, timeout=30)
    r.raise_for_status()
    # The API sometimes prefixes PHP warnings / appends an error object; parse the first JSON object.
    raw = r.text
    obj, _ = json.JSONDecoder().raw_decode(raw, raw.index('{"data"'))
    return obj["data"]


def flatten(p):
    info = p["product"]["product_information"]
    prices = p["product"]["product_prices"]
    el = prices.get("electricity") or {}
    gas = prices.get("gas") or {}
    normal = el.get("normal_tariff") or {}
    low = el.get("low_tariff") or {}
    single = el.get("single_tariff") or {}
    feed_in = el.get("feed_in") or {}
    return {
        "product_id": p["id"],
        "provider": p["provider_name"],
        "contract": info["name"] or "",
        "tariff_type": info["tariff_type"],
        "duration_months": info["duration"],
        "el_peak_incl_per_kwh": normal.get("tariff_incl"),
        "el_offpeak_incl_per_kwh": low.get("tariff_incl"),
        "el_single_incl_per_kwh": single.get("tariff_incl"),
        "el_excl_per_kwh": normal.get("tariff_excl") or single.get("tariff_excl"),
        "el_feed_in_per_kwh": feed_in.get("tariff_single"),
        "el_fixed_supply_costs_year": el.get("fixed_supply_costs"),
        "el_network_costs_year": el.get("network_costs"),
        "gas_incl_per_m3": gas.get("tariff_incl"),
        "gas_excl_per_m3": gas.get("tariff_excl"),
        "gas_fixed_supply_costs_year": gas.get("fixed_supply_costs"),
        "gas_network_costs_year": gas.get("network_costs"),
        "network_operator": el.get("network_operator") or gas.get("network_operator"),
        "discount_total": (prices.get("action") or {}).get("discount_total"),
        "total_year_incl_discount": prices.get("total_year_cost_including_discount"),
        "total_year_excl_discount": prices.get("total_year_cost_excluding_discount"),
        "green_electricity_level": info["sustainability"]["electricity_level"],
        "link": info["link"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--peak", type=int, default=1500)
    ap.add_argument("--off-peak", type=int, default=1000)
    ap.add_argument("--gas", type=int, default=1200)
    ap.add_argument("--postal-code")
    ap.add_argument("--house-number")
    ap.add_argument("--out", default="tariffs.csv")
    a = ap.parse_args()

    rows = [flatten(p) for p in fetch_products(a.peak, a.off_peak, a.gas, a.postal_code, a.house_number)]
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} contracts -> {a.out}", file=sys.stderr)
    for r in rows:
        print(f"{r['provider']:<22} {r['contract']:<32} {r['tariff_type']:<8} "
              f"el {r['el_peak_incl_per_kwh'] or r['el_single_incl_per_kwh'] or 0:.4f}/kWh  "
              f"gas {r['gas_incl_per_m3'] or 0:.4f}/m3  "
              f"year €{r['total_year_incl_discount']:.0f}")


if __name__ == "__main__":
    main()
