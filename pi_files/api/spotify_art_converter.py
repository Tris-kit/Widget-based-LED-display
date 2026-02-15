try:
    from typing import Callable, Optional
except ImportError:
    from local.typing_compat import Callable, Optional

from api.http_client import HttpClient
from local.jpeg_bmp_converter import JpegBmpConverter


class SpotifyArtConverter:
    """Download album art and convert it to a 64x64 BMP on-device."""

    def __init__(
        self,
        http_client=None,
        art_path: str = "spotify_art.bmp",
        temp_jpeg_path: str = "spotify_art.jpg",
    ) -> None:
        self.http_client = http_client or HttpClient()
        self.converter = JpegBmpConverter(temp_jpeg_path=temp_jpeg_path)
        self.art_path = art_path or "spotify_art.bmp"
        self.last_error: Optional[Exception] = None
        self._pending = False

    @property
    def available(self) -> bool:
        return self.converter.available

    @property
    def pending(self) -> bool:
        return self._pending

    def request_bmp(
        self,
        image_url: str,
        on_success: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
        timeout: int = 10,
    ) -> bool:
        """Queue a request to download and convert album art to BMP."""
        if self._pending:
            return False
        if not image_url:
            self.last_error = ValueError("Spotify image URL missing")
            if on_error:
                on_error(self.last_error)
            return False
        if not self.available:
            self.last_error = RuntimeError("jpegio/displayio not available")
            if on_error:
                on_error(self.last_error)
            return False
        self._pending = True

        def _handle_success(_text, body, status, _headers):
            self._pending = False
            try:
                if not body:
                    raise ValueError("Empty album art response")
                if not self.converter.convert_jpeg_bytes(body, self.art_path):
                    raise self.converter.last_error or RuntimeError("BMP conversion failed")
                self.last_error = None
                if on_success:
                    on_success(self.art_path, status)
            except Exception as exc:
                self.last_error = exc
                if on_error:
                    on_error(exc)

        def _handle_error(exc):
            self._pending = False
            self.last_error = exc
            if on_error:
                on_error(exc)

        started = self.http_client.enqueue_get(
            image_url,
            on_success=_handle_success,
            on_error=_handle_error,
            timeout=timeout,
            key="spotify_art",
        )
        if not started:
            self._pending = False
            if self.last_error is None:
                self.last_error = RuntimeError("Spotify art request skipped")
        return started
