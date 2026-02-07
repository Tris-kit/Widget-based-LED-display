try:
    from typing import List, Optional
except ImportError:
    from local.typing_compat import List, Optional

from api.muni_api import MuniStop


class TrainTimeWidget:
    def __init__(
        self,
        stop_code: str,
        api_token: str,
        route_prefix: Optional[str] = None,
        max_trains: int = 2,
        http_client=None,
    ) -> None:
        self.stop = MuniStop(
            stop_code=stop_code,
            api_token=api_token,
            http_client=http_client,
        )
        self.route_prefix = route_prefix.upper() if route_prefix else None
        self.max_trains = max_trains

    def refresh(self, on_progress=None) -> None:
        self.stop.populate_stop_data(on_progress=on_progress)
        if not self.route_prefix and self.stop.primary_route:
            self.route_prefix = self.stop.primary_route.upper()

    def get_lines(self, now_epoch: Optional[float] = None) -> List[str]:
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
        trains = self._filtered_trains()

        times = []
        if not trains:
            return ["No trains"]

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
