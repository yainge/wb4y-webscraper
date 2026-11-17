"""Weekly tariff collection for fixed and variable energy contracts.

Two kinds of sources:
  * public tariff pages (plain HTTP), e.g. SamenOM
  * sign-up flows walked in a normal browser up to the offer page, e.g.
    PowerPeers and Pure Energie, with hard stops (see below)

Ground rules (keep these when adding suppliers):
  * Only suppliers whose website terms do NOT forbid copying/reuse of site
    content. Checked 2026-11-17; see TERMS below. Re-check yearly.
  * robots.txt is checked before every site; disallowed URLs are skipped.
  * A supplier that blocks automated access (e.g. a 403 from a bot filter)
    stays manual. Don't work around it.
  * Plain browser defaults (nl-NL locale, Amsterdam timezone, normal
    viewport). No disguise of the automation.
  * HARD STOPS in sign-up flows: only allow-listed fields are filled
    (postcode, house number, usage); clicks on anything that submits or
    continues to personal details are refused (FORBIDDEN); navigation to
    details/confirmation pages is aborted (FORBIDDEN_NAV). The script stops
    on the offer page.

Usage:
  .venv/Scripts/python.exe "Energy provider scraper/supplier_tariffs.py"
  .venv/Scripts/python.exe "Energy provider scraper/supplier_tariffs.py" --no-save --only PowerPeers
  .venv/Scripts/python.exe "Energy provider scraper/supplier_tariffs.py" --headed
"""
import argparse
import csv
import re
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

OUT_CSV = Path(__file__).parent / "data" / "supplier_tariffs.csv"

# Address and usage used in the sign-up flows.
POSTCODE, HOUSE_NUMBER = "5621AK", "54"
ELECTRICITY_KWH, GAS_M3 = 2400, 800          # Pure Energie: filled in
POWERPEERS_HOME, POWERPEERS_PERSONS = "Tussenwoning", "2 personen"  # PowerPeers estimates from this

FIELDS = [
    "scraped_at", "supplier", "product", "product_id", "period", "source", "vat_included",
    "el_normal_tariff", "el_normal_tax", "el_normal_total",
    "el_low_tariff", "el_low_tax", "el_low_total",
    "el_single_tariff", "el_single_tax", "el_single_total",
    "feed_in", "gas_tariff", "gas_tax", "gas_total",
    "fixed_supply_per_day", "fixed_supply_el_per_day", "fixed_supply_gas_per_day",
    "welcome_discount", "monthly_amount", "el_usage_kwh", "gas_usage_m3", "postcode",
    "source_url",
]

TERMS = {  # result of the website-terms check, 2026-11-17
    "SamenOM": "geen verbod gevonden (samenom.nl/voorwaarden)",
    "PowerPeers": "geen websitevoorwaarden gevonden; alleen contractvoorwaarden en privacy",
    "Pure Energie": "geen verbod gevonden (pure-energie.nl/voorwaarden)",
}

MANUAL = {  # not automated, and why
    "Budget Thuis": "disclaimer verbiedt hergebruik + robots.txt blokkeert aanbod-op-maat",
    "Eneco": "disclaimer verbiedt reproduceren/gebruiken zonder toestemming",
    "Oxxio": "disclaimer verbiedt reproduceren/gebruiken zonder toestemming",
    "Vandebron": "voorwaarden verbieden reproduceren/gebruiken zonder toestemming",
    "Greenchoice": "disclaimer verbiedt opslaan in geautomatiseerd gegevensbestand",
    "Energiek": "gebruiksvoorwaarden art. 8 verbieden hergebruik van gegevens",
    "Vattenfall": "voorwaarden verbieden kopiëren/verveelvoudigen zonder toestemming",
    "UnitedConsumers": "disclaimer verbiedt elektronisch kopiëren zonder toestemming",
    "Essent": "blokkeert automatische toegang (403)",
    "Energiedirect": "blokkeert automatische toegang (403)",
}

FORBIDDEN = re.compile(
    r"afrond|aanvra|bevestig|bestel|akkoord|verstuur|verzend|onderteken|betal|klant worden|"
    r"aanmelden|contract afsluiten|sluit af|gegevens in|prijs bewaren|mail mij|bewaar", re.I)
FORBIDDEN_NAV = re.compile(r"gegevens|afronden|bevestig|bedankt|checkout|betalen|overzicht", re.I)

session = requests.Session()
USER_AGENT = session.headers["User-Agent"]
_robots: dict[str, RobotFileParser] = {}


class Blocked(Exception):
    pass


class HardStop(Exception):
    pass


def allowed(url: str) -> bool:
    root = "{0.scheme}://{0.netloc}".format(urlparse(url))
    if root not in _robots:
        rp = RobotFileParser()
        r = session.get(root + "/robots.txt", timeout=20)
        rp.parse(r.text.splitlines() if r.ok else [])
        _robots[root] = rp
    return _robots[root].can_fetch(USER_AGENT, url)


def fetch(url: str) -> bytes:
    if not allowed(url):
        raise Blocked(f"robots.txt staat {url} niet toe")
    r = session.get(url, timeout=30)
    if r.status_code in (401, 403, 429):
        raise Blocked(f"{r.status_code} van {urlparse(url).netloc}; site weigert automatische toegang")
    r.raise_for_status()
    return r.content


def euro(text):
    """'€ 1.353,77' / '€ -0,105300' / '0,22772' -> float"""
    if text is None:
        return None
    m = re.search(r"(-?)\s*€?\s*(-?\d{1,3}(?:\.\d{3})*|\d+),(\d+)", text)
    if not m:
        return None
    sign = -1 if (m.group(1) or m.group(2).startswith("-")) else 1
    return sign * float(m.group(2).lstrip("-").replace(".", "") + "." + m.group(3))


def grab(pattern, text):
    m = re.search(pattern, text, re.I)
    return euro(m.group(1)) if m else None


# --------------------------------------------------------------------------
# Browser helpers with hard stops
# --------------------------------------------------------------------------

def open_browser(pw, headed=False):
    browser = pw.chromium.launch(headless=not headed)
    ctx = browser.new_context(locale="nl-NL", timezone_id="Europe/Amsterdam",
                              viewport={"width": 1366, "height": 900})

    def guard(route):
        req = route.request
        if req.resource_type == "document" and req.is_navigation_request() and FORBIDDEN_NAV.search(urlparse(req.url).path):
            print(f"   [hard stop] navigatie geblokkeerd: {req.url}")
            return route.abort()
        return route.continue_()

    ctx.route("**/*", guard)
    return browser, ctx


def safe_click(locator, label=None):
    text = label or ""
    try:
        text += " " + (locator.inner_text(timeout=3000) or "")
    except Exception:
        pass
    if FORBIDDEN.search(text):
        raise HardStop(f"klik geweigerd: {text.strip()[:80]!r}")
    locator.click()


def check_blocked(page):
    body = page.inner_text("body")[:2000]
    if re.search(r"Request blocked|Access denied|403 ERROR", body):
        raise Blocked(f"{urlparse(page.url).netloc} blokkeert de browser")


# --------------------------------------------------------------------------
# SamenOM: public page https://www.samenom.nl/tarieven/
# Each product/period is an <article class="tariffs__item" data-product
# data-period>, period as YYYYMM or YYYYMMDD. We take the period valid today.
# --------------------------------------------------------------------------

SAMENOM_URL = "https://www.samenom.nl/tarieven/"
SAMENOM_PRODUCTS = {  # fixed + variable consumer products (no model/dynamic/business)
    "consument-vast-1": "1 jaar vast",
    "consument-vast-3": "3 jaar vast",
    "consument-tot2027": "Vast tot 2027",
    "consument-flex": "Flex",
    "consument-variabel": "Variabel",
}


def _period_date(p: str):
    try:
        return datetime.strptime(p, "%Y%m%d").date() if len(p) == 8 else datetime.strptime(p + "01", "%Y%m%d").date()
    except ValueError:
        return None


def scrape_samenom(today: date, headed=False):
    soup = BeautifulSoup(fetch(SAMENOM_URL), "html.parser")
    current = {}
    for art in soup.select("article.tariffs__item[data-product]"):
        pid = art["data-product"]
        start = _period_date(art.get("data-period", ""))
        if pid not in SAMENOM_PRODUCTS or start is None or start > today:
            continue
        if pid not in current or start > current[pid][0]:
            current[pid] = (start, art)

    rows = []
    for pid, (start, art) in current.items():
        row = {
            "supplier": "SamenOM", "product": SAMENOM_PRODUCTS[pid], "product_id": pid,
            "period": art.select_one(".period-name").get_text(" ", strip=True),
            "source": "openbare tariefpagina", "source_url": SAMENOM_URL,
        }
        note = art.get_text(" ", strip=True).lower()
        row["vat_included"] = "inclusief" in note and "btw" in note and "exclusief btw" not in note

        for tr in art.select(".tariffs__table .tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all("div", recursive=False)]
            label, values = cells[0].lower(), [euro(c) for c in cells[1:]]
            key = {"normaal": "el_normal", "laag": "el_low", "enkel": "el_single", "gas": "gas"}.get(label)
            if key:
                row[f"{key}_tariff"], row[f"{key}_tax"], row[f"{key}_total"] = (values + [None] * 3)[:3]
            elif label == "teruglevering":
                row["feed_in"] = values[0]

        fixed = re.findall(r"€\s*([\d,]+)\s*\(per dag", art.get_text(" ", strip=True))
        row["fixed_supply_per_day"] = euro(fixed[-1]) if fixed else None
        rows.append(row)
    return rows


# --------------------------------------------------------------------------
# PowerPeers: sign-up flow https://powerpeers.nl/aanvragen/
# Questions are answered from ANSWERS; the offer page lists contracts with a
# "Tarieven en prijsopbouw" panel holding the per-kWh / per-m3 tariff
# (incl. energy tax and VAT) and yearly fixed costs.
# --------------------------------------------------------------------------

POWERPEERS_URL = f"https://powerpeers.nl/aanvragen/?pc={POSTCODE}&hn={HOUSE_NUMBER}&sm=true"
POWERPEERS_ANSWERS = [
    (r"Wat voor energie heb je nodig", "Stroom & gas"),
    (r"In wat voor huis woon je", POWERPEERS_HOME),
    (r"Met hoeveel personen", POWERPEERS_PERSONS),
    (r"Heb je zonnepanelen", "Nee"),
    (r"Hoeveel kan jij besparen", None),   # informational step -> "Verder"
]


def scrape_powerpeers(today: date, headed=False):
    from playwright.sync_api import sync_playwright
    if not allowed(POWERPEERS_URL):
        raise Blocked("robots.txt staat de aanvraagflow niet toe")
    rows = []
    with sync_playwright() as pw:
        browser, ctx = open_browser(pw, headed)
        page = ctx.new_page()
        page.goto(POWERPEERS_URL, wait_until="networkidle", timeout=60_000)
        check_blocked(page)
        cookie = page.get_by_role("button", name="Weigeren")
        if cookie.count():
            safe_click(cookie.first, "Weigeren")
        page.wait_for_timeout(800)

        for _ in range(10):
            main = page.inner_text("main")
            if "Tarieven en prijsopbouw" in main:
                break
            step = next(((q, a) for q, a in POWERPEERS_ANSWERS if re.search(q, main)), None)
            if step is None:
                raise HardStop(f"onbekende stap: {main[:120]!r}")
            if step[1]:
                safe_click(page.locator("main").get_by_text(step[1], exact=True).last, step[1])
            else:
                safe_click(page.get_by_role("button", name="Verder", exact=True).first, "Verder")
            page.wait_for_timeout(2500)
        else:
            raise HardStop("aanbodpagina niet bereikt")

        usage = re.search(r"([\d.]+)\s*kWh\s*([\d.]+)\s*m³", page.inner_text("main"))
        links = page.get_by_text("Tarieven en prijsopbouw", exact=True)
        for i in range(links.count()):
            safe_click(links.nth(i), "Tarieven en prijsopbouw")
            page.wait_for_timeout(1500)
            panel = page.locator("[role=dialog], dialog[open], .modal, [class*=drawer], [class*=Dialog]").last
            t = re.sub(r"\s+", " ", panel.inner_text())
            page.keyboard.press("Escape")
            page.wait_for_timeout(800)

            name = re.search(r"Prijsopbouw (.+?) Stroomtarief", t)
            name = name.group(1).strip() if name else f"aanbod {i}"
            if re.search(r"dynamisch", name, re.I):
                continue  # fixed and variable only
            rows.append({
                "supplier": "PowerPeers", "product": name, "product_id": name.lower().replace(" ", "-"),
                "period": today.isoformat(), "source": "aanmeldflow", "vat_included": True,
                "el_single_total": grab(r"Stroomtarief / kWh Per kilowattuur (€ ?[\d.,]+)", t),
                "gas_total": grab(r"Gastarief / m3 Per kubieke meter (€ ?[\d.,]+)", t),
                "fixed_supply_el_per_day": round(grab(r"Vaste leveringskosten voor stroom (€ ?[\d.,]+)", t) / 365, 6),
                "fixed_supply_gas_per_day": round(grab(r"Vaste leveringskosten voor gas (€ ?[\d.,]+)", t) / 365, 6),
                "welcome_discount": abs(grab(r"welkomstkorting (€ ?-?[\d.,]+)", t) or 0),
                "monthly_amount": grab(r"Maandelijks termijnbedrag (€ ?[\d.,]+)", t),
                "el_usage_kwh": usage.group(1).replace(".", "") if usage else None,
                "gas_usage_m3": usage.group(2).replace(".", "") if usage else None,
                "postcode": POSTCODE, "source_url": POWERPEERS_URL,
            })
        browser.close()
    return rows


# --------------------------------------------------------------------------
# Pure Energie: sign-up flow https://pure-energie.nl/groene-stroom/aanmelden/
# Usage form -> offer page with "Vast" / "Variabel"; "Bekijk prijsopbouw"
# opens a .modal-window with tabs per period showing supply tariff and energy
# tax separately (incl. VAT).
# --------------------------------------------------------------------------

PURE_URL = "https://pure-energie.nl/groene-stroom/aanmelden/"
NL_MONTHS = {m: i for i, m in enumerate(["januari", "februari", "maart", "april", "mei", "juni", "juli",
                                          "augustus", "september", "oktober", "november", "december"], 1)}


def _days_in_range(text, year_hint):
    """'1 januari - 3 december 2027' -> 337"""
    m = re.search(r"(\d{1,2}) (\w+) - (\d{1,2}) (\w+) (\d{4})", text)
    if not m or m.group(2) not in NL_MONTHS or m.group(4) not in NL_MONTHS:
        return None
    y = int(m.group(5))
    d1 = date(y, NL_MONTHS[m.group(2)], int(m.group(1)))
    d2 = date(y, NL_MONTHS[m.group(4)], int(m.group(3)))
    return (d2 - d1).days + 1


def _pure_offer_page(ctx):
    page = ctx.new_page()
    page.goto(PURE_URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(3500)
    check_blocked(page)
    cookie = page.get_by_role("button", name="Weigeren")
    if cookie.count():
        safe_click(cookie.first, "Weigeren")
    # only these fields are ever filled
    page.fill("#postal_code", POSTCODE)
    page.fill("#house_number", HOUSE_NUMBER)
    page.fill("#electricity_usage", str(ELECTRICITY_KWH))
    if not page.locator("#gas_usage").is_visible():
        safe_click(page.get_by_text("AAN UIT").nth(2), "gas aan")   # toggles: stroom, zonnepanelen, gas
        page.wait_for_timeout(600)
    page.fill("#gas_usage", str(GAS_M3))
    page.wait_for_timeout(1500)
    safe_click(page.get_by_text("Kies je energiecontract", exact=True), "Kies je energiecontract")
    page.wait_for_timeout(4000)
    return page


def scrape_pure(today: date, headed=False):
    from playwright.sync_api import sync_playwright
    if not allowed(PURE_URL + "aanbod"):
        raise Blocked("robots.txt staat de aanmeldflow niet toe")
    rows = []
    with sync_playwright() as pw:
        browser, ctx = open_browser(pw, headed)
        for typ in ["Vast", "Variabel"]:
            page = _pure_offer_page(ctx)
            safe_click(page.locator("main").get_by_text(typ, exact=True).first, typ)
            page.wait_for_timeout(3000)
            offer = re.sub(r"\s+", " ", page.inner_text("main"))
            # monthly amount: last euro amount before "per maand" in the chosen contract card
            monthly = re.findall(r"€ ?([\d.]+,\d{2})(?= (?:MEEST GEKOZEN )?per maand)", offer)
            discount = re.search(r"Inclusief € ?([\d.]+),-? korting", offer)
            safe_click(page.get_by_text("Bekijk prijsopbouw", exact=True).first, "Bekijk prijsopbouw")
            page.wait_for_timeout(2000)
            modal = page.locator(".modal-window").last
            name = re.search(r"Prijsopbouw (.+?) Prijs bewaren", re.sub(r"\s+", " ", modal.inner_text()))
            name = name.group(1).strip() if name else typ

            tabs = {}
            for tab in ["Nu tot", "Vanaf"]:
                btn = modal.locator("button:visible", has_text=tab)
                if btn.count():
                    safe_click(btn.first, tab)
                    page.wait_for_timeout(1200)
                    tabs[tab] = (re.sub(r"\s+", " ", btn.first.inner_text()), re.sub(r"\s+", " ", modal.inner_text()))
            label, cur = tabs.get("Nu tot", ("", ""))
            el, gas = (cur.split("Standaard gas", 1) + [""])[:2] if cur else ("", "")
            el = el.split("100% Groene stroom", 1)[-1]

            # fixed supply cost per day from the longer "Vanaf ..." period
            per_day = None
            if "Vanaf" in tabs:
                vlabel, vtxt = tabs["Vanaf"]
                days = _days_in_range(vlabel, today.year)
                fixed = grab(r"Vaste leveringskosten (€ ?[\d.,]+)", vtxt.split("100% Groene stroom", 1)[-1])
                per_day = round(fixed / days, 6) if fixed and days else None

            rows.append({
                "supplier": "Pure Energie", "product": name, "product_id": name.lower().replace(" ", "-"),
                "period": label or today.isoformat(), "source": "aanmeldflow", "vat_included": True,
                "el_single_tariff": grab(r"Leveringskosten (€ ?[\d.,]+) €", el),
                "el_single_tax": grab(r"Energiebelasting (€ ?[\d.,]+) €", el),
                "gas_tariff": grab(r"Leveringskosten (€ ?[\d.,]+) €", gas),
                "gas_tax": grab(r"Energiebelasting (€ ?[\d.,]+) €", gas),
                "fixed_supply_el_per_day": per_day, "fixed_supply_gas_per_day": per_day,
                "welcome_discount": float(discount.group(1).replace(".", "")) if discount else 0,
                "monthly_amount": euro(monthly[-1]) if monthly else None,
                "el_usage_kwh": ELECTRICITY_KWH, "gas_usage_m3": GAS_M3,
                "postcode": POSTCODE, "source_url": PURE_URL,
            })
            r = rows[-1]
            for k in ("el_single", "gas"):
                if r.get(f"{k}_tariff") is not None and r.get(f"{k}_tax") is not None:
                    r[f"{k}_total"] = round(r[f"{k}_tariff"] + r[f"{k}_tax"], 6)
            page.close()
        browser.close()
    return rows


# --------------------------------------------------------------------------

SUPPLIERS = {
    "SamenOM": scrape_samenom,
    "PowerPeers": scrape_powerpeers,
    "Pure Energie": scrape_pure,
}


def main():
    ap = argparse.ArgumentParser(description="Wekelijkse tariefcheck leveranciers")
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--headed", action="store_true", help="laat de browser zien")
    ap.add_argument("--only", choices=list(SUPPLIERS), help="alleen deze leverancier")
    args = ap.parse_args()

    today = date.today()
    stamp = datetime.now().isoformat(timespec="seconds")
    rows, problems = [], []
    for name, scraper in SUPPLIERS.items():
        if args.only and name != args.only:
            continue
        print(f"> {name} ...")
        try:
            got = scraper(today, headed=args.headed)
            if not got:
                problems.append(f"{name}: niets gevonden; is de pagina veranderd?")
            rows += [{"scraped_at": stamp, **r} for r in got]
        except Blocked as e:
            problems.append(f"{name}: handmatig ({e})")
        except HardStop as e:
            problems.append(f"{name}: gestopt door harde stop ({e}); controleer de flow")
        except Exception as e:  # keep going for the other suppliers
            problems.append(f"{name}: fout {type(e).__name__}: {str(e)[:200]}")

    def f(v, n=5):
        return f"{v:.{n}f}" if isinstance(v, (int, float)) else "-"

    print()
    for r in rows:
        el = r.get("el_single_total") or r.get("el_normal_total")
        print(f"{r['supplier']:12} {r['product'][:30]:30} stroom {f(el)}/kWh  gas {f(r.get('gas_total'))}/m3  "
              f"maand {f(r.get('monthly_amount'), 2)}  korting {f(r.get('welcome_discount'), 0)}  ({r['source']})")
    if not args.only:
        problems += [f"{n}: handmatig ({why})" for n, why in MANUAL.items()]
    if problems:
        print("\nAandacht nodig:", *problems, sep="\n  - ")

    if rows and not args.no_save:
        OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
        new = not OUT_CSV.exists()
        with OUT_CSV.open("a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerows(rows)
        print(f"\n{len(rows)} regels toegevoegd aan {OUT_CSV}")
    return 1 if any("fout" in p or "niets gevonden" in p or "harde stop" in p for p in problems) else 0


if __name__ == "__main__":
    sys.exit(main())
