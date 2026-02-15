try:
    from typing import Optional
except ImportError:
    from local.typing_compat import Optional

import struct

try:
    import displayio
except Exception:
    displayio = None

try:
    import jpegio
except Exception:
    jpegio = None


class JpegBmpConverter:
    """Convert JPEG bytes/files into a 64x64 RGB565 BMP on-device."""

    def __init__(
        self,
        target_width: int = 64,
        target_height: int = 64,
        temp_jpeg_path: str = "spotify_art.jpg",
    ) -> None:
        self.target_width = int(target_width) if target_width else 64
        self.target_height = int(target_height) if target_height else 64
        self.temp_jpeg_path = temp_jpeg_path or "spotify_art.jpg"
        self.last_error: Optional[Exception] = None

    @property
    def available(self) -> bool:
        return displayio is not None and jpegio is not None

    def convert_jpeg_bytes(self, data: bytes, out_path: str) -> bool:
        """Write JPEG bytes to a temp file, decode, resize, and save BMP."""
        if not data:
            self.last_error = ValueError("JPEG data missing")
            return False
        try:
            with open(self.temp_jpeg_path, "wb") as out_file:
                out_file.write(data)
            return self.convert_jpeg_file(self.temp_jpeg_path, out_path)
        finally:
            try:
                import os

                os.remove(self.temp_jpeg_path)
            except Exception:
                pass

    def convert_jpeg_file(self, jpeg_path: str, out_path: str) -> bool:
        """Decode a JPEG file, resize, and write a 64x64 BMP."""
        if not self.available:
            self.last_error = RuntimeError("jpegio/displayio not available")
            return False
        try:
            bitmap = _decode_jpeg_to_bitmap(jpeg_path)
            _write_bmp_scaled(bitmap, out_path, self.target_width, self.target_height)
            self.last_error = None
            try:
                import gc

                gc.collect()
            except Exception:
                pass
            return True
        except Exception as exc:
            self.last_error = exc
            return False


def _decode_jpeg_to_bitmap(jpeg_path: str):
    decoder_cls = getattr(jpegio, "JpegDecoder", None) or getattr(jpegio, "JPEGDecoder", None)
    if decoder_cls is None:
        raise RuntimeError("jpegio decoder class missing")

    decoder = decoder_cls()
    decoded = None
    errors = []

    for attempt in range(3):
        try:
            if attempt == 0 and hasattr(decoder, "open"):
                decoder.open(jpeg_path)
                decoded = decoder.decode()
            elif attempt == 1:
                decoded = decoder.decode(jpeg_path)
            else:
                decoder = decoder_cls(jpeg_path)
                decoded = decoder.decode()
            break
        except Exception as exc:
            errors.append(exc)
            decoded = None

    if decoded is None:
        raise RuntimeError("JPEG decode failed: {}".format(errors[-1] if errors else "unknown"))

    if isinstance(decoded, tuple):
        decoded = decoded[0]
    if not hasattr(decoded, "width") or not hasattr(decoded, "height"):
        raise ValueError("Decoded JPEG did not return a bitmap")
    return decoded


def _write_bmp_scaled(bitmap, out_path: str, width: int, height: int) -> None:
    if width <= 0 or height <= 0:
        raise ValueError("Invalid output size")
    src_w = int(getattr(bitmap, "width", 0) or 0)
    src_h = int(getattr(bitmap, "height", 0) or 0)
    if src_w <= 0 or src_h <= 0:
        raise ValueError("Source bitmap has invalid dimensions")

    row_bytes = width * 2
    image_size = row_bytes * height
    pixel_offset = 14 + 40 + 12
    file_size = pixel_offset + image_size

    x_map = [int(x * src_w / width) for x in range(width)]
    y_map = [int(y * src_h / height) for y in range(height)]

    with open(out_path, "wb") as out_file:
        # BITMAPFILEHEADER
        out_file.write(b"BM")
        out_file.write(struct.pack("<IHHI", file_size, 0, 0, pixel_offset))
        # BITMAPINFOHEADER (BITMAPINFOHEADER size = 40)
        out_file.write(
            struct.pack("<IIIHHIIIIII", 40, width, height, 1, 16, 3, image_size, 0, 0, 0, 0)
        )
        # RGB565 color masks (BI_BITFIELDS)
        out_file.write(struct.pack("<III", 0xF800, 0x07E0, 0x001F))

        for out_y in range(height - 1, -1, -1):
            src_y = y_map[out_y]
            for out_x in range(width):
                src_x = x_map[out_x]
                try:
                    pixel = bitmap[src_x, src_y]
                except Exception:
                    pixel = 0
                out_file.write(struct.pack("<H", _to_rgb565(pixel)))


def _to_rgb565(pixel: int) -> int:
    try:
        value = int(pixel)
    except Exception:
        return 0
    if value <= 0xFFFF:
        return value & 0xFFFF
    r = (value >> 16) & 0xFF
    g = (value >> 8) & 0xFF
    b = value & 0xFF
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
