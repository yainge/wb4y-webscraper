import re
import json
import asyncio
import uuid
import sys
import argparse
import time
from pathlib import Path
from html.parser import HTMLParser

# Force UTF-8 output on Windows
if sys.platform == 'win32':
    import codecs
    sys.stdout.reconfigure(encoding='utf-8')

VIEW_URL = "https://public.tableau.com/views/MonitorConsumentenmarktEnergie/Variabeleenvastecontracten?:showVizHome=no"

# Load providers and months from JSON files
def load_providers():
    providers_path = Path(__file__).parent / "providers.json"
    with open(providers_path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_months():
    months_path = Path(__file__).parent / "months.json"
    with open(months_path, "r", encoding="utf-8") as f:
        return json.load(f)

PROVIDERS = load_providers()
MONTHS = load_months()


def get_year_from_month_name(month_name: str) -> int:
    """Extract year from month name format like 'januari 2026'."""
    parts = month_name.strip().split()
    if parts:
        try:
            return int(parts[-1])
        except (ValueError, IndexError):
            return 2026  # Default to 2026 if parsing fails
    return 2026


def create_year_directories(base_path: Path) -> None:
    """Create year directories: 2023/, 2024/, 2025/, 2026/."""
    for year in [2023, 2024, 2025, 2026]:
        year_dir = base_path / str(year)
        year_dir.mkdir(parents=True, exist_ok=True)


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


class TooltipTableParser(HTMLParser):
    """Minimal HTML table parser for Tableau tooltip content."""

    def __init__(self) -> None:
        super().__init__()
        self.in_tr = False
        self.in_td = False
        self.current_cell_parts = []
        self.current_row = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.in_tr = True
            self.current_row = []
        elif tag == "td" and self.in_tr:
            self.in_td = True
            self.current_cell_parts = []

    def handle_endtag(self, tag):
        if tag == "td" and self.in_td:
            cell_text = " ".join(part.strip() for part in self.current_cell_parts if part.strip())
            self.current_row.append(cell_text.strip())
            self.current_cell_parts = []
            self.in_td = False
        elif tag == "tr" and self.in_tr:
            if self.current_row:
                self.rows.append(self.current_row)
            self.current_row = []
            self.in_tr = False

    def handle_data(self, data):
        if self.in_td:
            self.current_cell_parts.append(data)


def parse_tooltip_table(raw_text: str) -> dict:
    """Parse tooltip HTML table into a dict. Extracts euro currency values."""
    html = raw_text.replace("\\\"", "\"").replace("\\\\/", "/")
    parser = TooltipTableParser()
    parser.feed(html)
    out = {}
    for row in parser.rows:
        if len(row) >= 2:
            label = row[0].rstrip(":").strip()
            value = row[-1].strip()
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


def detect_meter_type(data: dict) -> str:
    """
    Detect if contract is single or double meter based on presence of dal tariff.
    Returns "single" if only piek tariff exists, "double" if dal tariff also exists.
    """
    dal_field = "Variabel elektriciteit dal per kWh"
    dal_value = data.get(dal_field, "NaN")
    
    # If dal field exists and is not NaN, it's a double meter
    if dal_value and dal_value != "NaN":
        return "double"
    
    return "single"


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


def restructure_contract_data(
    provider_name: str,
    normalized_data: dict,
    meter_type: str,
    month_name: str,
    session_id: str
) -> dict:
    """
    Restructure contract data into new format that allows duplicate contract names
    with different meter types.
    
    Returns a dict with:
    - provider, contract_name, contract_duration, meter_type
    - tariffs dict (gas and electricity)
    - metadata (_tupleId, _month_idx, _session_id)
    """
    # Extract tariff values
    piek_field = "Variabel elektriciteit enkel / piek per kWh"
    dal_field = "Variabel elektriciteit dal per kWh"
    
    piek_value = normalized_data.get(piek_field, "NaN")
    dal_value = normalized_data.get(dal_field, "NaN")
    
    # Convert "NaN" to None for null tariffs
    piek_value = None if piek_value == "NaN" else piek_value
    dal_value = None if dal_value == "NaN" else dal_value
    
    # For single meter, dal should be None
    if meter_type == "single":
        dal_value = None
    
    restructured = {
        "provider": provider_name,
        "contract_name": normalized_data.get("Contractnaam", ""),
        "contract_duration": normalized_data.get("Contractduur", ""),
        "meter_type": meter_type,
        "tariffs": {
            "gas": {
                "fixed_yearly": normalized_data.get("Vastrecht gas per jaar", "NaN"),
                "variable_per_m3": normalized_data.get("Variabel gas per m3", "NaN")
            },
            "electricity": {
                "fixed_yearly": normalized_data.get("Vastrecht elektriciteit per jaar", "NaN"),
                "piek_per_kwh": piek_value,
                "dal_per_kwh": dal_value
            }
        },
        "estimated_annual_costs": normalized_data.get("Geschatte leveringskosten obv verbruik", "NaN"),
        "_tupleId": normalized_data.get("_tupleId", ""),
        "_month_idx": month_name,
        "_session_id": session_id
    }
    
    return restructured


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




async def scrape_provider_contracts(page, base_url: str, provider_name: str, provider_index: int, month_name: str, session_id: str, required_headers: dict) -> list:
    """
    Scrape all contracts for a specific provider.
    Returns a list of contracts (allows duplicate contract names with different meter types).
    """
    print(f"\nProvider: {provider_name} (index {provider_index})")
    print(f"Selecting provider...")
    provider_selected = await filter_by_provider(page, base_url, provider_index, "select", required_headers)
    if not provider_selected:
        print("  Warning: Provider selection may have failed")
    
    await asyncio.sleep(0.5)
    
    print(f"Phase 1: Scanning Y positions to discover tuple IDs...")
    discovered_tuple_ids = set()
    tuple_id_coords = {}
    
    select_url = f"{base_url}/tabsrv/select-region-no-return-server"
    tooltip_url = f"{base_url}/tabsrv/render-tooltip-server"
    
    X_CLICK = 140
    Y_POSITIONS = list(range(0, 4001, 30))  # Scan every 30 pixels from 0 to 4000
    
    async def scan_y_position(y_pos):
        """Scan a single Y position and return tuple IDs if found."""
        try:
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
            await post_multipart(page, select_url, select_payload, required_headers)
            
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
                            return tid, y_pos
                except:
                    pass
        except:
            pass
        return None, None
    
    # Scan all Y positions in parallel
    scan_tasks = [scan_y_position(y_pos) for y_pos in Y_POSITIONS]
    results = await asyncio.gather(*scan_tasks)
    
    for tid, y_pos in results:
        if tid is not None:
            discovered_tuple_ids.add(str(tid))
            tuple_id_coords[str(tid)] = (X_CLICK, y_pos)
            print(f"  y={y_pos}: Discovered tuple_id={tid}")
    
    print(f"[OK] Discovered {len(discovered_tuple_ids)} unique tuple IDs")
    
    # Phase 2: Fetch each contract (only if we found any tuples)
    contracts = []  # Changed from dict to list
    if discovered_tuple_ids:
        print(f"Phase 2: Fetching full contract data...")
        
        async def fetch_contract(tid):
            """Fetch a single contract's full data."""
            if tid not in tuple_id_coords:
                return None, None, None
            
            x_pos, y_pos = tuple_id_coords[tid]
            contract_data = await fetch_tooltip_at_coordinates(page, base_url, x_pos, y_pos, required_headers)
            
            if contract_data:
                normalized_data = normalize_contract_data(contract_data)
                meter_type = detect_meter_type(normalized_data)
                restructured = restructure_contract_data(
                    provider_name, normalized_data, meter_type, month_name, session_id
                )
                return tid, restructured
            return tid, None
        
        # Fetch all contracts in parallel (with concurrency limit to avoid overload)
        fetch_tasks = [fetch_contract(tid) for tid in sorted(discovered_tuple_ids)]
        results = await asyncio.gather(*fetch_tasks)
        
        for tid, contract_data in results:
            if contract_data:
                contracts.append(contract_data)
                meter_type = contract_data.get("meter_type", "unknown")
                contract_name = contract_data.get("contract_name", "")
                print(f"  [OK] tuple_id={tid}: {contract_name} ({meter_type})")
            elif tid:
                print(f"  [FAIL] tuple_id={tid}: Failed to fetch")
    
    print(f"[OK] {len(contracts)} contracts fetched for {provider_name}")
    
    # Deselect this provider before moving to next
    await filter_by_provider(page, base_url, provider_index, "deselect", required_headers)
    
    return contracts


async def scrape_with_playwright_async(month_filter: int = None, month_range: tuple = None) -> dict:
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
        
        # Create output directory structure
        output_base = Path(__file__).parent
        create_year_directories(output_base)
        
        # Wait a bit for viz to render
        await asyncio.sleep(2)
        
        # Loop through all months
        print(f"\n{'='*60}")
        print(f"Processing {len(MONTHS)} months with {len(PROVIDERS)} providers each")
        print(f"{'='*60}\n")
        
        month_results = {}  # Dict to store results per month
        
        # Filter months if specified
        if month_filter is not None:
            months_to_process = {k: v for k, v in MONTHS.items() if v == month_filter}
        elif month_range is not None:
            min_idx, max_idx = month_range
            months_to_process = {k: v for k, v in MONTHS.items() if min_idx <= v <= max_idx}
        else:
            months_to_process = MONTHS
        
        print(f"Processing {len(months_to_process)} month(s) with {len(PROVIDERS)} providers each")
        start_time = time.time()
        
        for month_name, month_idx in months_to_process.items():
            print(f"\n{'='*60}")
            print(f"Month: {month_name} (ID: {month_idx})")
            print(f"{'='*60}")
            
            year = get_year_from_month_name(month_name)
            
            # Set month parameter
            month_url = f"{base_url}/tabdoc/set-parameter-value-from-index"
            month_payload = {
                "parameterName": "[Parameters].[Parameter 1]",
                "idx": str(month_idx),
                "telemetryCommandId": "wb4y"
            }
            status, _ = await post_multipart(page, month_url, month_payload, required_headers)
            
            await asyncio.sleep(0.1)
            
            # Clear all providers first
            await filter_by_provider(page, base_url, 0, "clear_all", required_headers)
            await asyncio.sleep(0.1)
            
            # Loop over ALL providers
            all_contracts = []  # Changed from dict to list
            provider_list = list(PROVIDERS.items())
            for i, (provider_name, provider_index) in enumerate(provider_list):
                progress = f"[{i+1}/{len(PROVIDERS)}]"
                provider_contracts = await scrape_provider_contracts(
                    page, base_url, provider_name, provider_index, month_name, session_id, required_headers
                )
                all_contracts.extend(provider_contracts)  # Extend list instead of dict.update()
                
                # Minimal wait to avoid overwhelming the server
                await asyncio.sleep(0.05)
            
            # Store results for this month
            month_results[month_name] = all_contracts
            
            # Save contracts for this month to year-specific folder
            year_dir = output_base / str(year)
            output_path = year_dir / f"contracts_{month_name}.json"
            
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(all_contracts, f, indent=2, ensure_ascii=False)
            
            print(f"[OK] Saved {len(all_contracts)} contracts to: {output_path}")
        
        elapsed = time.time() - start_time
        print(f"\n{'='*60}")
        print(f"Extraction Complete!")
        print(f"{'='*60}")
        print(f"Total months processed: {len(months_to_process)}")
        print(f"Time elapsed: {elapsed:.1f} seconds ({elapsed/60:.1f} minutes)")
        
        for month_name, contracts in month_results.items():
            year = get_year_from_month_name(month_name)
            contracts_count = len(contracts)
            
            # Count by meter type
            single_count = sum(1 for c in contracts if c.get("meter_type") == "single")
            double_count = sum(1 for c in contracts if c.get("meter_type") == "double")
            
            print(f"  {month_name} ({year}/): {contracts_count} contracts ({single_count} single, {double_count} double meter)")
        
        await browser.close()
        return month_results


async def main():
    """Run the tariff scraper for all months and all providers."""
    parser = argparse.ArgumentParser(description="Extract energy tariffs from Tableau dashboard")
    parser.add_argument("--month-0-only", action="store_true", help="Only extract data for month 0")
    parser.add_argument("--month", type=int, help="Only extract data for a specific month index")
    parser.add_argument("--from-month", type=str, help="Start month (e.g., 'maart 2025')")
    parser.add_argument("--to-month", type=str, help="End month (e.g., 'februari 2026')")
    args = parser.parse_args()
    
    print("Launching Playwright tariff scraper...\n")
    
    # Determine which month(s) to process
    month_filter = None
    month_range = None
    
    if args.month_0_only:
        month_filter = 0
        print("Mode: Processing month 0 only for testing\n")
    elif args.month is not None:
        month_filter = args.month
        print(f"Mode: Processing month {args.month} only\n")
    elif args.from_month and args.to_month:
        # Find month indices
        from_idx = None
        to_idx = None
        
        for month_name, month_idx in MONTHS.items():
            if month_name.lower() == args.from_month.lower():
                from_idx = month_idx
            if month_name.lower() == args.to_month.lower():
                to_idx = month_idx
        
        if from_idx is None:
            print(f"Error: Start month '{args.from_month}' not found in months.json")
            available = ", ".join(sorted(MONTHS.keys()))
            print(f"Available months: {available}")
            return None
        
        if to_idx is None:
            print(f"Error: End month '{args.to_month}' not found in months.json")
            available = ", ".join(sorted(MONTHS.keys()))
            print(f"Available months: {available}")
            return None
        
        # Create range filter: include all months with indices between from_idx and to_idx (inclusive)
        month_range = (min(from_idx, to_idx), max(from_idx, to_idx))
        print(f"Mode: Processing months from '{args.from_month}' (index {from_idx}) to '{args.to_month}' (index {to_idx})\n")
    else:
        print(f"Mode: Processing all {len(MONTHS)} months\n")
    
    month_results = await scrape_with_playwright_async(month_filter=month_filter, month_range=month_range)
    
    # Results are already saved per month in appropriate year folders
    print(f"\n[OK] Extraction completed\n")
    
    return month_results


if __name__ == "__main__":
    asyncio.run(main())
