import time
try:
    from typing import Optional, Sequence
except ImportError:
    from local.typing_compat import Optional, Sequence

try:
    import displayio
except Exception:
    displayio = None

class LoadingAnimator:
    """Loading animation state helper (no display side effects)."""

    def __init__(
        self,
        frames: Optional[Sequence[str]] = None,
        interval: float = 0.25,
        color: int = 0xFFFFFF,
    ) -> None:
        self.frames = tuple(frames) if frames else ("|", "/", "-", "\\")
        self.interval = interval
        self.color = color
        self.index = 0
        self.last = 0.0
        self._group = None
        self._spinner = None
        self._base = None
        self._layout = None

    def _ensure_group(self, layout):
        if displayio is None or layout is None:
            return None
        if self._group is not None and self._layout is layout:
            return self._group
        try:
            from adafruit_display_text import label as _label
        except Exception:
            return None

        group = displayio.Group()
        bg_bitmap = displayio.Bitmap(64, 64, 1)
        bg_palette = displayio.Palette(1)
        bg_palette[0] = 0x000000
        group.append(displayio.TileGrid(bg_bitmap, pixel_shader=bg_palette))

        base = _label.Label(
            layout.font,
            text="Loading ",
            color=self.color,
            scale=layout.scale,
        )
        base.x = 2
        base.y = 30
        group.append(base)
        try:
            base_width = base.bounding_box[2]
        except Exception:
            base_width = 8 * len("Loading ") * layout.scale

        spinner = _label.Label(
            layout.font,
            text=self.frames[self.index],
            color=self.color,
            scale=layout.scale,
        )
        spinner.x = base.x + base_width + 1
        spinner.y = base.y
        group.append(spinner)

        self._group = group
        self._spinner = spinner
        self._base = base
        self._layout = layout
        return self._group

    def next_group(self, layout):
        """Return the next loading group when it's time, or None if not."""
        if not layout:
            return None
        now = time.monotonic()
        if now - self.last < self.interval and self.last > 0:
            return None
        group = self._ensure_group(layout)
        if group is None:
            return None
        if self._base is not None:
            try:
                self._base.color = self.color
            except Exception:
                pass
        if self._spinner is not None:
            try:
                self._spinner.color = self.color
                self._spinner.text = self.frames[self.index]
            except Exception:
                pass
        self.index = (self.index + 1) % len(self.frames)
        self.last = now
        return group
