"""Scrape the electricity tariff (EUR/kWh) from budgetthuis.nl "aanbod op maat".

The offer page is a client-side app, so the price is not in the raw HTML. This
script drives a headless Chromium (Playwright) through the same steps a
visitor takes:

  1. open the "aanbod-op-maat" URL for an address
  2. decline optional cookies
  3. click "Verbruik inschatten" (estimate usage from house type/residents)
  4. click "Bekijk je aanbod"
  5. read <td data-testid="cost-breakdown__electricity-tariff-price">

The tariff shown is for the offer that is selected by default on the page
(at the time of writing "Budget Energie 1 jaar vast"), incl. VAT.

Usage:
  .venv/Scripts/python.exe "Energy provider scraper/budgetthuis_scraper.py"
  .venv/Scripts/python.exe "Energy provider scraper/budgetthuis_scraper.py" \
      --postal-code 5014LD --house-number 12 --headed
"""
import argparse
import asyncio
import csv
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from playwright.async_api import async_playwright

BASE_URL = "https://www.budgetthuis.nl/energie/aanbod-op-maat"
OUT_CSV = Path(__file__).parent / "data" / "budgetthuis_tariffs.csv"

TESTIDS = {
    "electricity_eur_per_kwh": "cost-breakdown__electricity-tariff-price",
    "electricity_offpeak_eur_per_kwh": "cost-breakdown__electricity-tariff-off-peak-price",
    "gas_eur_per_m3": "cost-breakdown__gas-tariff-price",
}


def build_url(postal_code, house_number, house_number_ext="", city="", street=""):
    params = {
        "postalCode": postal_code, "houseNumber": house_number,
        "houseNumberExt": house_number_ext, "p": 1,
        "buildingNr": house_number, "buildingNrExt": house_number_ext,
        "city": city, "street": street, "noSmartMeter": 0,
        "elePeak": "", "eleOffPeak": "", "gasUsage": "",
        "eleSolarPeak": "", "eleSolarOffPeak": "",
        "isHasGas": 1, "isHasElectricity": 1,
    }
    return f"{BASE_URL}?{urlencode(params)}"


def parse_euro(text):
    """'€\xa00,32672 / kWh' -> 0.32672"""
    m = re.search(r"(\d+(?:[.,]\d+)?)", text.replace("\xa0", " "))
    return float(m.group(1).replace(",", ".")) if m else None


async def scrape(url, headed=False):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not headed)
        page = await browser.new_page(locale="nl-NL")
        await page.goto(url, wait_until="networkidle", timeout=60_000)

        cookie_btn = page.get_by_text("Nee, ik wil geen optimale cookies")
        if await cookie_btn.count():
            await cookie_btn.click()

        # The estimate fills in usage via /api/consumption-data; the offer
        # button does nothing until that has come back.
        async with page.expect_response(lambda r: "consumption-data" in r.url):
            await page.get_by_test_id("signup__consumption-estimate-button").click()
        await page.wait_for_timeout(1000)
        await page.get_by_text("Bekijk je aanbod").last.click()

        price_cell = page.get_by_test_id(TESTIDS["electricity_eur_per_kwh"])
        await price_cell.wait_for(state="attached", timeout=30_000)

        result = {"scraped_at": datetime.now().isoformat(timespec="seconds")}
        offer = page.get_by_test_id("receipt__proposition-title")
        result["offer"] = (await offer.first.text_content() or "").strip() if await offer.count() else ""
        for key, testid in TESTIDS.items():
            cell = page.get_by_test_id(testid)
            if await cell.count():
                raw = (await cell.first.text_content() or "").strip()
                result[key] = parse_euro(raw)
                result[key + "_raw"] = raw.replace("\xa0", " ")
        await browser.close()
        return result


def append_csv(row, path=OUT_CSV):
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if new:
            w.writeheader()
        w.writerow(row)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--postal-code", default="5014LD")
    ap.add_argument("--house-number", default="12")
    ap.add_argument("--house-number-ext", default="")
    ap.add_argument("--city", default="TILBURG")
    ap.add_argument("--street", default="Paduaplein")
    ap.add_argument("--headed", action="store_true", help="show the browser window")
    ap.add_argument("--no-save", action="store_true", help="don't append to the CSV")
    args = ap.parse_args()

    url = build_url(args.postal_code, args.house_number, args.house_number_ext,
                    args.city, args.street)
    row = {"postal_code": args.postal_code, "house_number": args.house_number,
           **asyncio.run(scrape(url, headed=args.headed))}

    for k, v in row.items():
        print(f"{k:35} {v}")
    if not args.no_save:
        append_csv(row)
        print(f"\nSaved to {OUT_CSV}")


if __name__ == "__main__":
    main()
