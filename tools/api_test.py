#!/usr/bin/env python3
"""Simple API smoke tests runnable with normal Python."""

import argparse
import datetime as _dt
import json
import sys
import urllib.error
import urllib.request
from typing import Optional


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


def _safe_json_load(text: str) -> dict:
    cleaned = text
    for token in ("{", "["):
        idx = cleaned.find(token)
        if idx != -1:
            cleaned = cleaned[idx:]
            break
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        preview = cleaned[:200].replace("\n", " ")
        raise ValueError("JSON parse failed. Preview: {}".format(preview)) from exc


def fetch_json(url: str, timeout: int = 10) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "api-test"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
    except urllib.error.URLError as exc:
        raise RuntimeError("Network error: {}".format(exc)) from exc
    text = data.decode("utf-8-sig", errors="ignore")
    return _safe_json_load(text)


def _extract_stop_error_message(payload: dict) -> Optional[str]:
    if not isinstance(payload, dict):
        return None

    def _extract(container):
        if not isinstance(container, dict):
            return None
        for key in ("ErrorCondition", "Error", "ResponseStatus"):
            value = container.get(key)
            if isinstance(value, dict):
                for desc_key in ("Description", "ErrorText", "Text"):
                    desc = value.get(desc_key)
                    if desc:
                        return str(desc)
            elif isinstance(value, str):
                return value
        return None

    service = payload.get("ServiceDelivery", {})
    msg = _extract(service)
    if msg:
        return msg
    delivery = service.get("StopMonitoringDelivery", [])
    if isinstance(delivery, dict):
        delivery = [delivery]
    for item in delivery:
        msg = _extract(item)
        if msg:
            return msg
    return None


def _parse_utc_epoch(datetime_str: Optional[str]) -> Optional[float]:
    if not datetime_str:
        return None
    try:
        dt = _dt.datetime.strptime(datetime_str, "%Y-%m-%dT%H:%M:%SZ")
        return dt.replace(tzinfo=_dt.timezone.utc).timestamp()
    except Exception:
        return None


def test_muni_api(stop_code: str, api_token: str, agency: str = "SF", max_trains: int = 3) -> None:
    if not api_token or api_token == "YOUR_511_API_TOKEN":
        print("Muni API token missing. Set muni_api_token in config.json or pass --token.")
        return
    if not stop_code:
        print("Stop code missing. Set stop_code in config.json or pass --stop-code.")
        return

    url = (
        "http://api.511.org/transit/StopMonitoring?api_key={}"
        "&agency={}&stopcode={}&format=json"
    ).format(api_token, agency, stop_code)
    print("Muni API request:", url)
    payload = fetch_json(url)

    error_message = _extract_stop_error_message(payload)
    if error_message:
        print("Muni API error:", error_message)

    delivery = payload.get("ServiceDelivery", {}).get("StopMonitoringDelivery", [])
    if isinstance(delivery, dict):
        delivery = [delivery]
    visits = delivery[0].get("MonitoredStopVisit", []) if delivery else []

    if not visits:
        print("No arrivals returned.")
        return

    stop_name = ""
    trains = []
    for visit in visits:
        train_data = visit.get("MonitoredVehicleJourney", {})
        arrival_data = train_data.get("MonitoredCall", {})
        stop_name = arrival_data.get("StopPointName") or stop_name
        route = train_data.get("LineRef") or ""
        destination = train_data.get("DestinationName") or ""
        expected = arrival_data.get("ExpectedArrivalTime")
        trains.append((route, destination, expected))

    print("Stop:", stop_name or "Unknown")
    print("Trains:", len(trains))
    now = _dt.datetime.now(tz=_dt.timezone.utc).timestamp()
    for route, destination, expected in trains[:max_trains]:
        eta_minutes = None
        expected_epoch = _parse_utc_epoch(expected)
        if expected_epoch is not None:
            eta_minutes = int((expected_epoch - now) // 60)
        eta_text = "{}m".format(eta_minutes) if eta_minutes is not None else "?"
        print("- {} to {} in {} (expected {})".format(route, destination, eta_text, expected or "?"))


def test_weather_api(latitude: float, longitude: float) -> None:
    if latitude is None or longitude is None:
        print("Latitude/longitude missing. Set in config.json or pass --lat/--lon.")
        return

    params = (
        "latitude={}&longitude={}"
        "&daily=temperature_2m_min,temperature_2m_max"
        "&current=temperature_2m,weather_code"
        "&timezone=auto"
        "&timeformat=unixtime"
        "&wind_speed_unit=mph"
        "&temperature_unit=fahrenheit"
        "&precipitation_unit=inch"
    ).format(latitude, longitude)
    url = "https://api.open-meteo.com/v1/forecast?{}".format(params)
    print("Weather API request:", url)
    payload = fetch_json(url)

    current = payload.get("current", {})
    temp = current.get("temperature_2m")
    code = current.get("weather_code")
    utc_offset = payload.get("utc_offset_seconds")
    now_epoch = current.get("time")

    daily = payload.get("daily", {})
    mins = daily.get("temperature_2m_min") or []
    maxs = daily.get("temperature_2m_max") or []

    print("Current temp:", temp)
    print("Weather code:", code)
    print("UTC offset seconds:", utc_offset)
    print("Current epoch:", now_epoch)
    if mins and maxs:
        print("Today min/max:", mins[0], "/", maxs[0])


def run_api_checks(config_path: str, stop_code: Optional[str], token: Optional[str],
                   lat: Optional[float], lon: Optional[float],
                   agency: str, muni_only: bool, weather_only: bool) -> None:
    config = load_config(config_path)
    stop_code = stop_code or config.get("stop_code")
    token = token or config.get("muni_api_token")
    lat = lat if lat is not None else config.get("latitude")
    lon = lon if lon is not None else config.get("longitude")

    if not weather_only:
        print("=== Muni API ===")
        test_muni_api(stop_code=stop_code, api_token=token, agency=agency)
        print("")
    if not muni_only:
        print("=== Weather API ===")
        test_weather_api(latitude=lat, longitude=lon)


def main() -> int:
    parser = argparse.ArgumentParser(description="API smoke tests (Muni + Open-Meteo).")
    parser.add_argument("--config", default="pi_files/config.json", help="Path to config.json")
    parser.add_argument("--stop-code", help="Override stop_code")
    parser.add_argument("--token", help="Override muni_api_token")
    parser.add_argument("--lat", type=float, help="Override latitude")
    parser.add_argument("--lon", type=float, help="Override longitude")
    parser.add_argument("--agency", default="SF", help="Agency (default: SF)")
    parser.add_argument("--muni-only", action="store_true", help="Only run Muni API test")
    parser.add_argument("--weather-only", action="store_true", help="Only run Weather API test")

    args = parser.parse_args()
    run_api_checks(
        config_path=args.config,
        stop_code=args.stop_code,
        token=args.token,
        lat=args.lat,
        lon=args.lon,
        agency=args.agency,
        muni_only=args.muni_only,
        weather_only=args.weather_only,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
