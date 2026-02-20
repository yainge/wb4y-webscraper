import re
import json
import asyncio
from bs4 import BeautifulSoup

VIEW_URL = "https://public.tableau.com/views/MonitorConsumentenmarktEnergie/Variabeleenvastecontracten?:showVizHome=no"

# Extraction constants
X_CLICK = 228
Y_POSITIONS = [60, 90, 120, 150, 180]


def parse_tooltip_table(raw_text: str) -> dict:
    """Parse tooltip HTML table into a dict. Extracts euro currency values."""
    html = raw_text.replace("\\\"", "\"").replace("\\\\/", "/")
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) >= 2:
            label = tds[0].get_text(" ", strip=True).rstrip(":").strip()
            value = tds[-1].get_text(" ", strip=True).strip()
            if label and value:
                # Extract euro values: "€ 0,2153" -> "0,2153"
                if "€" in value:
                    euro_match = re.search(r"€\s*([\d,]+)", value)
                    if euro_match:
                        value = euro_match.group(1)
                out[label] = value
    return out


def extract_session_id(bootstrap_url: str) -> str:
    """Extract session_id from bootstrapSession URL."""
    m = re.search(r"/sessions/([0-9A-F]{32}-\d+:\d+)", bootstrap_url, re.IGNORECASE)
    if not m:
        raise RuntimeError("Could not extract session id from bootstrap URL.")
    return m.group(1)


async def post_form(page, url: str, payload: dict) -> tuple:
    """
    POST form data, JSON-encoding dict values.
    Returns (status_code, response_text).
    """
    form_data = {}
    for key, value in payload.items():
        if isinstance(value, dict) or isinstance(value, list):
            form_data[key] = json.dumps(value)
        elif value is None:
            form_data[key] = json.dumps(None)
        else:
            form_data[key] = str(value)
    
    response = await page.request.post(url, form=form_data)
    status = response.status
    text = await response.text()
    
    return status, text


async def scrape_with_playwright_async() -> list:
    """
    Load Tableau dashboard, capture real bootstrap session, and extract tariffs
    via VizQL POST requests in the same browser context.
    """
    from playwright.async_api import async_playwright
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        captured = {
            "bootstrap_url": None,
            "bootstrap_status": None,
            "bootstrap_post_data": None
        }

        def on_request(req):
            """Capture bootstrap POST request."""
            if "bootstrapSession/sessions/" in req.url and req.method == "POST":
                captured["bootstrap_url"] = req.url
                # Try to get post data asynchronously (may not always be available)
                try:
                    import asyncio as sync_asyncio
                    post_data = req.post_data()
                    if post_data:
                        captured["bootstrap_post_data"] = post_data
                except:
                    pass
                print(f"✓ CAPTURED bootstrap POST: {req.url}")

        def on_response(resp):
            """Capture bootstrap response status."""
            if "bootstrapSession/sessions/" in resp.url and resp.status in [200, 204]:
                if captured["bootstrap_url"] and captured["bootstrap_url"] in resp.url:
                    captured["bootstrap_status"] = resp.status
                    print(f"✓ Bootstrap response status: {resp.status}")

        page.on("request", on_request)
        page.on("response", on_response)
        
        # Navigate to dashboard
        print("Loading Tableau dashboard...")
        try:
            await asyncio.wait_for(
                page.goto(VIEW_URL, wait_until="networkidle"),
                timeout=10
            )
        except asyncio.TimeoutError:
            print("Page load timed out, continuing...")
        except Exception as e:
            print(f"Navigation: {e}")
        
        # Wait for bootstrap to complete
        print("Waiting for bootstrap session to initialize...")
        for i in range(30):
            if captured["bootstrap_status"] in [200, 204]:
                break
            await asyncio.sleep(0.2)
        
        if not captured["bootstrap_url"]:
            await browser.close()
            raise RuntimeError("Bootstrap session URL not captured from page.")
        
        if captured["bootstrap_status"] not in [200, 204]:
            print(f"Warning: Bootstrap status is {captured['bootstrap_status']}, proceeding anyway...")
        
        bootstrap_url = captured["bootstrap_url"]
        session_id = extract_session_id(bootstrap_url)
        
        print(f"✓ Session ID: {session_id}")
        
        # Build base commands URL
        base_url = f"https://public.tableau.com/vizql/w/MonitorConsumentenmarktEnergie/v/Variabeleenvastecontracten/sessions/{session_id}/commands"
        
        # Wait a bit for viz to render
        await page.wait_for_timeout(2000)
        
        results = []
        seen_keys = set()
        
        print(f"\nSetting month parameter...")
        month_url = f"{base_url}/tabdoc/set-parameter-value-from-index"
        month_payload = {
            "parameterName": "[Parameters].[Parameter 1]",
            "idx": "1",
            "telemetryCommandId": "wb4y"
        }
        status, resp = await post_form(page, month_url, month_payload)
        print(f"  Status: {status}")
        if status != 200:
            print(f"  Response: {resp[:200]}")
        
        await page.wait_for_timeout(500)
        
        print(f"Setting contract length filter...")
        filter_url = f"{base_url}/tabdoc/categorical-filter-by-index"
        filter_payload = {
            "visualIdPresModel": {
                "worksheet": "Retail Tarieven staafdiagram",
                "dashboard": "Variabele en vaste contracten"
            },
            "globalFieldName": "[federated.0u3wpws1o2j28v19rn3tk17z9105].[none:Calculation_979814396187639808:nk]",
            "membershipTarget": "filter",
            "filterIndices": "[0]",
            "filterUpdateType": "filter-replace",
            "telemetryCommandId": "wb4y"
        }
        status, resp = await post_form(page, filter_url, filter_payload)
        print(f"  Status: {status}")
        if status != 200:
            print(f"  Response: {resp[:200]}")
        
        await page.wait_for_timeout(500)
        
        print(f"\nExtracting tariffs from {len(Y_POSITIONS)} positions...\n")
        select_url = f"{base_url}/tabsrv/select-region-no-return-server"
        tooltip_url = f"{base_url}/tabsrv/render-tooltip-server"
        
        for y_pos in Y_POSITIONS:
            # Select region
            select_payload = {
                "worksheet": "Retail Tarieven staafdiagram alle contracten",
                "dashboard": "Variabele en vaste contracten",
                "vizRegionRect": {
                    "x": X_CLICK,
                    "y": y_pos,
                    "w": 0,
                    "h": 0,
                    "r": "viz"
                },
                "mouseAction": "simple",
                "telemetryCommandId": "wb4y"
            }
            status, _ = await post_form(page, select_url, select_payload)
            
            # Get tooltip
            tooltip_payload = {
                "worksheet": "Retail Tarieven staafdiagram alle contracten",
                "dashboard": "Variabele en vaste contracten",
                "vizRegionRect": {
                    "r": "viz",
                    "x": X_CLICK,
                    "y": y_pos,
                    "w": 0,
                    "h": 0,
                    "fieldVector": None
                },
                "allowHoverActions": "true",
                "allowPromptText": "true",
                "allowWork": "true",
                "useInlineImages": "true",
                "telemetryCommandId": "wb4y"
            }
            status, tooltip_text = await post_form(page, tooltip_url, tooltip_payload)
            
            if status == 200 and tooltip_text and len(tooltip_text.strip()) > 0:
                try:
                    tooltip_dict = parse_tooltip_table(tooltip_text)
                    
                    # Dedup key
                    supplier = tooltip_dict.get("Energie leveranciers") or tooltip_dict.get("Energieleverancier", "")
                    contract_naam = tooltip_dict.get("Contractnaam", "")
                    contract_duur = tooltip_dict.get("Contractduur", "")
                    
                    dedup_key = (supplier, contract_naam, contract_duur)
                    
                    if dedup_key not in seen_keys:
                        seen_keys.add(dedup_key)
                        results.append(tooltip_dict)
                        print(f"  ✓ {contract_naam} | {contract_duur} | {supplier}")
                        # Show tariff fields if present
                        for key in ["Variabel elektriciteit enkel", "Variabel elektriciteit enkel / piek per kWh", "Vast bedrag per maand"]:
                            if key in tooltip_dict:
                                print(f"      {key}: {tooltip_dict[key]}")
                
                except Exception as e:
                    print(f"  Parse error at y={y_pos}: {e}")
            elif status == 410:
                print(f"  ✗ Status 410 at y={y_pos} - session invalid, skipping")
            elif status != 200:
                print(f"  ✗ Status {status} at y={y_pos}")
            
            await page.wait_for_timeout(200)
        
        print(f"\nExtraction complete: {len(results)} unique tariffs\n")
        await browser.close()
        return results


async def main():
    """Run the tariff scraper."""
    print("Launching Playwright tariff scraper...\n")
    results = await scrape_with_playwright_async()
    
    print(f"{'='*60}")
    print(f"Total extracted: {len(results)} tariffs")
    print(f"{'='*60}\n")
    
    return results


if __name__ == "__main__":
    asyncio.run(main())
