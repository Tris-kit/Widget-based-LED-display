import time
try:
    from typing import Optional
except ImportError:
    from local.typing_compat import Optional

try:
    import displayio
except Exception:
    displayio = None

from api.spotify_api import SpotifyClient
from api.spotify_art_converter import SpotifyArtConverter
from local.ui.display_helpers import build_error_message_group


class SpotifyNowPlayingWidget:
    """Show the current Spotify album cover on the LED matrix."""

    def __init__(
        self,
        client_id: Optional[str],
        client_secret: Optional[str],
        refresh_token: Optional[str],
        image_proxy_url: Optional[str],
        http_client=None,
        refresh_seconds: int = 15,
        request_timeout: int = 10,
        art_path: str = "spotify_art.bmp",
    ) -> None:
        self.refresh_seconds = max(5, int(refresh_seconds))
        self.request_timeout = int(request_timeout)
        self.art_path = art_path or "spotify_art.bmp"

        self.spotify = SpotifyClient(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            http_client=http_client,
        )
        self.art_converter = SpotifyArtConverter(
            http_client=http_client,
            art_path=self.art_path,
        )

        self._last_refresh = 0.0
        self._request_pending = False
        self._image_pending = False
        self._status = "idle"
        self._last_error: Optional[Exception] = None
        self._current_image_url = ""

        self._group = None
        self._dirty = True

        self._art_file = None
        self._art_bitmap = None
        self._art_tilegrid = None
        self._art_width = 0
        self._art_height = 0
        self._background = None

        if not self.spotify.has_credentials():
            self._status = "config"

    def on_activate(self, _now_monotonic: Optional[float] = None) -> None:
        """Force a refresh when the widget becomes active."""
        self._last_refresh = 0.0
        self._request_refresh()

    def force_refresh(self) -> None:
        """Force a rebuild of the display group."""
        self._dirty = True

    def update(self, now_monotonic: float) -> None:
        """Queue refreshes at the configured interval."""
        if self._status == "config":
            return
        if self._request_pending:
            return
        if (now_monotonic - self._last_refresh) >= self.refresh_seconds:
            self._request_refresh()

    def render(self, layout):
        """Render the current album art or a text fallback."""
        if displayio is None or layout is None:
            return None
        if self._group is None or self._dirty:
            self._group = self._build_group(layout)
            self._dirty = False
            return self._group
        return None

    def _request_refresh(self) -> None:
        """Queue a Spotify now-playing request."""
        if self._request_pending:
            return
        if self._status == "config":
            return
        self._request_pending = True
        self._last_refresh = time.monotonic()
        self._status = "loading"

        def _on_update():
            self._request_pending = False
            self._last_error = None
            image_url = self.spotify.album_image_url or ""
            if not image_url:
                self._status = "no_music"
                self._current_image_url = ""
                self._clear_art()
                self._dirty = True
                return
            if image_url != self._current_image_url:
                if self._download_art(image_url):
                    self._current_image_url = image_url
                else:
                    # Allow retries if the request was skipped.
                    self._current_image_url = ""
            else:
                self._status = "ok"
                self._dirty = True

        def _on_error(exc):
            self._request_pending = False
            self._set_spotify_error(exc)
            self._dirty = True

        started = self.spotify.request_currently_playing(
            on_update=_on_update,
            on_error=_on_error,
            timeout=self.request_timeout,
        )
        if not started:
            # Allow the next tick to retry if the request was skipped.
            self._request_pending = False
            if self.spotify.last_error is not None:
                self._set_spotify_error(self.spotify.last_error)
                self._dirty = True

    def _download_art(self, image_url: str) -> bool:
        """Queue a proxy request to fetch the album art BMP."""
        if self._image_pending:
            return False
        self._image_pending = True
        self._status = "loading"

        def _on_success(_path, _status):
            self._image_pending = False
            try:
                self._load_art()
                self._status = "ok"
            except Exception as exc:
                self._last_error = exc
                self._status = "error"
            self._dirty = True

        def _on_error(exc):
            self._image_pending = False
            self._last_error = exc
            self._status = "error"
            self._dirty = True

        started = self.art_converter.request_bmp(
            image_url,
            on_success=_on_success,
            on_error=_on_error,
            timeout=self.request_timeout,
        )
        if not started:
            self._image_pending = False
            if self.art_converter.last_error is not None:
                self._last_error = self.art_converter.last_error
                self._status = "error"
                self._dirty = True
            return False
        return True

    def _set_spotify_error(self, exc: Exception) -> None:
        """Set widget error status based on Spotify error stage."""
        self._last_error = exc
        stage = getattr(self.spotify, "last_error_stage", "")
        if stage == "token" or stage == "config":
            self._status = "auth_error"
        else:
            self._status = "error"

    def _load_art(self) -> None:
        """Load the downloaded BMP into a TileGrid."""
        self._clear_art()
        if displayio is None:
            return
        try:
            self._art_file = open(self.art_path, "rb")
            bitmap = displayio.OnDiskBitmap(self._art_file)
            pixel_shader = getattr(bitmap, "pixel_shader", None)
            if pixel_shader is None:
                pixel_shader = displayio.ColorConverter()
            self._art_bitmap = bitmap
            self._art_width = bitmap.width
            self._art_height = bitmap.height
            self._art_tilegrid = displayio.TileGrid(bitmap, pixel_shader=pixel_shader)
        except Exception as exc:
            self._last_error = exc
            self._status = "error"
            self._clear_art()

    def _clear_art(self) -> None:
        """Release any loaded art bitmap and file handle."""
        self._art_tilegrid = None
        self._art_bitmap = None
        self._art_width = 0
        self._art_height = 0
        try:
            if self._art_file is not None:
                self._art_file.close()
        except Exception:
            pass
        self._art_file = None

    def _build_group(self, layout):
        """Assemble a display group for the album art or fallback text."""
        group = self._group if self._group is not None else displayio.Group()
        while len(group):
            group.pop()

        if self._background is None:
            try:
                bg_bitmap = displayio.Bitmap(64, 64, 1)
                bg_palette = displayio.Palette(1)
                bg_palette[0] = 0x000000
                self._background = displayio.TileGrid(bg_bitmap, pixel_shader=bg_palette)
            except Exception:
                self._background = None
        if self._background is not None:
            group.append(self._background)

        if self._art_tilegrid is not None:
            # Center the art if it is smaller than 64x64.
            self._art_tilegrid.x = max(0, (64 - self._art_width) // 2)
            self._art_tilegrid.y = max(0, (64 - self._art_height) // 2)
            group.append(self._art_tilegrid)
            return group

        # Fallback text messages.
        if self._status == "config":
            lines = ["Spotify", "config"]
        elif self._status == "auth_error":
            return build_error_message_group(layout, ["Spotify", "refresh", "token"])
        elif self._status == "no_music":
            lines = ["No music"]
        elif self._status == "error":
            return build_error_message_group(layout, ["Spotify", "error"])
        else:
            lines = ["Loading"]

        line_height = layout.line_spacing
        total_height = line_height * len(lines)
        start_y = max(0, (64 - total_height) // 2)
        label_group = layout.build_group(
            lines,
            x=0,
            y=start_y,
            width=64,
            align="center",
            scale=1,
        )
        group.append(label_group)
        return group
