try:
    from typing import Optional, Tuple
except ImportError:
    from local.typing_compat import Optional, Tuple

try:
    import analogio
except Exception:
    analogio = None

from local.hardware.button import resolve_pin


class BrightnessKnobController:
    """Read a potentiometer over ADC and map it to brightness (0.0 to 1.0)."""

    def __init__(
        self,
        pin_name: Optional[str],
        min_value: float = 0.0,
        max_value: float = 1.0,
        invert: bool = False,
        smoothing: float = 0.2,
        deadband: float = 0.01,
    ) -> None:
        self.pin = resolve_pin(pin_name)
        self.available = analogio is not None and self.pin is not None
        self._io = analogio.AnalogIn(self.pin) if self.available else None
        self.invert = bool(invert)
        self.min_value, self.max_value = _clamp_range(min_value, max_value)
        self.smoothing = _clamp01(smoothing)
        self.deadband = max(0.0, float(deadband))
        self._filtered: Optional[float] = None
        self._last_value: Optional[float] = None

    def read_brightness(self) -> Tuple[float, bool, int]:
        """Return (brightness, changed, raw_adc) with smoothing and deadband applied."""
        if not self.available or self._io is None:
            return 0.0, False, 0
        try:
            raw_value = int(self._io.value)
            raw = float(raw_value) / 65535.0
        except Exception:
            return (self._last_value or 0.0), False, 0
        if self.invert:
            raw = 1.0 - raw
        raw = _clamp01(raw)
        scaled = self.min_value + raw * (self.max_value - self.min_value)
        if self._filtered is None or self.smoothing <= 0.0:
            filtered = scaled
        else:
            filtered = (1.0 - self.smoothing) * self._filtered + self.smoothing * scaled
        self._filtered = filtered
        if self._last_value is None or abs(filtered - self._last_value) >= self.deadband:
            self._last_value = filtered
            return filtered, True, raw_value
        return self._last_value, False, raw_value

    def deinit(self) -> None:
        try:
            if self._io is not None:
                self._io.deinit()
        except Exception:
            pass
        self._io = None


def _clamp01(value: float) -> float:
    try:
        value = float(value)
    except Exception:
        return 0.0
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _clamp_range(min_value: float, max_value: float) -> Tuple[float, float]:
    min_value = _clamp01(min_value)
    max_value = _clamp01(max_value)
    if max_value < min_value:
        max_value = min_value
    return min_value, max_value
