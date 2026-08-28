#!/usr/bin/env python3
"""Build favicon.ico from the small-tier PNGs, using BMP-encoded entries.

An ICO entry may hold either a PNG or a BMP. PNG entries are smaller and every
Windows browser since Vista reads them -- which is why this file used to emit
them. Safari does not reliably decode them, and a favicon it cannot decode is a
favicon it does not show: Safari falls back to its generic globe.

BMP entries are the original, universally understood form. The whole file is
still under 20KB at these sizes, so the size saving was never worth the risk.

No third-party imaging library: this decodes the PNGs directly (8-bit RGB,
non-interlaced, which is what the icon pipeline produces) and writes the BMPs
by hand, so it runs anywhere Python does.
"""
import struct
import sys
import zlib
from pathlib import Path

SOURCES = ("icons/favicon-16.png", "icons/favicon-32.png", "icons/favicon-48.png")
OUT = "favicon.ico"


def decode_png(path):
    """Minimal PNG reader -> (width, height, rows of RGB tuples)."""
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG")

    idat, pos = bytearray(), 8
    width = height = depth = colour = interlace = None
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height, depth, colour, _, _, interlace = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
        pos += 12 + length

    if (depth, colour, interlace) != (8, 2, 0):
        raise ValueError(f"{path}: expected 8-bit RGB non-interlaced, got "
                         f"depth={depth} colour={colour} interlace={interlace}")

    raw = zlib.decompress(bytes(idat))
    bpp, stride = 3, width * 3
    out, prev = [], bytearray(stride)
    pos = 0
    for _ in range(height):
        filt = raw[pos]; pos += 1
        line = bytearray(raw[pos:pos + stride]); pos += stride
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            x = line[i]
            if filt == 0:   line[i] = x
            elif filt == 1: line[i] = (x + a) & 0xFF
            elif filt == 2: line[i] = (x + b) & 0xFF
            elif filt == 3: line[i] = (x + (a + b) // 2) & 0xFF
            elif filt == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (x + pred) & 0xFF
            else:
                raise ValueError(f"{path}: unknown filter {filt}")
        out.append([tuple(line[i:i + 3]) for i in range(0, stride, 3)])
        prev = line
    return width, height, out


def bmp_entry(width, height, rows):
    """A 32-bit BGRA DIB plus its AND mask, as an ICO entry expects."""
    header = struct.pack(
        "<IiiHHIIiiII",
        40,            # biSize
        width,
        height * 2,    # colour data AND mask, per the ICO convention
        1, 32, 0, 0, 0, 0, 0, 0,
    )
    pixels = bytearray()
    for row in reversed(rows):                 # DIBs are bottom-up
        for r, g, b in row:
            pixels += bytes((b, g, r, 255))    # BGRA, fully opaque

    mask_stride = ((width + 31) // 32) * 4     # 1bpp, rows padded to 4 bytes
    mask = bytes(mask_stride * height)         # all zero = every pixel opaque
    return header + bytes(pixels) + mask


def main():
    entries = []
    for src in SOURCES:
        w, h, rows = decode_png(src)
        entries.append((w, h, bmp_entry(w, h, rows)))
        print(f"  read {src}: {w}x{h} -> {len(entries[-1][2])}B BMP entry")

    header = struct.pack("<HHH", 0, 1, len(entries))
    offset = len(header) + 16 * len(entries)
    directory, blobs = b"", b""
    for w, h, blob in entries:
        directory += struct.pack("<BBBBHHII",
                                 w if w < 256 else 0, h if h < 256 else 0,
                                 0, 0, 1, 32, len(blob), offset)
        blobs += blob
        offset += len(blob)

    Path(OUT).write_bytes(header + directory + blobs)
    print(f"  wrote {OUT}: {len(header + directory + blobs):,}B, {len(entries)} BMP entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
