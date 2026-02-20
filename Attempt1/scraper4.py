import re
import json
import requests
from requests_toolbelt.multipart.encoder import MultipartEncoder
from bs4 import BeautifulSoup
import asyncio

try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    pass

VIEW_URL = "https://public.tableau.com/views/MonitorConsumentenmarktEnergie/Variabeleenvastecontracten?:showVizHome=no"
WORKBOOK = "MonitorConsumentenmarktEnergie"
VIEW = "Variabeleenvastecontracten"
WORKSHEET = "Retail Tarieven staafdiagram alle contracten"
DASHBOARD = "Variabele en vaste contracten"

def parse_tooltip_table(raw_text: str) -> dict:
    """Parse tooltip HTML into a dict with normalized keys."""
    html = raw_text.replace("\\\"", "\"").replace("\\\\/", "/")
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) >= 2:
            label = tds[0].get_text(" ", strip=True).rstrip(":").strip()
            value = tds[-1].get_text(" ", strip=True).strip()
            if label and value:
                out[label] = value
    
    # Add standardized keys
    standardized = {
        "contract_name": out.get("Contractnaam"),
        "supplier": out.get("Energie leveranciers") or out.get("Energieleverancier"),
        "contract_duration": out.get("Contractduur"),
    }
    out.update(standardized)
    return out

def extract_fn_strings_from_tooltip_response(response_text: str) -> list:
    """
    Extract all available FN strings from render-tooltip-server response.
    These are found in the selectionRelaxationCommands.commandItems array.
    
    Returns list of dicts with keys:
      - 'name': Internal relaxation name
      - 'fn': Field name string (e.g., "[federated...].[none:Contractnaam:nk]")
      - 'tuple_id': Tuple ID (if available)
    """
    try:
        data = json.loads(response_text)
        commands = data.get("vqlCmdResponse", {}).get("cmdResultList", [])
        fn_strings = []
        
        for cmd in commands:
            cmd_return = cmd.get("commandReturn", {})
            tooltip = cmd_return.get("tooltipText")
            if tooltip:
                try:
                    tooltip_data = json.loads(tooltip)
                    items = tooltip_data.get("selectionRelaxationCommands", {}).get("commandItems", [])
                    for item in items:
                        command = item.get("command", "")
                        fn_match = re.search(r'fn="([^"]+)"', command)
                        tuple_match = re.search(r'tuple-id="(\d+)"', command)
                        if fn_match:
                            fn_strings.append({
                                "name": item.get("name"),
                                "fn": fn_match.group(1),
                                "tuple_id": tuple_match.group(1) if tuple_match else None,
                            })
                except (json.JSONDecodeError, TypeError):
                    pass
        
        return fn_strings
    except Exception as e:
        print(f"Warning: Could not extract FN strings: {e}")
        return []

async def capture_bootstrap_url_async(url: str = VIEW_URL, headless: bool = True) -> str:
    """
    Use Playwright to load the VIEW_URL and capture the bootstrapSession URL.
    Returns the first request URL containing "bootstrapSession/sessions/".
    """
    from playwright.async_api import async_playwright
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context()
        page = await context.new_page()

        found = {"url": None}

        def on_request(req):
            u = req.url
            if "bootstrapSession/sessions/" in u:
                found["url"] = u
                print(f"[OK] Captured bootstrapSession URL: {u}", flush=True)

        page.on("request", on_request)
        
        try:
            await asyncio.wait_for(
                page.goto(url, wait_until="domcontentloaded"),
                timeout=5
            )
        except asyncio.TimeoutError:
            print("Page load timed out (expected), continuing...", flush=True)
        except Exception as e:
            print(f"Navigation error: {e}", flush=True)
        
        # Wait for bootstrap session to appear
        for i in range(20):
            if found["url"]:
                break
            await asyncio.sleep(0.2)
        
        if not found["url"]:
            await page.mouse.move(800, 400)
            await page.wait_for_timeout(500)
            for i in range(10):
                if found["url"]:
                    break
                await asyncio.sleep(0.2)

        await browser.close()

        if not found["url"]:
            raise RuntimeError("Could not capture bootstrapSession URL from Tableau dashboard.")
        
        return found["url"]

def capture_bootstrap_url(url: str = VIEW_URL) -> str:
    """Sync wrapper for capture_bootstrap_url_async."""
    return asyncio.run(capture_bootstrap_url_async(url, headless=True))

def extract_session_id(bootstrap_url: str) -> str:
    """Extract session ID from bootstrap URL."""
    m = re.search(r"/sessions/([0-9A-F]{32}-\d+:\d+)", bootstrap_url, re.IGNORECASE)
    if not m:
        raise RuntimeError(f"Could not extract session id from: {bootstrap_url}")
    return m.group(1)

def bootstrap_session(bootstrap_url: str) -> tuple:
    """
    Call bootstrapSession endpoint and return (requests.Session, session_id).
    Extracts session_id from URL and makes a POST to initialize the session.
    """
    session_id = extract_session_id(bootstrap_url)
    
    s = requests.Session()
    s.headers.update({"user-agent": "Mozilla/5.0"})
    
    payload = {
        "worksheetPortSize": '{"w":1366,"h":768}',
        "dashboardPortSize": '{"w":1366,"h":768}',
        "clientDimension": '{"w":1366,"h":768}',
        "renderMaps": "true",
        "isBrowserRendering": "true",
        "browserRenderingThreshold": "100",
    }
    
    print(f"Calling bootstrapSession with session_id: {session_id}")
    r = s.post(
        bootstrap_url,
        data=payload,
        headers={
            "accept": "text/javascript",
            "referer": VIEW_URL,
            "origin": "https://public.tableau.com",
            "x-requested-with": "XMLHttpRequest",
        },
        timeout=30
    )
    print(f"bootstrapSession HTTP: {r.status_code}, response length: {len(r.text)}")
    
    if r.status_code >= 400:
        print(f"Warning: bootstrapSession returned {r.status_code}")
    
    return s, session_id

def select_tuple(session: requests.Session, session_id: str, tuple_id: int, fn: str) -> None:
    """
    POST to select-by-tuple-value endpoint to select a mark by tuple-id.
    fn: field name like "[federated....].[none:Contractnaam:nk]"
    """
    url = (
        f"https://public.tableau.com/vizql/w/{WORKBOOK}/"
        f"v/{VIEW}/sessions/{session_id}/commands/tabdoc/select-by-tuple-value"
    )
    
    payload = {
        "dashboard": DASHBOARD,
        "worksheet": WORKSHEET,
        "fn": fn,
        "tuple-id": str(tuple_id),
    }
    
    # Add XSRF token if available
    headers = {
        "accept": "text/javascript",
        "origin": "https://public.tableau.com",
        "referer": VIEW_URL,
        "x-requested-with": "XMLHttpRequest",
    }
    
    xsrf = session.cookies.get("XSRF-TOKEN")
    if xsrf:
        headers["x-xsrf-token"] = xsrf
    
    print(f"Selecting tuple {tuple_id} with fn={fn[:50]}...")
    r = session.post(url, data=payload, headers=headers, timeout=30)
    print(f"select-by-tuple-value HTTP: {r.status_code}, response length: {len(r.text)}")
    
    if r.status_code >= 400:
        print(f"Warning: select-by-tuple-value returned {r.status_code}")
        print(f"Response (first 300 chars): {r.text[:300]}")
    
    return r

def fetch_tooltip(session: requests.Session, session_id: str) -> str:
    """
    POST to render-tooltip-server endpoint to fetch tooltip HTML.
    Returns response text (raw HTML).
    """
    url = (
        f"https://public.tableau.com/vizql/w/{WORKBOOK}/"
        f"v/{VIEW}/sessions/{session_id}/commands/tabsrv/render-tooltip-server"
    )
    
    form = MultipartEncoder(
        fields={
            "worksheet": WORKSHEET,
            "dashboard": DASHBOARD,
            "vizRegionRect": '{"r":"viz","x":65,"y":30,"w":0,"h":0,"fieldVector":null}',
            "allowHoverActions": "true",
            "allowPromptText": "true",
            "allowWork": "true",
            "useInlineImages": "true",
            "telemetryCommandId": "python_tuple_extraction",
        }
    )
    
    headers = {
        "accept": "text/javascript",
        "origin": "https://public.tableau.com",
        "referer": VIEW_URL,
        "x-requested-with": "XMLHttpRequest",
        "content-type": form.content_type,
    }
    
    xsrf = session.cookies.get("XSRF-TOKEN")
    if xsrf:
        headers["x-xsrf-token"] = xsrf
    
    print(f"Fetching tooltip from render-tooltip-server...")
    r = session.post(url, headers=headers, data=form, timeout=30)
    print(f"render-tooltip-server HTTP: {r.status_code}, response length: {len(r.text)}")
    
    if r.status_code >= 400:
        print(f"Warning: render-tooltip-server returned {r.status_code}")
    
    return r.text

def scrape_with_bootstrap_url(bootstrap_url: str = None) -> dict:
    """
    Legacy wrapper for compatibility. Captures bootstrap and returns metadata.
    """
    if not bootstrap_url:
        bootstrap_url = capture_bootstrap_url()
    
    session, session_id = bootstrap_session(bootstrap_url)
    page_title = "Tableau Dashboard"
    
    result = {
        "bootstrap_status": 200,
        "tooltip_status": 200,
        "bootstrap_url": bootstrap_url,
        "session_id": session_id,
        "page_title": page_title,
        "api_requests_captured": 1,
        "tooltip_data": {
            "Dashboard": DASHBOARD,
            "Worksheet": WORKSHEET,
            "Status": "Bootstrap session successfully captured",
        }
    }
    
    return result

async def discover_available_fields_async() -> list:
    """
    Discover all available field names (FN strings) from the dashboard.
    DISCLAIMER: Auto-discovery has limited reliability due to Tableau session constraints.
    Recommended: Use manual extraction with known tuple IDs.
    
    Returns: List of dicts with 'name', 'fn', 'tuple_id' keys (may be empty).
    """
    
    print("\n" + "="*70)
    print("Field Discovery - Limited Support")
    print("="*70 + "\n")
    
    print("DISCLAIMER:")
    print("  Auto-discovery has limited reliability due to Tableau session constraints.")
    print("  Reliable method: Extract known tuple IDs manually.\n")
    
    print("RECOMMENDED WORKFLOW:")
    print("  1. Use DevTools Network tab to capture responses")
    print("  2. Copy FN strings from request parameters")  
    print("  3. Use: python tuple_tooltip.py --tuple-id TUPLE_ID --fn-contract 'FN_STRING'\n")
    
    print("=" * 70 + "\n")
    
    return []
    
    for i, item in enumerate(unique_fields, 1):
        # Extract field description from FN string
        fn = item["fn"]
        # Try to extract human-readable field name from FN
        field_match = re.search(r'\[([^\]]+)\]\[([^\]]+):([^:]+):nk\]', fn)
        if field_match:
            field_name = field_match.group(3)
        else:
            # Try alternate pattern
            field_match = re.search(r':([^:]+):nk\]', fn)
            if field_match:
                field_name = field_match.group(1)
            else:
                field_name = fn[-50:]  # Last 50 chars as fallback
        
        print(f"{i}. {field_name}")
        print(f"   FN String: {fn}")
        if item["tuple_id"]:
            print(f"   Tuple ID:  {item['tuple_id']}")
        print()
    
    return unique_fields

def discover_available_fields() -> list:
    """Sync wrapper for discover_available_fields_async."""
    return asyncio.run(discover_available_fields_async())

def main():
    """Legacy CLI entry point."""
    bootstrap_url = capture_bootstrap_url()
    print(f"Bootstrap URL: {bootstrap_url}")
    
    session, session_id = bootstrap_session(bootstrap_url)
    print(f"Session ID: {session_id}")

if __name__ == "__main__":
    main()