"""The VM's screen over QEMU's D-Bus display: frames arrive the moment Tails draws them.

VNC (rfb.Screen) polls the screen every 30 ms, which caps it near 33 fps. With
`-display dbus,p2p=yes`, QEMU calls us on every flush instead, and with the
Unix.Map interface the pixels live in memory QEMU shares with us: each update
is just "this rectangle changed". Same interface as rfb.Screen, so the window
and the autopilot do not care which one they get.

Two private, peer-to-peer D-Bus connections, no bus daemon involved. QEMU
serves both; we log in to each with a session-only cookie:
  1. handed to QEMU through QMP `add_client`: we call the Console on it;
  2. handed over by Console.RegisterListener: QEMU calls us on it, on the
     /org/qemu/Display1/Listener object we export.
Everything QEMU sends is bounds-checked: it is treated as hostile.
"""
import mmap, os, socket, struct, threading

import gi
from gi.repository import Gio, GLib

from .rfb import Frame, MAX_SIDE

LISTENER_XML = """
<node>
  <interface name="org.qemu.Display1.Listener">
    <method name="Scanout"><arg type="u" direction="in"/><arg type="u" direction="in"/><arg type="u" direction="in"/>
      <arg type="u" direction="in"/><arg type="ay" direction="in"/></method>
    <method name="Update"><arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="i" direction="in"/>
      <arg type="i" direction="in"/><arg type="u" direction="in"/><arg type="u" direction="in"/><arg type="ay" direction="in"/></method>
    <method name="Disable"/>
    <method name="MouseSet"><arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="CursorDefine"><arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="i" direction="in"/>
      <arg type="i" direction="in"/><arg type="ay" direction="in"/></method>
    <property name="Interfaces" type="as" access="read"/>
  </interface>
  <interface name="org.qemu.Display1.Listener.Unix.Map">
    <method name="ScanoutMap"><arg type="h" direction="in"/><arg type="u" direction="in"/><arg type="u" direction="in"/>
      <arg type="u" direction="in"/><arg type="u" direction="in"/><arg type="u" direction="in"/></method>
    <method name="UpdateMap"><arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="i" direction="in"/>
      <arg type="i" direction="in"/></method>
  </interface>
</node>"""
# pixman formats whose bytes in memory are B, G, R, X/A on little-endian machines.
BGRX = {0x20020888, 0x20028888}          # PIXMAN_x8r8g8b8, PIXMAN_a8r8g8b8
CONSOLE = "/org/qemu/Display1/Console_0"


class Screen(threading.Thread):
    def __init__(self, control, keyring, fill_alpha=False):
        super().__init__(daemon=True)
        self.control, self.keyring, self.fill_alpha = control, keyring, fill_alpha
        self.lock = threading.Lock()
        self.width = self.height = self.stride = 0
        self.buffer = None                 # shared mmap, or our own bytearray for copied updates
        self.serial = self.frames = 0
        self.damage, self.resized = [], True
        self.cursor, self.resizable, self.failed = None, True, None
        self.ready = threading.Event()
        self.ctx = GLib.MainContext()
        self.loop = GLib.MainLoop(self.ctx)
        self._conn = self._listener = None

    # ── setup, on our own GLib context ──────────────────────────────────────
    def run(self):
        self.ctx.push_thread_default()
        try:
            self._connect()
            self.loop.run()
        except Exception as e:             # anything wrong: the caller falls back to VNC
            self.failed = str(e)
            self.ready.set()
        finally:
            self.ctx.pop_thread_default()

    @staticmethod
    def _stream(sock):
        """Hand a socket over to GIO, which owns (and closes) it from then on."""
        return Gio.Socket.new_from_fd(sock.detach()).connection_factory_create_connection()

    def _connect(self):
        os.environ["G_DBUS_COOKIE_SHA1_KEYRING_DIR"] = self.keyring    # read by GLib at login time
        ours, theirs = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        self.control.add_display_client(theirs.fileno())  # QEMU becomes the D-Bus server on `theirs`
        theirs.close()
        flags = Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
        self._conn = Gio.DBusConnection.new_sync(self._stream(ours), None, flags, None, None)

        # The listener connection: QEMU serves it while RegisterListener runs; we log in as its client
        # and answer the display calls QEMU makes on it.
        mine, for_qemu = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        flags = Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.DELAY_MESSAGE_PROCESSING
        Gio.DBusConnection.new(self._stream(mine), None, flags, None, None, self._listener_ready)
        fds = Gio.UnixFDList.new()
        index = fds.append(for_qemu.fileno())
        self._conn.call_with_unix_fd_list(None, CONSOLE, "org.qemu.Display1.Console", "RegisterListener",
                                          GLib.Variant("(h)", (index,)), None, Gio.DBusCallFlags.NONE, -1, fds,
                                          None, self._registered, for_qemu)

    def _registered(self, conn, result, for_qemu):
        for_qemu.close()
        try:
            conn.call_with_unix_fd_list_finish(result)
        except GLib.Error as e:
            self.failed = e.message
            self.ready.set()

    def _listener_ready(self, _source, result):
        try:
            self._listener = Gio.DBusConnection.new_finish(result)
        except GLib.Error as e:
            self.failed = e.message
            self.ready.set()
            return
        node = Gio.DBusNodeInfo.new_for_xml(LISTENER_XML)
        for iface in node.interfaces:
            self._listener.register_object("/org/qemu/Display1/Listener", iface, self._method, self._property, None)
        self._listener.connect("closed", lambda *_: self.close())
        self._listener.start_message_processing()

    def _property(self, _conn, _sender, _path, _iface, name):
        if name == "Interfaces":
            return GLib.Variant("as", ["org.qemu.Display1.Listener.Unix.Map"])
        return None

    # ── what QEMU tells us ──────────────────────────────────────────────────
    def _method(self, _conn, _sender, _path, _iface, name, params, invocation):
        try:
            handler = getattr(self, "_on_" + name, None)
            if handler:
                handler(params, invocation)
        except (ValueError, OSError, struct.error) as e:
            self.failed = f"bad display message: {e}"
        invocation.return_value(None)

    def _check(self, w, h, stride, fmt):
        if not (0 < w <= MAX_SIDE and 0 < h <= MAX_SIDE and stride >= w * 4 and stride <= w * 4 + 4096):
            raise ValueError("implausible screen geometry")
        if fmt not in BGRX:
            raise ValueError(f"unsupported pixel format {fmt:#x}")

    def _publish(self, size, damage):
        with self.lock:
            if size:
                self.damage, self.resized = [], True
            self.damage.append(damage)
            self.serial += 1
            self.frames += 1
        self.ready.set()

    def _on_ScanoutMap(self, params, invocation):
        index, offset, w, h, stride, fmt = params.unpack()
        self._check(w, h, stride, fmt)
        fds = invocation.get_message().get_unix_fd_list()
        fd = fds.get(index)
        try:
            if offset % mmap.ALLOCATIONGRANULARITY or offset > (1 << 31):
                raise ValueError("unaligned mapping")
            mapped = mmap.mmap(fd, stride * h, mmap.MAP_SHARED, mmap.PROT_READ, offset=offset)
        finally:
            os.close(fd)
        with self.lock:
            old = self.buffer
            self.width, self.height, self.stride, self.buffer = w, h, stride, mapped
        if isinstance(old, mmap.mmap):
            old.close()
        self._publish(True, (0, 0, w, h))

    def _on_UpdateMap(self, params, _invocation):
        x, y, w, h = params.unpack()
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > self.width or y + h > self.height:
            raise ValueError("update outside the screen")
        self._publish(False, (x, y, w, h))

    def _on_Scanout(self, params, _invocation):
        w, h, stride, fmt = (params.get_child_value(i).unpack() for i in range(4))
        self._check(w, h, stride, fmt)
        data = params.get_child_value(4).get_data_as_bytes().get_data()
        if len(data) < stride * h:
            raise ValueError("short scanout")
        with self.lock:
            old = self.buffer
            self.width, self.height, self.stride, self.buffer = w, h, stride, bytearray(data[:stride * h])
        if isinstance(old, mmap.mmap):
            old.close()
        self._publish(True, (0, 0, w, h))

    def _on_Update(self, params, _invocation):
        x, y, w, h, stride, fmt = (params.get_child_value(i).unpack() for i in range(6))
        if not isinstance(self.buffer, bytearray) or fmt not in BGRX:
            raise ValueError("update without a scanout")
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > self.width or y + h > self.height or stride < w * 4:
            raise ValueError("update outside the screen")
        data = params.get_child_value(6).get_data_as_bytes().get_data()
        if len(data) < stride * (h - 1) + w * 4:
            raise ValueError("short update")
        with self.lock:
            for row in range(h):
                o = (y + row) * self.stride + x * 4
                self.buffer[o:o + w * 4] = data[row * stride:row * stride + w * 4]
        self._publish(False, (x, y, w, h))

    def _on_CursorDefine(self, params, _invocation):
        w, h, hx, hy = (params.get_child_value(i).unpack() for i in range(4))
        if not (0 < w <= 512 and 0 < h <= 512):
            raise ValueError("implausible pointer")
        data = params.get_child_value(4).get_data_as_bytes().get_data()
        if len(data) < w * h * 4:
            raise ValueError("short pointer")
        with self.lock:
            self.cursor = (self.serial + 1, w, h, min(max(hx, 0), w - 1), min(max(hy, 0), h - 1), bytes(data[:w * h * 4]))
            self.serial += 1

    # ── what the window and the autopilot ask ───────────────────────────────
    def _rows(self):
        """The picture as tightly packed BGRX rows (stride == width * 4)."""
        w4, size = self.width * 4, self.stride * self.height
        raw = bytes(self.buffer[:size])
        if self.stride == w4:
            return raw
        return b"".join(raw[r * self.stride:r * self.stride + w4] for r in range(self.height))

    def take(self, since):
        with self.lock:
            if self.serial == since or not self.width or self.buffer is None:
                return None
            frame = Frame(self.serial, self.width, self.height, self._rows(), self.damage, self.resized)
            self.damage, self.resized = [], False
            return frame

    def peek(self):
        with self.lock:
            if self.buffer is None:
                return 0, 0, b""
            return self.width, self.height, self._rows()

    def request_size(self, w, h):
        """Tell the VM what size its screen is shown at; Tails then adopts that resolution."""
        if self._conn and (w, h) != (self.width, self.height):
            # 96 dpi is what GNOME assumes anyway: keep Tails' scaling at 100%.
            mm = lambda px: max(1, min(65535, round(px * 25.4 / 96)))
            params = GLib.Variant("(qqiiuu)", (mm(w), mm(h), 0, 0, w, h))
            self.ctx.invoke_full(GLib.PRIORITY_DEFAULT, lambda: self._conn.call(
                None, CONSOLE, "org.qemu.Display1.Console", "SetUIInfo", params, None,
                Gio.DBusCallFlags.NONE, -1, None, None) and False)

    def close(self):
        def stop():
            for c in (self._listener, self._conn):
                if c and not c.is_closed():
                    c.close(None, None)
            self.loop.quit()
            return False
        self.ctx.invoke_full(GLib.PRIORITY_DEFAULT, stop)
        with self.lock:
            if isinstance(self.buffer, mmap.mmap):
                self.buffer.close()
            elif isinstance(self.buffer, bytearray):
                self.buffer[:] = bytes(len(self.buffer))      # do not keep the last guest frame around
            self.buffer = None
