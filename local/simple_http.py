from typing import Dict, Tuple

import socketpool
import wifi


class SimpleResponse:
    def __init__(self, text: str, content: bytes) -> None:
        self.text = text
        self.content = content

    def close(self) -> None:
        return None


class SimpleHttpClient:
    def __init__(self, pool: socketpool.SocketPool | None = None) -> None:
        self.pool = pool or socketpool.SocketPool(wifi.radio)

    def get(self, url: str, timeout: int = 10, **kwargs: Dict) -> SimpleResponse:
        host, port, path = _parse_url(url)
        addr = self.pool.getaddrinfo(host, port)[0][-1]
        sock = self.pool.socket(self.pool.AF_INET, self.pool.SOCK_STREAM)
        try:
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
            data = _recv_all(sock)
        finally:
            try:
                sock.close()
            except Exception:
                pass

        headers, body = _split_headers(data)
        if _is_chunked(headers):
            body = _decode_chunked(body)
        text = _safe_decode(body)
        return SimpleResponse(text, body)


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


def _recv_all(sock) -> bytes:
    chunks = []
    while True:
        try:
            buf = bytearray(1024)
            size = sock.recv_into(buf)
            if not size:
                break
            data = bytes(buf[:size])
        except AttributeError:
            data = sock.recv(1024)
        if not data:
            break
        chunks.append(data)
    return b"".join(chunks)


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
