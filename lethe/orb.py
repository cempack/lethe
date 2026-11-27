"""The Lethe mark as a living thing: the moon of moon.py, turning, over water that moves.

It is the logo in three dimensions (a half disc of light, and its reflection breaking up beneath
it). Nothing is an image: the sphere is ray-cast and carries a surface that turns slowly about a
tilted axis; the water mirrors it in rows that drift and thin out with depth.

Drag it to turn it, click it for one full turn. It rests when its window is not the one in use.

The work per frame is small: the geometry and the light do not change, so everything that depends
on them is worked out once per size. A frame only looks up which part of the surface faces each
cell, and slides the rows of the reflection.
"""
import math, threading

from . import moon
from .moon import TAU, TW
from .widgets import Gdk, GLib, Graphene, Gsk, Gtk

CELL = 3                 # the size of one cell, in pixels at 100% scale
FPS = 24
IDLE = 0.11              # radians per second, at rest


class Orb(Gtk.Widget):
    _map = None                      # shared by every Orb, drawn once in the background
    _map_lock = threading.Lock()

    def __init__(self, height=228, busy=False, **props):
        super().__init__(height_request=height, hexpand=True, **props)
        self.busy = busy             # True: turning fast, something is being done
        self.lon, self.omega, self.t = 0.6, IDLE, 0.0
        self.grid = None             # (W, H, cell in device pixels)
        self.last = self.turn = None
        self.texture = None
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._grab)
        drag.connect("drag-update", self._pull)
        drag.connect("drag-end", self._release)
        self.add_controller(drag)
        self.held = None
        self.set_cursor(Gdk.Cursor.new_from_name("grab"))
        self.add_tick_callback(self._tick)
        if Orb._map is None and Orb._map_lock.acquire(blocking=False):
            threading.Thread(target=self._chart, daemon=True).start()

    @staticmethod
    def _chart():
        Orb._map = moon.surface()

    def spin(self):
        """One quick full turn, for when something starts."""
        self.turn = [0.0, 0.0]       # seconds in, radians given so far

    # ── once per size: everything that light and shape decide ─────────────────
    def _build(self, W, H):
        cx, hy = W / 2, round(H * 0.655)
        R = min(H * 0.52, W * 0.27)
        rgba = lambda c: bytes((*c, 255))
        cells, air, level = moon.cast(cx, hy, R, W)
        base = bytearray(W * H * 4)
        for i, j, a in air:                          # the atmosphere, mixed over the window's own colour
            base[(j * W + i) * 4:(j * W + i) * 4 + 4] = bytes((*(round(p + (q - p) * a) for p, q in zip(moon.PAGE, moon.AIR)), 255))
        # The horizon: a line of light that is brightest under the moon and gives out to both sides.
        reach = R * 2.05
        for i in range(W):
            d = abs(i + 0.5 - cx) / reach
            if d < 1 and (1 - d ** 4) > moon.BAYER[(hy & 3) * 4 + (i & 3)] * 0.97:
                base[(hy * W + i) * 4:(hy * W + i) * 4 + 4] = rgba(moon.GLINT[0 if d < 0.42 else 1 if d < 0.72 else 2])
        rows = []
        for j, d, cells_in_row in moon.reflection(level, hy, R, W, H):
            line = bytearray(W * 4)
            for i, q in cells_in_row:
                line[i * 4:i * 4 + 4] = rgba(moon.WATER[q])
            rows.append((j * W * 4, bytes(line), d))
        self.cells = [((j * W + i) * 4, row, col, q) for i, j, row, col, q in cells]
        self.inks = [[rgba(c) for c in grounds] for grounds in moon.inks()]
        self.base, self.rows, self.W, self.H = bytes(base), rows, W, H

    # ── once per frame ────────────────────────────────────────────────────────
    def _frame(self):
        W, buf, surface, inks = self.W, bytearray(self.base), Orb._map, self.inks
        if surface:
            shift = int(self.lon / TAU * TW) % TW
            for k, row, col, q in self.cells:
                buf[k:k + 4] = inks[q][surface[row + (col + shift) % TW]]
        else:                                        # the map is still being drawn: plain ground
            for k, _row, _col, q in self.cells:
                buf[k:k + 4] = inks[q][1]
        blank, width = bytes(W * 4), W * 4
        for start, line, d in self.rows:
            slide = moon.ripple(d, self.t)
            if slide is None:                        # a gap between two ripples
                continue
            slide *= 4
            if slide > 0:
                buf[start:start + width] = blank[:slide] + line[:width - slide]
            elif slide < 0:
                buf[start:start + width] = line[-slide:] + blank[:-slide]
            else:
                buf[start:start + width] = line
        self.texture = Gdk.MemoryTexture.new(W, self.H, Gdk.MemoryFormat.R8G8B8A8_PREMULTIPLIED,
                                             GLib.Bytes.new(bytes(buf)), W * 4)

    def _scale(self):
        surface = self.get_native() and self.get_native().get_surface()
        if surface and hasattr(surface, "get_scale"):
            return surface.get_scale() or 1.0
        return float(self.get_scale_factor() or 1)

    def _tick(self, _widget, clock):
        now = clock.get_frame_time() / 1e6
        if self.last is None:
            self.last = now
        dt = now - self.last
        if dt < 1 / FPS:
            return True
        self.last, dt = now, min(dt, 0.1)
        root = self.get_root()
        still = not Gtk.Settings.get_default().get_property("gtk-enable-animations")
        if (still or (root and not root.is_active() and not self.busy)) and self.texture and not self.held:
            return True                              # at rest: the last frame stays
        self.t += dt
        if self.turn:                                # a full turn, eased in and out over 1.4 s
            self.turn[0] += dt
            p = min(1.0, self.turn[0] / 1.4)
            done = TAU * (4 * p ** 3 if p < 0.5 else 1 - (2 - 2 * p) ** 3 / 2)
            self.lon, self.turn[1] = self.lon + done - self.turn[1], done
            if p >= 1:
                self.turn = None
        elif not self.held:
            rest = IDLE * (7 if self.busy else 1)
            self.omega += (rest - self.omega) * min(1.0, dt * 1.6)
            self.lon += self.omega * dt
        self._frame() if self.grid else None
        self.queue_draw()
        return True

    def _grab(self, _gesture, _x, _y):
        self.held = (self.lon, 0.0, self.t)

    def _pull(self, _gesture, dx, _dy):
        if self.held:
            lon0, last_dx, last_t = self.held
            self.lon = lon0 - dx * 0.011
            self.omega = max(-5.0, min(5.0, -(dx - last_dx) * 0.011 * FPS))
            self.held = (lon0, dx, self.t)

    def _release(self, _gesture, dx, dy):
        self.held = None
        if abs(dx) < 3 and abs(dy) < 3:              # a click, not a drag: one full turn
            self.spin()

    def do_snapshot(self, snap):
        scale = self._scale()
        cell = max(2, round(CELL * scale))
        W, H = min(150, int(self.get_width() * scale) // cell), int(self.get_height() * scale) // cell
        if W < 24 or H < 24:
            return
        if self.grid != (W, H, cell):
            self.grid = (W, H, cell)
            self._build(W, H)
            self._frame()
        if not self.texture:
            self._frame()
        w, h = W * cell / scale, H * cell / scale
        x = round((self.get_width() - w) / 2 * scale) / scale
        y = round((self.get_height() - h) / 2 * scale) / scale
        rect = Graphene.Rect().init(x, y, w, h)
        if hasattr(snap, "append_scaled_texture"):
            snap.append_scaled_texture(self.texture, Gsk.ScalingFilter.NEAREST, rect)     # every cell a crisp square
        else:
            snap.append_texture(self.texture, rect)
