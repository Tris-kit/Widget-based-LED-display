import json
import time
try:
    from typing import List, Optional
except ImportError:
    from local.typing_compat import List, Optional

try:
    from datetime import datetime as _datetime
except ImportError:
    _datetime = None

import adafruit_requests
import socketpool
import wifi

from local.errors import DisplayError


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
        self.http_client = http_client
        self.trains: List[ArrivingTrain] = []
        self.routes: List[str] = []
        self.primary_route: str = ""

    def _get_http_client(self):
        if self.http_client is not None:
            return self.http_client
        # Choose the best available HTTP stack for the runtime.
        pool = socketpool.SocketPool(wifi.radio)
        return adafruit_requests.Session(pool)

    def query_stop_data(self, on_progress=None) -> dict:
        if not self.api_token:
            raise ValueError("api_token is required to query stop data")

        http_requests = self._get_http_client()
        # 511.org StopMonitoring endpoint.
        stop_url = (
            "http://api.511.org/transit/StopMonitoring?api_key={}"
            "&agency={}&stopcode={}&format=json"
        ).format(self.api_token, self.agency, self.stop_code)

        if on_progress and getattr(http_requests, "supports_progress", False):
            response = http_requests.get(stop_url, on_progress=on_progress)
        else:
            response = http_requests.get(stop_url)
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

        # Some responses include leading junk or non-JSON text; trim to first JSON token.
        trimmed = data
        for token in ("{", "["):
            idx = trimmed.find(token)
            if idx != -1:
                trimmed = trimmed[idx:]
                break

        try:
            return json.loads(trimmed)
        except ValueError:
            preview = trimmed[:200].replace("\n", " ")
            print("JSON parse failed. Preview:", preview)
            raise

    def populate_stop_data(self, on_progress=None) -> None:
        data = self.query_stop_data(on_progress=on_progress)
        error_message = _extract_stop_error_message(data)
        if error_message and _error_mentions_stop_code(error_message):
            raise DisplayError(
                "Invalid stop code.",
                ["Bad stop code", "Update config"],
            )
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

    def _parse_datetime_to_epoch(self, datetime_str: Optional[str]) -> Optional[int]:
        if not datetime_str:
            return None
        # Expected format: 2024-01-01T12:34:56Z (UTC)
        utc_epoch = None
        if _datetime is not None:
            try:
                dt = _datetime.strptime(datetime_str, "%Y-%m-%dT%H:%M:%SZ")
                try:
                    import calendar

                    utc_epoch = calendar.timegm(dt.timetuple())
                except Exception:
                    utc_epoch = time.mktime(dt.timetuple())
            except Exception:
                utc_epoch = None

        if utc_epoch is None:
            try:
                year = int(datetime_str[0:4])
                month = int(datetime_str[5:7])
                day = int(datetime_str[8:10])
                hour = int(datetime_str[11:13])
                minute = int(datetime_str[14:16])
                second = int(datetime_str[17:19])
            except (ValueError, IndexError):
                return None
            try:
                import calendar

                utc_epoch = calendar.timegm(
                    (year, month, day, hour, minute, second, 0, 0, 0)
                )
            except Exception:
                utc_epoch = time.mktime(
                    (year, month, day, hour, minute, second, 0, 0, 0)
                )

        return utc_epoch


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
