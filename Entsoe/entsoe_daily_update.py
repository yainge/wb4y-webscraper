#!/usr/bin/env python3
"""
ENTSO-E Price Updater (Parquet)

Fetches prices (documentType=A44) from ENTSO-E and updates a partitioned
Parquet dataset on disk. Designed for safe, idempotent daily runs.

Partitions written as: {parquet_dir}/year=YYYY/month=MM/prices.parquet

Usage examples:
  python scripts/entsoe_daily_update.py \
    --zone 10YNL----------L --days 2 \
    --contract A01 --parquet-dir data/entsoe/parquet

  python scripts/entsoe_daily_update.py \
    --zone 10YNL----------L --start 202407010000 --end 202408010000 \
    --parquet-dir data/entsoe/parquet

Requires: pandas, pyarrow
Token: pass via --token or env ENTSOE_TOKEN / ENTSOE_SECURITY_TOKEN
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from typing import List, Dict, Optional, Tuple

import xml.etree.ElementTree as ET
from urllib.parse import urlencode
import urllib.request

import pandas as pd

BASE_URL = "https://web-api.tp.entsoe.eu/api"


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Update ENTSO-E prices to Parquet")
    p.add_argument("--zone", required=True, help="in_Domain EIC (e.g., 10YNL----------L)")
    p.add_argument("--out_Domain", dest="out_zone", help="out_Domain EIC (defaults to --zone)")
    p.add_argument("--contract", default="A01", help="A01=Day-ahead, A07=Intraday")
    p.add_argument("--start", help="periodStart UTC yyyyMMddHHmm")
    p.add_argument("--end", help="periodEnd UTC yyyyMMddHHmm")
    p.add_argument("--days", type=int, default=None, help="If set, pulls last N days; omit when using --start/--end")
    p.add_argument("--offset", type=int, default=0, help="ENTSO-E offset param (default 0)")
    p.add_argument("--token", help="ENTSO-E token; or env ENTSOE_TOKEN")
    p.add_argument("--timeout", type=int, default=60, help="HTTP timeout seconds")
    p.add_argument("--parquet-dir", default=os.path.join("data", "entsoe", "parquet"),
                  help="Directory to store partitioned parquet dataset")
    return p.parse_args(argv)


def yyyymmddhhmm(x: dt.datetime) -> str:
    return x.strftime('%Y%m%d%H%M')


def infer_range_from_days(days: int) -> Tuple[str, str]:
    now = dt.datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    start = now - dt.timedelta(days=days)
    return yyyymmddhhmm(start), yyyymmddhhmm(now + dt.timedelta(hours=1))


def parse_resolution(iso_duration: str) -> dt.timedelta:
    if not iso_duration or not iso_duration.startswith("PT"):
        raise ValueError(f"Unsupported resolution: {iso_duration}")
    s = iso_duration[2:]
    hours = minutes = seconds = 0
    num = ""
    for ch in s:
        if ch.isdigit():
            num += ch
            continue
        if ch == 'H':
            hours = int(num or 0); num = ""
        elif ch == 'M':
            minutes = int(num or 0); num = ""
        elif ch == 'S':
            seconds = int(num or 0); num = ""
        else:
            raise ValueError(f"Unsupported resolution component: {iso_duration}")
    return dt.timedelta(hours=hours, minutes=minutes, seconds=seconds)


def parse_xml_prices(xml_bytes: bytes) -> List[Dict[str, str]]:
    root = ET.fromstring(xml_bytes)
    if root.tag.startswith("{"):
        ns_uri = root.tag[1: root.tag.find('}')]
    else:
        ns_uri = ''

    def tag(name: str) -> str:
        return f"{{{ns_uri}}}{name}" if ns_uri else name

    results: List[Dict[str, str]] = []
    for ts in root.findall(f".//{tag('TimeSeries')}"):
        currency = None
        unit = None
        doc_el = root.find(f".//{tag('mRID')}")
        doc_mrid = doc_el.text.strip() if (doc_el is not None and doc_el.text) else None

        cur_el = ts.find(tag('currency_Unit.name'))
        if cur_el is not None and cur_el.text:
            currency = cur_el.text.strip()
        unit_el = ts.find(tag('price_Measure_Unit.name'))
        if unit_el is not None and unit_el.text:
            unit = unit_el.text.strip()

        for period in ts.findall(tag('Period')):
            res_el = period.find(tag('resolution'))
            res = res_el.text.strip() if res_el is not None and res_el.text else 'PT60M'
            step = parse_resolution(res)

            intv = period.find(tag('timeInterval')) or period.find(tag('PeriodTimeInterval'))
            start_el = intv.find(tag('start')) if intv is not None else None
            end_el = intv.find(tag('end')) if intv is not None else None
            if start_el is None or end_el is None or not start_el.text or not end_el.text:
                continue
            start = dt.datetime.fromisoformat(start_el.text.replace('Z', '+00:00')).astimezone(dt.timezone.utc)

            for point in period.findall(tag('Point')):
                pos_el = point.find(tag('position'))
                price_el = point.find(tag('price.amount'))
                if pos_el is None or price_el is None or not pos_el.text or not price_el.text:
                    continue
                try:
                    position = int(pos_el.text)
                    price = float(price_el.text)
                except ValueError:
                    continue
                ts_utc = (start + (position - 1) * step).replace(tzinfo=dt.timezone.utc)
                results.append({
                    'ts_utc': ts_utc.isoformat().replace('+00:00', 'Z'),
                    'price': price,
                    'currency': currency or 'EUR',
                    'unit': unit or 'MWH',
                    'resolution': res,
                    'document_mrid': doc_mrid,
                })
    return results


def build_url(token: str, start: str, end: str, zone: str, out_zone: Optional[str],
              contract: str, offset: int) -> str:
    params = {
        'documentType': 'A44',
        'periodStart': start,
        'periodEnd': end,
        'in_Domain': zone,
        'out_Domain': out_zone or zone,
        'contract_MarketAgreement.type': contract,
        'offset': offset,
        'securityToken': token,
    }
    return f"{BASE_URL}?{urlencode(params)}"


def http_get(url: str, timeout: int) -> bytes:
    req = urllib.request.Request(url, headers={'User-Agent': 'wb4u-entsoe/1.0'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def upsert_parquet(rows: List[Dict[str, str]], zone: str, contract: str, parquet_dir: str) -> int:
    if not rows:
        return 0
    df = pd.DataFrame(rows)
    df['bidding_zone'] = zone
    df['contract'] = contract
    df['ts_utc'] = pd.to_datetime(df['ts_utc'], utc=True)
    df['year'] = df['ts_utc'].dt.year
    df['month'] = df['ts_utc'].dt.month

    total = 0
    for (year, month), g in df.groupby(['year', 'month']):
        part_dir = os.path.join(parquet_dir, f"year={year}", f"month={month:02d}")
        os.makedirs(part_dir, exist_ok=True)
        file_path = os.path.join(part_dir, "prices.parquet")

        if os.path.exists(file_path):
            try:
                existing = pd.read_parquet(file_path)
            except Exception:
                existing = pd.DataFrame()
            combined = pd.concat([existing, g], ignore_index=True)
            combined = combined.drop_duplicates(subset=['bidding_zone', 'contract', 'ts_utc'], keep='last')
        else:
            combined = g

        combined = combined.sort_values('ts_utc')
        combined.to_parquet(file_path, index=False)
        total += len(combined)
    return total


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    token = args.token or os.getenv('ENTSOE_TOKEN') or os.getenv('ENTSOE_SECURITY_TOKEN')
    if not token:
        print("ERROR: Provide ENTSO-E token via --token or ENTSOE_TOKEN env var", file=sys.stderr)
        return 1

    if (args.days is not None) and (args.start or args.end):
        print("ERROR: Use either --days or --start/--end, not both", file=sys.stderr)
        return 1

    if args.days is not None:
        start, end = infer_range_from_days(args.days)
    else:
        if not args.start or not args.end:
            print("ERROR: --start and --end required when --days not set", file=sys.stderr)
            return 1
        start, end = args.start, args.end

    url = build_url(token, start, end, args.zone, args.out_zone, args.contract, args.offset)
    print(f"Fetching: {url}")
    data = http_get(url, timeout=args.timeout)

    # Optional: echo message if ENTSO-E error document
    if data.strip().startswith(b"<"):
        try:
            root = ET.fromstring(data)
            text_el = root.find('.//{*}text')
            if text_el is not None and text_el.text:
                print(f"ENTSO-E response message: {text_el.text}")
        except ET.ParseError:
            pass

    rows = parse_xml_prices(data)
    print(f"Parsed {len(rows)} price points")
    written = upsert_parquet(rows, args.zone, args.contract, args.parquet_dir)
    print(f"Upserted to Parquet partitions: {written} rows (zone={args.zone}, contract={args.contract})")
    print(f"Dataset root: {args.parquet_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
