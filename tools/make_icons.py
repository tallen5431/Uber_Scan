#!/usr/bin/env python3
"""Generate the app icons (green tile, dark lightning bolt).

No image libraries available in this environment, so this rasterizes the
shapes directly and writes minimal PNGs. Re-run after changing the design:

    python3 tools/make_icons.py
"""

import os
import struct
import zlib

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")

GREEN = (0x17, 0xC9, 0x64)
DARK = (0x0B, 0x0F, 0x14)

# Lightning bolt in unit coordinates, clockwise.
BOLT = [
    (0.60, 0.04), (0.22, 0.56), (0.44, 0.56),
    (0.40, 0.96), (0.78, 0.44), (0.56, 0.44),
]

SS = 3  # supersampling factor per axis


def in_poly(x, y, poly):
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            if x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
        j = i
    return inside


def in_round_rect(x, y, radius):
    """Unit-square rounded rect membership; radius in unit coords."""
    cx = min(max(x, radius), 1.0 - radius)
    cy = min(max(y, radius), 1.0 - radius)
    dx, dy = x - cx, y - cy
    return dx * dx + dy * dy <= radius * radius


def render(size, radius, bolt_scale, bleed):
    """Return raw RGB rows. bleed=True fills the whole square (maskable)."""
    poly = [(0.5 + (px - 0.5) * bolt_scale, 0.5 + (py - 0.5) * bolt_scale)
            for px, py in BOLT]
    rows = []
    step = 1.0 / (size * SS)
    for py in range(size):
        row = bytearray()
        for px in range(size):
            bg_hits = 0
            fg_hits = 0
            for sy in range(SS):
                y = (py * SS + sy + 0.5) * step
                for sx in range(SS):
                    x = (px * SS + sx + 0.5) * step
                    if bleed or in_round_rect(x, y, radius):
                        bg_hits += 1
                        if in_poly(x, y, poly):
                            fg_hits += 1
            total = SS * SS
            # Composite bolt over tile over transparent-as-dark background.
            tile = [c * bg_hits / total for c in GREEN]
            base = [t + d * (1 - bg_hits / total) for t, d in zip(tile, DARK)]
            a = fg_hits / total
            row += bytes(int(round(b * (1 - a) + d * a)) for b, d in zip(base, DARK))
        rows.append(bytes(row))
    return rows


def write_png(path, size, rows):
    raw = b"".join(b"\x00" + r for r in rows)

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(png)
    print("wrote %s (%d bytes)" % (path, len(png)))


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, size, radius, scale, bleed in [
        ("icon-192.png", 192, 0.22, 0.86, False),
        ("icon-512.png", 512, 0.22, 0.86, False),
        ("apple-touch-icon.png", 180, 0.0, 0.80, True),
        ("maskable-512.png", 512, 0.0, 0.62, True),
    ]:
        write_png(os.path.join(OUT, name), size, render(size, radius, scale, bleed))


if __name__ == "__main__":
    main()
