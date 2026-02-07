try:
    from typing import Callable, Dict, Optional, Tuple
except ImportError:
    from local.typing_compat import Callable, Dict, Optional, Tuple

import time

import socketpool
import wifi


class HttpResponse:
    def __init__(self, text: str, content: bytes) -> None:
        self.text = text
        self.content = content

    def close(self) -> None:
        return None


class HttpClient:
    def __init__(self, pool: socketpool.SocketPool | None = None) -> None:
        self.pool = pool or socketpool.SocketPool(wifi.radio)
        self.supports_progress = True

    def get(
        self,
        url: str,
        timeout: int = 10,
        on_progress: Optional[Callable[[], None]] = None,
        **kwargs: Dict,
    ) -> HttpResponse:
        host, port, path = _parse_url(url)
        addr = self.pool.getaddrinfo(host, port)[0][-1]
        sock = self.pool.socket(self.pool.AF_INET, self.pool.SOCK_STREAM)
        try:
            deadline = None
            if on_progress:
                sock.settimeout(min(0.25, timeout))
                deadline = time.monotonic() + timeout
            else:
                sock.settimeout(timeout)
            sock.connect(addr)
            request = (
                "GET {} HTTP/1.1\r\n"
                "Host: {}\r\n"
                "User-Agent: Pico\r\n"
                "Accept: application/json\r\n"
                "Accept-Encoding: identity\r\n"
                "Connection: close\r\n"
                "\r\n"
            ).format(path, host)
            sock.send(request.encode("utf-8"))
            data = _recv_all(sock, deadline=deadline, on_progress=on_progress)
        finally:
            try:
                sock.close()
            except Exception:
                pass

        headers, body = _split_headers(data)
        if _is_chunked(headers):
            body = _decode_chunked(body)
        text = _safe_decode(body)
        return HttpResponse(text, body)


def _parse_url(url: str) -> Tuple[str, int, str]:
    if not url.startswith("http://"):
        raise ValueError("Only http:// URLs are supported")
    without_scheme = url[len("http://") :]
    path_start = without_scheme.find("/")
    if path_start == -1:
        host_port = without_scheme
        path = "/"
    else:
        host_port = without_scheme[:path_start]
        path = without_scheme[path_start:] or "/"
    if ":" in host_port:
        host, port_str = host_port.split(":", 1)
        port = int(port_str)
    else:
        host = host_port
        port = 80
    return host, port, path


def _recv_all(
    sock,
    deadline: Optional[float] = None,
    on_progress: Optional[Callable[[], None]] = None,
) -> bytes:
    chunks = []
    while True:
        try:
            buf = bytearray(1024)
            size = sock.recv_into(buf)
            if not size:
                break
            data = bytes(buf[:size])
        except AttributeError:
            try:
                data = sock.recv(1024)
            except Exception as exc:
                if _should_retry(exc, deadline):
                    if on_progress:
                        on_progress()
                    continue
                raise
        except Exception as exc:
            if _should_retry(exc, deadline):
                if on_progress:
                    on_progress()
                continue
            raise
        if not data:
            break
        chunks.append(data)
        if on_progress:
            on_progress()
    return b"".join(chunks)


def _should_retry(exc: Exception, deadline: Optional[float]) -> bool:
    if deadline is None:
        return False
    if time.monotonic() > deadline:
        return False
    err = getattr(exc, "errno", None)
    if err in (11, 35, 110, 116):
        return True
    msg = str(exc).lower()
    return "timed out" in msg or "timeout" in msg


def _split_headers(data: bytes) -> Tuple[bytes, bytes]:
    marker = b"\r\n\r\n"
    idx = data.find(marker)
    if idx == -1:
        return b"", data
    return data[:idx], data[idx + len(marker) :]


def _is_chunked(headers: bytes) -> bool:
    try:
        header_text = headers.decode("utf-8").lower()
    except Exception:
        return False
    return "transfer-encoding: chunked" in header_text


def _decode_chunked(body: bytes) -> bytes:
    out = bytearray()
    idx = 0
    length = len(body)
    while idx < length:
        line_end = body.find(b"\r\n", idx)
        if line_end == -1:
            break
        chunk_size_str = body[idx:line_end].split(b";", 1)[0]
        try:
            chunk_size = int(chunk_size_str, 16)
        except ValueError:
            break
        idx = line_end + 2
        if chunk_size == 0:
            break
        out.extend(body[idx : idx + chunk_size])
        idx += chunk_size + 2  # skip CRLF
    return bytes(out)


def _safe_decode(data: bytes) -> str:
    try:
        try:
            return data.decode("utf-8", errors="ignore")
        except TypeError:
            return data.decode("utf-8")
    except UnicodeError:
        try:
            return data.decode("latin-1")
        except Exception:
            return "".join(chr(b) if b < 128 else "?" for b in data)
