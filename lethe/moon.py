"""The Lethe moon: the shapes, inks and surface shared by everything that draws it.

The mark of Lethe is a light going down over still water. Here it is as a model: a sphere lit from
the upper left, with seas and highlands on it, cut by the horizon. It is drawn on a coarse grid of
cells, each cell one of a handful of inks; the shades in between are made by ordered dithering,
the way a plotter or an old terminal would. The window's emblem (orb.py) and the Tails wallpaper
(tools/wallpaper.py) are both drawn from this file, so they are the same moon.

No toolkit is needed here: it is arithmetic.
"""
import math, random

TILT = 0.36              # the axis leans towards the viewer
LIGHT = (-0.66, 0.56, 0.40)
TAU = math.tau
BAYER = [(v + 0.5) / 16 for v in (0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5)]

PAGE = (11, 11, 12)      # Lethe's window
# The surface: three kinds of ground, each with three inks from shadow to full light.
SEA = ((30, 34, 45), (64, 72, 94), (126, 137, 166))
LAND = ((52, 58, 76), (108, 118, 146), (198, 207, 227))
BRIGHT = ((108, 118, 146), (198, 207, 227), (242, 245, 251))
DUSK = ((30, 34, 45), (52, 58, 76), (64, 72, 94))       # the last light before the dark side
NIGHT = ((13, 14, 17), (17, 18, 23), (20, 22, 28), (25, 27, 34))
AIR = (104, 118, 152)    # the thin ring of atmosphere
GLINT = ((198, 207, 227), (126, 137, 166), (72, 80, 104))    # the line of the horizon, from the moon outwards
WATER = ((34, 39, 52), (70, 79, 102), (132, 143, 172))       # the reflection

TW, TH = 512, 128        # the surface map: longitude by latitude


def surface():
    """The moon's ground as a map: 0 sea, 1 land, 2 bright. Smooth noise on the sphere itself, so
    the map has no seam and no pinching at the poles."""
    rnd = random.Random(7)
    n = 16
    lattice = [rnd.random() for _ in range(n * n * n)]

    def noise(x, y, z):
        xi, yi, zi = math.floor(x), math.floor(y), math.floor(z)
        fx, fy, fz = x - xi, y - yi, z - zi
        fx, fy, fz = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy), fz * fz * (3 - 2 * fz)
        x0, y0, z0 = xi % n, yi % n, zi % n
        x1, y1, z1 = (x0 + 1) % n, (y0 + 1) % n, (z0 + 1) % n
        a = lattice[(z0 * n + y0) * n + x0] * (1 - fx) + lattice[(z0 * n + y0) * n + x1] * fx
        b = lattice[(z0 * n + y1) * n + x0] * (1 - fx) + lattice[(z0 * n + y1) * n + x1] * fx
        c = lattice[(z1 * n + y0) * n + x0] * (1 - fx) + lattice[(z1 * n + y0) * n + x1] * fx
        d = lattice[(z1 * n + y1) * n + x0] * (1 - fx) + lattice[(z1 * n + y1) * n + x1] * fx
        return (a * (1 - fy) + b * fy) * (1 - fz) + (c * (1 - fy) + d * fy) * fz

    out = bytearray(TW * TH)
    for row in range(TH):
        lat = (0.5 - (row + 0.5) / TH) * math.pi
        cl, sl = math.cos(lat), math.sin(lat)
        for col in range(TW):
            lon = col / TW * TAU
            x, y, z = cl * math.cos(lon), sl, cl * math.sin(lon)
            v = 0.62 * noise(x * 1.7 + 3, y * 1.7 + 5, z * 1.7 + 7) + 0.38 * noise(x * 4.3 + 11, y * 4.3 + 13, z * 4.3 + 17)
            fine = noise(x * 13 + 23, y * 13 + 29, z * 13 + 31)
            out[row * TW + col] = 0 if v < 0.47 else 2 if fine > 0.84 and v > 0.58 else 1
    return bytes(out)


def cast(cx, hy, R, W):
    """The half moon above row `hy`, centre column `cx`, radius `R` cells, on a grid `W` cells wide.
    Returns (cells, air, level):
      cells  [(i, j, map row offset, map column, q)] for every cell of the disc; q is 0..2 in the
             light (dithered between shadow and full light), 3 on the terminator, 4 or 5 in the dark
      air    [(i, j, strength)] for the dithered ring of atmosphere around it
      level  {(i, j): q} for the lit cells: what the water has to mirror
    """
    lx, ly, lz = (c / math.hypot(*LIGHT) for c in LIGHT)
    cp, sp = math.cos(TILT), math.sin(TILT)
    cells, air, level = [], [], {}
    for j in range(max(0, int(hy - R * 1.1)), hy):
        y = (hy - j - 0.5) / R
        for i in range(max(0, int(cx - R * 1.1)), min(W, int(cx + R * 1.1) + 1)):
            x = (i + 0.5 - cx) / R
            r2, th = x * x + y * y, BAYER[(j & 3) * 4 + (i & 3)]
            if r2 > 1:
                r = math.sqrt(r2)
                if r < 1.08:
                    g = (1.08 - r) / 0.08
                    if g * g * max(0.15, (x * lx + y * ly) / r * 0.7 + 0.45) > th:
                        air.append((i, j, 0.5 * g))
                continue
            z = math.sqrt(1 - r2)
            yw, zw = y * cp + z * sp, -y * sp + z * cp
            row = min(TH - 1, int((0.5 - math.asin(max(-1.0, min(1.0, yw))) / math.pi) * TH))
            col = int((math.atan2(x, zw) / TAU) % 1 * TW)
            lam = x * lx + y * ly + z * lz
            if lam > 0:
                s = max(0.0, min(1.0, lam * 1.3) * 2 - (0.7 if r2 > 0.88 else 0))
                q = min(2, int(s) + (s - int(s) > th))
                level[(i, j)] = q
            elif lam > -0.12 and (lam + 0.12) / 0.12 > th:
                q = 3
            else:
                q = 4 + (th > 0.55)
            cells.append((i, j, row * TW, col, q))
    return cells, air, level


def inks():
    """inks()[q][ground] -> (r, g, b), for q as in cast() and ground 0 sea, 1 land, 2 bright."""
    table = [[m[q] for m in (SEA, LAND, BRIGHT)] for q in range(3)]
    table.append(list(DUSK))
    table += [[NIGHT[0], NIGHT[2], NIGHT[2]], [NIGHT[1], NIGHT[3], NIGHT[3]]]
    return table


def reflection(level, hy, R, W, H):
    """The moon in the water: [(row j, depth d, [(i, q)])]. Each row mirrors a row of the moon,
    squeezed, and thins out with depth."""
    rows, depth = [], int(R * 0.74)
    for d in range(1, depth + 1):
        j = hy + d
        if j >= H:
            break
        src, fade, line = hy - 1 - int((d - 1) / 0.74), (1 - d / (depth + 1)) ** 1.25, []
        for i in range(W):
            q = level.get((i, src))
            if q is not None and fade * (0.55 + 0.2 * q) > BAYER[(j & 3) * 4 + (i & 3)]:
                line.append((i, q))
        rows.append((j, d, line))
    return rows


def ripple(d, t):
    """How row `d` of the reflection sits at time `t`: None in a gap between ripples, else how many
    cells it has drifted sideways."""
    if (d + int(t * 2.6)) % (3 if d < 9 else 4 if d < 16 else 5) == 0:
        return None
    return round(math.sin(t * 1.25 + d * 0.85) * (0.5 + d * 0.085))
