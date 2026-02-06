import json
import time

from local.simple_http import SimpleHttpClient
from local.wifi import connect_wifi
from local.hardware.led import blink_error, init_status_led, toggle_led
from local.ui.display_helpers import (
    add_time_label,
    build_display_group,
    build_error_group,
    init_panel,
    show_loading,
)
from local.weather_request import WeatherClient
from widgets.train_time import TrainTimeWidget

with open("config.json", "r") as config_file:
    config = json.load(config_file)

muni_api_token = config.get("muni_api_token")
stop_code = config.get("stop_code")
route_prefix = config.get("route_prefix", "N")
utc_offset_hours = config.get("utc_offset_hours", 0)
use_dummy_times = False
latitude = config.get("latitude")
longitude = config.get("longitude")

if not muni_api_token or muni_api_token == "YOUR_511_API_TOKEN":
    raise ValueError("Set muni_api_token in config.json before running.")

if not stop_code:
    raise ValueError("Set stop_code in config.json before running.")
if latitude is None or longitude is None:
    raise ValueError("Set latitude and longitude in config.json before running.")

status_led = init_status_led()

connect_wifi()

http_client = SimpleHttpClient()
widget = TrainTimeWidget(
    stop_code=stop_code,
    api_token=muni_api_token,
    route_prefix=route_prefix,
    http_client=http_client,
)
weather_client = WeatherClient(latitude=latitude, longitude=longitude, http_client=http_client)

panel = None
layout = None
panel_ok = False
try:
    panel, layout = init_panel()
    show_loading(panel, layout)
    panel_ok = True
except Exception as exc:
    print("RGB panel init failed:", exc)

refresh_seconds = 30
next_refresh = time.monotonic()
led_state = False
error_state = False
error_group = None

while True:
    try:
        now = time.monotonic()
        if now >= next_refresh:
            try:
                weather_client.refresh()
            except Exception:
                pass
            if use_dummy_times:
                times = ["3 minutes", "12 minutes"]
            else:
                widget.refresh()
                times = widget.get_next_times()
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
            if error_group is None:
                error_group = build_error_group(layout)
            if error_group is not None:
                panel.show(error_group)
        blink_error(status_led)
        time.sleep(0.5)
    else:
        led_state = not led_state
        toggle_led(status_led, led_state)
        time.sleep(0.1)
