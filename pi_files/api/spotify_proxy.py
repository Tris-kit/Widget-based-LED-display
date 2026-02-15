try:
    from typing import Callable, Optional
except ImportError:
    from local.typing_compat import Callable, Optional

from api.http_client import HttpClient


class SpotifyImageProxy:
    """Fetch album art through a proxy that returns a 64x64 BMP."""

    def __init__(self, proxy_url: Optional[str], http_client=None) -> None:
        self.proxy_url = (proxy_url or "").strip()
        self.http_client = http_client or HttpClient()
        self.last_error: Optional[Exception] = None

    def request_bmp(
        self,
        image_url: str,
        on_success: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
        timeout: int = 10,
    ) -> bool:
        """Queue a proxy request to convert album art into a BMP."""
        if not self.proxy_url:
            err = ValueError("Spotify image proxy URL missing")
            self.last_error = err
            if on_error:
                on_error(err)
            return False
        if not image_url:
            err = ValueError("Spotify image URL missing")
            self.last_error = err
            if on_error:
                on_error(err)
            return False

        url = _build_proxy_url(self.proxy_url, image_url)

        def _handle_success(_text, body, status, _headers):
            try:
                if status and status >= 400:
                    raise RuntimeError("Image proxy error {}".format(status))
                self.last_error = None
                if on_success:
                    on_success(body, status)
            except Exception as exc:
                self.last_error = exc
                if on_error:
                    on_error(exc)

        def _handle_error(exc):
            self.last_error = exc
            if on_error:
                on_error(exc)

        return self.http_client.enqueue_get(
            url,
            on_success=_handle_success,
            on_error=_handle_error,
            timeout=timeout,
            key="spotify_art",
        )


def _build_proxy_url(proxy_url: str, image_url: str) -> str:
    """Build the proxy URL by attaching the encoded image URL."""
    if "{url}" in proxy_url:
        return proxy_url.replace("{url}", _url_encode(image_url))
    if "?" in proxy_url:
        return "{}&url={}".format(proxy_url, _url_encode(image_url))
    return "{}?url={}".format(proxy_url, _url_encode(image_url))


def _url_encode(text: str) -> str:
    """Percent-encode a string for URL query parameters."""
    safe = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~"
    encoded = []
    for ch in text:
        if ch in safe:
            encoded.append(ch)
        else:
            encoded.append("%{:02X}".format(ord(ch)))
    return "".join(encoded)
