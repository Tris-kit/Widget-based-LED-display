#!/usr/bin/env python3
"""Fetch Spotify album art through the proxy and save a BMP for Pico testing."""

import argparse
import json
import os
import struct
import sys
import urllib.error
import urllib.request
from typing import Optional, Tuple


def load_config(path: str) -> dict:
    try:
        with open(path, "r") as fh:
            return json.load(fh)
    except FileNotFoundError:
        print("Config not found:", path)
        return {}
    except json.JSONDecodeError as exc:
        print("Config JSON error:", exc)
        return {}


def url_encode(text: str) -> str:
    safe = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~"
    encoded = []
    for ch in text:
        if ch in safe:
            encoded.append(ch)
        else:
            encoded.append("%{:02X}".format(ord(ch)))
    return "".join(encoded)


def build_proxy_url(proxy_url: str, image_url: str) -> str:
    if "{url}" in proxy_url:
        return proxy_url.replace("{url}", url_encode(image_url))
    base = (proxy_url or "").rstrip("/")
    encoded = url_encode(image_url)
    return "{}/unsafe/resize:fill:64:64:1/plain/{}@bmp".format(base, encoded)


def fetch_bytes(url: str, timeout: int = 10) -> Tuple[bytes, int, dict]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "spotify-art-test",
            "Accept": "image/bmp,*/*",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", None) or resp.getcode() or 0
            data = resp.read()
            headers = dict(resp.headers.items()) if resp.headers else {}
            return data, int(status), headers
    except urllib.error.HTTPError as exc:
        body = exc.read() if hasattr(exc, "read") else b""
        raise RuntimeError("HTTP error {} ({} bytes)".format(exc.code, len(body))) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("Network error: {}".format(exc)) from exc


def inspect_bmp(data: bytes) -> Optional[dict]:
    if not data or len(data) < 54:
        return None
    if data[:2] != b"BM":
        return None
    file_size = struct.unpack("<I", data[2:6])[0]
    pixel_offset = struct.unpack("<I", data[10:14])[0]
    dib_size = struct.unpack("<I", data[14:18])[0]
    width = struct.unpack("<i", data[18:22])[0]
    height = struct.unpack("<i", data[22:26])[0]
    planes = struct.unpack("<H", data[26:28])[0]
    bpp = struct.unpack("<H", data[28:30])[0]
    compression = struct.unpack("<I", data[30:34])[0]
    return {
        "file_size": file_size,
        "pixel_offset": pixel_offset,
        "dib_size": dib_size,
        "width": width,
        "height": height,
        "planes": planes,
        "bpp": bpp,
        "compression": compression,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch album art through the Spotify proxy and save a BMP."
    )
    parser.add_argument(
        "--config",
        default="pi_files/config.json",
        help="Path to config.json (default: pi_files/config.json)",
    )
    parser.add_argument("--image-url", help="Spotify album art URL to convert")
    parser.add_argument("--proxy", help="Override spotify_image_proxy URL")
    parser.add_argument(
        "--out",
        default="pi_files/images/spotify_art_test.bmp",
        help="Output path for the BMP",
    )
    parser.add_argument("--timeout", type=int, default=10, help="Request timeout seconds")
    args = parser.parse_args()

    config = load_config(args.config)
    image_url = args.image_url or config.get("spotify_image_url")
    if not image_url:
        print("Missing image URL. Pass --image-url with a Spotify album art URL.")
        return 2

    proxy_url = args.proxy or config.get("spotify_image_proxy")
    if not proxy_url:
        print("Missing spotify_image_proxy. Set it in config.json or pass --proxy.")
        return 2

    request_url = build_proxy_url(proxy_url, image_url)
    print("Proxy request:", request_url)
    try:
        data, status, headers = fetch_bytes(request_url, timeout=args.timeout)
    except Exception as exc:
        print("Request failed:", exc)
        return 1

    if status >= 400:
        print("Proxy returned status:", status)
        return 1
    if not data:
        print("Proxy returned empty response.")
        return 1

    out_path = args.out
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "wb") as fh:
        fh.write(data)
    print("Saved BMP:", out_path, "bytes", len(data))
    if headers:
        content_type = headers.get("Content-Type") or headers.get("content-type")
        if content_type:
            print("Content-Type:", content_type)

    info = inspect_bmp(data)
    if not info:
        print("Warning: response does not look like a valid BMP.")
        return 1

    width = info["width"]
    height = info["height"]
    if height < 0:
        height = -height
    print(
        "BMP info: {}x{} bpp={} compression={}".format(
            width, height, info["bpp"], info["compression"]
        )
    )
    if width != 64 or height != 64:
        print("Warning: expected 64x64 output.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
