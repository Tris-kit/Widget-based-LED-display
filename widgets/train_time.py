from typing import List, Optional

from local.muni_api import MuniStop


class TrainTimeWidget:
    def __init__(
        self,
        stop_code: str,
        api_token: str,
        route_prefix: str = "N",
        max_trains: int = 2,
        http_client=None,
    ) -> None:
        self.stop = MuniStop(
            stop_code=stop_code,
            api_token=api_token,
            http_client=http_client,
        )
        self.route_prefix = route_prefix.upper()
        self.max_trains = max_trains

    def refresh(self) -> None:
        self.stop.populate_stop_data()

    def get_lines(self) -> List[str]:
        lines: List[str] = []
        stop_name = self.stop.stop_name or "Muni"
        header = "{} Line".format(self.route_prefix)
        lines.append("{} - {}".format(header, stop_name))

        trains = [
            train
            for train in self.stop.trains
            if (train.route or "").upper().startswith(self.route_prefix)
        ]

        if not trains:
            lines.append("No {} trains".format(self.route_prefix))
            return lines

        now_epoch = None
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

    def get_next_times(self) -> List[str]:
        trains = [
            train
            for train in self.stop.trains
            if (train.route or "").upper().startswith(self.route_prefix)
        ]

        times = []
        if not trains:
            return ["No trains"]

        for train in trains[: self.max_trains]:
            minutes = train.minutes_until()
            if minutes is None:
                times.append("No data")
            elif minutes <= 0:
                times.append("Arriving")
            elif minutes == 1:
                times.append("1 minute")
            else:
                times.append("{} minutes".format(minutes))
        return times

    def _short_destination(self, destination: Optional[str]) -> str:
        if not destination:
            return "Train"
        destination = destination.replace("Station", "Sta").replace("Street", "St")
        words = destination.split()
        if len(words) <= 2:
            return destination
        return "{} {}".format(words[0], words[-1])
