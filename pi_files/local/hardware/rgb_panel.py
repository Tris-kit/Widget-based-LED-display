import board
import displayio
import framebufferio
import rgbmatrix


class RgbPanel:
    def __init__(
        self,
        width: int = 64,
        height: int = 64,
        bit_depth: int = 6,
        serpentine: bool = True,
        doublebuffer: bool = True,
        rgb_pins=None,
    ) -> None:
        # Fail loudly if RGB matrix libraries are missing.

        displayio.release_displays()

        pins = _resolve_rgb_pins(rgb_pins)
        matrix = rgbmatrix.RGBMatrix(
            width=width,
            height=height,
            bit_depth=bit_depth,
            rgb_pins=pins,
            addr_pins=[board.GP10, board.GP16, board.GP18, board.GP20, board.GP22],
            clock_pin=board.GP11,
            latch_pin=board.GP12,
            output_enable_pin=board.GP13,
            tile=1,
            serpentine=serpentine,
            doublebuffer=doublebuffer,
        )

        self.matrix = matrix
        self.display = framebufferio.FramebufferDisplay(matrix, auto_refresh=True)
        self._brightness_warned = False
        self._brightness_mode = None
        self._matrix_brightness_scale = None

    def show(self, group: displayio.Group) -> None:
        try:
            self.display.root_group = group
        except AttributeError:
            self.display.show(group)

    def set_brightness(self, value: float) -> None:
        """Set panel brightness (0.0 to 1.0), if supported."""
        try:
            level = float(value)
        except Exception:
            return
        if level < 0.0:
            level = 0.0
        elif level > 1.0:
            level = 1.0
        if self._brightness_mode == "matrix":
            if self._try_set_matrix_brightness(level):
                return
            self._brightness_mode = None
        elif self._brightness_mode == "display":
            if self._try_set_display_brightness(level):
                return
            self._brightness_mode = None
        elif self._brightness_mode == "unsupported":
            return

        if self._try_set_matrix_brightness(level):
            self._brightness_mode = "matrix"
            return
        if self._try_set_display_brightness(level):
            self._brightness_mode = "display"
            return

        # Some display drivers don't expose brightness control.
        if not self._brightness_warned:
            self._brightness_warned = True
            print("Panel brightness control not supported by this display driver.")
        self._brightness_mode = "unsupported"

    def _try_set_matrix_brightness(self, level: float) -> bool:
        try:
            if self.matrix is None:
                return False
            if self._matrix_brightness_scale is None:
                # Detect whether brightness expects 0-1 or an integer scale.
                try:
                    self.matrix.brightness = level
                    current = getattr(self.matrix, "brightness", None)
                except Exception:
                    current = None
                if isinstance(current, int):
                    scale = None
                    for candidate in (100, 255):
                        try:
                            test_value = int(round(level * candidate))
                            self.matrix.brightness = test_value
                            current2 = getattr(self.matrix, "brightness", None)
                            if current2 == test_value:
                                scale = candidate
                                break
                        except Exception:
                            continue
                    self._matrix_brightness_scale = scale if scale is not None else 1.0
                else:
                    self._matrix_brightness_scale = 1.0
            scale = self._matrix_brightness_scale or 1.0
            if scale == 1.0:
                value = level
            else:
                value = int(round(level * scale))
            self.matrix.brightness = value
            return True
        except Exception:
            return False

    def _try_set_display_brightness(self, level: float) -> bool:
        try:
            self.display.brightness = level
            return True
        except Exception:
            return False


def _resolve_rgb_pins(rgb_pins):
    default = [
        board.GP2,
        board.GP3,
        board.GP4,
        board.GP5,
        board.GP8,
        board.GP9,
    ]
    if not rgb_pins:
        return default
    resolved = []
    try:
        for pin in rgb_pins:
            if isinstance(pin, str):
                name = pin.strip()
                if not name:
                    continue
                candidate = getattr(board, name, None)
                if candidate is None:
                    print("RGB pin not found on board:", name)
                    return default
                resolved.append(candidate)
            else:
                resolved.append(pin)
    except Exception:
        return default
    if len(resolved) != 6:
        print("RGB pin list invalid (expected 6 pins); using defaults.")
        return default
    return resolved
