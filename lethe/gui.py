"""The Lethe window: home, preferences, launch, the live session, and its end.

Pages are widget trees built once; `refresh` and the session thread only change
their contents. Everything that touches GTK runs on the main thread: worker
threads hand results over with `ui(...)`.
"""
import os, subprocess, sys, threading, time

from .widgets import (Column, Display, Gtk, GLib, Meter, Pango, box, button, check_row, clear, dot, icon_button,
                      image, label, log, margins, panel, set_state, setting_row, setup_style, ui, NEEDS_ALPHA)
from . import core, pilot, rfb, sentinel

APP_ID = "org.lethe.App"
INSTALLED = os.path.exists("/etc/systemd/system/lethe-vpn.service")
WIDE = 940         # from this width up, the home page sets the hero and the protection panel side by side
BAR = 44           # height of the session bar

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
        self.width, self.columns, self.vm_size, self.vm_size_at = 0, [], None, 0
        self.meter = Meter("display")
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=180)
        self.set_child(self.stack)
        for name, page in (("home", self._home()), ("prefs", self._prefs()), ("launch", self._launch()),
                           ("live", self._live()), ("end", self._end())):
            self.stack.add_named(page, name)
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

    # ── home ────────────────────────────────────────────────────────────────
    def _home(self):
        col = Column(1120)
        top = box(False, 10)
        top.append(image("lethe", 24))
        top.append(label("Lethe", "wordmark"))
        top.append(Gtk.Box(hexpand=True))
        top.append(button("Preferences", "quiet", lambda: self.show("prefs")))
        col.add(margins(top, top=26))

        self.home_body = box(False, 64, valign=Gtk.Align.CENTER, vexpand=True)
        hero = box(hexpand=True, valign=Gtk.Align.CENTER)
        hero.append(label("PRIVATE SESSION", "eyebrow"))
        hero.append(margins(label("Leave no\nmemory.", "display"), top=14))
        hero.append(margins(label("Tails in a sealed virtual machine with no disk. "
                                  "When the session ends, nothing of it remains.", "lede", wrap=True, chars=40), top=18))
        actions = self.actions = box(False, 14, margin_top=34)
        self.start = button("Start Session", "primary", self.launch)
        self.start.set_halign(Gtk.Align.START)
        actions.append(self.start)
        status = box(False, 9, css="pill-status", valign=Gtk.Align.CENTER, halign=Gtk.Align.START)
        self.status_dot = dot()
        status.append(self.status_dot)
        self.status = label("Checking…")
        status.append(self.status)
        actions.append(status)
        hero.append(actions)
        self.problem = label("", "caption", wrap=True, chars=44)
        hero.append(margins(self.problem, top=16))
        self.home_body.append(hero)

        self.side = box(spacing=12, valign=Gtk.Align.CENTER)
        head = box(False, 8, margin_start=4, margin_end=4)
        title = label("PROTECTION", "eyebrow")
        title.set_hexpand(True)
        head.append(title)
        self.score = label("", "eyebrow")
        head.append(self.score)
        self.side.append(head)
        self.checks = box(css="panel")
        self.side.append(self.checks)
        self.home_body.append(self.side)
        col.add(margins(self.home_body, top=40, bottom=40))
        return self._scroller(col)

    # ── preferences ─────────────────────────────────────────────────────────
    def _prefs(self):
        col = Column(680)
        back = button("Back", "ghost", lambda: self.show("home"), icon="back")
        back.set_halign(Gtk.Align.START)
        col.add(margins(back, top=22))
        col.add(margins(label("Preferences", "title"), top=18, bottom=8))

        def section(title, *rows):
            col.add(margins(label(title, "eyebrow"), top=30, bottom=10, start=4))
            col.add(panel(*rows))

        self.vpn_switch = Gtk.Switch()
        self.vpn_switch.connect("notify::active", self._vpn_toggled)
        vpn_actions = box(False, 8)
        self.vpn_remove = button("Remove", "quiet", lambda: self._vpn_helper(["remove"], None))
        vpn_actions.append(self.vpn_remove)
        vpn_actions.append(button("Import…", "quiet", self._vpn_import))
        profile_row = setting_row("WireGuard profile", "None", vpn_actions)
        self.vpn_state = profile_row.get_first_child().get_last_child()
        section("NETWORK",
                setting_row("Connect to Tor automatically",
                            "Skips the Tor Connection screen. Your network can see that you use Tor, unless "
                            "the VPN below is on. Turn this off to use bridges.", self._switch("auto_tor")),
                setting_row("Route the session through a VPN",
                            "Recommended. Your provider sees a VPN instead of Tor, and the VPN only ever sees Tor. "
                            "The tunnel is the session's only route: if it drops, nothing leaves.", self.vpn_switch),
                profile_row)
        section("SESSION",
                setting_row("Skip the Welcome Screen",
                            "Starts in English with a US keyboard, like most Tails users. Your own keyboard "
                            "layout is translated as you type.", self._switch("skip_welcome")),
                setting_row("Harden and restyle Tails",
                            "Stricter privacy settings, Tor Browser at its Safest level, and the Lethe appearance.",
                            self._switch("harden_guest")))
        self.findings = box(css="divided")
        section("SENTINEL",
                setting_row("Watch this computer during sessions",
                            "Destroys the session at once if a debugger attaches to it, someone logs in remotely, "
                            "or a new keyboard is plugged in. A tripwire, not an antivirus: it cannot see "
                            "malware that already controls the system.", self._switch("sentinel")),
                self.findings)
        col.add(margins(Gtk.Box(), bottom=40))
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
        clear(self.checks)
        for c in checks:
            self.checks.append(check_row(c))
        self.score.set_label(f"{sum(c.state == 'ok' for c in checks)} OF {len(checks)}")

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
            self.status.set_label(("Protected" if not weak else "Reduced protection")
                                  + (f"  ·  Tails {version}" if version else ""))
            new = self.latest and version and self.latest != version
            self.problem.set_label(f"Tails {self.latest} will be fetched and verified at the next start." if new else "")
        self.problem.set_visible(bool(self.problem.get_label()))
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
        # Tails starts at the size of the area it will be shown in.
        self.vm_size = self._fit(self.get_width(), self.get_height() - BAR)
        cfg = {**self.cfg, "width": self.vm_size[0], "height": self.vm_size[1]}
        threading.Thread(target=self._run, args=(cfg, outdated), daemon=True).start()

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
            self.screen = rfb.Screen(self.session.vnc_path, fill_alpha=NEEDS_ALPHA)
            self.screen.start()
            self.control = rfb.Control(self.session.qmp_path)
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
            ui(self._ended, why, wiped, time.time() - started if started else 0, bool(error), bool(self.threat))

    # ── live session ────────────────────────────────────────────────────────
    def _live(self):
        page = box()
        bar = box(False, 12, css="bar", height_request=BAR)
        bar.append(image("lethe", 18))
        self.clock = label("00:00", "mono")
        bar.append(self.clock)
        bar.append(Gtk.Box(hexpand=True))
        self.state_dot = dot("ok")
        bar.append(self.state_dot)
        self.state = label("", "caption")
        self.state.set_ellipsize(Pango.EllipsizeMode.END)
        bar.append(self.state)
        bar.append(margins(icon_button("fullscreen", "Full Screen", self._toggle_fullscreen), start=6))
        bar.append(button("End Session", "end", lambda: self.destroy_session("You ended the session")))
        page.append(bar)
        self.alert = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.alert_text = label("", "banner", wrap=True, chars=80)
        self.alert.set_child(self.alert_text)
        page.append(self.alert)
        self.display = Display()
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

    def _toggle_fullscreen(self):
        self.unfullscreen() if self.is_fullscreen() else self.fullscreen()

    def _go_live(self, vpn, manual, autopilot):
        log("live", "manual" if manual else "auto", "tor=" + str(autopilot and autopilot.online))
        firewalled = vpn or os.path.exists(core.NET_SOCK)
        parts = [f"VPN · {core.vpn_profile()}" if vpn else ("Firewalled" if firewalled else "Not firewalled")]
        if autopilot and autopilot.online:
            parts.append("Tor connected")
        parts.append("Sentinel armed" if self.cfg["sentinel"] else "Sentinel off")
        if not core.has_kvm():
            parts.append("Software emulation")
        self.state.set_label("     ".join(parts))
        set_state(self.state_dot, "ok" if firewalled and self.cfg["sentinel"] else "warn")
        if manual:
            self._warn("The Welcome Screen could not be passed automatically. Continue by hand: "
                       "press Start Tails if you see it.")
        elif autopilot and autopilot.connect and autopilot.hardened and not autopilot.online:
            self._warn("Tor did not connect within three minutes. The Tor Connection window is open so you can "
                       "try again or use a bridge.")
        self.display.control = self.control
        self.show("live")
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
        """Once per display refresh: layout, VM size and picture follow the window."""
        width = self.get_width()
        if width and width != self.width:
            self.width = width
            wide = width >= WIDE
            self.home_body.set_orientation(Gtk.Orientation.HORIZONTAL if wide else Gtk.Orientation.VERTICAL)
            self.home_body.set_homogeneous(wide)          # two equal columns, or one stack
            self.home_body.set_spacing(72 if wide else 44)
            compact = width < 640
            (self.add_css_class if compact else self.remove_css_class)("compact")
            self.actions.set_orientation(Gtk.Orientation.VERTICAL if compact else Gtk.Orientation.HORIZONTAL)
        if self.autostart and width and self.status.get_label() != "Checking…":
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
        elif self.vm_size_at and time.monotonic() - self.vm_size_at > 0.3:
            self.vm_size_at = 0
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
        elif page == "live":
            self._go_live(False, False, None)
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
