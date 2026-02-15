import time
try:
    from typing import List, Optional
except ImportError:
    from local.typing_compat import List, Optional

from api.muni_api import MuniStop
from api.weather_request_api import WeatherClient
from local.ui.display_helpers import build_display_group, build_error_group
from local.ui.loading_animator import LoadingAnimator


def _normalize_unit(unit: str) -> str:
    """Normalize a temperature unit string to celsius or fahrenheit."""
    value = (unit or "").strip().lower()
    if value.startswith("c"):
        return "celsius"
    return "fahrenheit"


def _convert_temperature(value: Optional[float], from_unit: str, to_unit: str) -> Optional[float]:
    """Convert a temperature value between Fahrenheit and Celsius."""
    if value is None:
        return None
    base = _normalize_unit(from_unit)
    target = _normalize_unit(to_unit)
    if base == target:
        return value
    try:
        temp = float(value)
    except Exception:
        return None
    if base == "fahrenheit" and target == "celsius":
        return (temp - 32.0) * 5.0 / 9.0
    if base == "celsius" and target == "fahrenheit":
        return (temp * 9.0 / 5.0) + 32.0
    return value


class TrainTimeWidget:
    """Self-contained train widget (requests data + renders display)."""

    def __init__(
        self,
        stop_code: str,
        api_token: str,
        latitude: float,
        longitude: float,
        http_client,
        route_prefix: Optional[str] = None,
        max_trains: int = 2,
        refresh_seconds: int = 30,
        time_format: str = "12h",
        temperature_unit: str = "fahrenheit",
        time_to_stop: int = 5,
        use_dummy_times: bool = False,
        request_timeout: int = 20,
    ) -> None:
        self.stop = MuniStop(
            stop_code=stop_code,
            api_token=api_token,
            http_client=http_client,
        )
        self.weather = WeatherClient(
            latitude=latitude,
            longitude=longitude,
            http_client=http_client,
            temperature_unit=temperature_unit,
        )
        self.route_prefix = route_prefix.upper() if route_prefix else None
        self.max_trains = max_trains
        # Clamp refresh so we never query more often than every 10 seconds.
        try:
            refresh_value = int(refresh_seconds)
        except Exception:
            refresh_value = 30
        self.refresh_seconds = max(10, refresh_value)
        self.time_format = time_format
        self.temperature_unit = _normalize_unit(temperature_unit)
        self.time_to_stop = time_to_stop
        self.use_dummy_times = use_dummy_times
        self.request_timeout = request_timeout

        self.display_mode = "times"
        self.show_time = True
        self.show_temperature = True

        self.next_refresh = 0.0
        self.data_ready = False
        self.error_state = False
        self._dirty = True
        self._last_render_minute = None
        self._loading = LoadingAnimator()
        self._last_error_sig = None

    def on_activate(self, now_monotonic: float) -> None:
        """Delay querying briefly when the widget becomes active."""
        try:
            delay_until = now_monotonic + 2.0
        except Exception:
            delay_until = None
        if delay_until is None:
            return
        # Show loading immediately when activated.
        self.data_ready = False
        self._dirty = True
        if self.next_refresh < delay_until:
            self.next_refresh = delay_until

    def handle_button(self, action: str) -> None:
        if action == "click":
            if self.temperature_unit.startswith("c"):
                self.set_temperature_unit("fahrenheit")
            else:
                self.set_temperature_unit("celsius")
            print("Train widget -> temp unit:", self.temperature_unit)
        elif action == "hold":
            if self.show_time or self.show_temperature:
                self.set_display_options(False, False)
                print("Train widget -> hide time/temp")
            else:
                self.set_display_options(True, True)
                print("Train widget -> show time/temp")

    def set_display_options(self, show_time: bool, show_temperature: bool) -> None:
        if self.show_time != show_time or self.show_temperature != show_temperature:
            self.show_time = show_time
            self.show_temperature = show_temperature
            self._dirty = True

    def set_temperature_unit(self, unit: str) -> None:
        if not unit:
            return
        self.temperature_unit = _normalize_unit(unit)
        self._dirty = True

    def update(self, now_monotonic: float) -> None:
        if now_monotonic >= self.next_refresh:
            self.request_refresh()
            self.next_refresh = now_monotonic + self.refresh_seconds

    def force_refresh(self) -> None:
        self.next_refresh = 0.0

    def request_refresh(self) -> None:
        self.stop.request_refresh(
            on_update=self._on_train_update,
            on_error=self._on_train_error,
            timeout=self.request_timeout,
        )
        self.weather.request_refresh(
            on_update=self._on_weather_update,
            on_error=self._on_weather_error,
            timeout=self.request_timeout,
        )

    def render(self, layout):
        """Return a display group for the current widget state (or None)."""
        if self._sync_error_state():
            return build_error_group(layout)

        if not self.data_ready:
            return self._loading.next_group(layout)

        now_monotonic = time.monotonic()
        now_utc = self._get_now_utc(now_monotonic)
        now_local = self.weather.get_local_epoch(now_monotonic)

        # Refresh the time display when the minute changes or state is dirty.
        minute_bucket = None
        if now_utc is not None:
            minute_bucket = int(now_utc // 60)
        if not self._dirty and minute_bucket == self._last_render_minute:
            return None
        self._last_render_minute = minute_bucket
        self._dirty = False

        times = self._get_times(now_utc)
        current_temp = self.weather.current_temperature
        if not self.show_temperature:
            current_temp = None
        else:
            current_temp = _convert_temperature(
                current_temp,
                self.weather.temperature_unit,
                self.temperature_unit,
            )

        return build_display_group(
            layout,
            times,
            now_epoch=now_local,
            utc_offset_seconds=self.weather.utc_offset_seconds,
            current_temperature=current_temp,
            temperature_unit=self.temperature_unit,
            time_format=self.time_format,
            time_to_stop=self.time_to_stop,
            show_time=self.show_time,
            show_temperature=self.show_temperature,
        )

    # --- Internal helpers ---

    def _on_train_update(self) -> None:
        if not self.route_prefix and self.stop.primary_route:
            self.route_prefix = self.stop.primary_route.upper()
        self.data_ready = True
        self._dirty = True
        self._sync_error_state()

    def _on_train_error(self, _exc) -> None:
        self.data_ready = True
        self._dirty = True
        self._sync_error_state()

    def _on_weather_update(self) -> None:
        self.data_ready = True
        self._dirty = True
        self._sync_error_state()

    def _on_weather_error(self, _exc) -> None:
        self.data_ready = True
        self._dirty = True
        self._sync_error_state()

    def _sync_error_state(self) -> bool:
        error = self.stop.last_error or self.weather.last_error
        fatal = self.stop.fatal_error_lines
        self.error_state = bool(fatal or error)
        if self.error_state:
            self._log_error_once(error=error, fatal=fatal)
        return self.error_state

    def _log_error_once(self, error=None, fatal=None) -> None:
        sig = None
        if error is not None:
            sig = "exc:{}".format(repr(error))
        elif fatal is not None:
            sig = "fatal:{}".format("|".join(fatal))
        if sig is None or sig == self._last_error_sig:
            return
        self._last_error_sig = sig
        if error is not None:
            print("Widget error:", repr(error))
            try:
                import traceback

                traceback.print_exception(error)
            except Exception:
                pass
        elif fatal is not None:
            print("Widget fatal error:", fatal)

    def _get_now_utc(self, now_monotonic: float) -> Optional[int]:
        utc_epoch = self.stop.get_utc_epoch(now_monotonic)
        if utc_epoch is not None:
            return utc_epoch
        utc_epoch = self.weather.get_utc_epoch(now_monotonic)
        if utc_epoch is not None:
            return utc_epoch
        try:
            return int(time.time())
        except Exception:
            return None

    def _get_times(self, now_epoch: Optional[float]) -> List[str]:
        if self.use_dummy_times:
            return ["3 minutes", "12 minutes"]
        if self.display_mode == "lines":
            return self.get_lines(now_epoch)
        return self.get_next_times(now_epoch)

    def get_lines(self, now_epoch: Optional[float] = None) -> List[str]:
        if now_epoch is None:
            now_epoch = self.stop.response_epoch
        lines: List[str] = []
        stop_name = self.stop.stop_name or "Muni"
        header = (
            "{} Line".format(self.route_prefix)
            if self.route_prefix
            else "Muni"
        )
        lines.append("{} - {}".format(header, stop_name))

        trains = self._filtered_trains()

        if not trains:
            if self.route_prefix:
                lines.append("No {} trains".format(self.route_prefix))
            else:
                lines.append("No trains")
            return lines

        for train in trains[: self.max_trains]:
            minutes = train.minutes_until(now_epoch)
            if minutes is None:
                eta = "?"
            elif minutes <= 0:
                eta = "Due"
            else:
                eta = "{}m".format(minutes)

            destination = self._short_destination(train.destination)
            lines.append("{} {}".format(destination, eta))

        return lines

    def get_next_times(self, now_epoch: Optional[float] = None) -> List[str]:
        if now_epoch is None:
            now_epoch = self.stop.response_epoch
        trains = self._filtered_trains()

        if not trains:
            return ["No trains"]

        times = []
        for train in trains[: self.max_trains]:
            minutes = train.minutes_until(now_epoch)
            if minutes is None:
                times.append("No data")
            elif minutes <= 0:
                times.append("Arriving")
            elif minutes == 1:
                times.append("1 minute")
            else:
                times.append("{} minutes".format(minutes))
        return times

    def _filtered_trains(self) -> List:
        if not self.route_prefix:
            return list(self.stop.trains)
        return [
            train
            for train in self.stop.trains
            if (train.route or "").upper().startswith(self.route_prefix)
        ]

    def _short_destination(self, destination: Optional[str]) -> str:
        if not destination:
            return "Train"
        destination = destination.replace("Station", "Sta").replace("Street", "St")
        words = destination.split()
        if len(words) <= 2:
            return destination
        return "{} {}".format(words[0], words[-1])
