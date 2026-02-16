import json
import time

import wifi as cp_wifi

from local.errors import DisplayError


def _append_error_log(context: str, message: str = "", exc: Exception = None) -> None:
    try:
        with open("error.log", "a") as fh:
            fh.write("\n---\n")
            fh.write("context: {}\n".format(context or "wifi"))
            try:
                fh.write("timestamp: {}\n".format(time.time()))
            except Exception:
                fh.write("timestamp: unknown\n")
            if message:
                fh.write("message: {}\n".format(message))
            if exc is not None:
                fh.write("error: {}\n".format(repr(exc)))
    except Exception:
        pass


def load_wifi_config(config_path: str = "config.json") -> dict:
    with open(config_path, "r") as config_file:
        return json.load(config_file)


def connect_wifi(
    config_path: str = "config.json",
    timeout_seconds: int = 20,
    force_reconnect: bool = False,
) -> bool:
    config = load_wifi_config(config_path)
    ssid = config.get("ssid")
    password = config.get("ssid_password")

    if not ssid or not password:
        print("Wi-Fi config missing: ssid or password not set.")
        _append_error_log("wifi", "Wi-Fi config missing (ssid or password).")
        raise DisplayError(
            "Wi-Fi config missing.",
            ["Wi-Fi config", "missing"],
        )

    # CircuitPython
    if cp_wifi.radio.ipv4_address and not force_reconnect:
        try:
            print("Wi-Fi already connected:", cp_wifi.radio.ipv4_address)
        except Exception:
            pass
        return True

    if force_reconnect:
        print("Wi-Fi reconnect requested.")
        try:
            cp_wifi.radio.disconnect()
        except Exception:
            pass
        try:
            if hasattr(cp_wifi.radio, "enabled"):
                cp_wifi.radio.enabled = False
                time.sleep(0.5)
                cp_wifi.radio.enabled = True
                time.sleep(0.5)
        except Exception:
            pass

    try:
        print("Wi-Fi connect: ssid={}".format(ssid))
        cp_wifi.radio.connect(ssid, password)
        try:
            print("Wi-Fi connected:", cp_wifi.radio.ipv4_address)
        except Exception:
            pass
    except Exception as exc:
        print("Wi-Fi connect error:", exc.__class__.__name__, repr(exc))
        _append_error_log("wifi", "Wi-Fi connect failed (ssid={})".format(ssid), exc)
        raise DisplayError(
            "Wi-Fi connection failed.",
            ["Wi-Fi failed", "Check SSID/pw"],
        ) from exc
    return True
