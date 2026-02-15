import time
try:
    from typing import Optional
except ImportError:
    from local.typing_compat import Optional

try:
    import displayio
except Exception:
    displayio = None


class SpriteSheetPlayer:
    """Play a vertical sprite sheet (BMP) by advancing tile indices."""

    def __init__(
        self,
        path: Optional[str],
        frame_height: int = 64,
        frame_delay: float = 0.05,
    ) -> None:
        """Load the BMP spritesheet and prepare a TileGrid."""
        self.path = path or ""
        self.frame_height = frame_height
        self.frame_delay = max(0.02, float(frame_delay))
        self.tilegrid = None
        self.width = 0
        self.height = 0
        self.frame_width = 0
        self.display_height = 0
        self.frame_count = 0
        self.current_frame = 0
        self.last_error = None
        self._bitmap = None
        self._file = None
        self._next_frame_at = 0.0

        if displayio is None or not self.path:
            return
        self._load()

    def _load(self) -> None:
        """Open the BMP file and configure the TileGrid for sprites."""
        try:
            resolved = _resolve_path(self.path)
            if resolved != self.path:
                print("SpriteSheet path fallback:", self.path, "->", resolved)
                self.path = resolved
            # OnDiskBitmap expects an open file handle for streaming.
            self._file = open(self.path, "rb")
            bitmap = displayio.OnDiskBitmap(self._file)
            self._bitmap = bitmap
            self.width = bitmap.width
            self.height = bitmap.height
            self.frame_width = self.width
            self.display_height = self.frame_height
            if self.frame_height <= 0:
                self.frame_height = 64
            self.frame_count = int(self.height // self.frame_height)
            if self.frame_count <= 0:
                raise ValueError("spritesheet has no frames")
            pixel_shader = getattr(bitmap, "pixel_shader", None)
            if pixel_shader is None:
                pixel_shader = displayio.ColorConverter()
            self.tilegrid = displayio.TileGrid(
                bitmap,
                pixel_shader=pixel_shader,
                width=1,
                height=1,
                tile_width=self.width,
                tile_height=self.frame_height,
            )
            self._next_frame_at = time.monotonic() + self.frame_delay
            print(
                "SpriteSheet loaded:",
                self.path,
                "{}x{}".format(self.width, self.height),
                "frames",
                self.frame_count,
            )
        except Exception as exc:
            self.last_error = exc
            self.tilegrid = None

    def reset(self) -> None:
        """Reset animation to the first frame."""
        self.current_frame = 0
        if self.tilegrid is not None:
            try:
                self.tilegrid[0] = 0
            except Exception:
                pass
        self._next_frame_at = time.monotonic() + self.frame_delay

    def next_frame(self, now: float) -> bool:
        """Advance to the next frame when enough time has elapsed."""
        if self.tilegrid is None or self.frame_count <= 0:
            return False
        if now < self._next_frame_at:
            return False
        try:
            self.tilegrid[0] = self.current_frame
        except Exception:
            return False
        self.current_frame = (self.current_frame + 1) % self.frame_count
        self._next_frame_at = now + self.frame_delay
        return True

    def deinit(self) -> None:
        """Release the file handle and bitmap references."""
        self.tilegrid = None
        self._bitmap = None
        try:
            if self._file is not None:
                self._file.close()
        except Exception:
            pass
        self._file = None


def _resolve_path(path: str) -> str:
    """Try to resolve absolute vs relative paths for CircuitPython FS."""
    if not path:
        return path
    try:
        open(path, "rb").close()
        return path
    except Exception:
        pass
    if path.startswith("/"):
        alt = path[1:]
        try:
            open(alt, "rb").close()
            return alt
        except Exception:
            pass
    return path
