"""The Lethe window: home, preferences, launch, the live session, and its end.

Pages are widget trees built once; `refresh` and the session thread only change
their contents. Everything that touches GTK runs on the main thread: worker
threads hand results over with `ui(...)`.
"""
import hashlib, os, subprocess, sys, threading, time, types

from .widgets import (Column, Display, Gtk, GLib, Meter, Pango, box, button, check_row, clear, dot, icon_button,
                      image, label, log, margins, panel, set_state, setting_row, setup_style, tile, ui, NEEDS_ALPHA)
from . import core, dbusdisplay, pilot, rfb, sentinel

APP_ID = "org.lethe.App"
INSTALLED = os.path.exists("/etc/systemd/system/lethe-vpn.service")
NARROW = 760       # below this width the sidebar shows only its icons
BAR = 40           # height of the session bar

PASTE_LIMIT = 2000             # Ctrl+Alt+V types text, for where the clipboard cannot reach
CLIP_LIMIT = 32 << 20          # the largest thing shared with Tails' clipboard

STEPS = [("update", "Fetching the latest Tails"), ("integrity", "Verifying the Tails signature"),
         ("sandbox", "Building the sandbox"), ("network", "Opening the protected network"),
         ("boot", "Starting Tails"), ("welcome", "Passing the Welcome Screen"),
         ("hardening", "Hardening Tails"), ("tor", "Connecting to Tor")]


class Window(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Lethe", default_width=1120, default_height=760)
        self.add_css_class("lethe")
        self.cfg = core.settings()
        self.session = self.screen = self.control = self.watch = None
        self.serial, self.pointer, self.threat, self.latest = 0, None, None, None
        self.width, self.columns, self.vm_size, self.vm_size_at, self.vm_asked, self.vm_retries = 0, [], None, 0, 0, 3
        self.meter = Meter("display")
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=180)
        self.set_child(self.stack)
        for name, page in (("home", self._home()), ("launch", self._launch()),
                           ("live", self._live()), ("end", self._end())):
            self.stack.add_named(page, name)
        self.clip_ready = False
        self._clipboard_watch()
        self.connect("close-request", self._closing)
        self.add_tick_callback(self._frame)                 # once per display refresh
        GLib.timeout_add_seconds(1, self._tick)
        self.autostart = bool(os.environ.pop("LETHE_AUTOSTART", None))     # `lethe start`
        self.refresh()
        threading.Thread(target=self._check_latest, daemon=True).start()

    def _scroller(self, column):
        self.columns.append(column)
        return Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, child=column)

    def show(self, page):
        if page == "home":
            self.refresh()
        self.stack.set_visible_child_name(page)

    # ── home: a sidebar app ─────────────────────────────────────────────────
    SECTIONS = [("overview", "shield", "Overview"), ("network", "network", "Network"),
                ("session", "display", "Session"), ("sentinel", "sentinel", "Sentinel")]

    def _home(self):
        shell = box(False, 0)
        side = self.sidebar = box(css="sidebar")
        head = box(False, 9, css="sidebar-head")
        head.append(image("lethe", 22))
        self.side_labels = [head.append(label("Lethe", "wordmark")) or head.get_last_child()]
        side.append(head)

        self.nav = Gtk.ListBox(css_classes=["nav"], selection_mode=Gtk.SelectionMode.BROWSE)
        for key, icon, text in self.SECTIONS:
            row = box(False, 10, css="nav-item")
            row.append(image(icon, 17))
            name = label(text)
            self.side_labels.append(name)
            row.append(name)
            item = Gtk.ListBoxRow(child=row, name=key, tooltip_text=text)
            self.nav.append(item)
        self.nav.connect("row-selected", lambda _l, row: row and self.sections.set_visible_child_name(row.get_name()))
        side.append(self.nav)
        side.append(Gtk.Box(vexpand=True))

        foot = box(False, 9, css="sidebar-foot")
        self.status_dot = dot()
        foot.append(self.status_dot)
        status = box(spacing=1)
        self.status = label("Checking…", "foot-title")
        self.status.set_ellipsize(Pango.EllipsizeMode.END)
        self.version = label("", "foot-caption")
        status.append(self.status)
        status.append(self.version)
        self.side_labels.append(status)
        foot.append(status)
        side.append(foot)
        shell.append(side)

        self.sections = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=120,
                                  hexpand=True, css_classes=["content"])
        self.sections.add_named(self._overview(), "overview")
        for key, build in (("network", self._network), ("session", self._session_prefs),
                           ("sentinel", self._sentinel_prefs)):
            self.sections.add_named(build(), key)
        shell.append(self.sections)
        self.nav.select_row(self.nav.get_row_at_index(0))
        return shell

    def _section(self, title, caption=None):
        col = Column(760)
        col.add(margins(label(title, "section-title"), top=30))
        if caption:
            col.add(margins(label(caption, "secondary", wrap=True, chars=60), top=4))
        return col

    def _group(self, col, title, *rows):
        if title:
            col.add(margins(label(title, "group-title"), top=26, bottom=8, start=2))
        col.add(margins(panel(*rows), top=0 if title else 22))

    def _overview(self):
        col = self._section("Overview")
        card = box(False, 16, css="panel session-card", margin_top=20)
        card.append(margins(image("lethe", 48), end=2))
        text = box(spacing=3, hexpand=True, valign=Gtk.Align.CENTER)
        text.append(label("Private Session", "card-title"))
        self.card_caption = label("Tails in a sealed machine with no disk. Nothing remains when it ends.",
                                  "caption", wrap=True, chars=36)
        text.append(self.card_caption)
        card.append(text)
        self.start = button("Start Session", "primary", self.launch)
        card.append(self.start)
        col.add(card)
        self.problem = label("", "caption", wrap=True, chars=44)
        col.add(margins(self.problem, top=12, start=2))

        head = box(False, 8, margin_top=28, margin_bottom=10, margin_start=2, margin_end=2)
        title = label("Protection", "group-title")
        title.set_hexpand(True)
        head.append(title)
        self.score = label("", "foot-caption")
        head.append(self.score)
        col.add(head)
        self.checks = Gtk.Grid(column_spacing=10, row_spacing=10, column_homogeneous=True, row_homogeneous=True)
        self.tiles, self.tile_cols = [], 0
        col.add(self.checks)
        col.add(margins(Gtk.Box(), bottom=36))
        return self._scroller(col)

    def _network(self):
        col = self._section("Network", "How the session reaches the internet.")
        self.vpn_switch = Gtk.Switch()
        self.vpn_switch.connect("notify::active", self._vpn_toggled)
        vpn_actions = box(False, 8)
        self.vpn_remove = button("Remove", "quiet", lambda: self._vpn_helper(["remove"], None))
        vpn_actions.append(self.vpn_remove)
        vpn_actions.append(button("Import…", "quiet", self._vpn_import))
        profile_row = setting_row("WireGuard profile", "None", vpn_actions)
        self.vpn_state = profile_row.get_first_child().get_last_child()
        self._group(col, "Tor",
                    setting_row("Connect to Tor automatically",
                                "Skips the Tor Connection screen. Your network can see that you use Tor, unless "
                                "the VPN is on. Turn this off to use bridges.", self._switch("auto_tor")))
        self._group(col, "VPN",
                    setting_row("Route the session through a VPN",
                                "Recommended. Your provider sees a VPN instead of Tor, and the VPN only ever sees "
                                "Tor. The tunnel is the session's only route: if it drops, nothing leaves.",
                                self.vpn_switch),
                    profile_row)
        col.add(margins(Gtk.Box(), bottom=36))
        return self._scroller(col)

    def _session_prefs(self):
        col = self._section("Session", "What happens when Tails starts.")
        self._group(col, None,
                    setting_row("Skip the Welcome Screen",
                                "Starts in English with a US keyboard, like most Tails users. Your own keyboard "
                                "layout is translated as you type.", self._switch("skip_welcome")),
                    setting_row("Harden and restyle Tails",
                                "Stricter privacy settings, Tor Browser at its Safest level, and the Lethe desktop: "
                                "dock, menu bar and icons.", self._switch("harden_guest")),
                    setting_row("Share your clipboard with Tails",
                                "Text and images you copy on this computer are ready to paste in Tails when you come "
                                "back to the session. One way only: nothing copied in Tails ever leaves it.",
                                self._switch("clipboard")))
        col.add(margins(Gtk.Box(), bottom=36))
        return self._scroller(col)

    def _sentinel_prefs(self):
        col = self._section("Sentinel", "A tripwire on this computer while a session runs.")
        self._group(col, None,
                    setting_row("Watch this computer during sessions",
                                "Destroys the session at once if a debugger attaches to it, someone logs in remotely, "
                                "or a new keyboard is plugged in. Not an antivirus: it cannot see malware that "
                                "already controls the system.", self._switch("sentinel")))
        self.findings = box(css="panel divided", margin_top=26)
        col.add(self.findings)
        col.add(margins(Gtk.Box(), bottom=36))
        return self._scroller(col)

    def _switch(self, key):
        sw = Gtk.Switch(active=self.cfg[key])
        sw.connect("notify::active", lambda s, _p: self._set(key, s.get_active()))
        return sw

    def _set(self, key, value):
        if self.cfg.get(key) != value:
            self.cfg[key] = value
            core.save_settings(self.cfg)
            self.refresh()

    # ── state ───────────────────────────────────────────────────────────────
    def refresh(self):
        """Re-run the checks off the main thread, then redraw what depends on them."""
        cfg = dict(self.cfg)

        def work():
            checks = core.audit(cfg)
            found = sentinel.preflight() if cfg["sentinel"] else []
            ui(self._show_status, checks, found)

        threading.Thread(target=work, daemon=True).start()

    def _show_status(self, checks, found):
        if not self.cfg["sentinel"]:
            guard = core.Check("sentinel", "idle", "Sentinel", "Off", "Sessions are not watched.")
        elif found:
            guard = core.Check("sentinel", found[0][0], "Sentinel", "Alert", f"{found[0][1]}. {found[0][2]}")
        else:
            guard = core.Check("sentinel", "ok", "Sentinel", "Armed", "Watching this computer. Nothing suspicious found.")
        checks = checks + [guard]
        for t in self.tiles:
            self.checks.remove(t)
        self.tiles, self.tile_cols = [tile(c) for c in checks], 0
        self._lay_tiles()
        self.score.set_label(f"{sum(c.state == 'ok' for c in checks)} of {len(checks)} active")

        blocking = [c for c in checks if c.state in ("bad", "critical")]
        weak = [c for c in checks if c.state in ("warn", "warning")]
        version = core.current_version()
        self.problem.remove_css_class("critical")
        if blocking:
            set_state(self.status_dot, "bad")
            self.status.set_label("Not safe to start")
            self.problem.add_css_class("critical")
            self.problem.set_label(f"{blocking[0].title}: {blocking[0].detail}")
        else:
            set_state(self.status_dot, "warn" if weak else ("ok" if version else "idle"))
            self.status.set_label("Protected" if not weak else "Reduced protection")
            new = self.latest and version and self.latest != version
            notes = [f"{c.title}: {c.detail}" for c in weak]
            notes += [f"Tails {self.latest} will be fetched and verified at the next start."] if new else []
            self.problem.set_label("\n".join(notes))
        self.problem.set_visible(bool(self.problem.get_label()))
        self.version.set_label(f"Tails {version}" if version else "Tails not downloaded")
        self.start.set_sensitive(not blocking)
        self.start.set_label("Start Session" if core.current_iso() else "Download Tails and Start")

        clear(self.findings)
        for state, title, detail in (found if self.cfg["sentinel"] else []):
            row = box(False, 12, css="row")
            row.append(dot(state))
            text = box(spacing=3, hexpand=True)
            text.append(label(title, "headline"))
            text.append(label(detail, "caption", wrap=True, chars=48))
            row.append(text)
            self.findings.append(row)
        self.findings.set_visible(bool(self.findings.get_first_child()))

        profile = core.vpn_profile()
        self.vpn_state.set_label(profile or ("No profile imported" if INSTALLED else "Run the installer to enable the VPN"))
        self.vpn_remove.set_visible(bool(profile))
        self.vpn_switch.set_sensitive(bool(profile))
        self.vpn_switch.set_active(bool(self.cfg["vpn"] and profile))

    def _lay_tiles(self):
        """Eight tiles, four across or two: never a lone tile on the last row."""
        cols = 2 if self.width and self.width - (64 if self.width < NARROW else 212) < 680 else 4
        if cols == self.tile_cols:
            return
        self.tile_cols = cols
        for i, t in enumerate(self.tiles):
            if t.get_parent():
                self.checks.remove(t)
            self.checks.attach(t, i % cols, i // cols, 1, 1)

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
            return self.vpn_state.set_label("Run the installer first: the VPN needs its system service")
        chooser = Gtk.FileChooserNative(title="Import a WireGuard Profile", transient_for=self,
                                        action=Gtk.FileChooserAction.OPEN)
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
        col = Column(440, valign=Gtk.Align.CENTER, vexpand=True)
        col.add(image("lethe", 56)).set_halign(Gtk.Align.CENTER)
        col.add(margins(label("Starting your session", "title", 0.5, wrap=True), top=24))
        self.launch_hint = col.add(margins(label("", "secondary", 0.5, wrap=True), top=8))
        self.step_rows = {}
        steps = col.add(box(css="panel divided", margin_top=30))
        for key, text in STEPS:
            row = box(False, 14, css="row")
            mark = Gtk.Stack(width_request=18, height_request=18, valign=Gtk.Align.CENTER)
            ring = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
            ring.add_css_class("ring")
            mark.add_named(ring, "idle")
            mark.add_named(Gtk.Spinner(spinning=True), "active")
            mark.add_named(image("check", 18), "done")
            name = label(text, "step")
            name.set_hexpand(True)
            extra = label("", "mono")
            for w in (mark, name, extra):
                row.append(w)
            steps.append(row)
            self.step_rows[key] = (row, mark, name, extra)
        cancel = button("Cancel", "quiet", lambda: self.destroy_session("You cancelled the launch"))
        cancel.set_halign(Gtk.Align.CENTER)
        col.add(margins(cancel, top=26, bottom=30))
        return self._scroller(col)

    def step(self, key, extra=""):
        log("step", key)
        seen = False
        for k, (row, mark, name, more) in self.step_rows.items():
            state = "active" if k == key else ("idle" if seen else "done")
            seen = seen or k == key
            mark.set_visible_child_name(state)
            for c in ("active", "done"):
                name.remove_css_class(c)
            if state != "idle":
                name.add_css_class(state)
            more.set_label(extra if k == key else "")

    def launch(self):
        self.cfg = core.settings()
        self.threat = None
        outdated = bool(not core.current_iso() or (self.latest and self.latest != core.current_version()))
        harden = self.cfg["skip_welcome"] and self.cfg["harden_guest"]
        plan = {"update": outdated, "welcome": self.cfg["skip_welcome"], "hardening": harden,
                "tor": harden and self.cfg["auto_tor"]}
        for key, (row, *_) in self.step_rows.items():
            row.set_visible(plan.get(key, True))
        self.launch_hint.set_label("About a minute." if core.has_kvm() else
                                   "This computer has no hardware virtualisation, so this takes several minutes.")
        self.step("update" if outdated else "integrity")
        self.show("launch")
        # Tails starts at the size of the area it will be shown in, in real screen pixels.
        # The content area, not the window: some desktops draw a title bar inside the window.
        scale = self.display.device_scale()
        width, height = self.stack.get_width() or self.get_width(), self.stack.get_height() or self.get_height()
        bar = max(BAR, self.bar.measure(Gtk.Orientation.VERTICAL, width)[1])
        self.vm_size = self._fit(width * scale, (height - bar) * scale)
        self.vm_asked = 0
        cfg = {**self.cfg, "width": self.vm_size[0], "height": self.vm_size[1], "scale": scale}
        threading.Thread(target=self._run, args=(cfg, outdated), daemon=True).start()

    def _open_screen(self):
        """The VM's picture: D-Bus with shared memory when QEMU offers it (frames as fast as Tails
        draws them), VNC otherwise (about 33 frames per second)."""
        if self.session.dbus:
            screen = dbusdisplay.Screen(self.control, self.session.keyring, fill_alpha=NEEDS_ALPHA)
            screen.start()
            if screen.ready.wait(20) and not screen.failed:
                log("display", "dbus", "shared memory" if screen.stride and screen.buffer is not None else "")
                return screen
            raise core.LetheError(f"The VM's display did not connect ({screen.failed or 'timed out'}).")
        screen = rfb.Screen(self.session.vnc_path, fill_alpha=NEEDS_ALPHA)
        screen.start()
        log("display", "vnc")
        return screen

    @staticmethod
    def _fit(w, h):
        """A resolution for the VM: the display area, even-sized and within sane bounds."""
        return max(800, min(3840, int(w))) & ~1, max(600, min(2160, int(h))) & ~1

    def _run(self, cfg, outdated):
        """The whole life of one session, on a worker thread."""
        error, wiped = None, 0
        try:
            if outdated:
                try:
                    core.update(lambda _text, f: ui(self.step, "update", f"{f:.0%}" if f else ""))
                except core.LetheError:
                    if not core.current_iso():
                        raise                              # offline with an older image: carry on with it
            self.session = core.Session(cfg, stage=lambda name: ui(self.step, name))
            vpn = self.session.start()
            self.control = rfb.Control(self.session.qmp_path)
            self.screen = self._open_screen()
            if cfg["sentinel"]:
                self.watch = sentinel.Sentinel(self.session.vm.pid, self._alarm)
                self.watch.start()
            if cfg["skip_welcome"]:
                autopilot = None

                def report(state):
                    if state in ("welcome", "hardening", "tor"):
                        ui(self.step, state)
                    elif state in ("ready", "manual"):
                        ui(self._go_live, vpn, state == "manual", autopilot)

                autopilot = pilot.Pilot(self.screen, self.control, self.session, cfg["harden_guest"],
                                        cfg["auto_tor"], report)
                autopilot.start()
            else:
                ui(self._go_live, vpn, False, None)
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
            self.clip_ready, self.shared = False, None
            ui(self._ended, why, wiped, time.time() - started if started else 0, bool(error), bool(self.threat))

    # ── live session ────────────────────────────────────────────────────────
    def _live(self):
        page = box()
        # A window title bar, macOS style: identity on the left, one status capsule truly centred,
        # tools and the one destructive action on the right.
        bar = self.bar = Gtk.CenterBox(css_classes=["bar"], height_request=BAR)
        start = box(False, 8, valign=Gtk.Align.CENTER)
        start.append(image("lethe", 16))
        start.append(label("Lethe", "bar-title"))
        start.append(label("·", "bar-faint"))
        self.clock = label("00:00", "bar-clock")
        self.clock.set_tooltip_text("Time in this session")
        start.append(self.clock)
        bar.set_start_widget(start)

        self.capsule = box(False, 0, css="capsule", valign=Gtk.Align.CENTER)
        self.state_dot = dot("ok")
        self.capsule.append(margins(self.state_dot, end=9))
        self.bar_facts = {}
        for i, (key, icon) in enumerate((("net", "isolation"), ("tor", "network"), ("sentinel", "sentinel"))):
            if i:
                self.capsule.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
            item = box(False, 6, css="fact")
            item.append(image(icon, 14))
            text = label("", "fact-text")
            text.set_ellipsize(Pango.EllipsizeMode.END)
            item.append(text)
            self.capsule.append(item)
            self.bar_facts[key] = (item, text)
        bar.set_center_widget(self.capsule)

        end = box(False, 4, valign=Gtk.Align.CENTER)
        end.append(icon_button("fullscreen", "Full Screen", self._toggle_fullscreen))
        end.append(margins(button("End Session", "end", lambda: self.destroy_session("You ended the session")), start=8))
        bar.set_end_widget(end)
        page.append(bar)
        self.alert = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.alert_text = label("", "banner", wrap=True, chars=80)
        self.alert.set_child(self.alert_text)
        page.append(self.alert)
        self.display = Display()
        self.display.on_paste = self.paste
        overlay = Gtk.Overlay(child=self.display, vexpand=True)
        self.curtain = box(css="curtain", visible=False)
        inner = box(spacing=8, valign=Gtk.Align.CENTER, vexpand=True)
        inner.append(image("lethe", 48))
        inner.append(margins(label("Hidden while your screen is being captured", "headline", 0.5, wrap=True), top=10))
        inner.append(label("The session reappears when the recording or screen share stops.", "caption", 0.5, wrap=True))
        self.curtain.append(inner)
        overlay.add_overlay(self.curtain)
        page.append(overlay)
        return page

    # ── clipboard: this computer -> Tails, never back ─────────────────────────
    def _clipboard_watch(self):
        self.shared = None
        self.connect("notify::is-active", lambda *_: self.share_clipboard())
        self.get_clipboard().connect("changed", lambda *_: self.share_clipboard())

    def share_clipboard(self):
        """Whenever you come back to the session, what you copied on this computer is already on Tails'
        clipboard: text, or an image. Lethe hands it over on a small read-only disc; nothing can travel
        the other way."""
        session = self.session
        if not (self.cfg.get("clipboard", True) and self.is_active() and self.clip_ready and session
                and session.clipboard and self.stack.get_visible_child_name() == "live"):
            return
        clipboard = self.get_clipboard()
        if clipboard.is_local():
            return
        mimes = clipboard.get_formats().get_mime_types() or []
        if any(m.startswith("image/") for m in mimes) and not any(m.startswith("text/plain") for m in mimes):
            clipboard.read_texture_async(None, self._clip_image)
        elif any(m.startswith("text/") or m in ("UTF8_STRING", "STRING", "TEXT") for m in mimes):
            clipboard.read_text_async(None, self._clip_text)

    def _clip_text(self, clipboard, result):
        try:
            text = clipboard.read_text_finish(result)
        except GLib.Error:
            return
        if text:
            self._clip_send("text/plain;charset=utf-8", text.encode())

    def _clip_image(self, clipboard, result):
        try:
            texture = clipboard.read_texture_finish(result)
        except GLib.Error:
            return
        if texture:
            self._clip_send("image/png", texture.save_to_png_bytes().get_data())

    def _clip_send(self, mime, data):
        digest = hashlib.sha256(mime.encode() + b"\0" + data).digest()
        if digest == self.shared:
            return
        if len(data) > CLIP_LIMIT:
            return self._warn("What you copied is too large to share with Tails.")
        self.shared = digest
        session, control = self.session, self.control

        def work():
            try:
                control.insert("clipdisc", session.clip_disc(mime, data))
            except (OSError, AttributeError):
                pass

        threading.Thread(target=work, daemon=True).start()

    def paste(self):
        """Ctrl+Alt+V: type the text on this computer's clipboard into Tails, for places the clipboard
        cannot reach (the Welcome Screen, or a session without the Lethe desktop)."""
        if self.control:
            self.get_clipboard().read_text_async(None, self._pasted)

    def _pasted(self, clipboard, result):
        try:
            text = clipboard.read_text_finish(result)
        except GLib.Error:
            text = None
        text = (text or "").replace("\r\n", "\n").rstrip("\n")
        if not text:
            return self._warn("There is no text on your computer's clipboard to paste.")
        if len(text) > PASTE_LIMIT:
            text = text[:PASTE_LIMIT]
            self._warn(f"Only the first {PASTE_LIMIT} characters were pasted.")
        control, session, translator = self.control, self.session, self.display.translator
        self.display.grab_focus()

        def work():
            control.keys(translator.release_all())       # Ctrl and Alt are still held from the shortcut
            control.type(text, 0.006, stop=lambda: self.control is not control or not (session and session.alive()))

        threading.Thread(target=work, daemon=True).start()

    def _toggle_fullscreen(self):
        self.unfullscreen() if self.is_fullscreen() else self.fullscreen()

    def _go_live(self, vpn, manual, autopilot):
        log("live", "manual" if manual else "auto", "tor=" + str(autopilot and autopilot.online))
        firewalled = vpn or os.path.exists(core.NET_SOCK)
        tor = bool(autopilot and autopilot.online)
        self._fact("net", firewalled, f"VPN · {core.vpn_profile()}" if vpn else ("Firewall" if firewalled else "No firewall"),
                   "All traffic leaves through the WireGuard tunnel" if vpn else
                   "Tails can reach the internet and nothing else on your network" if firewalled else
                   "Run the installer to put the session behind Lethe's firewall")
        self._fact("tor", tor, "Tor" if tor else "Tor offline",
                   "Tor is connected" if tor else "Connect from the Tor Connection window in Tails")
        self._fact("sentinel", self.cfg["sentinel"], "Sentinel" if self.cfg["sentinel"] else "Sentinel off",
                   "Watching your computer: the session is destroyed at the first sign of tampering"
                   if self.cfg["sentinel"] else "Turned off in Preferences")
        good = firewalled and self.cfg["sentinel"]
        set_state(self.state_dot, "ok" if good else "warn")
        self.capsule.set_tooltip_text(None if core.has_kvm() else "Running without hardware acceleration: slower")
        if manual:
            self._warn("The Welcome Screen could not be passed automatically. Continue by hand: "
                       "press Start Tails if you see it.")
        elif autopilot and autopilot.connect and autopilot.hardened and not autopilot.online:
            self._warn("Tor did not connect within three minutes. The Tor Connection window is open so you can "
                       "try again or use a bridge.")
        self.display.control = self.control
        self.show("live")
        self.display.grab_focus()
        self.clip_ready = bool(autopilot and getattr(autopilot, "desktop", False))
        self.share_clipboard()

    def _fact(self, key, on, text, tooltip):
        item, label_ = self.bar_facts[key]
        label_.set_label(text)
        item.set_tooltip_text(tooltip)
        (item.remove_css_class if on else item.add_css_class)("off")

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
        """Once per display refresh: layout, VM size and picture follow the window."""
        width = self.get_width()
        if width and width != self.width:
            self.width = width
            narrow = width < NARROW                       # the sidebar folds down to its icons
            for w in self.side_labels:
                w.set_visible(not narrow)
            (self.sidebar.add_css_class if narrow else self.sidebar.remove_css_class)("folded")
            compact = width < 640
            (self.add_css_class if compact else self.remove_css_class)("compact")
            self._lay_tiles()
        if self.autostart and width and self.status.get_label() != "Checking…":
            self.autostart = False
            if self.start.get_sensitive():
                self.launch()

        screen = self.screen
        if not screen or self.stack.get_visible_child_name() != "live":
            return True
        # Tails follows the window: once a new size has held for a moment, ask the VM to adopt it.
        # If Tails is still at another size a while later (it was busy, or reset its screen), ask again.
        scale, now = self.display.device_scale(), time.monotonic()
        want = self._fit(self.display.get_width() * scale, self.display.get_height() * scale)
        if want != self.vm_size:
            self.vm_size, self.vm_size_at, self.vm_retries = want, now, 3
        elif self.vm_size_at and now - self.vm_size_at > 0.3:
            self.vm_size_at, self.vm_asked = 0, now
            screen.request_size(*want)
        elif (screen.width and (screen.width, screen.height) != want and now - self.vm_asked > 2
              and self.vm_retries > 0):
            self.vm_asked, self.vm_retries = now, self.vm_retries - 1
            screen.request_size(*want)
        frame = screen.take(self.serial)
        if frame:
            self.serial = frame.serial
            self.display.update(frame)
            if screen.cursor and screen.cursor[0] != self.pointer:
                self.pointer = screen.cursor[0]
                self.display.show_pointer(*screen.cursor[1:])
        self.meter.tick(vm=screen.frames, shown=self.display.shown)
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
        col = Column(480, valign=Gtk.Align.CENTER, vexpand=True)
        col.add(image("lethe", 56)).set_halign(Gtk.Align.CENTER)
        self.end_title = col.add(margins(label("", "title", 0.5, wrap=True), top=24))
        self.end_text = col.add(margins(label("", "secondary", 0.5, wrap=True), top=8))
        self.wipe_bar = col.add(Gtk.ProgressBar(margin_top=30, margin_start=70, margin_end=70))
        self.facts = col.add(box(css="panel", margin_top=30))
        self.end_button = button("Done", "primary", lambda: self.show("home"))
        self.end_button.set_halign(Gtk.Align.CENTER)
        col.add(margins(self.end_button, top=28, bottom=30))
        return self._scroller(col)

    def _ending(self):
        self.display.control = None
        self.display.clear()
        self.pointer = None
        self.curtain.set_visible(False)
        self.alert.set_reveal_child(False)
        if self.is_fullscreen():
            self.unfullscreen()
        self.end_title.remove_css_class("critical")
        self.end_title.set_label("Ending session")
        self.end_text.set_label("Overwriting the session's memory…")
        self.wipe_bar.set_fraction(0)
        self.wipe_bar.set_visible(True)
        self.facts.set_visible(False)
        self.end_button.set_visible(False)
        self.show("end")

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
        clear(self.facts)
        facts = []
        if wiped:
            facts.append(core.Check("memory", "ok", "Memory", f"{wiped / (1 << 30):.1f} GB",
                                    "Overwritten with zeros before release."))
        if wiped or not failed:
            facts.append(core.Check("integrity", "ok", "Disk", "Untouched",
                                    "No virtual disk, swap, crash dump or activity log."))
            facts.append(core.Check("image", "ok", "Tails image", "Unmodified",
                                    f"The session lasted {int(seconds) // 60} min {int(seconds) % 60} s."))
        for f in facts:
            self.facts.append(check_row(f))
        self.facts.set_visible(bool(facts))
        self.end_button.set_visible(True)

    def _closing(self, *_):
        if self.session:                      # closing the window ends the session
            self.session.destroy("You closed Lethe")
            deadline = time.time() + 8
            while self.session and time.time() < deadline:
                GLib.MainContext.default().iteration(False)
                time.sleep(0.02)
        return False

    # ── rendering pages without a session (development) ─────────────────────
    def preview(self, page):
        self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
        if page == "launch":
            for key, (row, *_) in self.step_rows.items():
                row.set_visible(key != "update")
            self.launch_hint.set_label("About a minute.")
            self.step("hardening")
        elif page == "end":
            self._ending()
            self._ended("You ended the session", 4 << 30, 754, False, False)
        elif page in ("network", "session", "sentinel"):
            self.sections.set_transition_type(Gtk.StackTransitionType.NONE)
            self.nav.select_row(self.nav.get_row_at_index([k for k, *_ in self.SECTIONS].index(page)))
            page = "home"
        elif page == "live":
            self._go_live(False, False, types.SimpleNamespace(online=True, connect=True, hardened=True))
        self.stack.set_visible_child_name(page)


def main():
    app = Gtk.Application(application_id=APP_ID)

    def activate(app):
        if app.get_active_window():
            return app.get_active_window().present()
        setup_style()
        Window(app).present()

    app.connect("activate", activate)
    return app.run(None)
