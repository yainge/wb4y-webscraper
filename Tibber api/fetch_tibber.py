"""
Extract data from the Tibber Data API into parquet files (one per device x resolution).

The API exposes the third-party devices paired in the Tibber app (EV, charger, heat pump / thermostat,
inverter, battery) plus a live stream for Tibber Pulse / Watty meters. It does NOT expose prices or the
home's hourly consumption - those live in the GraphQL API (api.tibber.com), see README.

Outputs (in ./data):
    devices_<home>.json                        raw device catalog (info, supportedHistory, attributes, capabilities)
    history_<device-slug>_<resolution>.parquet ts_utc, ts_local, home_id, device_id, resolution, source, <flattened data.* keys>
    device_state.parquet                       one row per device x capability per snapshot (for devices without history)

Usage:
    python fetch_tibber.py homes
    python fetch_tibber.py devices                         # devices of TIBBER_HOME_ID (or the first home)
    python fetch_tibber.py device <deviceId>               # attributes + capabilities (current state)
    python fetch_tibber.py history <deviceId> --resolution hour --since 2026-09-01      # print + save
    python fetch_tibber.py update                          # every device, every resolution, incremental (daily job)
    python fetch_tibber.py update --backfill               # first run: everything the API retains
    python fetch_tibber.py snapshot                        # append the current state of every device (schedule this)
    python fetch_tibber.py live --count 10                 # 10 live meter measurements (data-api-meters-read)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys

import pandas as pd

from common import DATA_DIR, LOCAL_TZ, describe, env, upsert_parquet
from tibber_client import RESOLUTIONS, AuthError, TibberApiError, TibberDataClient

BACKFILL_SINCE = "2000-01-01T00:00:00Z"  # the API clamps this to the first stored record
# step back one unit when resuming from the last stored timestamp so a partially-stored unit is re-fetched
RESUME_OVERLAP = {"quarterHour": pd.Timedelta(hours=1), "hour": pd.Timedelta(days=1), "day": pd.Timedelta(days=2), "month": pd.Timedelta(days=62)}


# ----------------------------------------------------------------------------- helpers
def resolve_home(client: TibberDataClient, home_arg: str | None) -> str:
    home_id = home_arg or env("TIBBER_HOME_ID")
    if home_id:
        return home_id
    homes = client.homes()
    if not homes:
        raise SystemExit("no homes visible for this token (scope data-api-homes-read missing?)")
    if len(homes) > 1:
        print(f"multiple homes, using the first; set TIBBER_HOME_ID or --home: {[(h['id'], h['name']) for h in homes]}")
    return homes[0]["id"]


def device_slug(device: dict) -> str:
    info = device.get("info") or {}
    label = "-".join(x for x in (info.get("brand"), info.get("model") or info.get("name")) if x)
    label = re.sub(r"[^A-Za-z0-9]+", "-", label).strip("-").lower() or "device"
    return f"{label}-{re.sub(r'[^A-Za-z0-9]', '', device['id'])[:8]}"


def history_path(device: dict, resolution: str):
    return DATA_DIR / f"history_{device_slug(device)}_{resolution}.parquet"


def items_to_frame(items: list[dict], home_id: str, device_id: str, resolution: str) -> pd.DataFrame:
    if not items:
        return pd.DataFrame()
    df = pd.json_normalize(items, sep=".")
    df = df.rename(columns={c: c[5:] for c in df.columns if c.startswith("data.")})
    # ``time`` carries the home's UTC offset -> keep the local wall time and add a UTC key
    ts_local = pd.to_datetime(df.pop("time"), utc=True).dt.tz_convert(LOCAL_TZ)
    out = pd.DataFrame(
        {
            "ts_utc": ts_local.dt.tz_convert("UTC"),
            "ts_local": ts_local.dt.tz_localize(None),
            "home_id": home_id,
            "device_id": device_id,
            "resolution": resolution,
            "source": "tibber",
        }
    )
    return pd.concat([out, df.reset_index(drop=True)], axis=1)


def last_timestamp(path) -> pd.Timestamp | None:
    if not path.exists():
        return None
    ts = pd.to_datetime(pd.read_parquet(path, columns=["ts_utc"])["ts_utc"], utc=True)
    return ts.max() if len(ts) else None


def fetch_history(client, home_id: str, device: dict, resolution: str, since: str | None, until: str | None) -> pd.DataFrame:
    items = list(client.history(home_id, device["id"], resolution, since=since, until=until))
    return items_to_frame(items, home_id, device["id"], resolution)


# ----------------------------------------------------------------------------- commands
def cmd_homes(client, _args) -> int:
    for h in client.homes():
        print(f"{h['id']}  {h['name']}")
    return 0


def cmd_devices(client, args) -> int:
    home_id = resolve_home(client, args.home)
    devices = client.devices(home_id)
    if not devices:
        print("no devices - either nothing is paired in the Tibber app or the token lacks the category scopes")
        return 0
    print(f"{'device id':<40} {'brand / model / name':<45} {'history':<28} retention")
    for d in devices:
        info, hist = d.get("info") or {}, d.get("supportedHistory") or {}
        label = " / ".join(str(x) for x in (info.get("brand"), info.get("model"), info.get("name")) if x)
        res = ",".join(hist.get("resolutions") or []) or "-"
        print(f"{d['id']:<40} {label[:45]:<45} {res:<28} {hist.get('maxRetentionDays', '?')} d")
    if args.save:
        DATA_DIR.mkdir(exist_ok=True)
        full = [client.device(home_id, d["id"]) for d in devices]
        path = DATA_DIR / f"devices_{home_id[:8]}.json"
        path.write_text(json.dumps(full, indent=2), encoding="utf-8")
        print(f"\nsaved full device details to {path}")
    return 0


def cmd_device(client, args) -> int:
    home_id = resolve_home(client, args.home)
    d = client.device(home_id, args.device_id)
    info, hist = d.get("info") or {}, d.get("supportedHistory") or {}
    print(f"id          : {d['id']}\nexternal id : {d.get('externalId')}")
    print(f"info        : {info}")
    print(f"last seen   : {(d.get('status') or {}).get('lastSeen')}")
    print(f"history     : {hist.get('resolutions')}  retention={hist.get('maxRetentionDays')} days")
    print("\nattributes (seldom changing):")
    for a in d.get("attributes") or []:
        print(f"  {a.get('id'):<40} {a.get('value')!s:<30} [{a.get('$type', '')}]")
    print("\ncapabilities (current state):")
    for c in d.get("capabilities") or []:
        unit = c.get("unit") or (f"one of {c['availableValues']}" if c.get("availableValues") else "")
        print(f"  {c.get('id'):<40} {c.get('value')!s:<15} {unit:<20} {c.get('description', '')}")
    if args.json:
        print("\n" + json.dumps(d, indent=2))
    return 0


def cmd_history(client, args) -> int:
    home_id = resolve_home(client, args.home)
    device = client.device(home_id, args.device_id)
    supported = (device.get("supportedHistory") or {}).get("resolutions") or []
    if args.resolution not in supported:
        print(f"device supports history resolutions {supported}, not {args.resolution!r}", file=sys.stderr)
        return 1
    since = args.since or (None if args.until else BACKFILL_SINCE)
    print(f"{device_slug(device)}  resolution={args.resolution}  since={since}  until={args.until}")
    df = fetch_history(client, home_id, device, args.resolution, since, args.until)
    print(describe(df, "history"))
    if not df.empty:
        with pd.option_context("display.width", 200, "display.max_columns", 30):
            print(df.drop(columns=["home_id", "device_id", "source", "resolution"]).tail(args.rows).to_string(index=False))
        if not args.no_save:
            path = history_path(device, args.resolution)
            total = upsert_parquet(df, path, key=["device_id", "ts_utc"])
            print(f"\nupserted -> {path} ({len(total)} rows total)")
    return 0


def cmd_update(client, args) -> int:
    """Incremental pull for every device x resolution: resume from the last stored ts (minus an overlap)."""
    home_id = resolve_home(client, args.home)
    devices = client.devices(home_id)
    wanted = [args.resolution] if args.resolution else list(RESOLUTIONS)
    todo = [(d, r) for d in devices for r in (d.get("supportedHistory") or {}).get("resolutions") or [] if r in wanted]
    if not todo:
        print("nothing to do: no device with history support (or --resolution not supported)")
        return 0
    failures = 0
    for device, resolution in todo:
        path = history_path(device, resolution)
        last = None if args.backfill else last_timestamp(path)
        since = (last - RESUME_OVERLAP[resolution]).isoformat() if last is not None else BACKFILL_SINCE
        try:
            df = fetch_history(client, home_id, device, resolution, since, None)
        except TibberApiError as exc:
            failures += 1
            print(f"  {device_slug(device)} {resolution}: {exc}", file=sys.stderr)
            continue
        if df.empty:
            print(f"  {device_slug(device):<40} {resolution:<12} no new rows (since {since[:19]})")
            continue
        total = upsert_parquet(df, path, key=["device_id", "ts_utc"])
        print(f"  {device_slug(device):<40} {resolution:<12} +{len(df):>5} rows -> {len(total):>6} total  ({path.name})")
    return 1 if failures else 0


def cmd_snapshot(client, args) -> int:
    """Record the current capabilities of every device (long format). The only time series for devices without history."""
    home_id = resolve_home(client, args.home)
    now = pd.Timestamp.now(tz="UTC").floor("s")
    rows = []
    for d in client.devices(home_id):
        full = client.device(home_id, d["id"])
        info = full.get("info") or {}
        last_seen = (full.get("status") or {}).get("lastSeen")
        for c in full.get("capabilities") or []:
            num = pd.to_numeric(pd.Series([c.get("value")]), errors="coerce").iloc[0]
            rows.append(
                {
                    "ts_utc": now,
                    "home_id": home_id,
                    "device_id": full["id"],
                    "device": " ".join(str(x) for x in (info.get("brand"), info.get("model")) if x),
                    "capability": c.get("id"),
                    "value_num": num,
                    "value_str": None if pd.notna(num) else str(c.get("value")),
                    "unit": c.get("unit"),
                    "last_seen": pd.to_datetime(last_seen, utc=True) if last_seen else pd.NaT,
                    "source": "tibber",
                }
            )
    df = pd.DataFrame(rows)
    if df.empty:
        print("no capabilities returned")
        return 1
    with pd.option_context("display.width", 200):
        print(df[["device", "capability", "value_num", "value_str", "unit", "last_seen"]].to_string(index=False))
    path = DATA_DIR / "device_state.parquet"
    total = upsert_parquet(df, path, key=["device_id", "capability", "ts_utc"])
    print(f"\n{len(df)} values at {now} -> {path} ({len(total)} rows, {total['ts_utc'].nunique()} snapshots)")
    return 0


def cmd_live(client, args) -> int:
    home_id = resolve_home(client, args.home)
    device_ids = args.device or [d["id"] for d in client.live_event_devices(home_id)][:5]
    if not device_ids:
        print("no streamable meters in this home (scope data-api-meters-read missing, or no Pulse/Watty)")
        return 1
    print(f"streaming {device_ids} - Ctrl+C to stop")
    seen = 0
    for event, payload in client.stream_live(home_id, device_ids):
        if event == "measurement":
            seen += 1
            keys = ("timestamp", "power", "powerProduction", "accumulatedConsumption", "accumulatedProduction")
            print("  " + "  ".join(f"{k}={payload.get(k)}" for k in keys if k in payload))
            if args.count and seen >= args.count:
                break
        elif event == "stream_error":
            print(f"  stream_error: {payload}", file=sys.stderr)
            if not payload.get("transient"):
                return 1
        elif event == "ping":
            pass
    return 0


# ----------------------------------------------------------------------------- main
def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--home", help="home id (default: TIBBER_HOME_ID from .env, else the first home)")
    p.add_argument("--verbose", "-v", action="store_true", help="log every request")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("homes", help="list homes")
    s = sub.add_parser("devices", help="list devices of a home")
    s.add_argument("--save", action="store_true", help="also dump full device details to data/devices_<home>.json")
    s = sub.add_parser("device", help="show attributes + capabilities of one device")
    s.add_argument("device_id")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("history", help="fetch history for one device")
    s.add_argument("device_id")
    s.add_argument("--resolution", default="hour", choices=RESOLUTIONS)
    s.add_argument("--since", help="ISO date/datetime; forward pagination (default: everything retained)")
    s.add_argument("--until", help="ISO date/datetime; backward pagination from this point")
    s.add_argument("--rows", type=int, default=12, help="rows to print")
    s.add_argument("--no-save", action="store_true")
    s = sub.add_parser("update", help="incremental update of every device x resolution into parquet")
    s.add_argument("--resolution", choices=RESOLUTIONS)
    s.add_argument("--backfill", action="store_true", help="ignore stored data and refetch all retained history")
    sub.add_parser("snapshot", help="append the current capability values of every device to data/device_state.parquet")
    s = sub.add_parser("live", help="print live meter measurements (SSE)")
    s.add_argument("--device", action="append", help="deviceId (repeatable, max 5); default: all streamable")
    s.add_argument("--count", type=int, default=10, help="stop after N measurements (0 = forever)")
    args = p.parse_args(argv)

    for name in ("since", "until"):  # accept plain dates on the CLI
        val = getattr(args, name, None)
        if val and re.fullmatch(r"\d{4}-\d{2}-\d{2}", val):
            setattr(args, name, dt.datetime.fromisoformat(val).strftime("%Y-%m-%dT00:00:00") + "Z")

    client = TibberDataClient(verbose=args.verbose)
    handler = {"homes": cmd_homes, "devices": cmd_devices, "device": cmd_device, "history": cmd_history, "update": cmd_update, "snapshot": cmd_snapshot, "live": cmd_live}
    try:
        return handler[args.command](client, args)
    except AuthError as exc:
        print(f"AUTH: {exc}", file=sys.stderr)
        return 2
    except TibberApiError as exc:
        print(f"API: {exc}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
