import json
from typing import Optional

from local.simple_http import SimpleHttpClient


class WeatherClient:
    def __init__(self, latitude: float, longitude: float, http_client=None) -> None:
        self.latitude = latitude
        self.longitude = longitude
        self.http_client = http_client or SimpleHttpClient()
        self.current_epoch: Optional[int] = None
        self.utc_offset_seconds: int = 0
        self.current_temperature: Optional[float] = None
        self.current_weather_code: Optional[int] = None
        self.daily_min: Optional[float] = None
        self.daily_max: Optional[float] = None

    def refresh(self) -> dict:
        params = (
            "latitude={}&longitude={}"
            "&daily=temperature_2m_min,temperature_2m_max"
            "&current=temperature_2m,weather_code"
            "&timezone=auto"
            "&timeformat=unixtime"
            "&wind_speed_unit=mph"
            "&temperature_unit=fahrenheit"
            "&precipitation_unit=inch"
        ).format(self.latitude, self.longitude)
        url = "https://api.open-meteo.com/v1/forecast?{}".format(params)
        response = self.http_client.get(url)
        try:
            data = response.text
        finally:
            try:
                response.close()
            except AttributeError:
                pass

        if isinstance(data, bytes):
            data = data.decode("utf-8-sig")
        else:
            data = data.encode().decode("utf-8-sig")

        payload = json.loads(data)
        self.utc_offset_seconds = int(payload.get("utc_offset_seconds", 0) or 0)

        current = payload.get("current", {})
        self.current_epoch = current.get("time")
        self.current_temperature = current.get("temperature_2m")
        self.current_weather_code = current.get("weather_code")

        daily = payload.get("daily", {})
        daily_min = daily.get("temperature_2m_min") or []
        daily_max = daily.get("temperature_2m_max") or []
        self.daily_min = daily_min[0] if daily_min else None
        self.daily_max = daily_max[0] if daily_max else None

        return payload
