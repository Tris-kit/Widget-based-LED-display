import json
import time

from local.errors import DisplayError
from api.http_client import HttpClient
from local.wifi import connect_wifi
from local.hardware.led import blink_error, init_status_led, toggle_led
from local.ui.display_helpers import (
    add_time_label,
    build_display_group,
    build_error_group,
    build_error_message_group,
    build_loading_group,
    init_panel,
)
from api.weather_request_api import WeatherClient
from widgets.train_time import TrainTimeWidget

panel = None
layout = None
panel_ok = False
try:
    panel, layout = init_panel()
    panel_ok = True
except Exception as exc:
    print("RGB panel init failed:", exc)

status_led = None
try:
    status_led = init_status_led()
except Exception as exc:
    print("Status LED init failed:", exc)

def _show_error_forever(lines=None) -> None:
    error_group = None
    while True:
        if panel and layout:
            if error_group is None:
                if lines:
                    error_group = build_error_message_group(layout, lines)
                else:
                    error_group = build_error_group(layout)
            if error_group is not None:
                panel.show(error_group)
        blink_error(status_led)
        time.sleep(0.5)


def _update_loading_animation() -> None:
    global loading_index, loading_last
    if not (panel and layout):
        return
    now = time.monotonic()
    if now - loading_last < loading_interval:
        return
    loading_group = build_loading_group(
        layout,
        loading_frames[loading_index],
    )
    if loading_group is not None:
        panel.show(loading_group)
    loading_index = (loading_index + 1) % len(loading_frames)
    loading_last = now


def _on_progress() -> None:
    if not data_ready:
        _update_loading_animation()

try:
    with open("config.json", "r") as config_file:
        config = json.load(config_file)
except OSError as exc:
    print("Config load error:", repr(exc))
    _show_error_forever(["Missing config", "config.json"])
except ValueError as exc:
    print("Config parse error:", repr(exc))
    _show_error_forever(["Bad config", "config.json"])

muni_api_token = config.get("muni_api_token")
stop_code = config.get("stop_code")
use_dummy_times = False
latitude = config.get("latitude")
longitude = config.get("longitude")

try:
    if not muni_api_token or muni_api_token == "YOUR_511_API_TOKEN":
        raise DisplayError("Missing API token.", ["Set API token", "in config.json"])

    if not stop_code:
        raise DisplayError("Missing stop code.", ["Set stop code", "in config.json"])
    if latitude is None or longitude is None:
        raise DisplayError("Missing location.", ["Set latitude", "in config.json"])

    connect_wifi()

    http_client = HttpClient()
    widget = TrainTimeWidget(
        stop_code=stop_code,
        api_token=muni_api_token,
        http_client=http_client,
    )
    weather_client = WeatherClient(
        latitude=latitude,
        longitude=longitude,
        http_client=http_client,
    )
except DisplayError as exc:
    print("Startup error:", repr(exc))
    _show_error_forever(exc.lines)
except Exception as exc:
    print("Startup error:", repr(exc))
    _show_error_forever()

refresh_seconds = 30
next_refresh = time.monotonic()
led_state = False
error_state = False
error_group = None
error_message_lines = None
last_error_lines = None
data_ready = False
loading_frames = ("|", "/", "-", "\\")
loading_index = 0
loading_last = 0.0
loading_interval = 0.25

while True:
    try:
        now = time.monotonic()
        if now >= next_refresh:
            try:
                weather_client.refresh(on_progress=_on_progress)
            except Exception:
                pass
            if use_dummy_times:
                times = ["3 minutes", "12 minutes"]
            else:
                widget.refresh(on_progress=_on_progress)
                now_epoch = weather_client.current_epoch
                if now_epoch is not None and weather_client.utc_offset_seconds:
                    now_epoch = now_epoch - int(weather_client.utc_offset_seconds)
                times = widget.get_next_times(now_epoch=now_epoch)
            if panel and layout:
                group = build_display_group(
                    layout,
                    times,
                    now_epoch=weather_client.current_epoch,
                    utc_offset_seconds=weather_client.utc_offset_seconds,
                )
                panel.show(group)
            else:
                print("\n".join(times))
            next_refresh = now + refresh_seconds
            error_state = False
            error_message_lines = None
            last_error_lines = None
            error_group = None
            data_ready = True
    except DisplayError as exc:
        print("Train widget error:", repr(exc))
        error_state = True
        error_message_lines = exc.lines
    except Exception as exc:
        print("Train widget error:", repr(exc))
        try:
            import traceback

            traceback.print_exception(exc)
        except Exception:
            pass
        error_state = True

    if error_state or not panel_ok:
        if panel and layout:
            if error_message_lines != last_error_lines or error_group is None:
                if error_message_lines:
                    error_group = build_error_message_group(layout, error_message_lines)
                    last_error_lines = list(error_message_lines)
                else:
                    error_group = build_error_group(layout)
                    last_error_lines = None
            if error_group is not None:
                panel.show(error_group)
        blink_error(status_led)
        time.sleep(0.5)
    else:
        if not data_ready:
            _update_loading_animation()
        led_state = not led_state
        toggle_led(status_led, led_state)
        time.sleep(0.1)
