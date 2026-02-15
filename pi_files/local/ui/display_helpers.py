import time
try:
    from typing import Optional, Sequence, Tuple
except ImportError:
    from local.typing_compat import Optional, Sequence, Tuple

import displayio

from local.hardware.rgb_panel import RgbPanel
from local.ui.text_layout import SimpleTextLayout


def init_panel() -> Tuple[RgbPanel, SimpleTextLayout]:
    """Create and return the RGB panel and text layout."""
    panel = RgbPanel(width=64, height=64)
    layout = SimpleTextLayout()
    if displayio is not None:
        bitmap = displayio.Bitmap(64, 64, 2)
        palette = displayio.Palette(2)
        palette[0] = 0x000000
        palette[1] = 0x00FF00
        for y in range(64):
            for x in range(64):
                bitmap[x, y] = 1 if (x + y) % 2 == 0 else 0
        test_group = displayio.Group()
        test_group.append(displayio.TileGrid(bitmap, pixel_shader=palette))
        panel.show(test_group)
        time.sleep(1)
    return panel, layout


def show_loading(panel: RgbPanel, layout: SimpleTextLayout) -> None:
    """Render the loading animation onto the panel."""
    for frame in ("|", "/", "--", "\\"):
        group = displayio.Group()
        from adafruit_display_text import label as _label

        base = _label.Label(
            layout.font,
            text="Loading ",
            color=0xFFFFFF,
            scale=layout.scale,
        )
        base.x = 2
        base.y = 30
        group.append(base)
        try:
            base_width = base.bounding_box[2]
        except Exception:
            base_width = 8 * len("Loading ") * layout.scale
        spinner = _label.Label(layout.font, text=frame, color=0xFFFFFF, scale=layout.scale)
        spinner.x = base.x + base_width + 1
        spinner.y = base.y
        group.append(spinner)
        panel.show(group)
        time.sleep(0.3)


def build_loading_group(
    layout: SimpleTextLayout,
    frame: str,
    width: int = 64,
    height: int = 64,
    color: int = 0xFFFFFF,
) -> displayio.Group:
    """Create a display group for a single loading frame."""
    if displayio is None or layout is None:
        return None
    group = displayio.Group()
    try:
        from adafruit_display_text import label as _label
    except Exception:
        return group

    base = _label.Label(
        layout.font,
        text="Loading ",
        color=color,
        scale=layout.scale,
    )
    base.x = 2
    base.y = 30
    group.append(base)
    try:
        base_width = base.bounding_box[2]
    except Exception:
        base_width = 8 * len("Loading ") * layout.scale
    spinner = _label.Label(layout.font, text=frame, color=color, scale=layout.scale)
    spinner.x = base.x + base_width + 1
    spinner.y = base.y
    group.append(spinner)
    return group


def build_error_group(layout: SimpleTextLayout, width: int = 64, height: int = 64) -> displayio.Group:
    """Create a display group with a red X and Error label."""
    if displayio is None:
        return None
    bitmap = displayio.Bitmap(width, height, 2)
    palette = displayio.Palette(2)
    palette[0] = 0x000000
    palette[1] = 0xFF0000
    for i in range(min(width, height)):
        bitmap[i, i] = 1
        bitmap[width - 1 - i, i] = 1
        if i + 1 < width:
            bitmap[i + 1, i] = 1
            bitmap[width - 2 - i, i] = 1
    group = displayio.Group()
    # Header row layout: [logo] [dash] [Line]
    group.append(displayio.TileGrid(bitmap, pixel_shader=palette))

    try:
        from adafruit_display_text import label as _label

        text = _label.Label(layout.font, text="ERROR", color=0xFF0000, scale=1)
        try:
            bounds = text.bounding_box
            text.x = max(0, (width - bounds[2]) // 2)
        except Exception:
            text.x = 8
        text.y = height - 8
        group.append(text)
    except Exception:
        pass
    return group


def build_error_message_group(
    layout: SimpleTextLayout,
    lines: Sequence[str],
    width: int = 64,
    height: int = 64,
    color: int = 0xFF0000,
) -> displayio.Group:
    """Create a display group with custom error text."""
    if displayio is None or layout is None:
        return None
    group = displayio.Group()
    try:
        from adafruit_display_text import label as _label
    except Exception:
        return group

    if not lines:
        lines = ("Error",)

    line_height = max(8, layout.line_spacing)
    total_height = line_height * len(lines)
    start_y = max(0, (height - total_height) // 2)

    for idx, line in enumerate(lines):
        text = _label.Label(layout.font, text=line, color=color, scale=1)
        try:
            bounds = text.bounding_box
            text.x = max(0, (width - bounds[2]) // 2)
        except Exception:
            text.x = 2
        text.y = start_y + idx * line_height
        group.append(text)
    return group


def build_display_group(
    layout: SimpleTextLayout,
    times: Sequence[str],
    now_epoch: Optional[int] = None,
    utc_offset_seconds: int = 0,
    current_temperature: Optional[float] = None,
    temperature_unit: str = "fahrenheit",
    time_format: str = "12h",
    time_to_stop: Optional[int] = None,
    show_time: bool = True,
    show_temperature: bool = True,
) -> displayio.Group:
    """Build the main display group from train times."""
    group = displayio.Group()
    logo_group, logo_size = build_n_logo(layout, size=24)
    x_offset = 1
    if logo_group is not None:
        logo_group.x = x_offset - 1
        logo_group.y = 0
        group.append(logo_group)
        x_offset += logo_size + 1

    dash_width = 4
    dash_height = 1
    dash_bitmap = displayio.Bitmap(dash_width, dash_height, 2)
    dash_palette = displayio.Palette(2)
    dash_palette[0] = 0x000000
    dash_palette[1] = 0xFFFFFF
    for dx in range(dash_width):
        dash_bitmap[dx, 0] = 1
    dash_group = displayio.Group()
    dash_group.append(displayio.TileGrid(dash_bitmap, pixel_shader=dash_palette))
    dash_group.x = x_offset - 1
    dash_group.y = 12
    group.append(dash_group)

    header_group = layout.build_group(
        ["Line"],
        x=x_offset + dash_width,
        y=13,
        width=64,
        align="left",
        scale=layout.scale,
    )
    group.append(header_group)

    # Two-line train list.
    line1 = times[0] if len(times) > 0 else "No data"
    line2 = times[1] if len(times) > 1 else ""

    # Parse minutes to drive dot colors.
    minutes1 = parse_minutes(line1)
    minutes2 = parse_minutes(line2)

    t1_group = layout.build_group(
        [line1],
        x=8,
        y=32,
        width=64,
        align="left",
        scale=layout.scale,
    )
    group.append(t1_group)
    t2_group = layout.build_group(
        [line2],
        x=8,
        y=47,
        width=64,
        align="left",
        scale=layout.scale,
    )
    group.append(t2_group)

    dot1 = build_status_dot(dot_color(minutes1, time_to_stop=time_to_stop), size=5)
    if dot1 is not None:
        dot1.x = 1
        dot1.y = 30
        group.append(dot1)
    dot2 = build_status_dot(dot_color(minutes2, time_to_stop=time_to_stop), size=5)
    if dot2 is not None:
        dot2.x = 1
        dot2.y = 45
        group.append(dot2)

    if show_time:
        add_time_label(
            group,
            layout,
            now_epoch=now_epoch,
            utc_offset_seconds=utc_offset_seconds,
            time_format=time_format,
        )
    if show_temperature:
        add_temperature_label(
            group,
            layout,
            temperature=current_temperature,
            temperature_unit=temperature_unit,
        )
    return group


def add_time_label(
    group: displayio.Group,
    layout: SimpleTextLayout,
    now_epoch: Optional[int] = None,
    utc_offset_seconds: int = 0,
    time_format: str = "12h",
) -> None:
    """Add the current time label to a display group."""
    try:
        base_epoch = now_epoch if now_epoch is not None else time.time()
        if now_epoch is None:
            base_epoch += int(utc_offset_seconds)
        now_time = time.localtime(base_epoch)
        hour = now_time.tm_hour
        if str(time_format).strip().lower().startswith("12"):
            hour = hour % 12
            if hour == 0:
                hour = 12
        hour_text = str(hour)
        minute_text = "{:02d}".format(now_time.tm_min)
        from adafruit_display_text import label as _label

        hour_label = _label.Label(
            layout.font,
            text=hour_text,
            color=0xFFFFFF,
            scale=1,
        )
        colon_label = _label.Label(
            layout.font,
            text=":",
            color=0xFFFFFF,
            scale=1,
        )
        minute_label = _label.Label(
            layout.font,
            text=minute_text,
            color=0xFFFFFF,
            scale=1,
        )

        def _char_width(ch: str) -> int:
            if ch == "1":
                return 3
            try:
                sample = _label.Label(layout.font, text=ch, color=0xFFFFFF, scale=1)
                return sample.bounding_box[2]
            except Exception:
                return 5

        def _text_width(text: str) -> int:
            return sum(_char_width(ch) for ch in text)

        hour_width = _text_width(hour_text)
        colon_width = _text_width(":")
        minute_width = _text_width(minute_text)
        # Tighten spacing around the colon, but keep a minimum gap so it renders.
        tight = 2
        min_gap = 1
        total_width = hour_width + colon_width + minute_width - (tight * 2) + min_gap
        start_x = max(0, 64 - total_width)
        hour_label.x = start_x
        colon_label.x = max(0, start_x + hour_width - tight)
        minute_label.x = max(0, colon_label.x + colon_width + min_gap)
        # Ensure the right edge never runs past the display.
        try:
            minute_bounds = minute_label.bounding_box
            right_edge = minute_label.x + minute_bounds[2] - 1
            if right_edge > 63:
                shift = right_edge - 63
                hour_label.x = max(0, hour_label.x - shift)
                colon_label.x = max(0, colon_label.x - shift)
                minute_label.x = max(0, minute_label.x - shift)
        except Exception:
            pass

        try:
            max_height = max(
                hour_label.bounding_box[3],
                colon_label.bounding_box[3],
                minute_label.bounding_box[3],
            )
        except Exception:
            max_height = 8
        base_y = max(0, 63 - max_height)
        y_pos = min(63, base_y + 9)
        hour_label.y = y_pos
        colon_label.y = y_pos
        minute_label.y = y_pos
        group.append(hour_label)
        group.append(colon_label)
        group.append(minute_label)
    except Exception:
        pass


def _format_temperature(temperature: Optional[float], temperature_unit: str) -> Optional[str]:
    unit = (temperature_unit or "").strip().lower()
    if unit.startswith("c"):
        suffix = "C"
    else:
        suffix = "F"
    if temperature is None:
        return "--{}".format(suffix)
    try:
        value = int(round(float(temperature)))
    except Exception:
        return None
    return "{}{}".format(value, suffix)


def add_temperature_label(
    group: displayio.Group,
    layout: SimpleTextLayout,
    temperature: Optional[float] = None,
    temperature_unit: str = "fahrenheit",
) -> None:
    """Add the temperature label to a display group."""
    try:
        text = _format_temperature(temperature, temperature_unit)
        if not text:
            return
        from adafruit_display_text import label as _label

        temp_label = _label.Label(
            layout.font,
            text=text,
            color=0xFFFFFF,
            scale=1,
        )
        try:
            temp_bounds = temp_label.bounding_box
            temp_label.x = max(0, 64 - temp_bounds[2] - 52)
            base_y = max(0, 63 - temp_bounds[3])
            temp_label.y = min(63, base_y + 9)
        except Exception:
            temp_label.x = max(0, 64 - (6 * len(text)) - 52)
            temp_label.y = 63
        group.append(temp_label)
    except Exception:
        pass


def _draw_filled_midpoint_circle(
    bitmap: displayio.Bitmap,
    center_x: int,
    center_y: int,
    radius: int,
    color_index: int = 1,
) -> None:
    """Draw a filled circle using the midpoint circle algorithm."""
    size_x = bitmap.width
    size_y = bitmap.height

    def _plot(x, y):
        if 0 <= x < size_x and 0 <= y < size_y:
            bitmap[x, y] = color_index

    x = radius
    y = 0
    p = 1 - radius

    # Midpoint circle perimeter (8-way symmetry).
    while x >= y:
        _plot(center_x + x, center_y + y)
        _plot(center_x - x, center_y + y)
        _plot(center_x + x, center_y - y)
        _plot(center_x - x, center_y - y)
        _plot(center_x + y, center_y + x)
        _plot(center_x - y, center_y + x)
        _plot(center_x + y, center_y - x)
        _plot(center_x - y, center_y - x)
        y += 1
        if p <= 0:
            p = p + 2 * y + 1
        else:
            x -= 1
            p = p + 2 * y - 2 * x + 1

    # Fill circle by scanline between perimeter pixels.
    for y in range(size_y):
        min_x = None
        max_x = None
        for x in range(size_x):
            if bitmap[x, y] == color_index:
                if min_x is None:
                    min_x = x
                max_x = x
        if min_x is not None and max_x is not None:
            for x in range(min_x, max_x + 1):
                bitmap[x, y] = color_index


def build_n_logo(
    layout: SimpleTextLayout,
    size: int = 24,
    color: int = 0x0066FF,
    text_color: int = 0xFFFFFF,
) -> Tuple[Optional[displayio.Group], int]:
    """Create the N logo group (blue circle + white N)."""
    if layout is None:
        return None, 0
    bitmap = displayio.Bitmap(size, size, 3)
    palette = displayio.Palette(2)
    palette[0] = 0x000000
    palette[1] = color
    center = size // 2
    radius = (size // 2) - 1

    _draw_filled_midpoint_circle(bitmap, center, center, radius, color_index=1)
    group = displayio.Group()
    group.append(displayio.TileGrid(bitmap, pixel_shader=palette))
    try:
        n_width = 13
        n_height = 17
        stroke = 2
        n_bitmap = displayio.Bitmap(n_width, n_height, 2)
        n_palette = displayio.Palette(2)
        n_palette[0] = 0x000000
        n_palette[1] = text_color
        n_palette.make_transparent(0)
        for y in range(n_height):
            for dx in range(stroke):
                n_bitmap[dx, y] = 1
                n_bitmap[n_width - 1 - dx, y] = 1
            x_pos = int((n_width - 1 - stroke) * y / max(1, n_height - 1))
            for dx in range(stroke):
                px = x_pos + dx
                if 0 <= px < n_width:
                    n_bitmap[px, y] = 1
        n_group = displayio.Group()
        n_group.append(displayio.TileGrid(n_bitmap, pixel_shader=n_palette))
        n_group.x = max(0, (size - n_width) // 2) + 1
        n_group.y = max(0, (size - n_height) // 2) + 1
        group.append(n_group)
    except Exception:
        pass
    return group, size


def parse_minutes(text: str) -> Optional[int]:
    """Extract minutes as an integer from a display string."""
    if not text:
        return None
    cleaned = text.strip().lower()
    if cleaned.startswith("arriv"):
        return 0
    for token in cleaned.split():
        if token.isdigit():
            return int(token)
    return None


def dot_color(minutes: Optional[int], time_to_stop: Optional[int] = None) -> int:
    """Map minutes to a status color."""
    if minutes is None:
        return 0xFFFFFF
    if time_to_stop is None:
        time_to_stop = 5
    try:
        stop_window = int(time_to_stop)
    except Exception:
        stop_window = 5
    warn_window = stop_window + 3
    if minutes <= stop_window:
        return 0xFF3333
    if minutes <= warn_window:
        return 0xFFCC33
    return 0x33FF66


def build_status_dot(color: int, size: int = 5) -> Optional[displayio.Group]:
    """Build a circular status dot bitmap group."""
    bitmap = displayio.Bitmap(size, size, 2)
    palette = displayio.Palette(2)
    palette[0] = 0x000000
    palette[1] = color
    palette.make_transparent(0)
    center = size // 2
    radius = max(1, (size // 2))
    for y in range(size):
        for x in range(size):
            dx = x - center
            dy = y - center
            if (dx * dx + dy * dy) <= (radius * radius):
                bitmap[x, y] = 1
    dot_group = displayio.Group()
    dot_group.append(displayio.TileGrid(bitmap, pixel_shader=palette))
    return dot_group
