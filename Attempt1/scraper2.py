import requests
from bs4 import BeautifulSoup
from requests_toolbelt.multipart.encoder import MultipartEncoder

# ---------- Fill these from your cURL ----------
SESSION = "0DF8027BB00A45FDA9245D8A5EFF07DE-0:0"
XSRF_TOKEN = "wuJB29efUUbS8qJnAnq1ayxQqNQhY6hl"

# IMPORTANT:
# Keep this cookie string private. It's copied from your cURL.
# If the request fails, refresh the Tableau page and copy a fresh cURL.
COOKIE = (
    "tableau_public_negotiated_locale=en-us; "
    "org.springframework.web.servlet.i18n.CookieLocaleResolver.LOCALE=en; "
    "tableau_locale=en; "
    "OptanonAlertBoxClosed=2026-02-20T09:30:05.585Z; "
    "_gid=GA1.2.1747343291.1771579883; "
    "XSRF-TOKEN=wuJB29efUUbS8qJnAnq1ayxQqNQhY6hl; "
    "_cs_c=1; "
    # --- your cookie is very long; keep everything exactly as in cURL ---
    # You can paste the full cookie string from your cURL here as one line.
)

URL = (
    "https://public.tableau.com/vizql/w/MonitorConsumentenmarktEnergie/"
    f"v/Variabeleenvastecontracten/sessions/{SESSION}/commands/tabsrv/render-tooltip-server"
)

# ---------- Tooltip parser ----------
def parse_tooltip_table(raw_text: str) -> dict:
    # Tableau returns escaped HTML in many cases; normalize a bit
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

def main():
    # Build multipart body (requests will set boundary automatically)
    form = MultipartEncoder(
        fields={
            "worksheet": "Retail Tarieven staafdiagram alle contracten",
            "dashboard": "Variabele en vaste contracten",
            "vizRegionRect": '{"r":"viz","x":65,"y":30,"w":0,"h":0,"fieldVector":null}',
            "allowHoverActions": "true",
            "allowPromptText": "true",
            "allowWork": "true",
            "useInlineImages": "true",
            "telemetryCommandId": "1jht8imk8$gmce-o6-ap-ee-6em6so",
        }
    )

    headers = {
        "accept": "text/javascript",
        "origin": "https://public.tableau.com",
        "referer": "https://public.tableau.com/views/MonitorConsumentenmarktEnergie/Variabeleenvastecontracten?:showVizHome=no",
        "x-requested-with": "XMLHttpRequest",
        "x-tableau-version": "2025.3",
        "x-tsi-active-tab": "Variabele en vaste contracten",
        "x-xsrf-token": XSRF_TOKEN,
        "content-type": form.content_type,  # includes boundary
        "user-agent": "Mozilla/5.0",
        "cookie": COOKIE,
    }

    resp = requests.post(URL, headers=headers, data=form, timeout=30)
    print("HTTP:", resp.status_code)

    # Print a small raw preview so you can see if it looks like tooltip HTML
    text = resp.text
    print("\n--- RAW RESPONSE (first 800 chars) ---")
    print(text[:800])

    # Parse tooltip rows
    parsed = parse_tooltip_table(text)
    print("\n--- PARSED FIELDS (label -> value) ---")
    for k in sorted(parsed.keys()):
        print(f"{k}: {parsed[k]}")

    # Convenience: common keys
    print("\n--- QUICK CHECK ---")
    print("Contractnaam:", parsed.get("Contractnaam"))
    print("Energie leveranciers:", parsed.get("Energie leveranciers") or parsed.get("Energieleverancier"))
    print("Variabel gas per m3:", parsed.get("Variabel gas per m3"))
    print("Vastrecht elektriciteit per jaar:", parsed.get("Vastrecht elektriciteit per jaar"))

if __name__ == "__main__":
    main()