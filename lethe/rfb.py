"""The two private channels between the Lethe window and the sandboxed VM.

Screen   reads raw pixels from QEMU's VNC socket. Output only: we never send
         input, clipboard or files over it, and ignore anything but pixels.
Control  sends keyboard and pointer events over QMP.

Both peers are treated as hostile: every size is bounds-checked before use.
"""
import json, socket, struct, threading, time

from .keys import typed

MAX_SIDE = 8192


class Screen(threading.Thread):
    def __init__(self, path, on_frame=lambda: None, on_closed=lambda: None):
        super().__init__(daemon=True)
        self.path, self.on_frame, self.on_closed = path, on_frame, on_closed
        self.lock = threading.Lock()
        self.width = self.height = 0
        self.pixels = bytearray()        # BGRA, alpha forced opaque
        self.serial = 0                  # bumped on every update
        self.sock = None
        self.send_lock = threading.Lock()
        self.resizable = False           # the VM accepts size requests (virtio display)
        self.cursor = None               # (serial, w, h, hot_x, hot_y, BGRA bytes) when the VM hands us its pointer
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

    def _resize(self, w, h):
        if not (0 < w <= MAX_SIDE and 0 < h <= MAX_SIDE):
            raise ValueError("implausible screen size")
        with self.lock:
            self.width, self.height = w, h
            self.pixels = bytearray(b"\0\0\0\xff" * (w * h))

    def run(self):
        try:
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.connect(self.path)
            self._read(12)                                       # "RFB 003.008\n"
            self.sock.sendall(b"RFB 003.008\n")
            if 1 not in self._read(self._read(1)[0]):            # security type 1 = none (socket is private)
                raise ConnectionError("unexpected VNC security")
            self.sock.sendall(b"\x01")
            if struct.unpack(">I", self._read(4))[0] != 0:
                raise ConnectionError("VNC handshake refused")
            self.sock.sendall(b"\x01")                           # shared session
            w, h = struct.unpack(">HH", self._read(4))
            self._read(16)
            self._read(min(struct.unpack(">I", self._read(4))[0], 4096))   # desktop name, unused
            self._resize(w, h)
            # 32-bit little-endian BGRX: the layout GTK textures take as-is.
            self.sock.sendall(struct.pack(">BxxxBBBBHHHBBBxxx", 0, 32, 24, 0, 1, 255, 255, 255, 16, 8, 0))
            # encodings: raw pixels, desktop size (plain and extended), pointer image with alpha
            self.sock.sendall(struct.pack(">BxHiiii", 2, 4, 0, -223, -308, -314))
            incremental = 0
            while True:
                with self.send_lock:
                    self.sock.sendall(struct.pack(">BBHHHH", 3, incremental, 0, 0, self.width, self.height))
                incremental = 1
                kind = self._read(1)[0]
                if kind == 0:
                    for _ in range(struct.unpack(">xH", self._read(3))[0]):
                        x, y, rw, rh, enc = struct.unpack(">HHHHi", self._read(12))
                        if enc == -223:
                            self._resize(rw, rh)
                            incremental = 0
                        elif enc == -308:                        # extended desktop size: x = reason, y = status
                            screens = self._read(4)[0]
                            if screens > 16:
                                raise ValueError("implausible screen count")
                            layout = self._read(16 * screens)
                            if screens:
                                self._layout = struct.unpack_from(">I", layout, 0)[0], struct.unpack_from(">I", layout, 12)[0]
                            self.resizable = True
                            if y == 0 and (rw, rh) != (self.width, self.height):
                                self._resize(rw, rh)
                                incremental = 0
                        elif enc == -314:                        # pointer image: x, y = hotspot
                            if rw > 512 or rh > 512 or struct.unpack(">i", self._read(4))[0] != 0:
                                raise ValueError("unexpected pointer image")
                            image = bytes(self._read(rw * rh * 4))
                            self.cursor = (self.serial, rw, rh, min(x, max(rw - 1, 0)), min(y, max(rh - 1, 0)), image)
                            self.serial += 1
                        elif enc == 0:
                            if x + rw > self.width or y + rh > self.height:
                                raise ValueError("update outside the screen")
                            data = self._read(rw * rh * 4)
                            data[3::4] = b"\xff" * (rw * rh)
                            with self.lock:
                                view, stride = memoryview(self.pixels), self.width * 4
                                for row in range(rh):
                                    o = (y + row) * stride + x * 4
                                    view[o:o + rw * 4] = data[row * rw * 4:(row + 1) * rw * 4]
                                self.serial += 1
                        else:
                            raise ValueError("unexpected encoding")
                    self.on_frame()
                elif kind == 2:
                    pass                                         # bell
                elif kind == 3:                                  # guest clipboard: read and discard, always
                    left = struct.unpack(">xxxI", self._read(7))[0]
                    while left:
                        left -= len(self._read(min(left, 65536)))
                else:
                    raise ValueError("unexpected VNC message")
        except (OSError, ValueError, struct.error):
            pass
        finally:
            self.close()
            self.on_closed()

    def request_size(self, w, h):
        """Ask the VM to change its resolution to w x h (ignored by displays that cannot)."""
        if self.resizable and self.sock and (w, h) != (self.width, self.height):
            try:
                with self.send_lock:
                    self.sock.sendall(struct.pack(">BxHHBxIHHHHI", 251, w, h, 1, self._layout[0], 0, 0, w, h, self._layout[1]))
            except OSError:
                pass

    def snapshot(self):
        with self.lock:
            return self.width, self.height, bytes(self.pixels), self.serial

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

    def type(self, text, delay=0.012):
        """Type text at a human-plausible pace: the emulated keyboard has a small buffer."""
        for ch in text:
            self.keys(typed(ch))
            time.sleep(delay)

    def move(self, fx, fy):
        """Pointer position as fractions 0..1 of the guest screen."""
        clamp = lambda f: max(0, min(32767, int(f * 32767)))
        self._events([{"type": "abs", "data": {"axis": "x", "value": clamp(fx)}},
                      {"type": "abs", "data": {"axis": "y", "value": clamp(fy)}}])

    def button(self, name, down):
        self._events([{"type": "btn", "data": {"down": bool(down), "button": name}}])

    def eject(self, device):
        """Pull a virtual disc out of the VM."""
        self._send({"execute": "eject", "arguments": {"id": device, "force": True}})

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass
