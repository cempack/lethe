#!/usr/bin/env python3
"""Draws the Tails wallpaper of a Lethe session: the Lethe moon (lethe/moon.py) going down over
still water, in the same cells, inks and dithering as the emblem in Lethe's window.

The picture is larger than any screen and is shown centred, never scaled: a dithered picture only
looks right when one of its cells is a whole number of screen pixels. Whatever the size of the
session window, the moon sits in the middle of the desktop and the picture is cropped around it.

Writes assets/wallpaper.png and assets/wallpaper-online.png. The second is the same picture a
touch brighter (1.4% towards white): Tails switches to it when Tor has connected, which is how
Lethe knows, without any channel out of the VM. Run it after changing the drawing.
"""
import math, os, random, struct, sys, zlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from lethe import moon
from lethe.moon import BAYER

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")
CELL = 4                     # screen pixels per cell
W, H = 960, 600              # in cells: 3840 x 2400 pixels
HORIZON = H // 2 + 24        # a little below the middle of the screen
RADIUS = 46

SKY = ((7, 8, 11), (10, 11, 15), (14, 16, 22), (20, 23, 31), (29, 33, 45))        # from night to the glow at the horizon
DEEP = ((7, 8, 11), (9, 10, 14), (12, 14, 19), (17, 19, 26))                        # the water
STARS = ((70, 79, 102), (126, 137, 166), (198, 207, 227))


def draw():
    cx, hy, R = W / 2, HORIZON, RADIUS
    palette, index = [], {}

    def ink(c):
        if c not in index:
            index[c] = len(palette)
            palette.append(c)
        return index[c]

    def dither(inks, level, th):
        level = max(0.0, min(len(inks) - 1.0, level))
        q = int(level)
        return ink(inks[min(len(inks) - 1, q + (level - q > th))])

    grid = [bytearray(W) for _ in range(H)]
    for j in range(H):
        row = grid[j]
        for i in range(W):
            th = BAYER[(j & 3) * 4 + (i & 3)]
            dx, dy = (i + 0.5 - cx) / R, (hy - j - 0.5) / R
            if j < hy:       # sky: dark above, a glow around the moon and along the horizon
                r = math.hypot(dx, dy)
                level = 2.9 * math.exp(-max(0.0, r - 1) * 0.95) + 1.5 * math.exp(-dy * 0.42) * math.exp(-abs(dx) * 0.10)
                row[i] = dither(SKY, level - 0.15, th)
            else:            # water: the same glow, fainter and squeezed flat
                r = math.hypot(dx, dy * 2.4)
                level = 2.1 * math.exp(-max(0.0, r - 0.6) * 0.75) + 0.9 * math.exp(dy * 0.5) * math.exp(-abs(dx) * 0.12)
                row[i] = dither(DEEP, level - 0.1, th)

    rnd = random.Random(11)  # stars: sparse, none close to the moon or low on the horizon
    for _ in range(W * H // 420):
        i, j = rnd.randrange(W), rnd.randrange(hy - 14)
        if math.hypot((i - cx) / R, (hy - j) / R) > 1.9:
            weight = rnd.random() * rnd.random()
            grid[j][i] = ink(STARS[2 if weight > 0.55 else 1 if weight > 0.22 else 0])

    cells, air, level = moon.cast(cx, hy, R, W)
    for i, j, a in air:
        under = palette[grid[j][i]]
        grid[j][i] = ink(tuple(round(p + (q - p) * a) for p, q in zip(under, moon.AIR)))
    surface, inks, shift = moon.surface(), moon.inks(), int(0.6 / moon.TAU * moon.TW)
    for i, j, row, col, q in cells:
        grid[j][i] = ink(inks[q][surface[row + (col + shift) % moon.TW]])

    for i in range(W):       # the horizon: a line of light from edge to edge, brightest under the moon
        d = abs(i + 0.5 - cx) / (W * 0.5)
        if (1 - d ** 1.5) > BAYER[(hy & 3) * 4 + (i & 3)] * 0.98:
            grid[hy][i] = ink(moon.GLINT[0 if d < 0.10 else 1 if d < 0.24 else 2] if d < 0.5 else SKY[4])

    for j, d, line in moon.reflection(level, hy, R, W, H):
        slide = moon.ripple(d, 0.9)
        if slide is not None:
            for i, q in line:
                if 0 <= i + slide < W:
                    grid[j][i + slide] = ink(moon.WATER[q])
    for _ in range(2600):    # glitter: short dashes of light on the water, thinning out with distance
        d = 2 + int(abs(rnd.gauss(0, 1)) * R * 0.75)
        i = int(cx + rnd.gauss(0, 1) * R * (1.6 + d * 0.05))
        j = hy + d
        if j < H and 0 <= i < W - 3 and rnd.random() < math.exp(-d / (R * 0.9)):
            for n in range(rnd.choice((1, 2, 2, 3))):
                grid[j][i + n] = ink(moon.WATER[0 if d > R * 0.5 else rnd.choice((0, 1))])
    return grid, palette


def png(path, grid, palette):
    """An indexed PNG, every cell CELL x CELL pixels."""
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    rows = bytearray()
    for row in grid:
        line = b"\0" + bytes(v for v in row for _ in range(CELL))
        rows += line * CELL
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", W * CELL, H * CELL, 8, 3, 0, 0, 0))
                + chunk(b"PLTE", bytes(v for c in palette for v in c)) + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
                + chunk(b"IEND", b""))


def main():
    grid, palette = draw()
    png(os.path.join(ASSETS, "wallpaper.png"), grid, palette)
    brighter = [tuple(round(v + (255 - v) * 0.014) for v in c) for c in palette]
    png(os.path.join(ASSETS, "wallpaper-online.png"), grid, brighter)
    print(f"{W * CELL} x {H * CELL} px, {len(palette)} inks, "
          f"{os.path.getsize(os.path.join(ASSETS, 'wallpaper.png')) // 1024} KB")


if __name__ == "__main__":
    main()
