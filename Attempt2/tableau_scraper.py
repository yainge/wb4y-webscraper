import re
import json
import asyncio
import uuid
import sys
from pathlib import Path
from bs4 import BeautifulSoup

# Force UTF-8 output on Windows
if sys.platform == 'win32':
    import codecs
    sys.stdout.reconfigure(encoding='utf-8')

VIEW_URL = "https://public.tableau.com/views/MonitorConsumentenmarktEnergie/Variabeleenvastecontracten?:showVizHome=no"

# Load providers from JSON file
def load_providers():
    providers_path = Path(__file__).parent / "providers.json"
    with open(providers_path, "r", encoding="utf-8") as f:
        return json.load(f)

PROVIDERS = load_providers()


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


def extract_tooltip_payload(response_text: str) -> dict:
    """Extract commandReturn payload from nested VQL response structure."""
    try:
        outer = json.loads(response_text)
        if isinstance(outer, dict) and "vqlCmdResponse" in outer:
            cmd_list = outer["vqlCmdResponse"].get("cmdResultList", [])
            if cmd_list and isinstance(cmd_list, list) and len(cmd_list) > 0:
                command_return = cmd_list[0].get("commandReturn", {})
                
                # If tooltipText exists, parse it as JSON and return that
                if "tooltipText" in command_return:
                    try:
                        tooltip_obj = json.loads(command_return["tooltipText"])
                        return tooltip_obj
                    except:
                        pass
                
                return command_return
    except:
        pass
    return {}


def extract_supplier_from_commands(tip_payload: dict) -> str:
    """Try to extract supplier name from selectionRelaxationCommands."""
    try:
        selection = tip_payload.get("selectionRelaxationCommands", {})
        if isinstance(selection, dict):
            items = selection.get("commandItems", [])
            if isinstance(items, list):
                for cmd_str in items:
                    if "Energie leveranciers" in cmd_str or "Energieleverancier" in cmd_str:
                        # Extract fn value that contains the lever field
                        fn_match = re.search(r'fn="([^"]*leverancier[^"]*)"', cmd_str, re.IGNORECASE)
                        if fn_match:
                            return cmd_str  # Return command string for reference
    except:
        pass
    return ""


def extract_tuple_id(response_text: str) -> str:
    """Extract tupleId from Tableau tooltip response.
    Handles nested VQL response structure where tooltipText is JSON-escaped.
    """
    try:
        # Parse outer VQL response
        outer = json.loads(response_text)
        
        # Navigate the nested structure: vqlCmdResponse -> cmdResultList[0] -> commandReturn -> tooltipText
        if isinstance(outer, dict) and "vqlCmdResponse" in outer:
            cmd_list = outer["vqlCmdResponse"].get("cmdResultList", [])
            if cmd_list and isinstance(cmd_list, list) and len(cmd_list) > 0:
                inner_text = cmd_list[0].get("commandReturn", {}).get("tooltipText", "")
                
                if inner_text:
                    try:
                        # Parse the inner JSON (which was escaped as a string)
                        inner_data = json.loads(inner_text)
                        
                        # Look for tupleId in the parsed inner content
                        if isinstance(inner_data, dict):
                            if "tupleId" in inner_data:
                                return str(inner_data["tupleId"])
                            elif "tuple_id" in inner_data:
                                return str(inner_data["tuple_id"])
                    except:
                        pass
        
        # Also check the top-level for tupleId
        if isinstance(outer, dict):
            if "tupleId" in outer:
                return str(outer["tupleId"])
            elif "tuple_id" in outer:
                return str(outer["tuple_id"])
    except:
        pass
    
    # Fallback: regex search for tupleId (numeric value)
    match = re.search(r'"tupleId"\s*:\s*(\d+)', response_text)
    if match:
        return match.group(1)
    
    # Last resort: snake_case tuple_id
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


async def filter_by_provider(page, base_url: str, provider_index: int, action: str, required_headers: dict) -> bool:
    """
    Apply categorical filter for Energie leveranciers.
    action: 'clear_all' (uses categorical-filter), 'select', or 'deselect' (use categorical-filter-by-index)
    Returns True if filter was applied successfully.
    """
    try:
        if action == "clear_all":
            # Clear all providers using categorical-filter endpoint
            filter_url = f"{base_url}/tabdoc/categorical-filter"
            payload = {
                "visualIdPresModel": {
                    "worksheet": "Retail Tarieven staafdiagram",
                    "dashboard": "Variabele en vaste contracten"
                },
                "membershipTarget": "filter",
                "globalFieldName": "[federated.0u3wpws1o2j28v19rn3tk17z9105].[none:Energie leveranciers:nk]",
                "filterValues": [],
                "filterUpdateType": "filter-replace",
                "heuristicCommandReinterpretation": "do-not-reinterpret-command",
                "telemetryCommandId": "wb4y"
            }
        else:
            # Select/deselect individual providers using categorical-filter-by-index endpoint
            filter_url = f"{base_url}/tabdoc/categorical-filter-by-index"
            if action == "select":
                payload = {
                    "visualIdPresModel": {
                        "worksheet": "Retail Tarieven staafdiagram",
                        "dashboard": "Variabele en vaste contracten"
                    },
                    "globalFieldName": "[federated.0u3wpws1o2j28v19rn3tk17z9105].[none:Energie leveranciers:nk]",
                    "membershipTarget": "filter",
                    "filterUpdateType": "filter-delta",
                    "filterAddIndices": [provider_index],
                    "filterRemoveIndices": [],
                    "telemetryCommandId": "wb4y"
                }
            elif action == "deselect":
                payload = {
                    "visualIdPresModel": {
                        "worksheet": "Retail Tarieven staafdiagram",
                        "dashboard": "Variabele en vaste contracten"
                    },
                    "globalFieldName": "[federated.0u3wpws1o2j28v19rn3tk17z9105].[none:Energie leveranciers:nk]",
                    "membershipTarget": "filter",
                    "filterUpdateType": "filter-delta",
                    "filterAddIndices": [],
                    "filterRemoveIndices": [provider_index],
                    "telemetryCommandId": "wb4y"
                }
            else:
                return False
        
        status, resp = await post_multipart(page, filter_url, payload, required_headers)
        print(f"  {action} status: {status}")
        if status != 200:
            print(f"    Response: {resp[:150] if resp else 'empty'}")
        return status == 200
    except Exception as e:
        print(f"  Filter error: {e}")
        return False


def normalize_contract_data(data: dict) -> dict:
    """
    Normalize contract data by adding missing fields as NaN.
    """
    # Define expected fields
    expected_fields = [
        "Contractnaam",
        "Contractduur",
        "Geschatte leveringskosten obv verbruik",
        "Vastrecht gas per jaar",
        "Variabel gas per m3",
        "Vastrecht elektriciteit per jaar",
        "Variabel elektriciteit enkel / piek per kWh",
        "Variabel elektriciteit dal per kWh"
    ]
    
    normalized = {}
    for field in expected_fields:
        if field in data:
            normalized[field] = data[field]
        else:
            normalized[field] = "NaN"
    
    # Add all other fields that exist
    for key, value in data.items():
        if key not in normalized:
            normalized[key] = value
    
    return normalized


async def fetch_tooltip_at_coordinates(page, base_url: str, x_pos: int, y_pos: int, required_headers: dict) -> dict:
    """
    Select region at coordinates, then fetch tooltip and parse the data.
    """
    try:
        # First, select the region
        select_url = f"{base_url}/tabsrv/select-region-no-return-server"
        select_payload = {
            "worksheet": "Retail Tarieven staafdiagram alle contracten",
            "dashboard": "Variabele en vaste contracten",
            "vizRegionRect": {
                "x": x_pos,
                "y": y_pos,
                "w": 0,
                "h": 0,
                "r": "viz"
            },
            "mouseAction": "simple",
            "telemetryCommandId": "wb4y"
        }
        status, _ = await post_multipart(page, select_url, select_payload, required_headers)
        
        await asyncio.sleep(0.1)
        
        # Then fetch the tooltip
        tooltip_url = f"{base_url}/tabsrv/render-tooltip-server"
        tooltip_payload = {
            "worksheet": "Retail Tarieven staafdiagram alle contracten",
            "dashboard": "Variabele en vaste contracten",
            "vizRegionRect": {
                "r": "viz",
                "x": x_pos,
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
        
        if status == 200 and tooltip_text:
            tip_payload = extract_tooltip_payload(tooltip_text)
            
            if "htmlTooltip" in tip_payload:
                html = tip_payload["htmlTooltip"]
                data = parse_tooltip_table(html)
                
                # Extract tuple ID from response
                if "tupleId" in tip_payload:
                    data["_tupleId"] = str(tip_payload["tupleId"])
                
                return data
    except:
        pass
    
    return None




async def scrape_provider_contracts(page, base_url: str, provider_name: str, provider_index: int, month_name: str, session_id: str, required_headers: dict) -> dict:
    """
    Scrape all contracts for a specific provider.
    Returns a dict of contracts keyed by provider | contract_name | duration.
    """
    print(f"\nProvider: {provider_name} (index {provider_index})")
    print(f"Selecting provider...")
    provider_selected = await filter_by_provider(page, base_url, provider_index, "select", required_headers)
    if not provider_selected:
        print("  Warning: Provider selection may have failed")
    
    await asyncio.sleep(0.5)
    
    print(f"Phase 1: Scanning Y positions to discover tuple IDs...\n")
    discovered_tuple_ids = set()
    tuple_id_coords = {}
    
    select_url = f"{base_url}/tabsrv/select-region-no-return-server"
    tooltip_url = f"{base_url}/tabsrv/render-tooltip-server"
    
    X_CLICK = 90
    Y_POSITIONS = [0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300]
    
    for y_pos in Y_POSITIONS:
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
        
        if status == 200 and tooltip_text:
            try:
                tip_payload = extract_tooltip_payload(tooltip_text)
                
                if "tupleId" in tip_payload:
                    tid = int(tip_payload["tupleId"])
                    is_empty = tip_payload.get("isEmpty", False)
                    
                    if tid > 0 and not is_empty:
                        discovered_tuple_ids.add(str(tid))
                        tuple_id_coords[str(tid)] = (X_CLICK, y_pos)
                        print(f"  y={y_pos}: Discovered tuple_id={tid}")
            except:
                pass
        
        await asyncio.sleep(0.2)
    
    print(f"\n[OK] Discovered {len(discovered_tuple_ids)} unique tuple IDs\n")
    
    # Phase 2: Fetch each contract
    print(f"Phase 2: Fetching full contract data...\n")
    contracts = {}
    
    for tid in sorted(discovered_tuple_ids):
        if tid in tuple_id_coords:
            x_pos, y_pos = tuple_id_coords[tid]
            
            contract_data = await fetch_tooltip_at_coordinates(page, base_url, x_pos, y_pos, required_headers)
            
            if contract_data:
                normalized_data = normalize_contract_data(contract_data)
                
                contract_name = normalized_data.get("Contractnaam", "")
                duration = normalized_data.get("Contractduur", "")
                
                key = f"{provider_name} | {contract_name} | {duration}"
                
                normalized_data["_month_idx"] = month_name
                normalized_data["_session_id"] = session_id
                
                contracts[key] = normalized_data
                print(f"  [OK] tuple_id={tid}: {contract_name}")
            else:
                print(f"  [FAIL] tuple_id={tid}: Failed to fetch")
        
        await asyncio.sleep(0.2)
    
    print(f"[OK] {len(contracts)} contracts fetched for {provider_name}\n")
    
    # Deselect this provider before moving to next
    print(f"Deselecting provider...")
    await filter_by_provider(page, base_url, provider_index, "deselect", required_headers)
    await asyncio.sleep(0.5)
    
    return contracts


async def scrape_with_playwright_async() -> dict:
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
            try:
                # Capture bootstrap
                if "bootstrapSession/sessions/" in req.url and req.method == "POST":
                    captured["bootstrap_url"] = req.url
                    try:
                        print(f"[OK] Bootstrap URL: {req.url}")
                    except:
                        pass
                
                # Capture headers from /commands/ POST (any command)
                # NOTE: We do NOT capture x-xsrf-token here; it will come from cookies via get_xsrf_from_context()
                if "/vizql/w/MonitorConsumentenmarktEnergie/v/Variabeleenvastecontracten/sessions/" in req.url and req.method == "POST" and "/commands/" in req.url:
                    try:
                        headers = req.headers
                        command_path = req.url.split('/commands/')[-1] if '/commands/' in req.url else 'unknown'
                        captured["observed_commands"].append(command_path)
                        
                        # Debug dump: print header keys and specific values for first /commands/ POST
                        if not debug_printed["done"]:
                            try:
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
                            except:
                                pass
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
                            try:
                                print(f"\n[OK] Captured GSH={gsh_short}... x-tableau-version={tv_val}\n")
                            except:
                                pass
                    
                    except Exception as e:
                        try:
                            print(f"  Error capturing headers: {e}")
                        except:
                            pass
            except:
                pass

        def on_response(resp):
            """Capture bootstrap response status."""
            try:
                if "bootstrapSession/sessions/" in resp.url and resp.status in [200, 204]:
                    if captured["bootstrap_url"] and captured["bootstrap_url"] in resp.url:
                        captured["bootstrap_status"] = resp.status
                        try:
                            print(f"[OK] Bootstrap status: {resp.status}")
                        except:
                            pass
            except:
                pass

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
        await asyncio.sleep(3)
        
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
        await asyncio.sleep(1.5)
        
        for attempt in range(40):  # 20 seconds timeout (500ms per iteration)
            try:
                # Try clicking in page
                await page.mouse.move(400, 400)
                await page.mouse.click(400, 400)
            except:
                pass
            
            await page.wait_for_timeout(500)
            
            if captured["command_headers_ready"]:
                print(f"[OK] Command headers ready on attempt {attempt+1}")
                break
        
        # Hard timeout: check if we have the command headers
        if not captured["command_headers_ready"]:
            error_msg = f"Command headers not captured after timeout. Observed commands: {captured['observed_commands'][-3:]}"
            await browser.close()
            raise RuntimeError(error_msg)
        
        # Verify all required values are present
        if not captured["gsh"]:
            await browser.close()
            raise RuntimeError("global-session-header not captured")
        
        # Build required headers from captured values
        required_headers = {
            "accept": "text/javascript",
            "origin": "https://public.tableau.com",
            "referer": VIEW_URL,
            "x-requested-with": "XMLHttpRequest",
            "x-tableau-version": captured["tableau_version"],
            "x-tsi-active-tab": captured["active_tab"],
            "global-session-header": captured["gsh"],
        }
        
        bootstrap_url = captured["bootstrap_url"]
        session_id = extract_session_id(bootstrap_url)
        print(f"[OK] Session ID: {session_id}")
        
        # Build base commands URL
        base_url = f"https://public.tableau.com/vizql/w/MonitorConsumentenmarktEnergie/v/Variabeleenvastecontracten/sessions/{session_id}/commands"
        
        # Wait a bit for viz to render
        await asyncio.sleep(2)
        
        print(f"\nSetting month parameter...")
        month_url = f"{base_url}/tabdoc/set-parameter-value-from-index"
        month_payload = {
            "parameterName": "[Parameters].[Parameter 1]",
            "idx": "1",
            "telemetryCommandId": "wb4y"
        }
        status, resp = await post_multipart(page, month_url, month_payload, required_headers)
        print(f"  Status: {status}")
        
        month_name = "December 2025"  # idx=1 corresponds to December 2025
        
        await asyncio.sleep(0.5)
        
        # Clear all providers first
        print(f"\nClearing all providers...")
        await filter_by_provider(page, base_url, 0, "clear_all", required_headers)
        await asyncio.sleep(0.5)
        
        # Loop over first three providers
        all_contracts = {}
        target_providers = [("All in Power", 0), ("AllureNRG", 1), ("ANWB Energie", 2)]
        
        for provider_name, provider_index in target_providers:
            provider_contracts = await scrape_provider_contracts(
                page, base_url, provider_name, provider_index, month_name, session_id, required_headers
            )
            all_contracts.update(provider_contracts)
        
        print(f"\n{'='*60}")
        print(f"Total extraction complete: {len(all_contracts)} contracts across all providers")
        print(f"{'='*60}\n")
        
        # Print sample keys
        if all_contracts:
            print("Sample contract keys:")
            for i, key in enumerate(list(all_contracts.keys())[:5]):
                print(f"  {i+1}. {key}")
            if len(all_contracts) > 5:
                print(f"  ... and {len(all_contracts) - 5} more\n")
        
        await browser.close()
        return all_contracts


async def main():
    """Run the tariff scraper and save results to JSON."""
    print("Launching Playwright tariff scraper...\n")
    contracts = await scrape_with_playwright_async()
    
    # Save results to JSON file in Attempt2 folder
    output_path = Path(__file__).parent / "contracts.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(contracts, f, indent=2, ensure_ascii=False)
    print(f"[OK] Results saved to: {output_path}")
    print(f"  Total contracts: {len(contracts)}\n")
    
    return contracts


if __name__ == "__main__":
    asyncio.run(main())

