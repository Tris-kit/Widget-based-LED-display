#!/usr/bin/env python3
import argparse
import sys
import urllib.parse
import urllib.request


def _read_le16(buf: bytes, offset: int) -> int:
    if offset + 2 > len(buf):
        return 0
    return buf[offset] | (buf[offset + 1] << 8)


def _read_le32(buf: bytes, offset: int, signed: bool = False) -> int:
    if offset + 4 > len(buf):
        return 0
    value = (
        buf[offset]
        | (buf[offset + 1] << 8)
        | (buf[offset + 2] << 16)
        | (buf[offset + 3] << 24)
    )
    if signed and value & 0x80000000:
        value -= 0x100000000
    return value


def _write_le16(value: int) -> bytes:
    return bytes((value & 0xFF, (value >> 8) & 0xFF))


def _write_le32(value: int) -> bytes:
    value &= 0xFFFFFFFF
    return bytes(
        (
            value & 0xFF,
            (value >> 8) & 0xFF,
            (value >> 16) & 0xFF,
            (value >> 24) & 0xFF,
        )
    )


def build_imgproxy_url(
    proxy_url: str,
    image_url: str,
    width: int,
    height: int,
    resize_mode: str,
    enlarge: bool,
    output_format: str,
) -> str:
    if "{url}" in proxy_url:
        return proxy_url.replace("{url}", urllib.parse.quote(image_url, safe=""))
    base = proxy_url.rstrip("/")
    encoded = urllib.parse.quote(image_url, safe="")
    enlarge_flag = 1 if enlarge else 0
    return f"{base}/unsafe/resize:{resize_mode}:{width}:{height}:{enlarge_flag}/plain/{encoded}@{output_format}"


def fetch_url(url: str, timeout: int = 10) -> bytes:
    req = urllib.request.Request(url, headers={"Accept": "image/bmp,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status >= 400:
            raise RuntimeError(f"HTTP {resp.status}")
        return resp.read()


def bmp_info(data: bytes) -> dict:
    if len(data) < 54 or data[:2] != b"BM":
        raise ValueError("Not a BMP")
    pixel_offset = _read_le32(data, 10)
    dib_size = _read_le32(data, 14)
    width = _read_le32(data, 18, signed=True)
    height = _read_le32(data, 22, signed=True)
    planes = _read_le16(data, 26)
    bpp = _read_le16(data, 28)
    compression = _read_le32(data, 30)
    masks = None
    if compression == 3 and len(data) >= 66:
        masks = (
            _read_le32(data, 54),
            _read_le32(data, 58),
            _read_le32(data, 62),
        )
    return {
        "pixel_offset": pixel_offset,
        "dib_size": dib_size,
        "width": width,
        "height": height,
        "planes": planes,
        "bpp": bpp,
        "compression": compression,
        "masks": masks,
    }


def _build_lut(scale: float):
    if scale < 0:
        scale = 0.0
    if scale > 1:
        scale = 1.0
    table = [0] * 256
    for i in range(256):
        table[i] = int(i * scale) & 0xFF
    return table


def convert_bmp_to_rgb565(data: bytes, scale: float) -> bytes:
    info = bmp_info(data)
    bpp = info["bpp"]
    compression = info["compression"]
    width_signed = info["width"]
    height_signed = info["height"]
    width = abs(width_signed)
    height = abs(height_signed)
    pixel_offset = info["pixel_offset"]

    if bpp not in (16, 24, 32):
        raise ValueError(f"Unsupported BMP bpp {bpp}")
    if compression not in (0, 3):
        raise ValueError(f"Unsupported BMP compression {compression}")

    mask_mode = "565"
    if bpp == 16:
        if compression == 3 and info["masks"]:
            g_mask = info["masks"][1]
            if g_mask == 0x03E0:
                mask_mode = "555"
        elif compression == 0:
            mask_mode = "555"

    row_stride_in = ((bpp * width + 31) // 32) * 4
    row_stride_out = ((16 * width + 31) // 32) * 4

    pixel_offset_out = 14 + 40 + 12
    image_size = row_stride_out * height
    file_size = pixel_offset_out + image_size

    out = bytearray()
    out += b"BM"
    out += _write_le32(file_size)
    out += _write_le16(0)
    out += _write_le16(0)
    out += _write_le32(pixel_offset_out)
    out += _write_le32(40)
    out += _write_le32(width)
    out += _write_le32(height_signed & 0xFFFFFFFF)
    out += _write_le16(1)
    out += _write_le16(16)
    out += _write_le32(3)
    out += _write_le32(image_size)
    out += _write_le32(0)
    out += _write_le32(0)
    out += _write_le32(0)
    out += _write_le32(0)
    out += _write_le32(0xF800)
    out += _write_le32(0x07E0)
    out += _write_le32(0x001F)

    lut = _build_lut(scale)
    bytes_per_pixel = bpp // 8
    offset = pixel_offset
    for _ in range(height):
        row = data[offset : offset + row_stride_in]
        offset += row_stride_in
        out_row = bytearray(row_stride_out)
        out_idx = 0
        limit = min(width * bytes_per_pixel, len(row))
        idx = 0
        while idx + bytes_per_pixel - 1 < limit:
            if bpp == 24:
                b = row[idx]
                g = row[idx + 1]
                r = row[idx + 2]
            elif bpp == 32:
                b = row[idx]
                g = row[idx + 1]
                r = row[idx + 2]
            else:
                value = row[idx] | (row[idx + 1] << 8)
                if mask_mode == "555":
                    r5 = (value >> 10) & 0x1F
                    g5 = (value >> 5) & 0x1F
                    b5 = value & 0x1F
                    r = (r5 << 3) | (r5 >> 2)
                    g = (g5 << 3) | (g5 >> 2)
                    b = (b5 << 3) | (b5 >> 2)
                else:
                    r5 = (value >> 11) & 0x1F
                    g6 = (value >> 5) & 0x3F
                    b5 = value & 0x1F
                    r = (r5 << 3) | (r5 >> 2)
                    g = (g6 << 2) | (g6 >> 4)
                    b = (b5 << 3) | (b5 >> 2)
            r = lut[r]
            g = lut[g]
            b = lut[b]
            out_val = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            out_row[out_idx] = out_val & 0xFF
            out_row[out_idx + 1] = (out_val >> 8) & 0xFF
            out_idx += 2
            idx += bytes_per_pixel
        out += out_row
    return bytes(out)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch a Spotify image via imgproxy and output RGB565 BMP."
    )
    parser.add_argument("--image-url", required=True, help="Spotify image URL")
    parser.add_argument("--proxy-url", default="http://127.0.0.1:8080", help="imgproxy base URL")
    parser.add_argument("--width", type=int, default=64)
    parser.add_argument("--height", type=int, default=64)
    parser.add_argument("--resize", default="fill")
    parser.add_argument("--enlarge", action="store_true")
    parser.add_argument("--format", default="bmp")
    parser.add_argument("--brightness-scale", type=float, default=0.35)
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument("--out", default="spotify_rgb565.bmp")
    args = parser.parse_args()

    url = build_imgproxy_url(
        args.proxy_url,
        args.image_url,
        args.width,
        args.height,
        args.resize,
        args.enlarge,
        args.format,
    )
    print("Proxy URL:", url)
    data = fetch_url(url, timeout=args.timeout)
    info = bmp_info(data)
    print(
        "Input BMP:",
        f"{abs(info['width'])}x{abs(info['height'])}",
        f"bpp={info['bpp']}",
        f"compression={info['compression']}",
        f"masks={info['masks']}",
    )

    out_data = convert_bmp_to_rgb565(data, args.brightness_scale)
    with open(args.out, "wb") as fh:
        fh.write(out_data)

    out_info = bmp_info(out_data)
    print(
        "Output BMP:",
        f"{abs(out_info['width'])}x{abs(out_info['height'])}",
        f"bpp={out_info['bpp']}",
        f"compression={out_info['compression']}",
        f"masks={out_info['masks']}",
    )
    print("Wrote:", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
