import json
import time

import wifi as cp_wifi

from local.errors import DisplayError

def load_wifi_config(config_path: str = "config.json") -> dict:
    with open(config_path, "r") as config_file:
        return json.load(config_file)


def connect_wifi(config_path: str = "config.json", timeout_seconds: int = 20) -> bool:
    config = load_wifi_config(config_path)
    ssid = config.get("ssid")
    password = config.get("ssid_password")

    if not ssid or not password:
        raise DisplayError(
            "Wi-Fi config missing.",
            ["Wi-Fi config", "missing"],
        )

    # CircuitPython
    if cp_wifi.radio.ipv4_address:
        return True

    try:
        cp_wifi.radio.connect(ssid, password)
    except Exception as exc:
        raise DisplayError(
            "Wi-Fi connection failed.",
            ["Wi-Fi failed", "Check SSID/pw"],
        ) from exc
    return True
