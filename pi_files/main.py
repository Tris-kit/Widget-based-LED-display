import json
import time
import sys

try:
    import displayio
except Exception:
    displayio = None

from local.errors import DisplayError
from api.http_client import HttpClient
from local.wifi import connect_wifi
from local.hardware.led import init_status_led, toggle_led
from local.hardware.brightness_knob import BrightnessKnobController
from local.hardware.button import ButtonController
from local.ui import io_indicator
from local.ui.display_helpers import build_error_group, init_panel
from widgets.train_time import TrainTimeWidget
from widgets.announcements import AnnouncementsWidget
from widgets.spotify_now_playing import SpotifyNowPlayingWidget

print("Started v2")

# --- Fatal error logging ---
_ERROR_LOG_PATH = "error.log"


def _write_fatal_log(context: str, exc: Exception = None) -> None:
    try:
        with open(_ERROR_LOG_PATH, "a") as fh:
            fh.write("\n---\n")
            fh.write("context: {}\n".format(context or "fatal"))
            try:
                timestamp = time.time()
                fh.write("timestamp: {}\n".format(timestamp))
            except Exception:
                fh.write("timestamp: unknown\n")
            if exc is not None:
                fh.write("error: {}\n".format(repr(exc)))
                try:
                    sys.print_exception(exc, fh)
                except Exception:
                    try:
                        import traceback

                        traceback.print_exception(exc, file=fh)
                    except Exception:
                        fh.write("traceback: unavailable\n")
    except Exception as log_exc:
        print("Error log write failed:", repr(log_exc))


_orig_excepthook = getattr(sys, "excepthook", None)


def _fatal_excepthook(exc_type, exc, tb) -> None:
    _write_fatal_log("uncaught exception", exc)
    if _orig_excepthook:
        try:
            _orig_excepthook(exc_type, exc, tb)
        except Exception:
            pass


try:
    sys.excepthook = _fatal_excepthook
except Exception:
    pass

# --- Display setup ---
panel = None
layout = None
panel_ok = False
root_group = None
content_group = None


def _setup_display(bit_depth: int = 6, rgb_pins=None) -> bool:
    global panel, layout, panel_ok, root_group, content_group
    try:
        panel, layout = init_panel(bit_depth=bit_depth, rgb_pins=rgb_pins)
        panel_ok = True
        if panel and displayio is not None:
            root_group = displayio.Group()
            content_group = displayio.Group()
            root_group.append(content_group)
            indicator_tile = io_indicator.init_indicator(width=64, height=64, color=0x00FF00)
            if indicator_tile is not None:
                root_group.append(indicator_tile)
            panel.show(root_group)
        return True
    except Exception as exc:
        print("RGB panel init failed:", exc)
        panel_ok = False
        return False


_setup_display()

# --- Status LED ---
status_led = None
try:
    status_led = init_status_led()
except Exception as exc:
    print("Status LED init failed:", exc)
toggle_led(status_led, False)


def _build_blank_group(width: int = 64, height: int = 64):
    if displayio is None:
        return None
    bitmap = displayio.Bitmap(width, height, 1)
    palette = displayio.Palette(1)
    palette[0] = 0x000000
    group = displayio.Group()
    group.append(displayio.TileGrid(bitmap, pixel_shader=palette))
    return group


# --- Root-group swap helper (keeps IO indicator alive) ---
def _set_content_group(group) -> None:
    if panel is None:
        return
    if content_group is None:
        try:
            panel.show(group)
        except Exception:
            pass
        return
    try:
        while len(content_group):
            content_group.pop()
        if group is not None:
            content_group.append(group)
    except Exception:
        try:
            panel.show(group)
        except Exception:
            pass


# --- Error screen helper ---
def _show_error_forever(lines=None, exc: Exception = None) -> None:
    if exc is not None:
        _log_exception("Fatal error", exc)
    _write_fatal_log("fatal screen", exc)
    error_group = None
    while True:
        if panel and layout:
            if error_group is None:
                error_group = build_error_group(layout)
            if error_group is not None:
                _set_content_group(error_group)
        toggle_led(status_led, False)
        time.sleep(0.5)


def _log_exception(context: str, exc: Exception) -> None:
    print("{}:".format(context), repr(exc))
    try:
        import traceback

        traceback.print_exception(exc)
    except Exception:
        pass


# --- Config load ---
try:
    with open("config.json", "r") as config_file:
        config = json.load(config_file)
except OSError as exc:
    print("Config load error:", repr(exc))
    _show_error_forever(["Missing config", "config.json"], exc=exc)
except ValueError as exc:
    print("Config parse error:", repr(exc))
    _show_error_forever(["Bad config", "config.json"], exc=exc)

# --- Config values ---
muni_api_token = config.get("muni_api_token")
stop_code = config.get("stop_code")
use_dummy_times = False
latitude = config.get("latitude")
longitude = config.get("longitude")
time_format = str(config.get("time_format", "12h"))
temperature_unit = str(config.get("temperature_unit", "fahrenheit"))
time_to_stop = config.get("time_to_stop", 5)
refresh_seconds = int(config.get("refresh_seconds", 30))
request_timeout = int(config.get("request_timeout_seconds", 20))
spotify_client_id = config.get("spotify_client_id", "")
spotify_client_secret = config.get("spotify_client_secret", "")
spotify_refresh_token = config.get("spotify_refresh_token", "")
spotify_image_proxy = config.get("spotify_image_proxy", "")
spotify_refresh_seconds = int(config.get("spotify_refresh_seconds", 15))
spotify_request_timeout = int(config.get("spotify_request_timeout_seconds", request_timeout))
spotify_art_path = config.get("spotify_art_path", "spotify_art.bmp")
button1_pin_name = config.get("button1_pin", "GP14")
button2_pin_name = config.get("button2_pin", "GP15")

panel_bit_depth = int(config.get("panel_bit_depth", 6))
panel_rgb_pins = config.get("rgb_pins")
if panel_rgb_pins:
    _setup_display(bit_depth=panel_bit_depth, rgb_pins=panel_rgb_pins)
button_active_low = bool(config.get("button_active_low", True))
button_hold_seconds = config.get("button_hold_seconds", 0.5)
announcement_rotation = int(config.get("announcement_duration_seconds", 10))
announcements_config = config.get("announcements") or []
announcement_text_color = config.get("announcement_text_color")
start_widget = str(config.get("start_widget", "spotify")).strip().lower()


def _coerce_int(value, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


# --- Button controller ---
button_controller = None
try:
    button_controller = ButtonController(
        button1_pin_name,
        button2_pin_name,
        hold_seconds=float(button_hold_seconds),
        active_low=button_active_low,
        status_led=status_led,
    )
except Exception as exc:
    print("Button init failed:", repr(exc))

brightness_knob = None
brightness_poll_s = 0.2
next_brightness_poll = 0.0


# --- Core services (Wi-Fi + API clients) ---
try:
    try:
        brightness_knob = BrightnessKnobController("GP26")
        if brightness_knob.available and panel is not None:
            value, changed, raw = brightness_knob.read_brightness()
            panel.set_brightness(value)
            if changed:
                print("Brightness knob:", raw, "->", value)
    except Exception as exc:
        print("Brightness knob init failed:", repr(exc))
    if not muni_api_token or muni_api_token == "YOUR_511_API_TOKEN":
        raise DisplayError("Missing API token.", ["Set API token", "in config.json"])

    if not stop_code:
        raise DisplayError("Missing stop code.", ["Set stop code", "in config.json"])
    if latitude is None or longitude is None:
        raise DisplayError("Missing location.", ["Set latitude", "in config.json"])

    connect_wifi()
    http_client = HttpClient()

    train_widget = TrainTimeWidget(
        stop_code=stop_code,
        api_token=muni_api_token,
        latitude=latitude,
        longitude=longitude,
        http_client=http_client,
        refresh_seconds=refresh_seconds,
        time_format=time_format,
        temperature_unit=temperature_unit,
        time_to_stop=_coerce_int(time_to_stop, 5),
        use_dummy_times=use_dummy_times,
        request_timeout=request_timeout,
    )

    announcements_widget = AnnouncementsWidget(
        announcements=announcements_config,
        rotation_seconds=announcement_rotation,
        text_color=announcement_text_color,
    )

    spotify_widget = SpotifyNowPlayingWidget(
        client_id=spotify_client_id,
        client_secret=spotify_client_secret,
        refresh_token=spotify_refresh_token,
        image_proxy_url=spotify_image_proxy,
        http_client=http_client,
        refresh_seconds=spotify_refresh_seconds,
        request_timeout=spotify_request_timeout,
        art_path=spotify_art_path,
    )

    widgets = [announcements_widget, train_widget, spotify_widget]
    start_map = {
        "announcements": 0,
        "announcement": 0,
        "train": 1,
        "trains": 1,
        "spotify": 2,
    }
    active_widget_index = start_map.get(start_widget, 2)
except DisplayError as exc:
    print("Startup error:", repr(exc))
    _show_error_forever(exc.lines, exc=exc)
except Exception as exc:
    print("Startup error:", repr(exc))
    _show_error_forever(exc=exc)


# --- Input polling ---
def _update_buttons(now_ts: float) -> bool:
    if button_controller is None:
        return False
    return button_controller.update(now_ts)


# --- Main loop ---
blank_group = _build_blank_group()
display_enabled = True

while True:
    try:
        now = time.monotonic()
        _update_buttons(now)

        if not panel_ok:
            time.sleep(0.5)
            continue

        widget = widgets[active_widget_index]

        if button_controller is not None:
            if button_controller.consume_next_widget_requested():
                active_widget_index = (active_widget_index + 1) % len(widgets)
                widget = widgets[active_widget_index]
                if hasattr(widget, "force_refresh"):
                    widget.force_refresh()
                if hasattr(widget, "on_activate"):
                    widget.on_activate(now)
                print("Active widget:", active_widget_index)

            display_toggle = button_controller.consume_display_toggle()
            if display_toggle is not None:
                display_enabled = display_toggle
                if not display_enabled:
                    if panel is not None and blank_group is not None:
                        try:
                            panel.show(blank_group)
                        except Exception:
                            pass
                else:
                    if panel is not None and root_group is not None:
                        try:
                            panel.show(root_group)
                        except Exception:
                            pass
                    if hasattr(widget, "force_refresh"):
                        widget.force_refresh()

            widget_event = button_controller.consume_widget_event()
            if widget_event and hasattr(widget, "handle_button"):
                widget.handle_button(widget_event)

        if brightness_knob is not None and brightness_knob.available and panel is not None:
            if now >= next_brightness_poll:
                next_brightness_poll = now + brightness_poll_s
                try:
                    value, changed, raw = brightness_knob.read_brightness()
                    if changed:
                        print("Brightness knob:", raw, "->", value)
                        panel.set_brightness(value)
                except Exception as exc:
                    print("Brightness knob read failed:", repr(exc))

        widget.update(now)

        if display_enabled:
            # Render first so the UI updates before any blocking network call.
            group = widget.render(layout)
            if group is not None:
                _set_content_group(group)

        # Advance queued network requests after enqueueing and rendering.
        http_client.tick()

        time.sleep(0.1)
    except Exception as exc:
        print("Main loop error:", repr(exc))
        try:
            import traceback

            traceback.print_exception(exc)
        except Exception:
            pass
        time.sleep(0.5)
