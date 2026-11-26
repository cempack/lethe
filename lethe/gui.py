"""The Lethe window: home, preferences, launch, the live session, and its destruction.

Design: monochrome. A near-black canvas, white type set in Inter, one white pill
for the main action, colour only where it carries meaning (a status dot). The
content is a single centred column and a tile grid that reflows with the window.
"""
import ctypes, ctypes.util, os, subprocess, sys, threading, time

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "assets")
try:    # make the bundled typeface available to this process only, before GTK starts
    _fc = ctypes.CDLL(ctypes.util.find_library("fontconfig") or "libfontconfig.so.1")
    _fc.FcConfigAppFontAddFile(None, os.path.join(ASSETS, "Inter.ttf").encode())
except OSError:
    pass

import gi
for _lib, _ver in (("Gtk", "4.0"), ("Gdk", "4.0"), ("Gsk", "4.0"), ("Graphene", "1.0")):
    gi.require_version(_lib, _ver)
from gi.repository import Gdk, GLib, Graphene, Gsk, Gtk, Pango

from . import core, keys, pilot, rfb, sentinel

APP_ID = "org.lethe.App"
INSTALLED = os.path.exists("/etc/systemd/system/lethe-vpn.service")
COLUMN = 720      # widest the content column gets
BAR = 41          # height of the session bar

CSS = """
window.lethe { background: #0a0a0b; color: #f4f4f5; font-family: Inter, "SF Pro Text", "Helvetica Neue", sans-serif; font-size: 13.5px; }
headerbar { background: #0a0a0b; border: none; box-shadow: none; min-height: 34px; }
.brand { font-size: 15px; font-weight: 600; letter-spacing: -0.2px; }
.hero { font-size: 44px; font-weight: 600; letter-spacing: -1.6px; }
.compact .hero { font-size: 30px; letter-spacing: -0.9px; }
.title { font-size: 28px; font-weight: 600; letter-spacing: -0.8px; }
.body { font-weight: 500; }
.secondary { color: rgba(244,244,245,0.56); }
.tertiary { color: rgba(244,244,245,0.36); font-size: 12.5px; }
.micro { font-size: 10.5px; font-weight: 600; letter-spacing: 1.3px; color: rgba(244,244,245,0.44); }
.critical { color: #f2555a; }
.mono { font-family: "SF Mono", "JetBrains Mono", "DejaVu Sans Mono", monospace; font-feature-settings: "tnum"; font-size: 12.5px; }

.tile { background: rgba(255,255,255,0.035); border: 1px solid rgba(255,255,255,0.08); border-radius: 14px; padding: 14px 16px; }
flowbox, flowboxchild { background: none; padding: 0; border: none; outline: none; }
.line { padding: 15px 2px; border-bottom: 1px solid rgba(255,255,255,0.08); }
.rule { border-bottom: 1px solid rgba(255,255,255,0.08); }

.dot { min-width: 7px; min-height: 7px; border-radius: 99px; }
.dot.ok { background: #3ecf8e; }
.dot.warn { background: #f5a524; }
.dot.bad { background: #f2555a; }
.dot.idle { background: rgba(255,255,255,0.24); }

button { background-image: none; box-shadow: none; text-shadow: none; border: none; transition: all 140ms ease; }
button.primary { background: #f4f4f5; color: #0a0a0b; font-weight: 600; font-size: 14.5px; border-radius: 999px; padding: 12px 30px; }
button.primary:hover { background: #ffffff; }
button.primary:active { background: #d4d4d8; }
button.primary:disabled { background: rgba(255,255,255,0.08); color: rgba(244,244,245,0.30); }
button.outline { background: none; color: #f4f4f5; font-weight: 500; font-size: 13px; border-radius: 999px; padding: 6px 15px;
                 border: 1px solid rgba(255,255,255,0.16); }
button.outline:hover { background: rgba(255,255,255,0.07); border-color: rgba(255,255,255,0.28); }
button.outline.end:hover { background: #e5484d; border-color: #e5484d; color: #ffffff; }
button.symbol { background: none; color: rgba(244,244,245,0.56); border-radius: 999px; padding: 7px; }
button.symbol:hover { background: rgba(255,255,255,0.08); color: #ffffff; }

switch { min-width: 40px; min-height: 22px; border-radius: 999px; background: rgba(255,255,255,0.14); border: none; padding: 2px; }
switch:checked { background: #f4f4f5; }
switch slider { min-width: 18px; min-height: 18px; border-radius: 999px; background: #f4f4f5; border: none; box-shadow: none; }
switch:checked slider { background: #0a0a0b; }
switch image { opacity: 0; }
progressbar trough { background: rgba(255,255,255,0.10); border-radius: 99px; min-height: 2px; border: none; }
progressbar progress { background: #f4f4f5; border-radius: 99px; min-height: 2px; border: none; }

.bar { background: #0a0a0b; border-bottom: 1px solid rgba(255,255,255,0.08); padding: 5px 12px; }
.banner { background: #2a1f0a; color: #f5c877; padding: 8px 14px; font-size: 12.5px; }
.vm, .curtain { background: #000000; }
scrollbar { background: none; border: none; }
"""


def label(text, css="", xalign=0.0, wrap=False):
    w = Gtk.Label(label=text, xalign=xalign, wrap=wrap)
    if wrap:
        w.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        w.set_max_width_chars(22)         # may shrink, within reason: the column decides the width
        w.set_hexpand(True)
        if xalign == 0.5:
            w.set_justify(Gtk.Justification.CENTER)
    for c in css.split():
        w.add_css_class(c)
    return w


def box(vertical=True, spacing=0, css="", **props):
    b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL, spacing=spacing, **props)
    for c in css.split():
        b.add_css_class(c)
    return b


def button(text, css, action):
    b = Gtk.Button(label=text, valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
    for c in css.split():
        b.add_css_class(c)
    b.connect("clicked", lambda *_: action())
    return b


def logo(size):
    img = Gtk.Image.new_from_file(os.path.join(ASSETS, "lethe.svg"))
    img.set_pixel_size(size)
    img.set_halign(Gtk.Align.CENTER)
    return img


def dot(state):
    d = Gtk.Box(valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
    d.add_css_class("dot")
    d.add_css_class({"critical": "bad", "warning": "warn"}.get(state, state))
    return d


def spaced(widget, top=0, bottom=0):
    widget.set_margin_top(top)
    widget.set_margin_bottom(bottom)
    return widget


def tile(state, name, text):
    """One cell of the status grid: a small caps label with a status dot, and what it means."""
    t = box(spacing=7, css="tile")
    head = box(False, 8)
    head.append(dot(state))
    head.append(label(name.upper(), "micro"))
    t.append(head)
    t.append(label(text, "secondary", wrap=True))
    return t


def line(title, detail="", trailing=None):
    """One row of preferences: title, explanation, control. Separated by a hairline."""
    r = box(False, 16, css="line")
    text = box(spacing=3, hexpand=True, valign=Gtk.Align.CENTER)
    text.append(label(title, "body", wrap=True))
    if detail:
        text.append(label(detail, "secondary", wrap=True))
    r.append(text)
    if trailing:
        trailing.set_valign(Gtk.Align.CENTER)
        r.append(trailing)
    return r


def clear(container):
    while container.get_first_child():
        container.remove(container.get_first_child())


def log(*what):
    if os.environ.get("LETHE_DEBUG"):
        print("lethe:", *what, file=sys.stderr, flush=True)


def ui(fn, *args):
    """Run `fn` on the GTK thread."""
    GLib.idle_add(lambda: fn(*args) and False)


class Display(Gtk.Widget):
    """Draws the VM's screen and turns local input into guest input."""

    def __init__(self):
        super().__init__(focusable=True, hexpand=True, vexpand=True)
        self.add_css_class("vm")
        self.texture = self.control = None
        self.translator, self.scroll = keys.Translator(), 0.0
        self.hidden = Gdk.Cursor.new_from_name("none")       # until the VM hands us its pointer image
        self.set_cursor(self.hidden)
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

    def show_frame(self, w, h, pixels):
        self.texture = Gdk.MemoryTexture.new(w, h, Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED, GLib.Bytes.new(pixels), w * 4)
        self.queue_draw()

    def show_pointer(self, w, h, hot_x, hot_y, image):
        """Draw the guest's pointer ourselves: it then follows the hand with no round trip through the VM."""
        if w and h:
            tex = Gdk.MemoryTexture.new(w, h, Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED, GLib.Bytes.new(image), w * 4)
            self.set_cursor(Gdk.Cursor.new_from_texture(tex, hot_x, hot_y, self.hidden))

    def _rect(self):
        """Where the guest screen sits inside the widget: 1:1 when it fits, scaled down otherwise, centred."""
        w, h, tw, th = self.get_width(), self.get_height(), self.texture.get_width(), self.texture.get_height()
        scale = min(w / tw, h / th, 1.0) if abs(w - tw) < 3 and abs(h - th) < 3 else min(w / tw, h / th)
        return round((w - tw * scale) / 2), round((h - th * scale) / 2), tw * scale, th * scale

    def do_snapshot(self, snap):
        if self.texture:
            rect = Graphene.Rect().init(*self._rect())
            if hasattr(snap, "append_scaled_texture"):
                snap.append_scaled_texture(self.texture, Gsk.ScalingFilter.TRILINEAR, rect)
            else:
                snap.append_texture(self.texture, rect)

    def _key(self, _ctl, keyval, keycode, _state, down):
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


STEPS = [("update", "Fetching the latest Tails"), ("integrity", "Verifying the Tails signature"),
         ("sandbox", "Building the sandbox"), ("network", "Opening the protected network"),
         ("boot", "Starting Tails"), ("welcome", "Passing the Welcome Screen"), ("hardening", "Hardening Tails")]


class Window(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Lethe", default_width=980, default_height=760)
        self.add_css_class("lethe")
        self.cfg = core.settings()
        self.session = self.screen = self.control = self.watch = None
        self.serial, self.pointer, self.threat, self.latest = -1, None, None, None
        self.width, self.columns, self.vm_size, self.vm_size_at = 0, [], None, 0
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=200)
        self.set_child(self.stack)
        for name, page in (("home", self._home()), ("prefs", self._prefs()), ("launch", self._launch()),
                           ("live", self._live()), ("end", self._end())):
            self.stack.add_named(page, name)
        self.connect("close-request", self._closing)
        self.add_tick_callback(self._frame)                 # once per display refresh
        GLib.timeout_add_seconds(1, self._tick)
        self.refresh()
        threading.Thread(target=self._check_latest, daemon=True).start()
        self.autostart = bool(os.environ.pop("LETHE_AUTOSTART", None))    # `lethe start`

    def _page(self, centered=False):
        """A scrolling page holding one centred column that never exceeds COLUMN px."""
        col = box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER if centered else Gtk.Align.START,
                  margin_top=22, margin_bottom=30)
        self.columns.append(col)
        return Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, child=col), col

    def _grid(self):
        return Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, column_spacing=10, row_spacing=10,
                           min_children_per_line=1, max_children_per_line=3, activate_on_single_click=False)

    def _fill(self, grid, tiles):
        clear(grid)
        for t in tiles:
            grid.append(tile(*t))
            grid.get_last_child().set_focusable(False)

    # ── home ────────────────────────────────────────────────────────────────
    def _home(self):
        page, col = self._page()
        top = box(False, 9)
        top.append(logo(24))
        top.append(label("Lethe", "brand"))
        top.append(Gtk.Box(hexpand=True))
        top.append(button("Preferences", "outline", lambda: self.stack.set_visible_child_name("prefs")))
        col.append(top)

        col.append(spaced(label("Leave no memory.", "hero", wrap=True), top=64))
        status = box(False, 9, margin_top=14)
        self.status_dot = dot("idle")
        status.append(self.status_dot)
        self.subline = label("", "secondary", wrap=True)
        status.append(self.subline)
        col.append(status)
        self.start = button("Start Session", "primary", self.launch)
        self.start.set_halign(Gtk.Align.START)
        col.append(spaced(self.start, top=30))
        col.append(spaced(label("A sealed, amnesic Tails session. Ending it erases it from memory.", "tertiary", wrap=True), top=14))

        col.append(spaced(label("PROTECTION", "micro"), top=58, bottom=12))
        self.tiles = self._grid()
        col.append(self.tiles)
        return page

    # ── preferences ─────────────────────────────────────────────────────────
    def _prefs(self):
        page, col = self._page()
        top = box(False, 10)
        top.append(button("Back", "outline", self._home_again))
        top.append(Gtk.Box(hexpand=True))
        col.append(top)
        col.append(spaced(label("Preferences", "title"), top=34))

        col.append(spaced(label("VPN", "micro"), top=38))
        col.append(Gtk.Box(css_classes=["rule"], margin_top=10))
        self.vpn_switch = Gtk.Switch()
        self.vpn_switch.connect("notify::active", self._vpn_toggled)
        col.append(line("Route the session through WireGuard",
                        "Recommended. Your internet provider then sees a VPN instead of Tor, and the VPN only ever sees "
                        "Tor. The tunnel is the VM's only route: if it drops, nothing leaves. The rest of this computer "
                        "is not affected.", self.vpn_switch))
        actions = box(False, 8)
        self.vpn_remove = button("Remove", "outline", lambda: self._vpn_helper(["remove"], None))
        actions.append(self.vpn_remove)
        actions.append(button("Import…", "outline", self._vpn_import))
        vpn_line = line("Profile", "None", actions)
        self.vpn_state = vpn_line.get_first_child().get_last_child()
        col.append(vpn_line)

        col.append(spaced(label("SENTINEL", "micro"), top=38))
        col.append(Gtk.Box(css_classes=["rule"], margin_top=10))
        self.sentinel_switch = Gtk.Switch(active=self.cfg["sentinel"])
        self.sentinel_switch.connect("notify::active", lambda s, _p: self._set("sentinel", s.get_active()))
        col.append(line("Watch this computer during sessions",
                        "Destroys the session at once if a debugger attaches to it, someone logs in remotely, or a new "
                        "keyboard is connected. A tripwire, not an antivirus: it cannot see malware that already "
                        "controls the system.", self.sentinel_switch))

        col.append(spaced(label("SESSION", "micro"), top=38))
        col.append(Gtk.Box(css_classes=["rule"], margin_top=10))
        for key, title, hint in (
                ("skip_welcome", "Skip the Welcome Screen", "Starts in English with a US keyboard, like most Tails users. "
                                                            "Your own keyboard layout is translated as you type."),
                ("harden_guest", "Harden and restyle Tails", "Stricter privacy settings, Tor Browser at Safest, and the Lethe appearance.")):
            sw = Gtk.Switch(active=self.cfg[key])
            sw.connect("notify::active", lambda s, _p, k=key: self._set(k, s.get_active()))
            col.append(line(title, hint, sw))
        return page

    def _set(self, key, value):
        if self.cfg.get(key) != value:
            self.cfg[key] = value
            core.save_settings(self.cfg)
            self.refresh()

    def refresh(self):
        """Re-run the checks off the UI thread, then redraw."""
        cfg = dict(self.cfg)

        def work():
            rows = core.audit(cfg)
            found = sentinel.preflight() if cfg["sentinel"] else []
            ui(self._show_status, rows, found)

        threading.Thread(target=work, daemon=True).start()

    def _show_status(self, rows, found):
        if not self.cfg["sentinel"]:
            guard = ("idle", "Sentinel", "Off. Sessions are not watched.")
        elif found:
            guard = (found[0][0], "Sentinel", f"{found[0][1]}. {found[0][2]}")
        else:
            guard = ("ok", "Sentinel", "Armed. No threats found on this computer.")
        self._fill(self.tiles, [r for r in rows if r[1] != "Components" or r[0] != "ok"] + [guard])
        bad = [r for r in rows if r[0] == "bad"] + [f for f in found if f[0] == "critical"]
        weak = [r for r in rows if r[0] == "warn"] + [f for f in found if f[0] == "warning"]
        version, profile = core.current_version(), core.vpn_profile()
        for c in ("ok", "warn", "bad", "idle"):
            self.status_dot.remove_css_class(c)
        self.subline.remove_css_class("critical")
        if bad:
            self.status_dot.add_css_class("bad")
            self.subline.add_css_class("critical")
            self.subline.set_label(f"{bad[0][1]}: {bad[0][2]}")
        elif not core.current_iso():
            self.status_dot.add_css_class("idle")
            self.subline.set_label("Tails will be downloaded and verified first (1.9 GB).")
        else:
            self.status_dot.add_css_class("warn" if weak else "ok")
            new = f"  ·  {self.latest} installs at next start" if self.latest and self.latest != version else ""
            self.subline.set_label(("Protected" if not weak else "Ready, with reduced protection")
                                   + f"  ·  Tails {version} verified{new}")
        self.start.set_sensitive(not bad)
        self.start.set_label("Start Session" if core.current_iso() else "Download Tails and Start")
        self.vpn_state.set_label(profile or ("None" if INSTALLED else "Run the installer to enable the VPN."))
        self.vpn_remove.set_visible(bool(profile))
        self.vpn_switch.set_sensitive(bool(profile))
        self.vpn_switch.set_active(bool(self.cfg["vpn"] and profile))

    def _check_latest(self):
        try:
            self.latest = core.latest(10)[0]
            self.refresh()
        except Exception:
            pass

    # ── VPN ─────────────────────────────────────────────────────────────────
    def _vpn_toggled(self, sw, _p):
        if core.vpn_profile():
            self._set("vpn", sw.get_active())

    def _vpn_import(self):
        if not INSTALLED:
            return self.vpn_state.set_label("Run the installer first: the VPN needs its system service.")
        chooser = Gtk.FileChooserNative(title="Import a WireGuard Profile", transient_for=self, action=Gtk.FileChooserAction.OPEN)
        flt = Gtk.FileFilter()
        flt.set_name("WireGuard profiles (*.conf)")
        flt.add_pattern("*.conf")
        chooser.add_filter(flt)

        def chosen(dialog, response):
            if response == Gtk.ResponseType.ACCEPT:
                path = dialog.get_file().get_path()
                try:
                    with open(path, "rb") as f:
                        data = f.read(65537)          # read as the user; root only ever receives the bytes
                except OSError as e:
                    return self.vpn_state.set_label(f"Could not read the file: {e.strerror}")
                self._vpn_helper(["import", os.path.splitext(os.path.basename(path))[0]], data)
            self._chooser = None

        chooser.connect("response", chosen)
        self._chooser = chooser
        chooser.show()

    def _vpn_helper(self, args, data):
        self.vpn_state.set_label("Waiting for authorisation…")

        def work():
            r = subprocess.run(["pkexec", sys.executable, "-I", os.path.join(core.LIB, "lethe", "vpn.py"), *args],
                               input=data, capture_output=True)
            err = r.stderr.decode(errors="replace").strip().splitlines()
            if r.returncode == 0:
                self.cfg["vpn"] = args[0] == "import"
                core.save_settings(self.cfg)
                self.refresh()
            else:
                ui(self.vpn_state.set_label, err[-1].replace("lethe-vpn: ", "").capitalize() if err else "Cancelled")

        threading.Thread(target=work, daemon=True).start()

    # ── launch ──────────────────────────────────────────────────────────────
    def _launch(self):
        page, col = self._page(centered=True)
        col.append(logo(60))
        col.append(spaced(label("Starting session", "title", 0.5, wrap=True), top=22))
        self.status = label("", "secondary", 0.5, wrap=True)
        col.append(spaced(self.status, top=8))
        self.progress = Gtk.ProgressBar(margin_top=28, margin_start=90, margin_end=90)
        col.append(self.progress)
        self.launch_hint = label("", "tertiary", 0.5, wrap=True)
        col.append(spaced(self.launch_hint, top=14))
        col.append(spaced(button("Cancel", "outline", lambda: self.destroy_session("You cancelled the launch")), top=30))
        return page

    def step(self, key):
        log("step", key)
        self.status.set_label(dict(STEPS)[key] + "…")
        if key != "update" and key in self.plan:
            self.progress.set_fraction((self.plan.index(key) + 0.5) / len(self.plan))

    def launch(self):
        self.cfg = core.settings()
        self.threat = None
        outdated = not core.current_iso() or (self.latest and self.latest != core.current_version())
        self.plan = [k for k, _ in STEPS if not (
            (k == "update" and not outdated) or (k == "welcome" and not self.cfg["skip_welcome"])
            or (k == "hardening" and not (self.cfg["skip_welcome"] and self.cfg["harden_guest"])))]
        self.launch_hint.set_label("About a minute." if core.has_kvm() else
                                   "This computer has no hardware virtualisation, so this takes several minutes.")
        self.progress.set_fraction(0)
        self.step(self.plan[0])
        self.stack.set_visible_child_name("launch")
        # Tails starts at the size of the area it will be shown in.
        self.vm_size = self._fit(self.get_width(), self.get_height() - BAR)
        threading.Thread(target=self._run, args=({**self.cfg, "width": self.vm_size[0], "height": self.vm_size[1]},),
                         daemon=True).start()

    @staticmethod
    def _fit(w, h):
        """A resolution for the VM: the display area, kept even and within sane bounds."""
        return max(800, min(3840, int(w))) & ~1, max(600, min(2160, int(h))) & ~1

    def _run(self, cfg):
        """The whole life of one session, on a worker thread."""
        error, wiped = None, 0
        try:
            if "update" in self.plan:
                def progress(text, fraction):
                    ui(self.status.set_label, text + "…")
                    ui(self.progress.set_fraction, fraction or 0.0)
                try:
                    core.update(progress)
                except core.LetheError:
                    if not core.current_iso():
                        raise                              # offline with an older image: carry on with it
            self.session = core.Session(cfg, stage=lambda name: ui(self.step, name))
            vpn = self.session.start()
            self.screen = rfb.Screen(self.session.vnc_path)
            self.screen.start()
            self.control = rfb.Control(self.session.qmp_path)
            if cfg["sentinel"]:
                self.watch = sentinel.Sentinel(self.session.vm.pid, self._alarm)
                self.watch.start()
            if cfg["skip_welcome"]:
                def report(state):
                    if state in ("welcome", "hardening"):
                        ui(self.step, state)
                    elif state in ("ready", "manual"):
                        ui(self._go_live, vpn, state == "manual")
                pilot.Pilot(self.screen, self.control, self.session, cfg["harden_guest"], report).start()
            else:
                ui(self._go_live, vpn, False)
            self.session.vm.wait()
        except core.LetheError as e:
            error = str(e)
        except Exception as e:                             # never leave a half-built session behind
            error = f"Unexpected error: {e}"
        finally:
            ui(self._ending)
            if self.watch:
                self.watch.stop()
            for channel in (self.control, self.screen):
                channel and channel.close()
            session, started = self.session, self.session and self.session.started
            if session:
                wiped = session.finish(lambda f: ui(self.wipe_bar.set_fraction, f))
            why = error or self.threat or (session and session.why)
            self.session = self.screen = self.control = self.watch = None
            ui(self._ended, why, wiped, time.time() - started if started else 0, bool(error), bool(self.threat))

    # ── live session ────────────────────────────────────────────────────────
    def _live(self):
        page = box()
        bar = box(False, 10, css="bar")
        bar.append(logo(18))
        self.clock = label("00:00", "mono secondary")
        bar.append(self.clock)
        self.state_dot = dot("ok")
        self.state_dot.set_margin_start(8)
        bar.append(self.state_dot)
        self.state = label("", "micro")
        self.state.set_ellipsize(Pango.EllipsizeMode.END)
        self.state.set_hexpand(True)
        bar.append(self.state)
        full = Gtk.Button(icon_name="view-fullscreen-symbolic", tooltip_text="Full Screen", valign=Gtk.Align.CENTER)
        full.add_css_class("symbol")
        full.connect("clicked", lambda *_: self.unfullscreen() if self.is_fullscreen() else self.fullscreen())
        bar.append(full)
        bar.append(button("End Session", "outline end", lambda: self.destroy_session("You ended the session")))
        page.append(bar)
        self.alert = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.alert_text = label("", "banner", wrap=True)
        self.alert.set_child(self.alert_text)
        page.append(self.alert)
        self.display = Display()
        overlay = Gtk.Overlay(child=self.display, vexpand=True)
        self.curtain = box(css="curtain", visible=False)
        inner = box(spacing=8, valign=Gtk.Align.CENTER, vexpand=True, margin_start=24, margin_end=24)
        inner.append(logo(52))
        inner.append(spaced(label("Hidden while your screen is captured", "body", 0.5, wrap=True), top=8))
        inner.append(label("The session reappears when the recording or screen share stops.", "secondary", 0.5, wrap=True))
        self.curtain.append(inner)
        overlay.add_overlay(self.curtain)
        page.append(overlay)
        return page

    def _go_live(self, vpn, manual):
        log("live", "manual" if manual else "auto")
        firewalled = vpn or os.path.exists(core.NET_SOCK)
        parts = ["Amnesic", f"VPN {core.vpn_profile()}" if vpn else ("Firewalled" if firewalled else "Not firewalled"),
                 "Sentinel armed" if self.cfg["sentinel"] else "Sentinel off"]
        if not core.has_kvm():
            parts.append("Software emulation")
        self.state.set_label("   ·   ".join(parts).upper())
        for c in ("ok", "warn"):
            self.state_dot.remove_css_class(c)
        self.state_dot.add_css_class("ok" if firewalled and self.cfg["sentinel"] else "warn")
        if manual:
            self._warn("The Welcome Screen could not be passed automatically. Continue by hand: press Start Tails if you see it.")
        self.display.control = self.control
        self.stack.set_visible_child_name("live")
        self.display.grab_focus()

    def _warn(self, text):
        self.alert_text.set_label(text)
        self.alert.set_reveal_child(True)
        GLib.timeout_add_seconds(12, lambda: self.alert.set_reveal_child(False) and False)

    def _alarm(self, severity, title, detail):
        """Called by the Sentinel from its own thread."""
        if severity == "critical":
            self.threat = f"{title}. {detail}"
            self.session and self.session.destroy(self.threat)
        elif severity == "warning":
            ui(self._warn, f"{title}. {detail}")
        else:
            ui(self.curtain.set_visible, severity == "capture")

    def _frame(self, *_):
        """Runs once per display refresh: keeps the layout, the VM's size and its picture in step with the window."""
        width = self.get_width()
        if width != self.width:
            self.width = width
            for col in self.columns:                        # every column stays inside the window
                col.set_size_request(max(260, min(COLUMN, width - 48)), -1)
            (self.add_css_class if width < 620 else self.remove_css_class)("compact")
        if self.autostart and width > 0 and self.subline.get_label():   # window has its real size, checks are in
            self.autostart = False
            if self.start.get_sensitive():
                self.launch()
        screen = self.screen
        if not screen or self.stack.get_visible_child_name() != "live":
            return True
        # Tails follows the window: once a new size has held for a moment, ask the VM to adopt it.
        want = self._fit(self.display.get_width(), self.display.get_height())
        if want != self.vm_size:
            self.vm_size, self.vm_size_at = want, time.monotonic()
        elif self.vm_size_at and time.monotonic() - self.vm_size_at > 0.35:
            self.vm_size_at = 0
            log("resize", want, "resizable" if screen.resizable else "fixed display")
            screen.request_size(*want)
        if screen.serial != self.serial:
            w, h, pixels, self.serial = screen.snapshot()
            if w:
                self.display.show_frame(w, h, pixels)
            if screen.cursor and screen.cursor[0] != self.pointer:
                self.pointer = screen.cursor[0]
                log("pointer", screen.cursor[1:5])
                self.display.show_pointer(*screen.cursor[1:])
        return True

    def _tick(self):
        if self.session and self.session.started:
            t = int(time.time() - self.session.started)
            self.clock.set_label(f"{t // 3600:d}:{t // 60 % 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60:02d}:{t % 60:02d}")
        return True

    def destroy_session(self, why):
        if self.session:
            self.session.destroy(why)

    # ── the end ─────────────────────────────────────────────────────────────
    def _end(self):
        page, col = self._page(centered=True)
        col.append(logo(60))
        self.end_title = label("", "title", 0.5, wrap=True)
        col.append(spaced(self.end_title, top=22))
        self.end_text = label("", "secondary", 0.5, wrap=True)
        col.append(spaced(self.end_text, top=8))
        self.wipe_bar = Gtk.ProgressBar(margin_top=28, margin_start=90, margin_end=90)
        col.append(self.wipe_bar)
        self.facts = self._grid()
        col.append(spaced(self.facts, top=34))
        self.end_button = button("Done", "primary", self._home_again)
        col.append(spaced(self.end_button, top=30))
        return page

    def _ending(self):
        self.display.control = None
        self.display.texture = None
        self.display.set_cursor(self.display.hidden)
        self.pointer = None
        self.curtain.set_visible(False)
        self.alert.set_reveal_child(False)
        if self.is_fullscreen():
            self.unfullscreen()
        self.end_title.remove_css_class("critical")
        self.end_title.set_label("Ending session")
        self.end_text.set_label("Overwriting the session's memory…")
        self.wipe_bar.set_fraction(0)
        for w in (self.facts, self.end_button):
            w.set_visible(False)
        self.wipe_bar.set_visible(True)
        self.stack.set_visible_child_name("end")

    def _ended(self, why, wiped, seconds, failed, threat):
        log("ended", f"why={why!r} wiped={wiped} seconds={seconds:.0f} failed={failed} threat={threat}")
        self.wipe_bar.set_visible(False)
        if threat or failed:
            self.end_title.add_css_class("critical")
            self.end_title.set_label("Threat detected." if threat else "The session could not start.")
            self.end_text.set_label(why + (" The session was destroyed." if threat else ""))
        else:
            self.end_title.set_label("Session destroyed.")
            self.end_text.set_label(f"{why}." if why else "Nothing of it remains.")
        facts = []
        if wiped:
            facts.append(("ok", "Memory", f"{wiped / (1 << 30):.1f} GB overwritten with zeros before release."))
        if wiped or not failed:
            facts.append(("ok", "Disk", "Nothing written: no virtual disk, swap, crash dump or activity log."))
            facts.append(("ok", "Duration", f"{int(seconds) // 60} min {int(seconds) % 60} s. The Tails image was never modified."))
        self._fill(self.facts, facts)
        self.facts.set_visible(bool(facts))
        self.end_button.set_visible(True)

    def _home_again(self):
        self.refresh()
        self.stack.set_visible_child_name("home")

    def _closing(self, *_):
        if self.session:                      # closing the window ends the session
            self.session.destroy("You closed Lethe")
            deadline = time.time() + 8
            while self.session and time.time() < deadline:
                GLib.MainContext.default().iteration(False)
                time.sleep(0.02)
        return False


def main():
    app = Gtk.Application(application_id=APP_ID)

    def activate(app):
        if app.get_active_window():
            return app.get_active_window().present()
        settings = Gtk.Settings.get_default()
        if hasattr(Gtk, "InterfaceColorScheme"):
            settings.set_property("gtk-interface-color-scheme", Gtk.InterfaceColorScheme.DARK)
        else:
            settings.set_property("gtk-application-prefer-dark-theme", True)
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS) if hasattr(provider, "load_from_string") else provider.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(ASSETS)
        Gtk.Window.set_default_icon_name("lethe")
        Window(app).present()

    app.connect("activate", activate)
    return app.run(None)
