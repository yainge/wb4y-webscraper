"""Playwright-based fallback extractor.

Intercepts the Tableau vizql bootstrapSession XHR response (the authoritative
data payload that Tableau's own JS uses) and hands the parsed state off to
TableauScraper's internal worksheet-parsing logic.

Why: TableauScraper v0.1.29 relies on `<textarea id="tsConfigContainer">` in the
initial HTML, but Tableau Public moved to client-side rendering post-2022 — that
element is now always empty. A real browser executes the JS, fires the bootstrap
POST, and we intercept the response before the browser processes it.
"""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

import requests
import structlog
from tableauscraper import dashboard as ts_dashboard
from tableauscraper.TableauScraper import TableauScraper as _TS

from wb4u_scraper.config import ScraperSettings

logger = structlog.get_logger()

BOOTSTRAP_PATTERN = "bootstrapSession/sessions/"

# A realistic browser UA so Tableau doesn't serve a reduced page
BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def _parse_bootstrap_body(body: str) -> tuple[dict, dict]:
    """Parse Tableau's length-prefixed bootstrap response body.

    Format: ``{n1};{json_block_1}{n2};{json_block_2}``
    where n1/n2 are the exact byte lengths of each JSON block.
    Returns (info, data) where info is the first block and data is the second.
    """
    pos = 0
    blocks: list[dict] = []
    while pos < len(body) and len(blocks) < 2:
        # Read the length prefix up to ';'
        semi = body.index(";", pos)
        length = int(body[pos:semi])
        start = semi + 1
        end = start + length
        chunk = body[start:end]
        blocks.append(json.loads(chunk))
        pos = end

    if len(blocks) < 2:
        raise ValueError(f"Expected 2 JSON blocks, got {len(blocks)}")

    return blocks[0], blocks[1]


class PlaywrightExtractor:
    """Headless Chromium extractor with bootstrapSession network interception."""

    def __init__(self, settings: ScraperSettings) -> None:
        self._settings = settings

    def extract(self) -> dict[str, list[dict[str, Any]]]:
        """Extract worksheet data via headless Chromium.

        Returns:
            Dict mapping worksheet name → list of row dicts.

        Raises:
            RuntimeError: If the bootstrap response is never captured or cannot be parsed.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright not installed. Run: uv pip install playwright && playwright install chromium"
            ) from exc

        url = self._settings.tableau_url
        embed_url = f"{url}?:embed=y&:showVizHome=no"
        logger.info("playwright_extraction_start", url=embed_url)

        bootstrap_body: str | None = None
        bootstrap_url: str | None = None
        pw_cookies: list[dict] = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=BROWSER_UA)
            page = context.new_page()

            def handle_response(response: Any) -> None:
                nonlocal bootstrap_body, bootstrap_url
                if bootstrap_body is not None:
                    return
                if BOOTSTRAP_PATTERN in response.url and response.request.method == "POST":
                    try:
                        bootstrap_body = response.text()
                        bootstrap_url = response.url
                        logger.info("bootstrap_intercepted", url=response.url[:120])
                    except Exception as exc:
                        logger.warning("bootstrap_intercept_error", error=str(exc))

            page.on("response", handle_response)

            try:
                page.goto(embed_url, wait_until="networkidle", timeout=60_000)
            except Exception as exc:
                logger.warning("playwright_goto_timeout", error=str(exc))

            # Extra patience if bootstrap XHR fired after network-idle
            if not bootstrap_body:
                logger.warning("bootstrap_not_captured_waiting", extra_ms=10000)
                page.wait_for_timeout(10_000)

            pw_cookies = context.cookies()
            browser.close()

        if not bootstrap_body or not bootstrap_url:
            raise RuntimeError(
                "Playwright could not intercept the Tableau bootstrapSession response. "
                "The dashboard may require authentication or may have moved. "
                f"URL attempted: {embed_url}"
            )

        # ── Parse session coordinates from intercepted URL ────────────────────
        parsed_url = urlparse(bootstrap_url)
        path = parsed_url.path
        try:
            bootstrap_idx = path.index("/bootstrapSession")
            vizql_root = path[:bootstrap_idx]
            sessionid = path.split("/sessions/")[-1]
        except ValueError as exc:
            raise RuntimeError(f"Could not parse vizql_root/sessionid from URL: {bootstrap_url}") from exc

        host = f"{parsed_url.scheme}://{parsed_url.netloc}"
        logger.info("session_parsed", vizql_root=vizql_root, sessionid=sessionid[:10] + "...")

        # ── Parse bootstrap response body ─────────────────────────────────────
        # Tableau uses a length-prefixed format: `{n1};{json1}{n2};{json2}`
        # where n1 and n2 are the exact byte lengths of the two JSON blocks.
        # We MUST split by length, not regex — the JSON blocks contain nested
        # `}` characters which confuse any greedy/non-greedy pattern.
        try:
            info, data = _parse_bootstrap_body(bootstrap_body)
        except Exception as exc:
            raise RuntimeError(
                f"Could not parse bootstrapSession response body: {exc}. "
                f"First 300 chars: {bootstrap_body[:300]!r}"
            ) from exc

        # ── Extract dataSegments (shared data dictionary) ─────────────────────
        try:
            data_segments = (
                data["secondaryInfo"]["presModelMap"]
                ["dataDictionary"]["presModelHolder"]
                ["genDataDictionaryPresModel"]["dataSegments"]
            )
        except (KeyError, TypeError):
            logger.warning("data_segments_not_found", falling_back_to_empty=True)
            data_segments = {}

        # ── Build a minimal TableauScraper state object ───────────────────────
        ts = _TS()
        ts.data = data
        ts.info = info
        ts.dashboard = info.get("sheetName", "")
        ts.host = host
        ts.tableauData = {"vizql_root": vizql_root, "sessionid": sessionid}
        ts.dataSegments = data_segments

        # Transfer Playwright session cookies to a requests.Session
        ts.session = requests.Session()
        for cookie in pw_cookies:
            ts.session.cookies.set(
                cookie["name"],
                cookie["value"],
                domain=cookie.get("domain"),
            )

        logger.info("extracting_worksheets_from_bootstrap")

        # ── Extract worksheets using TableauScraper's parsing logic ───────────
        try:
            workbook = ts_dashboard.getWorksheets(ts, data, info)
        except Exception as exc:
            raise RuntimeError(
                f"Worksheet extraction failed after successful bootstrap interception: {exc}"
            ) from exc

        worksheets = getattr(workbook, "worksheets", [])
        if not worksheets:
            logger.warning(
                "no_worksheets_found",
                info_sheet=info.get("sheetName"),
                data_keys=list(data.keys())[:10],
            )

        # ── Convert TableauWorksheet objects → dict[name → list[dict]] ───────
        result: dict[str, list[dict[str, Any]]] = {}
        for ws in worksheets:
            try:
                df = ws.data
                if df is not None and not df.empty:
                    result[ws.name] = df.to_dict(orient="records")
                    logger.info("worksheet_extracted", name=ws.name, rows=len(result[ws.name]))
                else:
                    logger.warning("worksheet_empty", name=ws.name)
            except Exception as exc:
                logger.warning("worksheet_data_error", name=ws.name, error=str(exc))

        logger.info(
            "playwright_extraction_complete",
            worksheets=len(result),
            total_rows=sum(len(v) for v in result.values()),
        )
        return result
