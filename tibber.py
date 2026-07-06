#!/usr/bin/env python3
"""
Tibber Data Access API - device lister with OAuth2 Authorization Code Flow.

Usage:
    python tibber_devices.py --client-id YOUR_ID --client-secret YOUR_SECRET
    python tibber_devices.py  # if CLIENT_ID / CLIENT_SECRET env vars are set

On first run it opens a browser for login and stores tokens in ~/.tibber_tokens.json.
Subsequent runs reuse the stored refresh token automatically.
"""

import argparse
import http.server
import json
import os
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

# ── constants ──────────────────────────────────────────────────────────────────

AUTH_URL   = "https://thewall.tibber.com/connect/authorize"
TOKEN_URL  = "https://thewall.tibber.com/connect/token"
API_BASE   = "https://data-api.tibber.com/v1"
SCOPES     = " ".join([
    "openid", "profile", "email", "offline_access",
    "data-api-user-read", "data-api-homes-read",
    "data-api-vehicles-read", "data-api-chargers-read",
])
CALLBACK_PORT  = 17235
REDIRECT_URI   = f"http://localhost:{CALLBACK_PORT}/callback"
TOKEN_FILE     = Path.home() / ".tibber_tokens.json"

# ── token storage ──────────────────────────────────────────────────────────────

def load_tokens():
    if TOKEN_FILE.exists():
        return json.loads(TOKEN_FILE.read_text())
    return {}

def save_tokens(tokens: dict):
    TOKEN_FILE.write_text(json.dumps(tokens, indent=2))
    TOKEN_FILE.chmod(0o600)

# ── HTTP helpers ───────────────────────────────────────────────────────────────

def post_form(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req  = urllib.request.Request(url, data=body,
                                   headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def api_get(path: str, access_token: str) -> dict | list:
    req = urllib.request.Request(f"{API_BASE}{path}",
                                  headers={"Authorization": f"Bearer {access_token}"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

# ── OAuth2 flow ────────────────────────────────────────────────────────────────

def wait_for_callback() -> str:
    """Start a one-shot local server and return the authorization code."""
    code_holder = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            code_holder["code"] = params.get("code", [None])[0]
            code_holder["error"] = params.get("error", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            if code_holder.get("code"):
                msg = "<h2>Authorization successful — you can close this tab.</h2>"
            else:
                msg = f"<h2>Authorization failed: {code_holder.get('error')}</h2>"
            self.wfile.write(msg.encode())

        def log_message(self, *_):  # silence access log
            pass

    server = http.server.HTTPServer(("localhost", CALLBACK_PORT), Handler)
    server.handle_request()  # blocks until exactly one request arrives
    server.server_close()

    if code_holder.get("error"):
        sys.exit(f"Authorization error: {code_holder['error']}")
    if not code_holder.get("code"):
        sys.exit("No code received in callback.")
    return code_holder["code"]


def authorize(client_id: str, client_secret: str) -> dict:
    """Full browser-based authorization code flow. Returns token dict."""
    params = urllib.parse.urlencode({
        "response_type": "code",
        "client_id":     client_id,
        "redirect_uri":  REDIRECT_URI,
        "scope":         SCOPES,
    })
    url = f"{AUTH_URL}?{params}"

    print(f"Opening browser for Tibber login …\n  {url}\n")
    # Open browser in background so the server below can start first
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    print(f"Waiting for callback on http://localhost:{CALLBACK_PORT}/callback …")
    code = wait_for_callback()
    print("Received authorization code, exchanging for tokens …")

    tokens = post_form(TOKEN_URL, {
        "grant_type":    "authorization_code",
        "client_id":     client_id,
        "client_secret": client_secret,
        "redirect_uri":  REDIRECT_URI,
        "code":          code,
    })
    tokens["client_id"]     = client_id
    tokens["client_secret"] = client_secret
    save_tokens(tokens)
    print("Tokens saved to", TOKEN_FILE)
    return tokens


def refresh(tokens: dict) -> dict:
    """Use the stored refresh token to get a new access token."""
    print("Refreshing access token …")
    new_tokens = post_form(TOKEN_URL, {
        "grant_type":    "refresh_token",
        "client_id":     tokens["client_id"],
        "client_secret": tokens["client_secret"],
        "refresh_token": tokens["refresh_token"],
    })
    new_tokens["client_id"]     = tokens["client_id"]
    new_tokens["client_secret"] = tokens["client_secret"]
    save_tokens(new_tokens)
    return new_tokens


def get_access_token(client_id: str, client_secret: str) -> str:
    tokens = load_tokens()
    # First run or missing credentials → full browser flow
    if not tokens.get("access_token"):
        tokens = authorize(client_id, client_secret)
        return tokens["access_token"]
    # Stored credentials differ → re-authorize
    if tokens.get("client_id") != client_id:
        tokens = authorize(client_id, client_secret)
        return tokens["access_token"]
    # Try refresh if we have a refresh token
    if tokens.get("refresh_token"):
        try:
            tokens = refresh(tokens)
            return tokens["access_token"]
        except Exception as e:
            print(f"Refresh failed ({e}), re-authorizing …")
    tokens = authorize(client_id, client_secret)
    return tokens["access_token"]

# ── device listing ─────────────────────────────────────────────────────────────

def unwrap_list(raw) -> list:
    """Return a list from whatever the API returns (list, dict-envelope, or empty)."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return next((v for v in raw.values() if isinstance(v, list)), [])
    return []


def print_json(label: str, data):
    print(f"\n{'─'*60}")
    print(f"  {label}")
    print('─'*60)
    print(json.dumps(data, indent=2))


def list_devices(access_token: str):
    homes = unwrap_list(api_get("/homes", access_token))

    if not homes:
        print("No homes found for this account.")
        return

    for home in homes:
        home_id   = home.get("id") or home.get("homeId")
        home_name = home.get("appNickname") or home.get("address", {}).get("address1") or home_id
        print(f"\n{'═'*60}")
        print(f"  HOME: {home_name}  (id: {home_id})")
        print(f"{'═'*60}")

        try:
            devices = unwrap_list(api_get(f"/homes/{home_id}/devices", access_token))
        except Exception as e:
            print(f"  Could not fetch devices: {e}")
            continue

        if not devices:
            print("  No devices found for this home.")
            continue

        for device in devices:
            device_id   = device.get("id") or device.get("deviceId")
            device_name = device.get("name") or device.get("type") or device_id
            print(f"\n  DEVICE: {device_name}  (id: {device_id})")

            try:
                detail = api_get(f"/homes/{home_id}/devices/{device_id}", access_token)
                print(json.dumps(detail, indent=4))
            except Exception as e:
                print(f"    Could not fetch device detail: {e}")

# ── entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="List Tibber devices via Data Access API")
    parser.add_argument("--client-id",     default=os.environ.get("TIBBER_CLIENT_ID"),
                        help="OAuth2 client_id  (or set TIBBER_CLIENT_ID)")
    parser.add_argument("--client-secret", default=os.environ.get("TIBBER_CLIENT_SECRET"),
                        help="OAuth2 client_secret  (or set TIBBER_CLIENT_SECRET)")
    parser.add_argument("--reauth", action="store_true",
                        help="Force a fresh browser authorization even if tokens exist")
    args = parser.parse_args()

    if not args.client_id or not args.client_secret:
        parser.error("Provide --client-id / --client-secret or set TIBBER_CLIENT_ID / TIBBER_CLIENT_SECRET")

    if args.reauth and TOKEN_FILE.exists():
        TOKEN_FILE.unlink()

    access_token = get_access_token(args.client_id, args.client_secret)
    list_devices(access_token)


if __name__ == "__main__":
    main()
