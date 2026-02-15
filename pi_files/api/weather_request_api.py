import json
try:
    from typing import Optional
except ImportError:
    from local.typing_compat import Optional

from api.http_client import HttpClient


def _normalize_temperature_unit(value: str) -> str:
    unit = (value or "").strip().lower()
    if unit.startswith("c"):
        return "celsius"
    if unit in ("f", "fahrenheit", "farenheit", "fahr"):
        return "fahrenheit"
    return "fahrenheit"


class WeatherClient:
    """Open-Meteo client with queued, callback-driven requests."""

    def __init__(
        self,
        latitude: float,
        longitude: float,
        http_client=None,
        temperature_unit: str = "fahrenheit",
    ) -> None:
        self.latitude = latitude
        self.longitude = longitude
        self.http_client = http_client or HttpClient()
        self.temperature_unit = _normalize_temperature_unit(temperature_unit)
        self.current_epoch: Optional[int] = None
        self.utc_offset_seconds: int = 0
        self.current_temperature: Optional[float] = None
        self.current_weather_code: Optional[int] = None
        self.daily_min: Optional[float] = None
        self.daily_max: Optional[float] = None
        self.last_error: Optional[Exception] = None
        self._last_update_monotonic: Optional[float] = None

    def _build_url(self) -> str:
        params = (
            "latitude={}&longitude={}"
            "&daily=temperature_2m_min,temperature_2m_max"
            "&current=temperature_2m,weather_code"
            "&timezone=auto"
            "&timeformat=unixtime"
            "&wind_speed_unit=mph"
            "&temperature_unit={}"
            "&precipitation_unit=inch"
        ).format(self.latitude, self.longitude, self.temperature_unit)
        return "https://api.open-meteo.com/v1/forecast?{}".format(params)

    def set_temperature_unit(self, unit: str) -> None:
        self.temperature_unit = _normalize_temperature_unit(unit)

    def request_refresh(self, on_update=None, on_error=None, on_progress=None, timeout: int = 10) -> bool:
        """Queue a weather refresh request."""
        url = self._build_url()

        def _handle_success(text, _body, _status, _headers):
            try:
                payload = _safe_json_load(text)
                self._apply_payload(payload)
                self.last_error = None
                self._last_update_monotonic = _now_monotonic()
                if on_update:
                    on_update()
            except Exception as exc:
                self.last_error = exc
                if on_error:
                    on_error(exc)

        def _handle_error(exc):
            self.last_error = exc
            if on_error:
                on_error(exc)

        return self.http_client.enqueue_get(
            url,
            on_success=_handle_success,
            on_error=_handle_error,
            on_progress=on_progress,
            timeout=timeout,
        )

    # Backwards-compatible alias: now non-blocking.
    def refresh(self, on_progress=None) -> None:
        self.request_refresh(on_progress=on_progress)

    def get_utc_epoch(self, now_monotonic: Optional[float] = None) -> Optional[int]:
        """Return a moving UTC epoch based on the last API timestamp."""
        if self.current_epoch is None or self._last_update_monotonic is None:
            return None
        if now_monotonic is None:
            now_monotonic = _now_monotonic()
        delta = int(now_monotonic - self._last_update_monotonic)
        return self.current_epoch + max(0, delta)

    def get_local_epoch(self, now_monotonic: Optional[float] = None) -> Optional[int]:
        """Return a moving local epoch based on the last API timestamp."""
        utc_epoch = self.get_utc_epoch(now_monotonic)
        if utc_epoch is None:
            return None
        return utc_epoch + int(self.utc_offset_seconds or 0)

    def _apply_payload(self, payload: dict) -> None:
        if isinstance(payload, dict):
            if payload.get("error"):
                print("Weather API error:", payload.get("reason") or payload.get("error"))
        self.utc_offset_seconds = int(payload.get("utc_offset_seconds", 0) or 0)

        current = payload.get("current", {})
        self.current_epoch = current.get("time")
        self.current_temperature = current.get("temperature_2m")
        self.current_weather_code = current.get("weather_code")

        if self.current_temperature is None:
            current_weather = payload.get("current_weather", {})
            if isinstance(current_weather, dict):
                if self.current_epoch is None:
                    self.current_epoch = current_weather.get("time")
                self.current_temperature = current_weather.get("temperature")
                if self.current_weather_code is None:
                    self.current_weather_code = current_weather.get("weathercode")

        daily = payload.get("daily", {})
        daily_min = daily.get("temperature_2m_min") or []
        daily_max = daily.get("temperature_2m_max") or []
        self.daily_min = daily_min[0] if daily_min else None
        self.daily_max = daily_max[0] if daily_max else None


def _safe_json_load(text: str) -> dict:
    cleaned = text or ""
    try:
        cleaned = cleaned.encode().decode("utf-8-sig")
    except Exception:
        pass
    for token in ("{", "["):
        idx = cleaned.find(token)
        if idx != -1:
            cleaned = cleaned[idx:]
            break
    return json.loads(cleaned)


def _now_monotonic() -> float:
    try:
        import time

        return time.monotonic()
    except Exception:
        return 0.0
