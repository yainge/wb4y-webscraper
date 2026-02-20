import re
import requests
from bs4 import BeautifulSoup
from requests_toolbelt.multipart.encoder import MultipartEncoder

BASE_VIEW_URL = "https://public.tableau.com/views/MonitorConsumentenmarktEnergie/Variabeleenvastecontracten?:showVizHome=no"

BOOTSTRAP_URL = "https://public.tableau.com/vizql/w/MonitorConsumentenmarktEnergie/v/Variabeleenvastecontracten/bootstrapSession/sessions/"

def parse_tooltip_table(raw_text: str) -> dict:
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
    return out

def extract_session_id(bootstrap_text: str) -> str:
    # Tableau session ids often look like: XXXXX-0:0
    m = re.search(r'sessions/([0-9A-F]{32}-\d+:\d+)', bootstrap_text)
    if m:
        return m.group(1)

    # Fallback: search for the raw token pattern
    m = re.search(r'([0-9A-F]{32}-\d+:\d+)', bootstrap_text)
    if m:
        return m.group(1)

    raise RuntimeError("Could not extract session id from bootstrap response.")

def main():
    s = requests.Session()

    # 1) Load the view once to get initial cookies
    r0 = s.get(BASE_VIEW_URL, timeout=30)
    r0.raise_for_status()

    # 2) Create a fresh Tableau session via bootstrapSession
    # Tableau expects a POST with form data "sheet_id" sometimes; but many Public vizzes work with an empty POST body.
    # We'll send a minimal payload that is commonly accepted.
    bootstrap_payload = {"worksheetPortSize": '{"w":1366,"h":768}', "dashboardPortSize": '{"w":1366,"h":768}'}

    r1 = s.post(BOOTSTRAP_URL, data=bootstrap_payload, timeout=30)
    print("bootstrap HTTP:", r1.status_code)
    r1.raise_for_status()

    session_id = extract_session_id(r1.text)
    print("Fresh session_id:", session_id)

    # Extract XSRF token if present in cookies
    xsrf = s.cookies.get("XSRF-TOKEN")
    if not xsrf:
        # Sometimes it's stored with lowercase name
        xsrf = s.cookies.get("xsrf-token")
    print("XSRF cookie:", xsrf)

    # 3) Call render-tooltip-server with the fresh session
    tooltip_url = (
        "https://public.tableau.com/vizql/w/MonitorConsumentenmarktEnergie/"
        f"v/Variabeleenvastecontracten/sessions/{session_id}/commands/tabsrv/render-tooltip-server"
    )

    form = MultipartEncoder(
        fields={
            "worksheet": "Retail Tarieven staafdiagram alle contracten",
            "dashboard": "Variabele en vaste contracten",
            "vizRegionRect": '{"r":"viz","x":65,"y":30,"w":0,"h":0,"fieldVector":null}',
            "allowHoverActions": "true",
            "allowPromptText": "true",
            "allowWork": "true",
            "useInlineImages": "true",
            "telemetryCommandId": "python_test",
        }
    )

    headers = {
        "accept": "text/javascript",
        "origin": "https://public.tableau.com",
        "referer": BASE_VIEW_URL,
        "x-requested-with": "XMLHttpRequest",
        "x-tableau-version": "2025.3",
        "x-tsi-active-tab": "Variabele en vaste contracten",
        "content-type": form.content_type,
        "user-agent": "Mozilla/5.0",
    }

    # XSRF header (Tableau uses it when present)
    if xsrf:
        headers["x-xsrf-token"] = xsrf

    r2 = s.post(tooltip_url, headers=headers, data=form, timeout=30)
    print("tooltip HTTP:", r2.status_code)
    r2.raise_for_status()

    print("\n--- RAW RESPONSE (first 600 chars) ---")
    print(r2.text[:600])

    parsed = parse_tooltip_table(r2.text)
    print("\n--- PARSED FIELDS ---")
    for k in sorted(parsed.keys()):
        print(f"{k}: {parsed[k]}")

    print("\n--- QUICK CHECK ---")
    print("Contractnaam:", parsed.get("Contractnaam"))
    print("Variabel gas per m3:", parsed.get("Variabel gas per m3"))

if __name__ == "__main__":
    main()