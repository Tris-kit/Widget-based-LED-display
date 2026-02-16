#!/usr/bin/env python3
"""
Spotify Authorization Code Flow helper.

Usage:
  python3 tools/spotify_auth.py \
    --client-id YOUR_ID \
    --client-secret YOUR_SECRET \
    --redirect-uri http://127.0.0.1:8888/callback \
    --scopes user-read-currently-playing \
    --write-config \
    --config-path pi_files/config.json
"""
import argparse
import base64
import json
import secrets
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen


AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"


class _AuthHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stdlib naming
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        self.server.auth_params = params
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        if "error" in params:
            self.wfile.write(b"Spotify auth error. You can close this window.\n")
        else:
            self.wfile.write(b"Spotify auth complete. You can close this window.\n")

    def log_message(self, _format, *_args):
        # Silence default HTTP server logs.
        return


def _build_auth_url(client_id: str, redirect_uri: str, scopes: str, state: str) -> str:
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scopes,
            "state": state,
        }
    )
    return "{}?{}".format(AUTH_URL, query)


def _exchange_code_for_tokens(
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
) -> dict:
    auth_bytes = "{}:{}".format(client_id, client_secret).encode("utf-8")
    auth_header = base64.b64encode(auth_bytes).decode("utf-8")
    body = urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }
    ).encode("utf-8")
    req = Request(TOKEN_URL, data=body, method="POST")
    req.add_header("Authorization", "Basic {}".format(auth_header))
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    return json.loads(raw)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Spotify auth helper")
    parser.add_argument("--client-id", required=True, help="Spotify Client ID")
    parser.add_argument("--client-secret", required=True, help="Spotify Client Secret")
    parser.add_argument(
        "--redirect-uri",
        default="http://127.0.0.1:15298/callback",
        help="Redirect URI configured in Spotify developer dashboard",
    )
    parser.add_argument(
        "--scopes",
        default="user-read-currently-playing",
        help="Spotify scopes (space-separated)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="Seconds to wait for the auth redirect",
    )
    parser.add_argument(
        "--write-config",
        action="store_true",
        help="Write spotify_* values into config.json",
    )
    parser.add_argument(
        "--config-path",
        default="pi_files/config.json",
        help="Path to config.json to update",
    )
    return parser.parse_args()


def _write_config(
    path: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> bool:
    """Write spotify credentials into the JSON config file."""
    try:
        with open(path, "r", encoding="utf-8") as config_file:
            config = json.load(config_file)
    except Exception:
        return False

    config["spotify_client_id"] = client_id
    config["spotify_client_secret"] = client_secret
    config["spotify_refresh_token"] = refresh_token

    try:
        with open(path, "w", encoding="utf-8") as config_file:
            json.dump(config, config_file, indent=2, sort_keys=False)
            config_file.write("\n")
    except Exception:
        return False
    return True


def main() -> int:
    args = _parse_args()
    redirect = urlparse(args.redirect_uri)
    if not redirect.hostname or not redirect.port:
        print("Redirect URI must include host and port, e.g. http://127.0.0.1:8888/callback")
        return 1

    state = secrets.token_urlsafe(16)
    auth_url = _build_auth_url(args.client_id, args.redirect_uri, args.scopes, state)

    print("\n1) Open this URL in a browser and authorize:\n")
    print(auth_url)
    print("\n2) Waiting for Spotify to redirect back...\n")

    server = HTTPServer((redirect.hostname, redirect.port), _AuthHandler)
    server.auth_params = {}
    server.timeout = 1.0

    start = time.time()
    while time.time() - start < args.timeout:
        server.handle_request()
        if server.auth_params:
            break

    params = server.auth_params or {}
    if not params:
        print("Timed out waiting for redirect.")
        return 2
    if "error" in params:
        print("Spotify returned error:", params.get("error", ["unknown"])[0])
        return 3
    code = params.get("code", [None])[0]
    returned_state = params.get("state", [None])[0]
    if not code:
        print("No authorization code received.")
        return 4
    if returned_state != state:
        print("State mismatch; aborting.")
        return 5

    print("Authorization code received. Exchanging for tokens...\n")
    try:
        tokens = _exchange_code_for_tokens(
            args.client_id,
            args.client_secret,
            code,
            args.redirect_uri,
        )
    except Exception as exc:
        print("Token exchange failed:", repr(exc))
        return 6

    refresh_token = tokens.get("refresh_token", "")
    access_token = tokens.get("access_token", "")
    expires_in = tokens.get("expires_in")
    scope = tokens.get("scope", "")

    print("Access token:", access_token)
    print("Expires in:", expires_in)
    print("Scope:", scope)
    print("\nRefresh token:")
    print(refresh_token)
    if not refresh_token:
        print("\nNo refresh token returned. Make sure this is a fresh auth code.")

    if args.write_config and refresh_token:
        if _write_config(
            args.config_path,
            args.client_id,
            args.client_secret,
            refresh_token,
        ):
            print("\nUpdated config:", args.config_path)
        else:
            print("\nFailed to update config:", args.config_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
