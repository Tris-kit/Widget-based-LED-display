try:
    from typing import Optional
except ImportError:
    from local.typing_compat import Optional

try:
    import displayio
except Exception:
    displayio = None

_indicator_bitmap = None
_indicator_tile = None
_active = False


def init_indicator(
    width: int = 64,
    height: int = 64,
    color: int = 0x00FF00,
) -> Optional[displayio.TileGrid]:
    """Create a 1x1 indicator pixel at the top-right corner."""
    global _indicator_bitmap, _indicator_tile
    if displayio is None:
        return None
    bitmap = displayio.Bitmap(1, 1, 2)
    palette = displayio.Palette(2)
    palette[0] = 0x000000
    palette[1] = color
    tile = displayio.TileGrid(bitmap, pixel_shader=palette)
    tile.x = max(0, width - 1)
    tile.y = 0
    _indicator_bitmap = bitmap
    _indicator_tile = tile
    set_active(_active)
    return tile


def set_active(active: bool) -> None:
    """Toggle the IO indicator pixel."""
    global _active
    _active = bool(active)
    if _indicator_bitmap is None:
        return
    try:
        _indicator_bitmap[0, 0] = 1 if _active else 0
    except Exception:
        pass
