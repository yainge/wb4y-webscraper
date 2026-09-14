"""
OAuth2 login for the Tibber Data API (https://data-api.tibber.com).

The Data API does NOT accept the personal access tokens of the old GraphQL API; it only supports the
OAuth2 Authorization Code flow (PKCE recommended) against Tibber's auth server "thewall":

    authorize : GET  https://thewall.tibber.com/connect/authorize
    token     : POST https://thewall.tibber.com/connect/token
    access token ~1 h (JWT, sent as ``Authorization: Bearer``), refresh token ~30 d (may rotate on use)

One-off setup:
    1. Create a client at https://thewall.tibber.com/clients/manage/ (also linked from data-api.tibber.com)
       - redirect URI: http://localhost:8765/callback   (plain http on localhost is allowed)
       - tick the scopes you need (see README)
    2. Put TIBBER_CLIENT_ID and TIBBER_CLIENT_SECRET in the repo-root .env (the token exchange rejects
       requests without the secret with `invalid_client`, even when PKCE is used)
    3. Run ``python tibber_auth.py login`` -> a browser opens, you log in and consent, tokens land in tokens.json

Afterwards every script calls ``get_access_token()`` which silently refreshes when needed.

Usage:
    python tibber_auth.py login                # interactive browser login (PKCE + state)
    python tibber_auth.py login --no-browser   # print the URL instead of opening a browser
    python tibber_auth.py refresh              # force a refresh-token exchange
    python tibber_auth.py status               # show expiry and scopes of the stored token
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

from common import TOKEN_FILE, env

AUTHORIZE_URL = "https://thewall.tibber.com/connect/authorize"
TOKEN_URL = "https://thewall.tibber.com/connect/token"
DEFAULT_REDIRECT_URI = "http://localhost:8765/callback"
# baseline scopes from the docs + every device category, so one consent covers everything the client allows.
# Scopes the OAuth client was not created with are simply not granted (check with ``status``).
DEFAULT_SCOPES = (
    "openid profile email offline_access "
    "data-api-user-read data-api-homes-read "
    "data-api-vehicles-read data-api-chargers-read data-api-thermostats-read "
    "data-api-energy-systems-read data-api-inverters-read data-api-meters-read"
)
USER_AGENT = "wb4u-tibber/0.1 (github.com/yainge/wb4y-webscraper)"
REFRESH_MARGIN_S = 120


class AuthError(RuntimeError):
    pass


# ----------------------------------------------------------------------------- token storage
def load_tokens() -> dict | None:
    if not TOKEN_FILE.exists():
        return None
    return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))


def save_tokens(payload: dict) -> dict:
    """Store a token response together with an absolute expiry so later calls can decide to refresh."""
    previous = load_tokens() or {}
    stored = {
        "access_token": payload["access_token"],
        "refresh_token": payload.get("refresh_token") or previous.get("refresh_token"),
        "token_type": payload.get("token_type", "Bearer"),
        "scope": payload.get("scope"),
        "expires_at": time.time() + float(payload.get("expires_in", 3600)),
        "obtained_at": time.time(),
    }
    TOKEN_FILE.write_text(json.dumps(stored, indent=2), encoding="utf-8")
    return stored


def decode_jwt_claims(token: str) -> dict:
    """Decode the (unverified) payload of a JWT; handy to inspect scopes/expiry. Empty dict if not a JWT."""
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part))
    except Exception:  # noqa: BLE001 - purely informational
        return {}


# ----------------------------------------------------------------------------- PKCE helpers
def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()  # 86 chars, within 43..128
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _client_config() -> tuple[str, str | None, str, str]:
    client_id = env("TIBBER_CLIENT_ID")
    if not client_id:
        raise AuthError("TIBBER_CLIENT_ID is not set - create a client at https://thewall.tibber.com/clients/manage/")
    return (
        client_id,
        env("TIBBER_CLIENT_SECRET"),
        env("TIBBER_REDIRECT_URI", DEFAULT_REDIRECT_URI),
        env("TIBBER_SCOPES", DEFAULT_SCOPES),
    )


def _token_request(form: dict) -> dict:
    r = requests.post(TOKEN_URL, data=form, headers={"User-Agent": USER_AGENT}, timeout=30)
    if r.status_code >= 400:
        try:
            detail = r.json()
        except ValueError:
            detail = r.text[:500]
        raise AuthError(f"token endpoint returned {r.status_code}: {detail}")
    return r.json()


# ----------------------------------------------------------------------------- interactive login
class _CallbackHandler(BaseHTTPRequestHandler):
    result: dict = {}

    def do_GET(self):  # noqa: N802 - http.server API
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _CallbackHandler.result = {k: v[0] for k, v in query.items()}
        ok = "code" in query
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        msg = "Login successful - you can close this tab." if ok else f"Login failed: {query}"
        self.wfile.write(f"<html><body><h2>Tibber Data API</h2><p>{msg}</p></body></html>".encode())

    def log_message(self, *_):  # silence the default request log
        pass


def login(open_browser: bool = True) -> dict:
    client_id, client_secret, redirect_uri, scopes = _client_config()
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scopes,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    parsed = urllib.parse.urlparse(redirect_uri)
    if parsed.hostname not in ("localhost", "127.0.0.1"):
        raise AuthError(
            "this helper only serves localhost redirect URIs; set TIBBER_REDIRECT_URI to http://localhost:8765/callback"
        )
    server = HTTPServer((parsed.hostname, parsed.port or 80), _CallbackHandler)
    _CallbackHandler.result = {}
    thread = threading.Thread(target=server.handle_request, daemon=True)  # serves exactly one request
    thread.start()

    print("Open this URL to log in to Tibber and grant access:\n\n  " + url + "\n")
    if open_browser:
        webbrowser.open(url)
    print(f"Waiting for the redirect on {redirect_uri} ...")
    thread.join(timeout=300)
    server.server_close()
    result = _CallbackHandler.result
    if not result:
        raise AuthError("no redirect received within 5 minutes")
    if result.get("state") != state:
        raise AuthError("state mismatch in redirect - possible CSRF, aborting")
    if "code" not in result:
        raise AuthError(f"authorization failed: {result.get('error')} {result.get('error_description', '')}")

    form = {
        "grant_type": "authorization_code",
        "code": result["code"],
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": verifier,
    }
    if client_secret:  # Tibber requires the secret even with PKCE (invalid_client without it)
        form["client_secret"] = client_secret
    tokens = save_tokens(_token_request(form))
    print(f"Tokens saved to {TOKEN_FILE}")
    return tokens


def refresh(tokens: dict | None = None) -> dict:
    tokens = tokens or load_tokens()
    if not tokens or not tokens.get("refresh_token"):
        raise AuthError("no refresh token stored - run `python tibber_auth.py login` first")
    client_id, client_secret, _, _ = _client_config()
    form = {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": client_id}
    if client_secret:
        form["client_secret"] = client_secret
    return save_tokens(_token_request(form))


def get_access_token() -> str:
    """
    Return a valid access token. Order: ``TIBBER_ACCESS_TOKEN`` env (e.g. pasted from the Playground)
    -> stored token (refreshed automatically when within 2 minutes of expiry).
    """
    override = env("TIBBER_ACCESS_TOKEN")
    if override:
        return override
    tokens = load_tokens()
    if not tokens:
        raise AuthError("not logged in - run `python tibber_auth.py login` (or set TIBBER_ACCESS_TOKEN)")
    if time.time() > tokens["expires_at"] - REFRESH_MARGIN_S:
        tokens = refresh(tokens)
    return tokens["access_token"]


# ----------------------------------------------------------------------------- CLI
def _status() -> int:
    tokens = load_tokens()
    if not tokens:
        print("no tokens stored")
        return 1
    remaining = tokens["expires_at"] - time.time()
    claims = decode_jwt_claims(tokens["access_token"])
    state = "valid" if remaining > 0 else "EXPIRED - will refresh on next use"
    print(f"token file : {TOKEN_FILE}")
    print(f"expires in : {remaining / 60:.1f} min ({state})")
    print(f"refresh tok: {'yes' if tokens.get('refresh_token') else 'no (offline_access scope missing?)'}")
    scopes = claims.get("scope") or tokens.get("scope")
    print(f"scopes     : {' '.join(scopes) if isinstance(scopes, list) else scopes}")
    for k in ("sub", "email", "name", "client_id"):
        if k in claims:
            print(f"{k:<11}: {claims[k]}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["login", "refresh", "status"])
    p.add_argument("--no-browser", action="store_true", help="only print the login URL")
    args = p.parse_args(argv)
    try:
        if args.command == "login":
            login(open_browser=not args.no_browser)
        elif args.command == "refresh":
            refresh()
        return _status()
    except AuthError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
