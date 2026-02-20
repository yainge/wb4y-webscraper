import re
import json
import asyncio
import uuid
from pathlib import Path
from bs4 import BeautifulSoup

VIEW_URL = "https://public.tableau.com/views/MonitorConsumentenmarktEnergie/Variabeleenvastecontracten?:showVizHome=no"

# Extraction constants
X_CLICK = 80
Y_POSITIONS = [0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330, 360, 390, 420, 450]


def encode_multipart(fields: dict) -> tuple:
    """
    Encode form fields as multipart/form-data.
    Returns (body_bytes, content_type_header).
    """
    boundary = str(uuid.uuid4()).replace("-", "")[:16]
    parts = []
    
    for key, value in fields.items():
        # JSON-encode dicts and lists
        if isinstance(value, (dict, list)):
            value = json.dumps(value)
        elif value is None:
            value = json.dumps(None)
        else:
            value = str(value)
        
        parts.append(f"--{boundary}\r\n")
        parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n')
        parts.append(f"{value}\r\n")
    
    parts.append(f"--{boundary}--\r\n")
    body_str = "".join(parts)
    body_bytes = body_str.encode("utf-8")
    content_type = f"multipart/form-data; boundary={boundary}"
    
    return body_bytes, content_type


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


def extract_tuple_id(response_text: str) -> str:
    """Extract tuple_id from Tableau tooltip response.
    Response might be JSON with tuple_id field or contain it in headers/body.
    """
    try:
        # Try parsing as JSON first
        data = json.loads(response_text)
        # Handle list response
        if isinstance(data, list) and len(data) > 0:
            data = data[0]
        # Look for tuple_id field
        if isinstance(data, dict):
            if "tuple_id" in data:
                return data["tuple_id"]
            # Sometimes nested in other fields
            for key in data:
                if "tuple" in key.lower():
                    return str(data[key])
    except:
        pass
    
    # Try regex extraction from response
    match = re.search(r'"tuple_id"\s*:\s*["\']?([^",}\]\']+)', response_text)
    if match:
        return match.group(1)
    
    return ""


def extract_session_id(bootstrap_url: str) -> str:
    """Extract session_id from bootstrapSession URL."""
    m = re.search(r"/sessions/([0-9A-F]{32}-\d+:\d+)", bootstrap_url, re.IGNORECASE)
    if not m:
        raise RuntimeError("Could not extract session id from bootstrap URL.")
    return m.group(1)

async def post_multipart(page, url: str, payload: dict, required_headers: dict) -> tuple:
    """
    POST multipart/form-data with captured required headers.
    Returns (status_code, response_text).
    """
    body, ctype = encode_multipart(payload)
    
    headers = required_headers.copy()
    headers["content-type"] = ctype
    
    response = await page.request.post(url, data=body, headers=headers)
    status = response.status
    text = await response.text()
    
    return status, text


async def get_xsrf_from_context(context, timeout_secs: float = 10.0) -> str:
    """
    Retrieve XSRF-TOKEN from Playwright context with URL scoping.
    Retries for up to timeout_secs to allow token to appear in cookies.
    Returns the token value if found, or empty string if not found.
    """
    import time
    start = time.time()
    while time.time() - start < timeout_secs:
        try:
            cookies = await context.cookies(["https://public.tableau.com"])
            for cookie in cookies:
                if cookie["name"] == "XSRF-TOKEN":
                    return cookie["value"]
        except Exception as e:
            print(f"  (cookie check error: {e})")
        
        await asyncio.sleep(0.5)
    
    return ""


async def scrape_with_playwright_async() -> list:
    """
    Load Tableau dashboard, capture bootstrap and command headers from first VizQL request, extract tariffs.
    """
    from playwright.async_api import async_playwright
    import re as regex
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        captured = {
            "bootstrap_url": None,
            "bootstrap_status": None,
            "gsh": None,
            "xsrf": None,
            "tableau_version": None,
            "active_tab": None,
            "command_headers_ready": False,
            "observed_commands": []
        }
        
        debug_printed = {"done": False}  # Mutable container to track debug state
        
        def hget(headers, name):
            """Case-insensitive header lookup."""
            name_l = name.lower()
            for k, v in headers.items():
                if k.lower() == name_l:
                    return v
            return None
        
        def on_request(req):
            """Capture bootstrap and command headers from VizQL requests."""
            # Capture bootstrap
            if "bootstrapSession/sessions/" in req.url and req.method == "POST":
                captured["bootstrap_url"] = req.url
                print(f"✓ Bootstrap URL: {req.url}")
            
            # Capture headers from /commands/ POST (any command)
            # NOTE: We do NOT capture x-xsrf-token here; it will come from cookies via get_xsrf_from_context()
            if "/vizql/w/MonitorConsumentenmarktEnergie/v/Variabeleenvastecontracten/sessions/" in req.url and req.method == "POST" and "/commands/" in req.url:
                try:
                    headers = req.headers
                    command_path = req.url.split('/commands/')[-1] if '/commands/' in req.url else 'unknown'
                    captured["observed_commands"].append(command_path)
                    
                    # Debug dump: print header keys and specific values for first /commands/ POST
                    if not debug_printed["done"]:
                        print(f"\nDEBUG command url: {req.url}")
                        print(f"DEBUG header keys: {sorted(headers.keys())}")
                        # Print specific headers if present
                        for k in ["global-session-header", "Global-Session-Header", "x-xsrf-token", "X-XSRF-TOKEN", "x-tableau-version", "x-tsi-active-tab", "cookie"]:
                            if k in headers:
                                val = headers[k]
                                # Truncate long values
                                if len(val) > 50:
                                    val = val[:50] + "..."
                                print(f"DEBUG {k}: {val}")
                        debug_printed["done"] = True
                    
                    # Capture required headers using case-insensitive lookup
                    gsh = hget(headers, "global-session-header")
                    ver = hget(headers, "x-tableau-version")
                    tab = hget(headers, "x-tsi-active-tab")
                    
                    if gsh and not captured["gsh"]:
                        captured["gsh"] = gsh
                    if ver and not captured["tableau_version"]:
                        captured["tableau_version"] = ver
                    if tab and not captured["active_tab"]:
                        captured["active_tab"] = tab
                    
                    # Mark ready when gsh, tableau_version, active_tab are captured
                    # (xsrf will be set separately via get_xsrf_from_context)
                    if captured["gsh"] and captured["tableau_version"] and captured["active_tab"] and not captured["command_headers_ready"]:
                        captured["command_headers_ready"] = True
                        gsh_short = captured["gsh"][:12]
                        tv_val = captured["tableau_version"]
                        print(f"\n✓ Captured GSH={gsh_short}... x-tableau-version={tv_val}\n")
                
                except Exception as e:
                    print(f"  Error capturing headers: {e}")

        def on_response(resp):
            """Capture bootstrap response status."""
            if "bootstrapSession/sessions/" in resp.url and resp.status in [200, 204]:
                if captured["bootstrap_url"] and captured["bootstrap_url"] in resp.url:
                    captured["bootstrap_status"] = resp.status
                    print(f"✓ Bootstrap status: {resp.status}")

        page.on("request", on_request)
        page.on("response", on_response)
        
        # Navigate to dashboard
        print("Loading Tableau dashboard...")
        try:
            await asyncio.wait_for(
                page.goto(VIEW_URL, wait_until="domcontentloaded"),
                timeout=10
            )
        except asyncio.TimeoutError:
            print("Page load timed out, continuing...")
        except Exception as e:
            print(f"Navigation: {e}")
        
        # Wait for page to fully settle
        await page.wait_for_timeout(3000)
        
        # Wait for bootstrap to complete
        print("Waiting for bootstrap session...")
        for i in range(30):
            if captured["bootstrap_status"] in [200, 204]:
                break
            await asyncio.sleep(0.2)
        
        if not captured["bootstrap_url"]:
            await browser.close()
            raise RuntimeError("Bootstrap session URL not captured.")
        
        # Force interaction to trigger command headers capture (hit-test-scene)
        print("Triggering VizQL commands to capture headers...")
        await page.wait_for_timeout(1500)
        
        for attempt in range(40):  # 20 seconds timeout (500ms per iteration)
            try:
                # Try clicking in page
                await page.mouse.move(400, 400)
                await page.mouse.click(400, 400)
            except:
                pass
            
            await page.wait_for_timeout(500)
            
            if captured["command_headers_ready"]:
                print(f"✓ Command headers ready on attempt {attempt+1}")
                break
        
        # Hard timeout: check if we have the command headers
        if not captured["command_headers_ready"]:
            error_msg = f"Command headers not captured after timeout. Observed commands: {captured['observed_commands'][-3:]}"
            await browser.close()
            raise RuntimeError(error_msg)
        
        # Now fetch XSRF token from cookies (with URL scoping and retries)
        print("Extracting XSRF-TOKEN from cookies...")
        xsrf_token = await get_xsrf_from_context(context, timeout_secs=10.0)
        
        if xsrf_token:
            print(f"✓ XSRF-TOKEN: {xsrf_token[:8]}...")
        else:
            print("ERROR: XSRF-TOKEN not found in cookies")
        
        captured["xsrf"] = xsrf_token
        
        # Verify all required values are present
        if not captured["gsh"]:
            await browser.close()
            raise RuntimeError("global-session-header not captured")
        if not captured["xsrf"]:
            print("WARNING: x-xsrf-token not found, commands may fail with 403")
        
        # Build required headers from captured values
        required_headers = {
            "accept": "text/javascript",
            "origin": "https://public.tableau.com",
            "referer": VIEW_URL,
            "x-requested-with": "XMLHttpRequest",
            "x-tableau-version": captured["tableau_version"],
            "x-tsi-active-tab": captured["active_tab"],
            "x-xsrf-token": captured["xsrf"],
            "global-session-header": captured["gsh"],
        }
        
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
        status, resp = await post_multipart(page, month_url, month_payload, required_headers)
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
        status, resp = await post_multipart(page, filter_url, filter_payload, required_headers)
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
            status, _ = await post_multipart(page, select_url, select_payload, required_headers)
            
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
            status, tooltip_text = await post_multipart(page, tooltip_url, tooltip_payload, required_headers)
            
            if status == 200 and tooltip_text and len(tooltip_text.strip()) > 0:
                try:
                    tooltip_dict = parse_tooltip_table(tooltip_text)
                    tuple_id = extract_tuple_id(tooltip_text)
                    
                    # Dedup key
                    supplier = tooltip_dict.get("Energie leveranciers") or tooltip_dict.get("Energieleverancier", "")
                    contract_naam = tooltip_dict.get("Contractnaam", "")
                    contract_duur = tooltip_dict.get("Contractduur", "")
                    
                    dedup_key = (supplier, contract_naam, contract_duur)
                    
                    if dedup_key not in seen_keys:
                        seen_keys.add(dedup_key)
                        # Add tuple_id to result if found
                        if tuple_id:
                            tooltip_dict["tuple_id"] = tuple_id
                        results.append(tooltip_dict)
                        print(f"  ✓ {contract_naam} | {contract_duur} | {supplier}")
                        if tuple_id:
                            print(f"      tuple_id: {tuple_id}")
                        # Show tariff fields if present
                        for key in ["Variabel elektriciteit enkel", "Variabel elektriciteit enkel / piek per kWh", "Vast bedrag per maand"]:
                            if key in tooltip_dict:
                                print(f"      {key}: {tooltip_dict[key]}")
                
                except Exception as e:
                    print(f"  Parse error at y={y_pos}: {e}")
            elif status == 410:
                print(f"  ✗ Status 410 at y={y_pos} - session invalid")
            elif status != 200:
                print(f"  ✗ Status {status} at y={y_pos}: {tooltip_text[:200]}")
            
            await page.wait_for_timeout(200)
        
        print(f"\nExtraction complete: {len(results)} unique tariffs\n")
        await browser.close()
        return results


async def main():
    """Run the tariff scraper and save results to JSON."""
    print("Launching Playwright tariff scraper...\n")
    results = await scrape_with_playwright_async()
    
    print(f"{'='*60}")
    print(f"Total extracted: {len(results)} tariffs")
    print(f"{'='*60}\n")
    
    # Save results to JSON file in Attempt2 folder
    output_path = Path(__file__).parent / "extracted_tariffs.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"✓ Results saved to: {output_path}\n")
    
    return results


if __name__ == "__main__":
    asyncio.run(main())
