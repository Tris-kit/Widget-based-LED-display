import json
import time

import board
import displayio
import framebufferio
import rgbmatrix


DEFAULT_WIDTH = 64
DEFAULT_HEIGHT = 64
DEFAULT_BIT_DEPTH = 6
DEFAULT_ORDER = "ROIGBIV"  # Change to "ROYGBIV" if you want the classic rainbow order.

COLOR_MAP = {
    "R": ("Red", 0xFF0000),
    "O": ("Orange", 0xFF7F00),
    "Y": ("Yellow", 0xFFFF00),
    "G": ("Green", 0x00FF00),
    "B": ("Blue", 0x0000FF),
    "I": ("Indigo", 0x4B0082),
    "V": ("Violet", 0x8F00FF),
}


def _load_config(path: str = "config.json") -> dict:
    try:
        with open(path, "r") as config_file:
            return json.load(config_file)
    except Exception:
        return {}


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


def _init_display(
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    bit_depth: int = DEFAULT_BIT_DEPTH,
    rgb_pins=None,
):
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
        serpentine=True,
        doublebuffer=True,
    )
    return framebufferio.FramebufferDisplay(matrix, auto_refresh=True)


def _build_color_group(width: int, height: int):
    bitmap = displayio.Bitmap(width, height, 2)
    palette = displayio.Palette(2)
    palette[0] = 0x000000
    palette[1] = 0x000000
    for y in range(height):
        for x in range(width):
            bitmap[x, y] = 1
    group = displayio.Group()
    group.append(displayio.TileGrid(bitmap, pixel_shader=palette))
    return group, palette


def _scale_color(color: int, level: float) -> int:
    if level < 0.0:
        level = 0.0
    elif level > 1.0:
        level = 1.0
    r = (color >> 16) & 0xFF
    g = (color >> 8) & 0xFF
    b = color & 0xFF
    return (int(r * level) << 16) | (int(g * level) << 8) | int(b * level)


def _pulse_color(
    palette: displayio.Palette,
    base_color: int,
    steps: int,
    step_delay: float,
    min_level: float,
):
    if steps < 1:
        steps = 1
    ramp = list(range(steps + 1)) + list(range(steps - 1, -1, -1))
    for idx in ramp:
        level = min_level + (1.0 - min_level) * (idx / steps)
        palette[1] = _scale_color(base_color, level)
        time.sleep(step_delay)


def _iter_colors(order: str):
    for key in order:
        entry = COLOR_MAP.get(key.upper())
        if entry is None:
            print("Unknown color key:", key)
            continue
        yield key.upper(), entry[0], entry[1]


def run(
    order: str = DEFAULT_ORDER,
    pulse_steps: int = 24,
    step_delay: float = 0.03,
    min_level: float = 0.05,
    hold_seconds: float = 0.15,
    loop: bool = True,
):
    """Pulse full-screen colors in the requested order until interrupted."""
    config = _load_config()
    bit_depth = int(config.get("panel_bit_depth", DEFAULT_BIT_DEPTH))
    rgb_pins = config.get("rgb_pins")
    display = _init_display(
        width=DEFAULT_WIDTH,
        height=DEFAULT_HEIGHT,
        bit_depth=bit_depth,
        rgb_pins=rgb_pins,
    )
    group, palette = _build_color_group(DEFAULT_WIDTH, DEFAULT_HEIGHT)
    try:
        display.root_group = group
    except AttributeError:
        display.show(group)

    print("Color test running. Order:", order)
    while True:
        for key, name, color in _iter_colors(order):
            print("Color:", key, "-", name)
            _pulse_color(palette, color, pulse_steps, step_delay, min_level)
            if hold_seconds > 0:
                time.sleep(hold_seconds)
        if not loop:
            break


def once(order: str = DEFAULT_ORDER):
    """Run a single pass through the order."""
    run(
        order=order,
        pulse_steps=24,
        step_delay=0.03,
        min_level=0.05,
        hold_seconds=0.15,
        loop=False,
    )
