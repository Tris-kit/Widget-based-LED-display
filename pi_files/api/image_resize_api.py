try:
    from typing import Callable, Optional
except ImportError:
    from local.typing_compat import Callable, Optional

from api.http_client import HttpClient, _get_socket_pool

try:
    import socketpool
    import wifi
except Exception:
    socketpool = None
    wifi = None


class ImageResizeApi:
    """Fetch resized images from imgproxy and save them to disk."""

    def __init__(
        self,
        proxy_url: Optional[str],
        http_client=None,
        output_path: str = "image.bmp",
        width: int = 64,
        height: int = 64,
        resize_mode: str = "fill",
        enlarge: bool = True,
        output_format: str = "bmp",
    ) -> None:
        self.proxy_url = (proxy_url or "").strip()
        self.http_client = http_client or HttpClient()
        self.output_path = output_path or "image.bmp"
        self.width = int(width) if width else 64
        self.height = int(height) if height else 64
        self.resize_mode = resize_mode or "fill"
        self.enlarge = bool(enlarge)
        self.output_format = output_format or "bmp"
        self.last_error: Optional[Exception] = None
        self._pending = False

    @property
    def available(self) -> bool:
        return bool(self.proxy_url)

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
        """Queue a proxy request to fetch a resized BMP image."""
        if self._pending:
            return False
        if not self.proxy_url:
            err = ValueError("Image proxy URL missing")
            self.last_error = err
            if on_error:
                on_error(err)
            return False
        if not image_url:
            err = ValueError("Image URL missing")
            self.last_error = err
            if on_error:
                on_error(err)
            return False

        url = _build_imgproxy_url(
            self.proxy_url,
            image_url,
            self.width,
            self.height,
            self.resize_mode,
            self.enlarge,
            self.output_format,
        )
        print("Image proxy URL:", url)
        self._pending = True

        def _handle_success(_text, body, status, _headers):
            self._pending = False
            try:
                if status and status >= 400:
                    raise RuntimeError("Image proxy error {}".format(status))
                if not body:
                    raise ValueError("Empty image response")
                try:
                    with open(self.output_path, "wb") as out_file:
                        out_file.write(body)
                except Exception as write_exc:
                    print(
                        "Image proxy write error:",
                        self.output_path,
                        repr(write_exc),
                    )
                    raise
                self.last_error = None
                if on_success:
                    on_success(self.output_path, status)
            except Exception as exc:
                self.last_error = exc
                if on_error:
                    on_error(exc)

        def _handle_error(exc):
            self._pending = False
            if _should_socket_fallback(exc):
                try:
                    status = _fetch_via_socket(url, self.output_path, timeout)
                    if status >= 400 or status == 0:
                        raise RuntimeError("Image proxy error {}".format(status))
                    self.last_error = None
                    if on_success:
                        on_success(self.output_path, status)
                    return
                except Exception as fallback_exc:
                    print("Image proxy socket fallback failed:", repr(fallback_exc))
                    exc = fallback_exc
            self.last_error = exc
            if on_error:
                on_error(exc)

        started = self.http_client.enqueue_get(
            url,
            headers={"Accept": "image/bmp,*/*", "Connection": "close"},
            on_success=_handle_success,
            on_error=_handle_error,
            timeout=timeout,
            key="image_proxy",
        )
        if not started:
            self._pending = False
            if self.last_error is None:
                self.last_error = RuntimeError("Image proxy request skipped")
        return started


def _build_imgproxy_url(
    proxy_url: str,
    image_url: str,
    width: int,
    height: int,
    resize_mode: str,
    enlarge: bool,
    output_format: str,
) -> str:
    if "{url}" in proxy_url:
        url = proxy_url.replace("{url}", _url_encode(image_url))
        return url
    base = (proxy_url or "").rstrip("/")
    encoded = _url_encode(image_url)
    enlarge_flag = 1 if enlarge else 0
    url = "{}/unsafe/resize:{}:{}:{}:{}/plain/{}@{}".format(
        base,
        resize_mode,
        width,
        height,
        enlarge_flag,
        encoded,
        output_format,
    )
    return url


def _url_encode(text: str) -> str:
    safe = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~"
    encoded = []
    for ch in text:
        if ch in safe:
            encoded.append(ch)
        else:
            encoded.append("%{:02X}".format(ord(ch)))
    return "".join(encoded)


def _should_socket_fallback(exc: Exception) -> bool:
    name = exc.__class__.__name__
    if "OutOfRetries" in name:
        return True
    if "MemoryError" in name:
        return True
    return False


def _parse_url(url: str):
    scheme = ""
    rest = url
    if "://" in url:
        scheme, rest = url.split("://", 1)
    host_port = rest
    path = "/"
    if "/" in rest:
        host_port, path = rest.split("/", 1)
        path = "/" + path
    host = host_port
    port = 443 if scheme == "https" else 80
    if ":" in host_port:
        host, port_str = host_port.rsplit(":", 1)
        try:
            port = int(port_str)
        except Exception:
            port = 443 if scheme == "https" else 80
    return scheme, host, port, path


def _fetch_via_socket(url: str, out_path: str, timeout: int) -> int:
    if socketpool is None or wifi is None:
        raise RuntimeError("socketpool unavailable")
    scheme, host, port, path = _parse_url(url)
    if scheme and scheme != "http":
        raise RuntimeError("socket fetch only supports http")
    pool = _get_socket_pool()
    sock = pool.socket()
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        request = "GET {} HTTP/1.1\r\nHost: {}:{}\r\nConnection: close\r\n\r\n".format(
            path, host, port
        )
        sock.send(request.encode())
        header = b""
        buf = bytearray(512)
        while b"\r\n\r\n" not in header:
            n = sock.recv_into(buf)
            if n == 0:
                break
            header += bytes(buf[:n])
            if len(header) > 8192:
                break
        header_end = header.find(b"\r\n\r\n")
        if header_end < 0:
            raise RuntimeError("socket response missing headers")
        header_bytes = header[:header_end]
        body_start = header[header_end + 4 :]
        status_line = header_bytes.split(b"\r\n", 1)[0].decode("utf-8", "ignore")
        status = 0
        try:
            status = int(status_line.split()[1])
        except Exception:
            status = 0
        with open(out_path, "wb") as out_file:
            if body_start:
                out_file.write(body_start)
            while True:
                n = sock.recv_into(buf)
                if n is None or n <= 0:
                    break
                out_file.write(buf[:n])
        return status
    finally:
        try:
            sock.close()
        except Exception:
            pass
