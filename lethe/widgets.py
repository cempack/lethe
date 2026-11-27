"""Building blocks for the Lethe window, and the display that draws the VM."""
import ctypes, ctypes.util, os, sys, time

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "assets")
try:    # the bundled typeface, for this process only, before GTK reads fonts
    _fc = ctypes.CDLL(ctypes.util.find_library("fontconfig") or "libfontconfig.so.1")
    _fc.FcConfigAppFontAddFile(None, os.path.join(ASSETS, "Inter.ttf").encode())
except OSError:
    pass

import gi
for _lib, _ver in (("Gtk", "4.0"), ("Gdk", "4.0"), ("Gsk", "4.0"), ("Graphene", "1.0")):
    gi.require_version(_lib, _ver)
from gi.repository import Gdk, GLib, Graphene, Gsk, Gtk, Pango

from . import keys

try:
    import cairo                           # only for telling GTK which parts of a frame changed
except ImportError:
    cairo = None

# GTK 4.14+ can ignore the unused fourth byte; 4.16+ can upload only the changed parts of a frame.
OPAQUE = getattr(Gdk.MemoryFormat, "B8G8R8X8", None)
PIXEL_FORMAT = OPAQUE or Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED
NEEDS_ALPHA = OPAQUE is None
PARTIAL_UPLOADS = hasattr(Gdk, "MemoryTextureBuilder") and cairo is not None


def setup_style():
    """Fonts, colours and icons for the whole application. Call once, after GTK starts."""
    display = Gdk.Display.get_default()
    settings = Gtk.Settings.get_for_display(display)
    if hasattr(Gtk, "InterfaceColorScheme"):
        settings.set_property("gtk-interface-color-scheme", Gtk.InterfaceColorScheme.DARK)
    else:
        settings.set_property("gtk-application-prefer-dark-theme", True)
    provider = Gtk.CssProvider()
    provider.load_from_path(os.path.join(ASSETS, "lethe.css"))
    Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    Gtk.IconTheme.get_for_display(display).add_search_path(ASSETS)
    Gtk.Window.set_default_icon_name("lethe")


def log(*what):
    if os.environ.get("LETHE_DEBUG"):
        print("lethe:", *what, file=sys.stderr, flush=True)


def ui(fn, *args):
    """Run `fn` on the GTK thread (from any thread)."""
    GLib.idle_add(lambda: fn(*args) and False)


# ── small constructors ───────────────────────────────────────────────────────

def label(text="", css="", xalign=0.0, wrap=False, chars=0):
    w = Gtk.Label(label=text, xalign=xalign, wrap=wrap)
    if wrap:
        w.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        w.set_max_width_chars(chars or 30)    # a floor for natural width; the layout decides the real width
        w.set_width_chars(min(chars or 30, 18))
        if xalign == 0.5:
            w.set_justify(Gtk.Justification.CENTER)
    for c in css.split():
        w.add_css_class(c)
    return w


def box(vertical=True, spacing=0, css="", **props):
    b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL,
                spacing=spacing, **props)
    for c in css.split():
        b.add_css_class(c)
    return b


def button(text, css, action, icon=None):
    b = Gtk.Button(valign=Gtk.Align.CENTER)
    if icon:
        inner = box(False, 4)
        inner.append(image(icon, 18))
        inner.append(Gtk.Label(label=text))
        b.set_child(inner)
    else:
        b.set_label(text)
    for c in css.split():
        b.add_css_class(c)
    b.connect("clicked", lambda *_: action())
    return b


def icon_button(icon, tooltip, action):
    b = Gtk.Button(child=image(icon, 20), tooltip_text=tooltip, valign=Gtk.Align.CENTER)
    b.add_css_class("iconic")
    b.connect("clicked", lambda *_: action())
    return b


def image(name, size):
    """A monoline icon from assets/icons, or the Lethe mark for name 'lethe'."""
    path = os.path.join(ASSETS, "lethe.svg" if name == "lethe" else f"icons/{name}.svg")
    img = Gtk.Image.new_from_file(path)
    img.set_pixel_size(size)
    if name != "lethe":
        img.add_css_class("icon")
    return img


def dot(state="idle"):
    d = Gtk.Box(valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
    d.add_css_class("dot")
    set_state(d, state)
    return d


def set_state(widget, state):
    for c in ("ok", "warn", "bad", "idle"):
        widget.remove_css_class(c)
    widget.add_css_class({"critical": "bad", "warning": "warn"}.get(state, state))


def margins(widget, top=0, bottom=0, start=0, end=0):
    widget.set_margin_top(top)
    widget.set_margin_bottom(bottom)
    widget.set_margin_start(start)
    widget.set_margin_end(end)
    return widget


def clear(container):
    while child := container.get_first_child():
        container.remove(child)


def check_row(check, icon=None, explain=False):
    """A protection layer on one line: icon, name, value, status. Its explanation is spelled out
    underneath when asked for, or when something needs attention."""
    r = box(False, 14, css="row slim", tooltip_text=check.detail)
    r.append(image(icon or check.key, 20))
    text = box(spacing=3, hexpand=True, valign=Gtk.Align.CENTER)
    text.append(label(check.title, "headline"))
    if explain or check.state not in ("ok", "idle"):
        text.append(label(check.detail, "caption", wrap=True, chars=30))
    r.append(text)
    end = box(False, 9, valign=Gtk.Align.CENTER)
    end.append(label(check.value or "", "value"))
    end.append(dot(check.state))
    r.append(end)
    return r


def setting_row(title, detail, control):
    r = box(False, 18, css="row")
    text = box(spacing=4, hexpand=True, valign=Gtk.Align.CENTER)
    text.append(label(title, "headline", wrap=True))
    if detail:
        text.append(label(detail, "caption", wrap=True, chars=48))
    r.append(text)
    control.set_valign(Gtk.Align.CENTER)
    r.append(control)
    return r


def panel(*rows):
    p = box(css="panel")
    for r in rows:
        p.append(r)
    return p


class Column(Gtk.Widget):
    """Centres a vertical stack of content and caps its width at `max_width`.

    Unlike margins, the cap adds nothing to the minimum size, so the window can
    always be made as narrow as the content itself allows.
    """
    H, V = Gtk.Orientation.HORIZONTAL, Gtk.Orientation.VERTICAL

    def __init__(self, max_width, spacing=0, **props):
        super().__init__(**props)
        self.max_width = max_width
        self.inner = box(spacing=spacing)
        self.inner.set_parent(self)

    def add(self, widget):
        self.inner.append(widget)
        return widget

    @staticmethod
    def _pad(width):
        return 48 if width > 760 else 22

    def _inner_width(self, width):
        least = self.inner.measure(self.H, -1)[0]
        return max(least, min(self.max_width, width - 2 * self._pad(width)))

    def do_get_request_mode(self):
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def do_measure(self, orientation, for_size):
        if orientation == self.H:
            least, natural = self.inner.measure(self.H, -1)[:2]
            return least + 2 * 22, min(natural, self.max_width) + 2 * 48, -1, -1
        least, natural = self.inner.measure(self.V, self._inner_width(for_size) if for_size >= 0 else -1)[:2]
        return least, natural, -1, -1

    def do_size_allocate(self, width, height, baseline):
        w = self._inner_width(width)
        self.inner.allocate(w, height, baseline, Gsk.Transform().translate(Graphene.Point().init((width - w) // 2, 0)))

    def do_dispose(self):
        self.inner.unparent()


# ── the VM's screen ──────────────────────────────────────────────────────────

class Display(Gtk.Widget):
    """Draws the VM's screen and turns local input into guest input.

    Frames come from rfb.Screen with the list of rectangles that changed. On GTK
    4.16+ only those rectangles are uploaded to the graphics card; the picture is
    drawn pixel for pixel when its size matches the widget (the usual case, since
    Tails follows the window size), and with a cheap linear filter otherwise.
    """

    def __init__(self):
        super().__init__(focusable=True, hexpand=True, vexpand=True)
        self.add_css_class("vm")
        self.texture = self.control = None
        self.on_paste = self.on_fullscreen = lambda: None
        self.translator, self.scroll = keys.Translator(), 0.0
        self.hidden = Gdk.Cursor.new_from_name("none")       # until the VM hands us its pointer image
        self.set_cursor(self.hidden)
        self.shown = 0                                       # frames drawn, for measuring
        k = Gtk.EventControllerKey()
        k.connect("key-pressed", self._key, True)
        k.connect("key-released", self._key, False)
        m = Gtk.EventControllerMotion()
        m.connect("motion", lambda _c, x, y: self._move(x, y))
        c = Gtk.GestureClick(button=0)
        c.connect("pressed", lambda g, _n, x, y: self._click(g, x, y, True))
        c.connect("released", lambda g, _n, x, y: self._click(g, x, y, False))
        s = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        s.connect("scroll", self._scroll)
        f = Gtk.EventControllerFocus()
        f.connect("leave", lambda *_: self.release())
        for ctl in (k, m, c, s, f):
            self.add_controller(ctl)

    def update(self, frame):
        data = GLib.Bytes.new(frame.pixels)
        if PARTIAL_UPLOADS:
            b = Gdk.MemoryTextureBuilder.new()
            b.set_bytes(data)
            b.set_width(frame.width)
            b.set_height(frame.height)
            b.set_stride(frame.width * 4)
            b.set_format(PIXEL_FORMAT)
            if self.texture and not frame.resized and frame.damage:
                b.set_update_texture(self.texture)
                b.set_update_region(cairo.Region([cairo.RectangleInt(*r) for r in frame.damage]))
            self.texture = b.build()
        else:
            self.texture = Gdk.MemoryTexture.new(frame.width, frame.height, PIXEL_FORMAT, data, frame.width * 4)
        self.shown += 1
        self.queue_draw()

    def clear(self):
        self.texture = None
        self.set_cursor(self.hidden)
        self.queue_draw()

    def show_pointer(self, w, h, hot_x, hot_y, image_bytes):
        """Draw the guest's pointer ourselves: it then follows the hand with no round trip through the VM."""
        if w and h:
            tex = Gdk.MemoryTexture.new(w, h, Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED, GLib.Bytes.new(image_bytes), w * 4)
            self.set_cursor(Gdk.Cursor.new_from_texture(tex, hot_x, hot_y, self.hidden))

    def device_scale(self):
        """Screen pixels per GTK unit: 1.25 on a screen scaled to 125%, 2 on a 200% one."""
        surface = self.get_native() and self.get_native().get_surface()
        if surface and hasattr(surface, "get_scale"):                 # fractional, GTK 4.12+
            return surface.get_scale() or 1.0
        return float(self.get_scale_factor() or 1)

    def _rect(self):
        """Where the guest screen sits, in GTK units: one guest pixel per screen pixel when it fits
        (Tails runs at the screen's real resolution), else scaled to fit; always centred."""
        s = self.device_scale()
        w, h = self.get_width(), self.get_height()
        tw, th = self.texture.get_width(), self.texture.get_height()
        exact = tw / s <= w + 0.5 and th / s <= h + 0.5 and w - tw / s < 8 and h - th / s < 8
        scale = 1 / s if exact else min(w / tw, h / th)
        dw, dh = tw * scale, th * scale
        snap = lambda v: round(v * s) / s                             # on the screen's pixel grid
        return snap((w - dw) / 2), snap((h - dh) / 2), dw, dh

    def do_snapshot(self, snap):
        if not self.texture:
            return
        x, y, w, h = self._rect()
        rect = Graphene.Rect().init(x, y, w, h)
        s = self.device_scale()
        if abs(w * s - self.texture.get_width()) < 0.01 and abs(h * s - self.texture.get_height()) < 0.01:
            snap.append_texture(self.texture, rect)                   # 1:1 on the screen, no filtering at all
        elif hasattr(snap, "append_scaled_texture"):
            snap.append_scaled_texture(self.texture, Gsk.ScalingFilter.LINEAR, rect)
        else:
            snap.append_texture(self.texture, rect)

    def _key(self, _ctl, keyval, keycode, state, down):
        both = Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK
        if down and keyval in (Gdk.KEY_v, Gdk.KEY_V) and state & both == both:
            self.on_paste()                                  # Ctrl+Alt+V: type this computer's text
            return True
        if down and keyval in (Gdk.KEY_f, Gdk.KEY_F) and state & both == both:
            self.on_fullscreen()                             # Ctrl+Alt+F: full screen and back
            return True
        if self.control:
            name = Gdk.keyval_name(keyval) or ""
            if down:
                code = Gdk.keyval_to_unicode(keyval)
                self.control.keys(self.translator.press(keycode, name, chr(code) if code else ""))
            else:
                self.control.keys(self.translator.release(keycode, name))
        return True

    def _move(self, x, y):
        if self.control and self.texture:
            ox, oy, w, h = self._rect()
            self.control.move((x - ox) / w, (y - oy) / h)

    def _click(self, gesture, x, y, down):
        self.grab_focus()
        name = {1: "left", 2: "middle", 3: "right"}.get(gesture.get_current_button())
        if self.control and name:
            self._move(x, y)
            self.control.button(name, down)

    def _scroll(self, _ctl, _dx, dy):
        self.scroll += dy
        while self.control and abs(self.scroll) >= 1:
            name = "wheel-down" if self.scroll > 0 else "wheel-up"
            self.control.button(name, True)
            self.control.button(name, False)
            self.scroll -= 1 if self.scroll > 0 else -1
        return True

    def release(self):
        if self.control:
            self.control.keys(self.translator.release_all())


class Meter:
    """Counts events per second; reports through `log` every few seconds when debugging."""

    def __init__(self, name, every=3.0):
        self.name, self.every, self.t0, self.counts = name, every, time.monotonic(), {}

    def tick(self, **values):
        now = time.monotonic()
        if now - self.t0 >= self.every:
            rates = " ".join(f"{k}={(v - self.counts.get(k, 0)) / (now - self.t0):.1f}/s" for k, v in values.items())
            log(self.name, rates)
            self.t0, self.counts = now, dict(values)
