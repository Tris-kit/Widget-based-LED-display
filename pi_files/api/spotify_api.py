import json
import time
try:
    from typing import Callable, Dict, Optional
except ImportError:
    from local.typing_compat import Callable, Dict, Optional

from api.http_client import HttpClient


_TOKEN_URL = "https://accounts.spotify.com/api/token"
_NOW_PLAYING_URL = "https://api.spotify.com/v1/me/player/currently-playing"


class SpotifyClient:
    """Spotify client that refreshes tokens and fetches current playback."""

    def __init__(
        self,
        client_id: Optional[str],
        client_secret: Optional[str],
        refresh_token: Optional[str],
        http_client=None,
    ) -> None:
        self.client_id = (client_id or "").strip()
        self.client_secret = (client_secret or "").strip()
        self.refresh_token = (refresh_token or "").strip()
        self.http_client = http_client or HttpClient()
        self.access_token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._refresh_inflight = False
        self._after_refresh = []
        self.last_error: Optional[Exception] = None
        self.last_error_stage: str = ""

        # Current playback state.
        self.is_playing: bool = False
        self.track_name: str = ""
        self.artist_name: str = ""
        self.album_name: str = ""
        self.album_image_url: str = ""
        self.track_id: str = ""
        self.album_id: str = ""

    def has_credentials(self) -> bool:
        """Return True when all required credentials are present."""
        return bool(self.client_id and self.client_secret and self.refresh_token)

    def request_currently_playing(
        self,
        on_update: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
        timeout: int = 10,
    ) -> bool:
        """Queue a current playback request (refreshing tokens if needed)."""
        if not self.has_credentials():
            err = ValueError("Spotify credentials missing")
            self._set_error(err, "config")
            if on_error:
                on_error(err)
            return False

        if not self._token_valid():
            return self._request_token(
                after_refresh=lambda: self._enqueue_now_playing(on_update, on_error, timeout),
                on_error=on_error,
                timeout=timeout,
            )

        return self._enqueue_now_playing(on_update, on_error, timeout)

    def _enqueue_now_playing(
        self,
        on_update: Optional[Callable],
        on_error: Optional[Callable],
        timeout: int,
    ) -> bool:
        if not self.access_token:
            err = ValueError("Spotify access token missing")
            self._set_error(err, "token")
            if on_error:
                on_error(err)
            return False

        headers = {"Authorization": "Bearer {}".format(self.access_token)}

        def _handle_success(text, _body, status, _headers):
            try:
                if status == 204:
                    self._clear_playback()
                    self._clear_error()
                    if on_update:
                        on_update()
                    return
                if status == 401:
                    # Access token expired or invalid; force refresh next time.
                    self._token_expires_at = 0.0
                    err = RuntimeError("Spotify access token expired")
                    self._set_error(err, "token")
                    if on_error:
                        on_error(err)
                    return
                if status and status >= 400:
                    err = RuntimeError("Spotify API error {}".format(status))
                    self._set_error(err, "now_playing")
                    if on_error:
                        on_error(err)
                    return

                payload = _safe_json_load(text)
                self._apply_payload(payload)
                self._clear_error()
                if on_update:
                    on_update()
            except Exception as exc:
                self._set_error(exc, "parse")
                if on_error:
                    on_error(exc)

        def _handle_error(exc):
            self._set_error(exc, "request")
            if on_error:
                on_error(exc)

        return self.http_client.enqueue_get(
            _NOW_PLAYING_URL,
            on_success=_handle_success,
            on_error=_handle_error,
            timeout=timeout,
            key="spotify_now_playing",
            headers=headers,
        )

    def _request_token(
        self,
        after_refresh: Optional[Callable],
        on_error: Optional[Callable],
        timeout: int,
    ) -> bool:
        if after_refresh:
            self._after_refresh.append(after_refresh)
        if self._refresh_inflight:
            return True
        self._refresh_inflight = True

        body = "grant_type=refresh_token&refresh_token={}".format(
            _url_encode(self.refresh_token)
        )
        headers = {
            "Authorization": _basic_auth_header(self.client_id, self.client_secret),
            "Content-Type": "application/x-www-form-urlencoded",
        }

        def _handle_success(text, _body, status, _headers):
            self._refresh_inflight = False
            try:
                if status and status >= 400:
                    err = RuntimeError("Spotify token error {}".format(status))
                    self._set_error(err, "token")
                    if on_error:
                        on_error(err)
                    return
                payload = _safe_json_load(text)
                token = payload.get("access_token")
                if not token:
                    err = ValueError("Spotify token missing in response")
                    self._set_error(err, "token")
                    if on_error:
                        on_error(err)
                    return
                expires_in = int(payload.get("expires_in", 3600) or 3600)
                self.access_token = token
                # Refresh a minute early to avoid race conditions.
                self._token_expires_at = _now_monotonic() + max(0, expires_in - 60)
                self._clear_error()
                callbacks = self._after_refresh
                self._after_refresh = []
                for callback in callbacks:
                    try:
                        callback()
                    except Exception:
                        pass
            except Exception as exc:
                self._set_error(exc, "token")
                if on_error:
                    on_error(exc)

        def _handle_error(exc):
            self._refresh_inflight = False
            self._set_error(exc, "token")
            self._after_refresh = []
            if on_error:
                on_error(exc)

        started = self.http_client.enqueue_post(
            _TOKEN_URL,
            body=body,
            headers=headers,
            on_success=_handle_success,
            on_error=_handle_error,
            timeout=timeout,
            key="spotify_token",
        )
        if not started:
            self._refresh_inflight = False
        return started

    def _token_valid(self) -> bool:
        if not self.access_token:
            return False
        return _now_monotonic() < self._token_expires_at

    def _clear_playback(self) -> None:
        self.is_playing = False
        self.track_name = ""
        self.artist_name = ""
        self.album_name = ""
        self.album_image_url = ""
        self.track_id = ""
        self.album_id = ""

    def _set_error(self, exc: Exception, stage: str) -> None:
        """Record the most recent error and where it happened."""
        self.last_error = exc
        self.last_error_stage = stage or ""

    def _clear_error(self) -> None:
        """Clear stored error state."""
        self.last_error = None
        self.last_error_stage = ""

    def _apply_payload(self, payload: Dict) -> None:
        self.is_playing = bool(payload.get("is_playing"))
        item = payload.get("item") or {}
        if not isinstance(item, dict):
            item = {}
        self.track_name = item.get("name") or ""
        self.track_id = item.get("id") or ""

        artists = item.get("artists") or []
        if isinstance(artists, list):
            names = [a.get("name") for a in artists if isinstance(a, dict) and a.get("name")]
            self.artist_name = ", ".join(names)
        else:
            self.artist_name = ""

        album = item.get("album") or {}
        if not isinstance(album, dict):
            album = {}
        self.album_name = album.get("name") or ""
        self.album_id = album.get("id") or ""

        images = album.get("images") or []
        self.album_image_url = _pick_image_url(images)


def _pick_image_url(images, target_size: int = 64) -> str:
    """Pick the album art URL closest to the target size."""
    if not isinstance(images, list) or not images:
        return ""
    _log_album_images(images)
    best_url = ""
    best_score = None
    for img in images:
        if not isinstance(img, dict):
            continue
        url = img.get("url") or ""
        if not url:
            continue
        width = img.get("width") or 0
        height = img.get("height") or 0
        size = max(int(width), int(height))
        score = abs(size - target_size)
        if best_score is None or score < best_score:
            best_score = score
            best_url = url
    if best_url:
        return best_url
    return images[0].get("url") or ""


def _log_album_images(images) -> None:
    for img in images:
        if not isinstance(img, dict):
            continue
        url = img.get("url") or ""
        if not url:
            continue
        try:
            width = int(img.get("width") or 0)
        except Exception:
            width = 0
        try:
            height = int(img.get("height") or 0)
        except Exception:
            height = 0
        print("Spotify album image: {}x{} {}".format(width, height, url))


def _basic_auth_header(client_id: str, client_secret: str) -> str:
    """Return the Basic auth header value for the Spotify token call."""
    token = "{}:{}".format(client_id, client_secret).encode("utf-8")
    try:
        import binascii

        encoded = binascii.b2a_base64(token).strip().decode("utf-8")
    except Exception:
        # Fallback: no encoding, will likely fail but keeps flow predictable.
        encoded = ""
    return "Basic {}".format(encoded)


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


def _safe_json_load(text: str) -> dict:
    """Parse JSON while tolerating stray bytes or BOMs."""
    cleaned = text or ""
    try:
        cleaned = cleaned.encode().decode("utf-8-sig")
    except Exception:
        pass
    for token in ("{", "["):
        idx = cleaned.find(token)
        if idx != -1:
            cleaned = cleaned[idx:]
            break
    return json.loads(cleaned)


def _now_monotonic() -> float:
    """Return a monotonic clock value (or 0 on failure)."""
    try:
        return time.monotonic()
    except Exception:
        return 0.0
