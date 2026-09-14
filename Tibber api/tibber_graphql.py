"""
Historic consumption / production / prices from the Tibber GraphQL API (the "old" API).

    POST https://api.tibber.com/v1-beta/gql     Authorization: Bearer <personal access token>

The Data API (data-api.tibber.com) only covers paired devices; the home's own history lives here:
    viewer.homes[].consumption(resolution: HOURLY|DAILY|WEEKLY|MONTHLY|ANNUAL)  kWh, cost, unitPrice per period
    viewer.homes[].production(...)                                             kWh fed back, profit (solar)
    viewer.homes[].currentSubscription.priceInfoRange(resolution: QUARTER_HOURLY|HOURLY|DAILY)  price history (total/energy/tax)
All three are Relay-style connections: fetch the newest ``last: N`` and walk back with ``before: pageInfo.startCursor``
until ``hasPreviousPage`` is false (or until the requested start date). ``from``/``startsAt`` carry the home's
UTC offset; stored here as ``ts_utc`` (start of the period).

Token: create a personal access token at https://developer.tibber.com/settings/access-token and put it in the
repo-root .env as TIBBER_TOKEN. (The old public demo token no longer works - "invalid token".)
Queries were validated against the live schema via introspection on 2026-09-14.

Outputs (in ./data):
    consumption_<resolution>.parquet   ts_utc, ts_end_utc, home_id, consumption_kwh, cost, unit_price, unit_price_vat, currency, source
    production_<resolution>.parquet    ts_utc, ts_end_utc, home_id, production_kwh, profit, unit_price, unit_price_vat, currency, source
    prices_<resolution>.parquet        ts_utc, home_id, total, energy, tax, level, currency, source

Usage:
    python tibber_graphql.py info                                   # login, homes, subscription
    python tibber_graphql.py consumption --resolution HOURLY --since 2025-01-01
    python tibber_graphql.py consumption --resolution DAILY         # everything available
    python tibber_graphql.py production --resolution HOURLY
    python tibber_graphql.py prices --since 2026-01-01              # --resolution QUARTER_HOURLY|HOURLY|DAILY
    python tibber_graphql.py update                                 # hourly consumption+production+prices, incremental
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys

import pandas as pd
import requests

from common import DATA_DIR, describe, env, upsert_parquet

GQL_URL = "https://api.tibber.com/v1-beta/gql"
USER_AGENT = "wb4u-tibber/0.1 (github.com/yainge/wb4y-webscraper)"
ENERGY_RESOLUTIONS = ("HOURLY", "DAILY", "WEEKLY", "MONTHLY", "ANNUAL")
PRICE_RESOLUTIONS = ("QUARTER_HOURLY", "HOURLY", "DAILY")
PAGE = {"QUARTER_HOURLY": 2976, "HOURLY": 744, "DAILY": 366, "WEEKLY": 104, "MONTHLY": 60, "ANNUAL": 20}  # ~a month/year per page

INFO_QUERY = """
{ viewer { login userId name
    homes { id appNickname timeZone type
      address { address1 postalCode city }
      meteringPointData { consumptionEan gridCompany estimatedAnnualConsumption }
      currentSubscription { status validFrom priceInfo { current { total energy tax startsAt currency } } } } } }
"""

CONSUMPTION_QUERY = """
query ($home: ID!, $res: EnergyResolution!, $last: Int!, $before: String) {
  viewer { home(id: $home) {
    consumption(resolution: $res, last: $last, before: $before) {
      pageInfo { startCursor hasPreviousPage count }
      nodes { from to consumption consumptionUnit cost unitPrice unitPriceVAT currency } } } } }
"""

PRODUCTION_QUERY = """
query ($home: ID!, $res: EnergyResolution!, $last: Int!, $before: String) {
  viewer { home(id: $home) {
    production(resolution: $res, last: $last, before: $before) {
      pageInfo { startCursor hasPreviousPage count }
      nodes { from to production productionUnit profit unitPrice unitPriceVAT currency } } } } }
"""

PRICE_QUERY = """
query ($home: ID!, $res: PriceInfoRangeResolution!, $last: Int!, $before: String) {
  viewer { home(id: $home) { currentSubscription {
    priceInfoRange(resolution: $res, last: $last, before: $before) {
      pageInfo { startCursor hasPreviousPage count }
      nodes { startsAt total energy tax level currency } } } } } }
"""


class TibberGraphQL:
    def __init__(self, token: str, verbose: bool = False):
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT})
        self.verbose = verbose

    def query(self, query: str, variables: dict | None = None) -> dict:
        r = self.session.post(GQL_URL, json={"query": query, "variables": variables or {}}, timeout=60)
        if self.verbose:
            print(f"  POST gql {variables} -> {r.status_code}", file=sys.stderr)
        r.raise_for_status()
        payload = r.json()
        if payload.get("errors"):
            raise RuntimeError(f"GraphQL error: {payload['errors'][0].get('message', payload['errors'])}")
        return payload["data"]

    def info(self) -> dict:
        return self.query(INFO_QUERY)["viewer"]

    def home_ids(self) -> list[str]:
        return [h["id"] for h in self.info()["homes"]]

    def walk_back(self, kind: str, home_id: str, resolution: str, since: pd.Timestamp | None) -> list[dict]:
        """Collect nodes newest-first page by page until ``since`` is reached or history is exhausted."""
        query = {"consumption": CONSUMPTION_QUERY, "production": PRODUCTION_QUERY, "prices": PRICE_QUERY}[kind]
        nodes, before = [], None
        while True:
            data = self.query(query, {"home": home_id, "res": resolution, "last": PAGE[resolution], "before": before})
            home = data["viewer"]["home"]
            conn = (home["currentSubscription"] or {}).get("priceInfoRange") if kind == "prices" else home[kind]
            if conn is None:
                raise RuntimeError("no active subscription for this home - no price history")
            page = conn["nodes"] or []
            nodes.extend(page)
            if self.verbose:
                first = page[0].get("from") or page[0].get("startsAt") if page else None
                print(f"  {kind} {resolution}: {len(page)} nodes, oldest {first}, total so far {len(nodes)}", file=sys.stderr)
            if not page or not conn["pageInfo"]["hasPreviousPage"]:
                break
            oldest = pd.to_datetime(page[0].get("from") or page[0].get("startsAt"), utc=True)
            if since is not None and oldest <= since:
                break
            before = conn["pageInfo"]["startCursor"]
        return nodes


# ----------------------------------------------------------------------------- frames
def energy_frame(nodes: list[dict], home_id: str, kind: str) -> pd.DataFrame:
    if not nodes:
        return pd.DataFrame()
    df = pd.DataFrame(nodes)
    value = "consumption" if kind == "consumption" else "production"
    out = pd.DataFrame(
        {
            "ts_utc": pd.to_datetime(df["from"], utc=True),
            "ts_end_utc": pd.to_datetime(df["to"], utc=True),
            "home_id": home_id,
            f"{value}_kwh": pd.to_numeric(df[value], errors="coerce"),
            "cost" if kind == "consumption" else "profit": pd.to_numeric(df["cost" if kind == "consumption" else "profit"], errors="coerce"),
            "unit_price": pd.to_numeric(df["unitPrice"], errors="coerce"),
            "unit_price_vat": pd.to_numeric(df["unitPriceVAT"], errors="coerce"),
            "currency": df["currency"],
            "source": "tibber-gql",
        }
    )
    return out.sort_values("ts_utc").reset_index(drop=True)


def price_frame(nodes: list[dict], home_id: str) -> pd.DataFrame:
    if not nodes:
        return pd.DataFrame()
    df = pd.DataFrame(nodes)
    out = pd.DataFrame(
        {
            "ts_utc": pd.to_datetime(df["startsAt"], utc=True),
            "home_id": home_id,
            "total": pd.to_numeric(df["total"], errors="coerce"),
            "energy": pd.to_numeric(df["energy"], errors="coerce"),
            "tax": pd.to_numeric(df["tax"], errors="coerce"),
            "level": df["level"],
            "currency": df["currency"],
            "source": "tibber-gql",
        }
    )
    return out.sort_values("ts_utc").reset_index(drop=True)


def last_stored(path) -> pd.Timestamp | None:
    if not path.exists():
        return None
    ts = pd.to_datetime(pd.read_parquet(path, columns=["ts_utc"])["ts_utc"], utc=True)
    return ts.max() if len(ts) else None


def pull(api: TibberGraphQL, kind: str, home_id: str, resolution: str, since: pd.Timestamp | None, save: bool) -> pd.DataFrame:
    nodes = api.walk_back(kind, home_id, resolution, since)
    df = price_frame(nodes, home_id) if kind == "prices" else energy_frame(nodes, home_id, kind)
    if since is not None and not df.empty:
        df = df[df["ts_utc"] >= since].reset_index(drop=True)
    label = f"{kind} {resolution}"
    print(describe(df, label))
    if save and not df.empty:
        path = DATA_DIR / f"{kind}_{resolution.lower()}.parquet"
        total = upsert_parquet(df, path, key=["home_id", "ts_utc"])
        print(f"   upserted -> {path.name} ({len(total)} rows total)")
    return df


# ----------------------------------------------------------------------------- CLI
def _since(arg: str | None) -> pd.Timestamp | None:
    return pd.Timestamp(arg, tz="UTC") if arg else None


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["info", "consumption", "production", "prices", "update"])
    p.add_argument("--resolution", default="HOURLY", choices=sorted(set(ENERGY_RESOLUTIONS) | set(PRICE_RESOLUTIONS)))
    p.add_argument("--since", help="ISO date; default: all history the API has")
    p.add_argument("--home", help="home id (default: TIBBER_HOME_ID if it exists in this account, else every home)")
    p.add_argument("--no-save", action="store_true")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args(argv)

    token = env("TIBBER_TOKEN")
    if not token:
        print("TIBBER_TOKEN not set - create one at https://developer.tibber.com/settings/access-token", file=sys.stderr)
        return 2
    api = TibberGraphQL(token, verbose=args.verbose)

    try:
        viewer = api.info()
    except (requests.RequestException, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3
    homes = viewer["homes"]
    if args.command == "info":
        print(f"login: {viewer.get('login')}  name: {viewer.get('name')}")
        for h in homes:
            sub = h.get("currentSubscription") or {}
            cur = (sub.get("priceInfo") or {}).get("current") or {}
            addr = h.get("address") or {}
            print(f"\nhome {h['id']}  '{h.get('appNickname')}'  {addr.get('postalCode')} {addr.get('city')}  tz={h.get('timeZone')}")
            print(f"   subscription: {sub.get('status')} since {sub.get('validFrom')}   price now: {cur.get('total')} {cur.get('currency')} ({cur.get('startsAt')})")
            print(f"   metering: {h.get('meteringPointData')}")
        return 0

    wanted = args.home or env("TIBBER_HOME_ID")
    ids = [h["id"] for h in homes if not wanted or h["id"] == wanted] or [h["id"] for h in homes]
    since = _since(args.since)
    allowed = PRICE_RESOLUTIONS if args.command == "prices" else ENERGY_RESOLUTIONS
    if args.command != "update" and args.resolution not in allowed:
        print(f"{args.command} supports --resolution {allowed}", file=sys.stderr)
        return 2
    save = not args.no_save
    DATA_DIR.mkdir(exist_ok=True)
    for home_id in ids:
        print(f"\nhome {home_id}")
        try:
            if args.command == "update":
                for kind, res in (("consumption", "HOURLY"), ("production", "HOURLY"), ("prices", "HOURLY")):
                    path = DATA_DIR / (f"{kind}_hourly.parquet")
                    last = last_stored(path)
                    pull(api, kind, home_id, res, (last - pd.Timedelta(days=2)) if last is not None else since, save)
            else:
                pull(api, args.command, home_id, args.resolution, since, save)
        except (requests.RequestException, RuntimeError) as exc:
            print(f"   ERROR: {exc}", file=sys.stderr)
            return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
