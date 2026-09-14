"""
Thin client for the Tibber Data API (REST, https://data-api.tibber.com, OpenAPI at /openapi/v1.json).

Endpoints (all GET, all need ``Authorization: Bearer <access token>``):
    /v1/homes                                          -> {"homes": [{"id", "name"}]}
    /v1/homes/{homeId}/devices                         -> {"devices": [{"id", "externalId", "info", "supportedHistory"}]}
    /v1/homes/{homeId}/devices/{deviceId}              -> + "status", "attributes", "capabilities"
    /v1/homes/{homeId}/devices/{deviceId}/history      ?since|until=<ISO date-time>&resolution=quarterHour|hour|day|month
                                                       -> {"query": {...effectiveStart/effectiveEnd/pageSize}, "items": [{"time", "data": {...}}], "next"?, "prev"?}
    /v1/homes/{homeId}/live-events/devices             -> streamable meters (needs data-api-meters-read)
    /v1/homes/{homeId}/live-events?deviceId=a&deviceId=b   -> Server-Sent Events, max 5 devices, 1 connection per home

Behaviour required by the docs (api-usage/requirements): a ``User-Agent`` of the form ``<App>/<Version> [...]``
on every request, full-jitter exponential backoff on 429/5xx honouring ``Retry-After``, never retry 400/401/403/404.
A 401 is handled once by refreshing the token.
"""

from __future__ import annotations

import json
import random
import sys
import time
from collections.abc import Iterator
from typing import Any

import requests

from tibber_auth import USER_AGENT, AuthError, get_access_token, load_tokens, refresh

BASE_URL = "https://data-api.tibber.com"
RESOLUTIONS = ("quarterHour", "hour", "day", "month")


class TibberApiError(RuntimeError):
    def __init__(self, status: int, problem: dict | str, url: str):
        self.status, self.problem, self.url = status, problem, url
        super().__init__(f"HTTP {status} for {url}: {problem}")


class TibberDataClient:
    def __init__(self, access_token: str | None = None, max_retries: int = 5, verbose: bool = False):
        self._token = access_token
        self.max_retries = max_retries
        self.verbose = verbose
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.session.headers["Accept"] = "application/json"

    # ------------------------------------------------------------------ low level
    def _headers(self) -> dict[str, str]:
        token = self._token or get_access_token()
        return {"Authorization": f"Bearer {token}"}

    def _request(self, url: str, params: dict | None = None, stream: bool = False) -> requests.Response:
        if url.startswith("/"):
            url = BASE_URL + url
        refreshed = False
        for attempt in range(self.max_retries + 1):
            r = self.session.get(url, params=params, headers=self._headers(), timeout=60, stream=stream)
            if self.verbose:
                print(f"  GET {r.url} -> {r.status_code}", file=sys.stderr)
            if r.status_code < 400:
                return r
            if r.status_code == 401 and not refreshed and not self._token:
                # expired access token: refresh once and retry immediately
                if load_tokens():
                    refresh()
                refreshed = True
                continue
            if r.status_code == 429 or r.status_code >= 500:
                if attempt >= self.max_retries:
                    break
                delay = _backoff_delay(r.headers.get("Retry-After"), attempt)
                if self.verbose:
                    print(f"  {r.status_code}: retrying in {delay:.1f}s", file=sys.stderr)
                time.sleep(delay)
                continue
            break  # 400/403/404: do not retry
        try:
            problem: dict | str = r.json()
        except ValueError:
            problem = r.text[:500]
        raise TibberApiError(r.status_code, problem, r.url)

    def get(self, path: str, params: dict | None = None) -> Any:
        return self._request(path, params=params).json()

    # ------------------------------------------------------------------ endpoints
    def homes(self) -> list[dict]:
        return self.get("/v1/homes")["homes"]

    def devices(self, home_id: str) -> list[dict]:
        return self.get(f"/v1/homes/{home_id}/devices")["devices"]

    def device(self, home_id: str, device_id: str) -> dict:
        return self.get(f"/v1/homes/{home_id}/devices/{device_id}")

    def history_page(
        self,
        home_id: str,
        device_id: str,
        resolution: str,
        since: str | None = None,
        until: str | None = None,
        cursor: str | None = None,
    ) -> dict:
        """One page. ``since`` -> forward pagination via ``next``; ``until`` -> backward via ``prev``."""
        if resolution not in RESOLUTIONS:
            raise ValueError(f"resolution must be one of {RESOLUTIONS}")
        params: dict[str, str] = {"resolution": resolution}
        if since:
            params["since"] = since
        if until:
            params["until"] = until
        if cursor:
            params["cursor"] = cursor
        return self.get(f"/v1/homes/{home_id}/devices/{device_id}/history", params)

    def history(
        self,
        home_id: str,
        device_id: str,
        resolution: str,
        since: str | None = None,
        until: str | None = None,
        max_pages: int = 10_000,
    ) -> Iterator[dict]:
        """
        Yield every ``{"time", "data"}`` item, following ``next`` (with ``since``) or ``prev`` (with ``until``)
        links until the API returns no more. The API clamps ``since`` to the earliest stored value, so
        ``since="2000-01-01T00:00:00Z"`` is a valid "give me everything" backfill.
        """
        direction = "prev" if until and not since else "next"
        page = self.history_page(home_id, device_id, resolution, since=since, until=until)
        for _ in range(max_pages):
            yield from page.get("items") or []
            link = page.get(direction)
            if not link:
                return
            page = self._follow(link)

    def _follow(self, link: str) -> dict:
        # ``next``/``prev`` are documented as navigation links; accept either a full/relative URL or a bare cursor
        if link.startswith("http"):
            return self._request(link).json()
        if link.startswith("/"):
            return self.get(link)
        raise TibberApiError(0, f"unrecognised navigation link {link!r}", link)

    def live_event_devices(self, home_id: str) -> list[dict]:
        return self.get(f"/v1/homes/{home_id}/live-events/devices")["devices"]

    def stream_live(self, home_id: str, device_ids: list[str]) -> Iterator[tuple[str, dict]]:
        """
        Yield ``(event_type, payload)`` from the SSE stream: ``measurement`` (LiveMeasurement JSON, W / kWh,
        ``timestamp`` in the home's local tz), ``ping`` (keep-alive) and ``stream_error``
        (``{"code", "transient", "retryAfter"?, "deviceId"?}``). Caller decides when to stop / reconnect.
        """
        if not 1 <= len(device_ids) <= 5:
            raise ValueError("between 1 and 5 deviceIds per connection")
        params = [("deviceId", d) for d in device_ids]
        r = self._request(f"/v1/homes/{home_id}/live-events", params=params, stream=True)
        event, data_lines = "message", []
        for raw in r.iter_lines(decode_unicode=True):
            if raw is None:
                continue
            line = raw.strip("\r")
            if line == "":  # blank line = end of one event
                if data_lines or event != "message":
                    payload_txt = "\n".join(data_lines)
                    try:
                        payload = json.loads(payload_txt) if payload_txt else {}
                    except ValueError:
                        payload = {"raw": payload_txt}
                    yield event, payload
                event, data_lines = "message", []
            elif line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
            # comments (":...") and id:/retry: are ignored


def _backoff_delay(retry_after: str | None, attempt: int, base: float = 0.4, cap: float = 15.0) -> float:
    if retry_after:
        try:
            return float(retry_after) + random.uniform(0, 0.25)
        except ValueError:  # HTTP-date form
            from email.utils import parsedate_to_datetime

            try:
                return max(0.0, (parsedate_to_datetime(retry_after).timestamp() - time.time())) + random.uniform(0, 0.25)
            except (TypeError, ValueError):
                pass
    return random.uniform(0, min(cap, base * 2**attempt))  # full jitter


__all__ = ["BASE_URL", "RESOLUTIONS", "AuthError", "TibberApiError", "TibberDataClient"]
