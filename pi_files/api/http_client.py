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

_socket_pool = None
_ssl_context = None


def _get_socket_pool():
    global _socket_pool
    if _socket_pool is None:
        if socketpool is None or wifi is None:
            raise RuntimeError("socketpool unavailable")
        _socket_pool = socketpool.SocketPool(wifi.radio)
    return _socket_pool


def _get_ssl_context():
    global _ssl_context
    if _ssl_context is None:
        try:
            _ssl_context = ssl.create_default_context() if ssl else None
        except Exception:
            _ssl_context = None
    return _ssl_context


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
        close_requested = False
        try:
            close_requested = (
                req.headers and str(req.headers.get("Connection", "")).lower() == "close"
            )
        except Exception:
            close_requested = False
        auth_header = False
        try:
            auth_header = bool(req.headers and req.headers.get("Authorization"))
        except Exception:
            auth_header = False
        print(
            "HTTP start:",
            req.key,
            req.method,
            "timeout",
            req.timeout,
            "close",
            close_requested,
            "auth",
            auth_header,
        )
        _log_network_state()
        _set_io_active(True)
        try:
            if adafruit_requests is None or socketpool is None or wifi is None:
                raise RuntimeError("adafruit_requests unavailable")
            fresh_session = False
            if close_requested:
                fresh_session = True
                self._close_session()
            session = self._create_session() if fresh_session else self._get_session()
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
            print("HTTP error:", req.key, repr(exc), _describe_errno(exc))
            _log_network_state(prefix="HTTP error")
            try:
                self._close_session()
            except Exception:
                pass
            if req.on_error:
                req.on_error(exc)
        finally:
            try:
                if req.headers and str(req.headers.get("Connection", "")).lower() == "close":
                    self._close_session()
            except Exception:
                pass
            self._pending_keys.discard(req.key)
            _set_io_active(False)

    def _get_session(self):
        if self._session is None:
            self._session = self._create_session()
        return self._session

    def _create_session(self):
        pool = _get_socket_pool()
        ssl_context = _get_ssl_context()
        return adafruit_requests.Session(pool, ssl_context)

    def _close_session(self) -> None:
        if self._session is None:
            return
        session = self._session
        self._session = None
        try:
            close_fn = getattr(session, "close", None)
            if close_fn:
                close_fn()
        except Exception:
            pass

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


def _log_network_state(prefix: str = "HTTP") -> None:
    if wifi is None:
        print("{} network: wifi unavailable".format(prefix))
        return
    try:
        ip = wifi.radio.ipv4_address
    except Exception:
        ip = None
    try:
        connected = wifi.radio.connected
    except Exception:
        connected = None
    ssid = None
    rssi = None
    channel = None
    try:
        ap_info = wifi.radio.ap_info
        if ap_info:
            ssid = getattr(ap_info, "ssid", None)
            rssi = getattr(ap_info, "rssi", None)
            channel = getattr(ap_info, "channel", None)
    except Exception:
        pass
    parts = ["ip={}".format(ip), "connected={}".format(connected)]
    if ssid is not None:
        parts.append("ssid={}".format(ssid))
    if rssi is not None:
        parts.append("rssi={}".format(rssi))
    if channel is not None:
        parts.append("channel={}".format(channel))
    print("{} network: {}".format(prefix, " ".join(parts)))


def _describe_errno(exc: Exception) -> str:
    code = getattr(exc, "errno", None)
    if code is None:
        try:
            if exc.args and isinstance(exc.args[0], int):
                code = exc.args[0]
        except Exception:
            code = None
    if code is None:
        return ""
    name = ""
    try:
        import errno as _errno

        for key, value in _errno.__dict__.items():
            if key.isupper() and value == code:
                name = key
                break
    except Exception:
        name = ""
    if name:
        return "errno={} {}".format(code, name)
    return "errno={}".format(code)


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
