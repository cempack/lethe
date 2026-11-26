"""The two private channels between the Lethe window and the sandboxed VM.

Screen   reads raw pixels from QEMU's VNC socket. Output only: we never send
         input, clipboard or files over it, and ignore anything but pixels.
Control  sends keyboard and pointer events over QMP.

Both peers are treated as hostile: every size is bounds-checked before use.
"""
import json, socket, struct, threading, time

from .keys import UNICODE_START, US, keystrokes

MAX_SIDE = 8192


class Frame:
    """What the window needs to draw: the whole picture plus what changed since it last looked."""
    __slots__ = ("serial", "width", "height", "pixels", "damage", "resized")

    def __init__(self, serial, width, height, pixels, damage, resized):
        self.serial, self.width, self.height = serial, width, height
        self.pixels, self.damage, self.resized = pixels, damage, resized


class Screen(threading.Thread):
    """Reads the VM's picture. Frames are published whole, never half-applied."""

    def __init__(self, path, fill_alpha=False):
        super().__init__(daemon=True)
        self.path, self.fill_alpha = path, fill_alpha    # fill_alpha: the drawing side cannot ignore byte 4
        self.lock, self.send_lock = threading.Lock(), threading.Lock()
        self.width = self.height = 0
        self.pixels = bytearray()        # BGRX
        self.serial = 0                  # bumped once per complete frame
        self.frames = 0                  # complete frames received, for measuring
        self.damage, self.resized = [], True
        self.sock = None
        self.resizable = False           # the VM accepts size requests (virtio display)
        self.cursor = None               # (serial, w, h, hot_x, hot_y, BGRA bytes) once the VM hands us its pointer
        self._layout = (0, 0)            # screen id and flags, echoed back in size requests

    def _read(self, n):
        buf = bytearray(n)
        view, got = memoryview(buf), 0
        while got < n:
            r = self.sock.recv_into(view[got:], n - got)
            if not r:
                raise ConnectionError("VM display closed")
            got += r
        return buf

    @staticmethod
    def _check(w, h):
        if not (0 < w <= MAX_SIDE and 0 < h <= MAX_SIDE):
            raise ValueError("implausible screen size")

    def _handshake(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.path)
        self._read(12)                                       # "RFB 003.008\n"
        self.sock.sendall(b"RFB 003.008\n")
        if 1 not in self._read(self._read(1)[0]):            # security type 1 = none (the socket is private)
            raise ConnectionError("unexpected VNC security")
        self.sock.sendall(b"\x01")
        if struct.unpack(">I", self._read(4))[0] != 0:
            raise ConnectionError("VNC handshake refused")
        self.sock.sendall(b"\x01")                           # shared session
        w, h = struct.unpack(">HH", self._read(4))
        self._read(16)
        self._read(min(struct.unpack(">I", self._read(4))[0], 4096))   # desktop name, unused
        self._check(w, h)
        self.width, self.height, self.pixels = w, h, bytearray(w * h * 4)
        # 32-bit little-endian BGRX: the layout GTK textures take as they are.
        self.sock.sendall(struct.pack(">BxxxBBBBHHHBBBxxx", 0, 32, 24, 0, 1, 255, 255, 255, 16, 8, 0))
        # Encodings: raw pixels, desktop size (plain and extended), pointer image with alpha.
        self.sock.sendall(struct.pack(">BxHiiii", 2, 4, 0, -223, -308, -314))

    def _request(self, incremental, w, h):
        with self.send_lock:
            self.sock.sendall(struct.pack(">BBHHHH", 3, incremental, 0, 0, w, h))

    def _update(self):
        """Read one FramebufferUpdate. Returns (new size or None, [(x, y, w, h, data)], pointer)."""
        size, rects, pointer = None, [], None
        for _ in range(struct.unpack(">xH", self._read(3))[0]):
            x, y, rw, rh, enc = struct.unpack(">HHHHi", self._read(12))
            if enc == 0:
                limit = size or (self.width, self.height)
                if x + rw > limit[0] or y + rh > limit[1]:
                    raise ValueError("update outside the screen")
                rects.append((x, y, rw, rh, self._read(rw * rh * 4)))
            elif enc == -223:
                self._check(rw, rh)
                size = (rw, rh)
            elif enc == -308:                        # extended desktop size: x = reason, y = status
                screens = self._read(4)[0]
                if screens > 16:
                    raise ValueError("implausible screen count")
                layout = self._read(16 * screens)
                if screens:
                    self._layout = struct.unpack_from(">I", layout, 0)[0], struct.unpack_from(">I", layout, 12)[0]
                self.resizable = True
                if y == 0 and (rw, rh) != (self.width, self.height):
                    self._check(rw, rh)
                    size = (rw, rh)
            elif enc == -314:                        # pointer image, hotspot in x, y
                if rw > 512 or rh > 512 or struct.unpack(">i", self._read(4))[0] != 0:
                    raise ValueError("unexpected pointer image")
                pointer = (rw, rh, min(x, max(rw - 1, 0)), min(y, max(rh - 1, 0)), bytes(self._read(rw * rh * 4)))
            else:
                raise ValueError("unexpected encoding")
        return size, rects, pointer

    def _apply(self, size, rects, pointer):
        """Apply a whole update at once, so the window never sees half of one."""
        if self.fill_alpha:
            for *_, data in rects:
                data[3::4] = b"\xff" * (len(data) // 4)
        with self.lock:
            if size:
                self.width, self.height = size
                self.pixels = bytearray(size[0] * size[1] * 4)
                self.damage, self.resized = [], True
            view, stride = memoryview(self.pixels), self.width * 4
            for x, y, rw, rh, data in rects:
                if rw == self.width:                 # full-width band: one copy
                    view[y * stride:(y + rh) * stride] = data
                else:
                    row = rw * 4
                    for r in range(rh):
                        o = (y + r) * stride + x * 4
                        view[o:o + row] = data[r * row:(r + 1) * row]
                self.damage.append((x, y, rw, rh))
            if pointer:
                self.cursor = (self.serial + 1, *pointer)
            if rects or size or pointer:
                self.serial += 1
                self.frames += 1

    def run(self):
        try:
            self._handshake()
            self._request(0, self.width, self.height)
            while True:
                kind = self._read(1)[0]
                if kind == 0:
                    size, rects, pointer = self._update()
                    w, h = size or (self.width, self.height)
                    # Ask for the next frame before applying this one, so QEMU is never left waiting on us.
                    self._request(0 if size else 1, w, h)
                    self._apply(size, rects, pointer)
                elif kind == 2:
                    pass                                 # bell
                elif kind == 3:                          # guest clipboard: read and discard, always
                    left = struct.unpack(">xxxI", self._read(7))[0]
                    while left:
                        left -= len(self._read(min(left, 65536)))
                else:
                    raise ValueError("unexpected VNC message")
        except (OSError, ValueError, struct.error):
            pass
        finally:
            self.close()

    def take(self, since):
        """The current frame if it is newer than serial `since`, else None. Damage is handed over once."""
        with self.lock:
            if self.serial == since or not self.width:
                return None
            frame = Frame(self.serial, self.width, self.height, bytes(self.pixels), self.damage, self.resized)
            self.damage, self.resized = [], False
            return frame

    def peek(self):
        """(width, height, pixels) without consuming the damage the window is waiting for."""
        with self.lock:
            return self.width, self.height, bytes(self.pixels)

    def request_size(self, w, h):
        """Ask the VM to change its resolution to w x h (ignored by displays that cannot)."""
        if self.resizable and self.sock and (w, h) != (self.width, self.height):
            try:
                with self.send_lock:
                    self.sock.sendall(struct.pack(">BxHHBxIHHHHI", 251, w, h, 1, self._layout[0], 0, 0, w, h, self._layout[1]))
            except OSError:
                pass

    def close(self):
        try:
            self.sock and self.sock.close()
        except OSError:
            pass
        with self.lock:                                          # do not keep the last guest frame around
            for i in range(0, len(self.pixels), 1 << 20):
                self.pixels[i:i + (1 << 20)] = bytes(min(1 << 20, len(self.pixels) - i))


class Control:
    def __init__(self, path):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
        self.lock = threading.Lock()
        self._send({"execute": "qmp_capabilities"})
        threading.Thread(target=self._drain, daemon=True).start()

    def _drain(self):
        try:
            while self.sock.recv(65536):
                pass                                             # replies are never interpreted
        except OSError:
            pass

    def _send(self, obj):
        try:
            with self.lock:
                self.sock.sendall(json.dumps(obj).encode() + b"\n")
        except OSError:
            pass

    def _events(self, events):
        self._send({"execute": "input-send-event", "arguments": {"events": events}})

    def keys(self, events):
        """events: [(qcode, down)]"""
        if events:
            self._events([{"type": "key", "data": {"down": bool(d), "key": {"type": "qcode", "data": q}}}
                          for q, d in events])

    def tap(self, *qcodes):
        self.keys([(q, True) for q in qcodes] + [(q, False) for q in reversed(qcodes)])

    def type(self, text, delay=0.012, stop=lambda: False):
        """Type any text into the guest, one character at a time; `stop()` can interrupt it."""
        for events in keystrokes(text):
            if stop():
                return False
            if events[0] == "unicode":
                # Ctrl+Shift+U, the code, Space. The guest's input method commits it asynchronously:
                # give it time on both sides, or neighbouring keys are lost or reordered.
                self.keys(UNICODE_START)
                time.sleep(0.05)
                self.keys([(US[d][0], down) for d in events[1] for down in (True, False)])
                time.sleep(0.03)
                self.keys([("spc", True), ("spc", False)])
                time.sleep(0.12)
            else:
                self.keys(events)
                time.sleep(delay)
        return True

    def move(self, fx, fy):
        """Pointer position as fractions 0..1 of the guest screen."""
        clamp = lambda f: max(0, min(32767, int(f * 32767)))
        self._events([{"type": "abs", "data": {"axis": "x", "value": clamp(fx)}},
                      {"type": "abs", "data": {"axis": "y", "value": clamp(fy)}}])

    def button(self, name, down):
        self._events([{"type": "btn", "data": {"down": bool(down), "button": name}}])

    def add_display_client(self, fd):
        """Give QEMU one end of a socket for its D-Bus display (QEMU serves, we connect)."""
        msg = json.dumps({"execute": "getfd", "arguments": {"fdname": "lethe-display"}}).encode() + b"\n"
        with self.lock:
            self.sock.sendmsg([msg], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, struct.pack("i", fd))])
        self._send({"execute": "add_client", "arguments": {"protocol": "@dbus-display", "fdname": "lethe-display"}})

    def eject(self, device):
        """Pull a virtual disc out of the VM."""
        self._send({"execute": "eject", "arguments": {"id": device, "force": True}})

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass
