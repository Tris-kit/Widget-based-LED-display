try:
    from typing import Optional
except ImportError:
    from local.typing_compat import Optional

try:
    import displayio
except Exception:
    displayio = None


class ProgressBar:
    """Bottom-row progress bar helper for the LED matrix."""

    def __init__(
        self,
        width: int = 64,
        height: int = 1,
        color: int = 0x00FF00,
        background: int = 0x000000,
    ) -> None:
        """Create a single-row progress bar with a 2-color palette."""
        self.width = width
        self.height = height
        self.color = color
        self.background = background
        self.group = None
        self._bitmap = None
        self._palette = None
        self._last_pixels = -1

        if displayio is None:
            return

        bitmap = displayio.Bitmap(width, height, 2)
        palette = displayio.Palette(2)
        palette[0] = background
        palette[1] = color
        tile = displayio.TileGrid(bitmap, pixel_shader=palette)
        group = displayio.Group()
        group.append(tile)

        self.group = group
        self._bitmap = bitmap
        self._palette = palette

    def set_progress(self, progress: float) -> bool:
        """Update the filled pixels based on a 0..1 progress value."""
        if self._bitmap is None:
            return False
        try:
            value = float(progress)
        except Exception:
            value = 0.0
        if value < 0:
            value = 0.0
        if value > 1:
            value = 1.0

        # Convert 0..1 progress to a count of lit pixels.
        pixels = int(round(value * self.width))
        if pixels == self._last_pixels:
            return False
        self._last_pixels = pixels
        # Fill the bar from left to right.
        for y in range(self.height):
            for x in range(self.width):
                self._bitmap[x, y] = 1 if x < pixels else 0
        return True
