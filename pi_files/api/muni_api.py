import json
import time
try:
    from typing import List, Optional
except ImportError:
    from local.typing_compat import List, Optional

from api.http_client import HttpClient

_DAYS_BEFORE_MONTH = (
    0,
    31,
    59,
    90,
    120,
    151,
    181,
    212,
    243,
    273,
    304,
    334,
)


def _is_leap_year(year: int) -> bool:
    return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)


def _days_before_year(year: int) -> int:
    year -= 1
    return (
        365 * (year - 1969)
        + (year // 4 - 1969 // 4)
        - (year // 100 - 1969 // 100)
        + (year // 400 - 1969 // 400)
    )


def _utc_epoch_from_parts(
    year: int, month: int, day: int, hour: int, minute: int, second: int
) -> Optional[int]:
    if month < 1 or month > 12:
        return None
    if day < 1 or day > 31:
        return None
    days = _days_before_year(year)
    days += _DAYS_BEFORE_MONTH[month - 1]
    if month > 2 and _is_leap_year(year):
        days += 1
    days += day - 1
    return days * 86400 + (hour * 3600) + (minute * 60) + second


class ArrivingTrain:
    def __init__(
        self,
        route: Optional[str],
        destination: Optional[str],
        aimed_arrival_epoch: Optional[int],
        expected_arrival_epoch: Optional[int],
        at_stop: bool,
        occupancy_status,
    ) -> None:
        self.route = route or ""
        self.destination = destination or ""
        self.aimed_arrival_epoch = aimed_arrival_epoch
        self.expected_arrival_epoch = expected_arrival_epoch
        self.at_stop = bool(at_stop)
        self.occupancy_status = occupancy_status

    def minutes_until(self, now_epoch: Optional[float] = None) -> Optional[int]:
        if now_epoch is None:
            now_epoch = time.time()
        if self.expected_arrival_epoch is None:
            return None
        return int((self.expected_arrival_epoch - now_epoch) // 60)


class MuniStop:
    """Muni stop client that enqueues requests and updates its own state."""

    def __init__(
        self,
        stop_code: str,
        agency: str = "SF",
        api_token: Optional[str] = None,
        http_client=None,
    ) -> None:
        self.stop_code = stop_code
        self.stop_name = ""
        self.agency = agency
        self.api_token = api_token
        self.http_client = http_client or HttpClient()
        self.trains: List[ArrivingTrain] = []
        self.routes: List[str] = []
        self.primary_route: str = ""
        self.response_epoch: Optional[int] = None
        self._last_update_monotonic: Optional[float] = None
        self.last_error: Optional[Exception] = None
        self.fatal_error_lines: Optional[List[str]] = None

    def request_refresh(self, on_update=None, on_error=None, on_progress=None, timeout: int = 10) -> bool:
        """Queue a stop monitoring request."""
        if not self.api_token:
            err = ValueError("api_token is required to query stop data")
            self.last_error = err
            if on_error:
                on_error(err)
            return False

        stop_url = (
            "http://api.511.org/transit/StopMonitoring?api_key={}"
            "&agency={}&stopcode={}&format=json"
        ).format(self.api_token, self.agency, self.stop_code)

        def _handle_success(text, _body, _status, _headers):
            try:
                payload = _safe_json_load(text)
                self._apply_payload(payload)
                self.last_error = None
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
            stop_url,
            on_success=_handle_success,
            on_error=_handle_error,
            on_progress=on_progress,
            timeout=timeout,
        )

    # Backwards-compatible alias (now non-blocking).
    def populate_stop_data(self, on_progress=None) -> None:
        self.request_refresh(on_progress=on_progress)

    def _apply_payload(self, data: dict) -> None:
        error_message = _extract_stop_error_message(data)
        if error_message and _error_mentions_stop_code(error_message):
            print("Muni API error:", error_message)
            self.fatal_error_lines = ["Bad stop code", "Update config"]
            self.trains = []
            return
        self.fatal_error_lines = None

        self.response_epoch = _extract_response_epoch(
            data, self._parse_datetime_to_epoch
        )
        try:
            self._last_update_monotonic = time.monotonic()
        except Exception:
            self._last_update_monotonic = None
        new_trains = []

        delivery = data.get("ServiceDelivery", {}).get("StopMonitoringDelivery", [])
        if isinstance(delivery, dict):
            delivery = [delivery]
        if not delivery:
            self.trains = []
            return

        arriving_trains = delivery[0].get("MonitoredStopVisit", [])
        for train in arriving_trains:
            train_data = train.get("MonitoredVehicleJourney", {})
            arrival_data = train_data.get("MonitoredCall", {})

            route = train_data.get("LineRef")
            destination = train_data.get("DestinationName")
            aimed_arrival_time = arrival_data.get("AimedArrivalTime")
            expected_arrival_time = arrival_data.get("ExpectedArrivalTime")
            at_stop = arrival_data.get("VehicleAtStop")
            occupancy_status = train_data.get("seatsAvailable")
            self.stop_name = arrival_data.get("StopPointName") or self.stop_name

            arriving_train = ArrivingTrain(
                route,
                destination,
                self._parse_datetime_to_epoch(aimed_arrival_time),
                self._parse_datetime_to_epoch(expected_arrival_time),
                at_stop,
                occupancy_status,
            )
            new_trains.append(arriving_train)

        self.trains = new_trains
        self.routes = _unique_routes(new_trains)
        self.primary_route = _pick_primary_route(new_trains)

    def get_utc_epoch(self, now_monotonic: Optional[float] = None) -> Optional[int]:
        if self.response_epoch is None or self._last_update_monotonic is None:
            return None
        if now_monotonic is None:
            try:
                now_monotonic = time.monotonic()
            except Exception:
                return self.response_epoch
        delta = int(now_monotonic - self._last_update_monotonic)
        return self.response_epoch + max(0, delta)

    def _parse_datetime_to_epoch(self, datetime_str: Optional[str]) -> Optional[int]:
        if not datetime_str:
            return None
        # Expected format: 2024-01-01T12:34:56Z (UTC)
        try:
            year = int(datetime_str[0:4])
            month = int(datetime_str[5:7])
            day = int(datetime_str[8:10])
            hour = int(datetime_str[11:13])
            minute = int(datetime_str[14:16])
            second = int(datetime_str[17:19])
        except (ValueError, IndexError):
            return None

        return _utc_epoch_from_parts(year, month, day, hour, minute, second)


# --- JSON helpers ---

def _safe_json_load(text: str) -> dict:
    cleaned = text
    try:
        cleaned = cleaned.encode().decode("utf-8-sig")
    except Exception:
        pass
    for token in ("{", "["):
        idx = cleaned.find(token)
        if idx != -1:
            cleaned = cleaned[idx:]
            break
    try:
        return json.loads(cleaned)
    except ValueError:
        preview = cleaned[:200].replace("\n", " ")
        raise ValueError("JSON parse failed. Preview: {}".format(preview))


# --- Payload helpers ---

def _unique_routes(trains: List[ArrivingTrain]) -> List[str]:
    seen = []
    for train in trains:
        route = (train.route or "").strip()
        if route and route not in seen:
            seen.append(route)
    return seen


def _pick_primary_route(trains: List[ArrivingTrain]) -> str:
    counts = {}
    for train in trains:
        route = (train.route or "").strip()
        if not route:
            continue
        counts[route] = counts.get(route, 0) + 1
    if not counts:
        return ""
    return max(counts, key=counts.get)


def _extract_response_epoch(data: dict, parser) -> Optional[int]:
    if not isinstance(data, dict):
        return None

    service = data.get("ServiceDelivery")
    if service is None:
        service = data.get("Siri", {}).get("ServiceDelivery", {})

    if isinstance(service, dict):
        timestamp = service.get("ResponseTimestamp") or service.get("ResponseTimeStamp")
        if timestamp:
            return parser(timestamp)

        delivery = service.get("StopMonitoringDelivery", [])
        if isinstance(delivery, dict):
            delivery = [delivery]
        for item in delivery:
            if not isinstance(item, dict):
                continue
            timestamp = item.get("ResponseTimestamp") or item.get("ResponseTimeStamp")
            if timestamp:
                parsed = parser(timestamp)
                if parsed is not None:
                    return parsed
    return None


def _extract_stop_error_message(data: dict) -> Optional[str]:
    if not isinstance(data, dict):
        return None

    def _extract_from_container(container) -> Optional[str]:
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

    service = data.get("ServiceDelivery", {})
    message = _extract_from_container(service)
    if message:
        return message

    delivery = service.get("StopMonitoringDelivery", [])
    if isinstance(delivery, dict):
        delivery = [delivery]
    for item in delivery:
        message = _extract_from_container(item)
        if message:
            return message
        error_condition = item.get("ErrorCondition")
        if isinstance(error_condition, dict):
            desc = error_condition.get("Description") or error_condition.get("ErrorText")
            if desc:
                return str(desc)
    return None


def _error_mentions_stop_code(message: str) -> bool:
    lowered = message.lower()
    return "stop" in lowered and ("code" in lowered or "stopcode" in lowered)
