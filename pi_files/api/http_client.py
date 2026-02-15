try:
    from typing import Callable, Dict, Optional, Tuple
except ImportError:
    from local.typing_compat import Callable, Dict, Optional, Tuple

import time

try:
    import adafruit_requests
    import socketpool
    import ssl
    import wifi
except Exception:
    adafruit_requests = None
    socketpool = None
    ssl = None
    wifi = None


class HttpResponse:
    def __init__(self, text: str, content: bytes, status_code: int = 0, headers=None) -> None:
        self.text = text
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}

    def close(self) -> None:
        return None


class _HttpRequest:
    def __init__(
        self,
        url: str,
        timeout: int,
        on_success: Optional[Callable],
        on_error: Optional[Callable],
        on_progress: Optional[Callable],
        key: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        body: Optional[str] = None,
    ) -> None:
        self.url = url
        self.key = key
        self.timeout = timeout
        self.on_success = on_success
        self.on_error = on_error
        self.on_progress = on_progress
        self.method = (method or "GET").upper()
        self.headers = headers or {}
        self.body = body


class HttpClient:
    """Queued HTTP client powered by adafruit_requests.

    - enqueue_get() / enqueue_post() add requests to a FIFO queue.
    - tick() executes at most ONE request per call.
    - Duplicate requests (same key) are ignored and logged.
    """

    def __init__(self) -> None:
        self.supports_progress = False
        self._queue = []
        self._pending_keys = set()
        self._ignored_log_at = {}
        self._ignored_log_interval = 10.0
        self._session = None

    def enqueue_get(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        on_success: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
        on_progress: Optional[Callable] = None,
        timeout: int = 10,
        key: Optional[str] = None,
    ) -> bool:
        return self.enqueue_request(
            method="GET",
            url=url,
            headers=headers,
            on_success=on_success,
            on_error=on_error,
            on_progress=on_progress,
            timeout=timeout,
            key=key,
        )

    def enqueue_post(
        self,
        url: str,
        body: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        on_success: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
        on_progress: Optional[Callable] = None,
        timeout: int = 10,
        key: Optional[str] = None,
    ) -> bool:
        return self.enqueue_request(
            method="POST",
            url=url,
            body=body,
            headers=headers,
            on_success=on_success,
            on_error=on_error,
            on_progress=on_progress,
            timeout=timeout,
            key=key,
        )

    def enqueue_request(
        self,
        method: str,
        url: str,
        body: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        on_success: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
        on_progress: Optional[Callable] = None,
        timeout: int = 10,
        key: Optional[str] = None,
    ) -> bool:
        request_key = key or url
        if request_key in self._pending_keys:
            self._log_ignored(request_key)
            return False
        req = _HttpRequest(
            url=url,
            timeout=timeout,
            on_success=on_success,
            on_error=on_error,
            on_progress=on_progress,
            key=request_key,
            method=method,
            headers=headers,
            body=body,
        )
        self._queue.append(req)
        self._pending_keys.add(request_key)
        return True

    def tick(self) -> None:
        """Run one queued request (blocking) if available."""
        if not self._queue:
            _set_io_active(False)
            return
        req = self._queue.pop(0)
        print("HTTP start:", req.key)
        _set_io_active(True)
        try:
            if adafruit_requests is None or socketpool is None or wifi is None:
                raise RuntimeError("adafruit_requests unavailable")
            session = self._get_session()
            if req.on_progress:
                req.on_progress()
            headers = {
                # Avoid gzip/binary responses that we can't decode reliably.
                "Accept-Encoding": "identity",
                "User-Agent": "Pico",
            }
            if req.headers:
                headers.update(req.headers)
            if req.method == "POST":
                response = session.post(
                    req.url,
                    data=req.body,
                    timeout=req.timeout,
                    headers=headers,
                )
            else:
                response = session.get(req.url, timeout=req.timeout, headers=headers)
            try:
                body = response.content
                if isinstance(body, str):
                    body = body.encode()
                resp_headers = getattr(response, "headers", {}) or {}
                text = _decode_body(body, resp_headers)
                status_code = getattr(response, "status_code", None)
                if status_code is None:
                    status_code = getattr(response, "status", 0) or 0
                print("HTTP success:", req.key, "status", status_code, "bytes", len(body))
                if status_code >= 400 or status_code == 0:
                    preview = (text or "").replace("\n", " ")[:200]
                    print("HTTP response error:", status_code, preview)
                if req.on_success:
                    req.on_success(text, body, status_code, resp_headers)
            finally:
                try:
                    response.close()
                except Exception:
                    pass
                if req.on_progress:
                    req.on_progress()
        except Exception as exc:
            print("HTTP error:", req.key, repr(exc))
            if req.on_error:
                req.on_error(exc)
        finally:
            self._pending_keys.discard(req.key)
            _set_io_active(False)

    def _get_session(self):
        if self._session is None:
            pool = socketpool.SocketPool(wifi.radio)
            try:
                ssl_context = ssl.create_default_context() if ssl else None
            except Exception:
                ssl_context = None
            self._session = adafruit_requests.Session(pool, ssl_context)
        return self._session

    def _log_ignored(self, key: str) -> None:
        now = time.monotonic()
        last = self._ignored_log_at.get(key, 0.0)
        if now - last < self._ignored_log_interval:
            return
        self._ignored_log_at[key] = now
        print("HTTP request ignored (already queued):", key)


def _set_io_active(active: bool) -> None:
    try:
        from local.ui import io_indicator
    except Exception:
        return
    try:
        io_indicator.set_active(active)
    except Exception:
        pass


def _decode_body(data: bytes, headers: Dict[str, str]) -> str:
    if not data:
        return ""
    encoding = ""
    try:
        encoding = (headers.get("content-encoding") or "").lower()
    except Exception:
        encoding = ""
    if encoding == "gzip" or data[:2] == b"\x1f\x8b":
        try:
            import uzlib

            try:
                # Try gzip wrapper (wbits=16+MAX_WBITS).
                data = uzlib.decompress(data, 16 + 15)
            except Exception:
                data = uzlib.decompress(data)
        except Exception:
            pass
    try:
        return data.decode("utf-8-sig", errors="ignore")
    except Exception:
        try:
            return data.decode("utf-8", errors="ignore")
        except Exception:
            try:
                return data.decode("latin-1", errors="ignore")
            except Exception:
                return "".join(chr(b) if b < 128 else "?" for b in data)
