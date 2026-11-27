"""Lethe's two windows.

The launcher is small and fixed in size: start a session, see that you are protected, change a
setting. The session opens in a window of its own, a normal resizable one, and the launcher steps
aside until the session has ended and been wiped.

Pages are widget trees built once; `refresh` and the session thread only change
their contents. Everything that touches GTK runs on the main thread: worker
threads hand results over with `ui(...)`.
"""
import hashlib, os, signal, subprocess, sys, threading, time, types

from .widgets import (Column, Display, Gtk, GLib, Meter, Pango, box, button, check_row, clear, dot, icon_button,
                      image, label, log, margins, panel, set_state, setting_row, setup_style, ui, NEEDS_ALPHA)
from gi.repository import Gdk, Gio          # versions are pinned in widgets
from . import core, dbusdisplay, pilot, rfb, sentinel

APP_ID = "org.lethe.App"
INSTALLED = os.path.exists("/etc/systemd/system/lethe-vpn.service")
SIZE = (420, 640)  # the launcher
BAR = 36           # height of the session bar

PASTE_LIMIT = 2000             # Ctrl+Alt+V types text, for where the clipboard cannot reach
CLIP_LIMIT = 32 << 20          # the largest thing shared with Tails' clipboard

STEPS = [("update", "Fetching the latest Tails"), ("integrity", "Verifying the Tails signature"),
         ("sandbox", "Building the sandbox"), ("network", "Opening the protected network"),
         ("boot", "Starting Tails"), ("welcome", "Passing the Welcome Screen"),
         ("hardening", "Hardening Tails"), ("tor", "Connecting to Tor")]


class Window(Gtk.ApplicationWindow):
    def __init__(self, app):
        # Not resizable: it is exactly as big as its content, and tiling desktops let it float.
        super().__init__(application=app, title="Lethe", resizable=False)
        self.add_css_class("lethe")
        self.cfg = core.settings()
        self.session = self.screen = self.control = self.watch = None
        self.serial, self.pointer, self.threat, self.latest = 0, None, None, None
        self.columns, self.vm_size, self.vm_size_at, self.vm_asked, self.vm_retries = [], None, 0, 0, 3
        self.pending, self.ticks = None, 0
        self.meter = Meter("display")
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT, transition_duration=220)
        self.stack.set_size_request(*SIZE)
        self.set_child(self.stack)
        for name, page in (("home", self._home()), ("protection", self._protection()),
                           ("settings", self._settings()), ("import", self._import_page()), ("end", self._end())):
            self.stack.add_named(page, name)
        self.viewer = self._viewer(app)
        self.clip_ready = False
        self._clipboard_watch()
        self.connect("close-request", self._closing)
        GLib.timeout_add_seconds(1, self._tick)
        self.autostart = bool(os.environ.pop("LETHE_AUTOSTART", None))     # `lethe start`
        self.refresh()
        threading.Thread(target=self._check_latest, daemon=True).start()

    def _scroller(self, column):
        self.columns.append(column)
        return Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, child=column)

    def show(self, page):
        """Pages of the session ("launch", "live") live in the session window; the rest in the launcher.
        Only one of the two windows is on screen at a time."""
        if page in ("launch", "live"):
            self.vstack.set_visible_child_name(page)
            if not self.viewer.get_visible():
                self.viewer.present()
                self.set_visible(False)
            return
        if page == "home":
            self.refresh()
        self.stack.set_visible_child_name(page)
        if self.viewer.get_visible():
            if self.viewer.is_fullscreen():
                self.viewer.unfullscreen()
            self.present()
            self.viewer.set_visible(False)

    def _is_live(self):
        return self.viewer.get_visible() and self.vstack.get_visible_child_name() == "live"

    # ── the launcher ────────────────────────────────────────────────────────
    def _home(self):
        page = box(css="launcher")
        top = box(False, 9)
        top.append(image("lethe", 22))
        name = label("Lethe", "wordmark")
        name.set_hexpand(True)
        top.append(name)
        top.append(icon_button("settings", "Settings", lambda: self.show("settings")))
        page.append(top)

        hero = box(valign=Gtk.Align.CENTER, vexpand=True)
        mark = image("lethe", 88)
        mark.set_halign(Gtk.Align.CENTER)
        hero.append(mark)
        hero.append(margins(label("Private Session", "title", 0.5), top=24))
        hero.append(margins(label("Tails in a sealed machine with no disk.\nNothing remains when it ends.",
                                  "secondary", 0.5, wrap=True, chars=34), top=8))
        page.append(hero)

        self.problem = label("", "caption", 0.5, wrap=True, chars=40)
        page.append(margins(self.problem, bottom=14))
        self.start = button("Start Session", "primary wide", self.launch)
        page.append(self.start)

        # One line of status; the details are a page away.
        row = box(False, 10)
        self.status_dot = dot()
        row.append(self.status_dot)
        self.status = label("Checking…", "status-text")
        self.status.set_ellipsize(Pango.EllipsizeMode.END)
        self.status.set_hexpand(True)
        row.append(self.status)
        self.score = label("", "caption")
        row.append(self.score)
        row.append(image("chevron", 16))
        details = Gtk.Button(child=row, tooltip_text="What protects this session")
        details.add_css_class("status-row")
        details.connect("clicked", lambda *_: self.show("protection"))
        page.append(margins(details, top=10))
        return page

    def _subpage(self, title, back="home"):
        """A page behind another: a back button, a title, and a scrolling column."""
        page = box()
        head = box(False, 6, css="subhead")
        head.append(icon_button("back", "Back", lambda: self.show(back)))
        head.append(label(title, "subtitle"))
        page.append(head)
        col = box(css="subpage")
        page.append(Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, child=col, vexpand=True))
        return page, col

    def _group(self, col, title, *rows):
        col.append(margins(label(title, "group-title"), top=18, bottom=8, start=4))
        col.append(panel(*rows))

    def _protection(self):
        page, col = self._subpage("Protection")
        self.checks = box(css="panel divided", margin_top=4)
        col.append(self.checks)
        return page

    def _settings(self):
        page, col = self._subpage("Settings")
        self.vpn_switch = Gtk.Switch()
        self.vpn_switch.connect("notify::active", self._vpn_toggled)
        vpn_actions = box(False, 8)
        self.vpn_remove = button("Remove", "quiet", lambda: self._vpn_helper(["remove"], None))
        vpn_actions.append(self.vpn_remove)
        vpn_actions.append(button("Import…", "quiet", self._vpn_import))
        profile_row = setting_row("WireGuard profile", "None", vpn_actions)
        self.vpn_state = profile_row.get_first_child().get_last_child()
        self._group(col, "Network",
                    setting_row("Connect to Tor automatically",
                                "Skips the Tor Connection screen. Turn this off to use bridges.",
                                self._switch("auto_tor")),
                    setting_row("Route the session through a VPN",
                                "Your provider sees a VPN instead of Tor. If the tunnel drops, nothing leaves.",
                                self.vpn_switch),
                    profile_row)
        self._group(col, "Session",
                    setting_row("Skip the Welcome Screen",
                                "English with a US keyboard, like most Tails users. Your own layout is "
                                "translated as you type.", self._switch("skip_welcome")),
                    setting_row("Harden and restyle Tails",
                                "Stricter privacy settings, Tor Browser at Safest, and the Lethe desktop.",
                                self._switch("harden_guest")),
                    setting_row("Share your clipboard with Tails",
                                "What you copy on this computer can be pasted in Tails. Never the other way.",
                                self._switch("clipboard")))
        self._group(col, "Sentinel",
                    setting_row("Watch this computer during sessions",
                                "Destroys the session if a debugger attaches, someone logs in remotely, or a "
                                "new keyboard is plugged in.", self._switch("sentinel")))
        self.findings = box(css="panel divided", margin_top=14)
        col.append(self.findings)
        return page

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
            self.checks.append(check_row(c, explain=True))
        self.score.set_label(f"{sum(c.state == 'ok' for c in checks)} of {len(checks)}")

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
            if self.autostart:
                self.autostart = False
                GLib.idle_add(lambda: self.launch() and False)
            new = self.latest and version and self.latest != version
            notes = [f"{c.title}: {c.detail}" for c in weak]
            notes += [f"Tails {self.latest} will be fetched and verified at the next start."] if new else []
            self.problem.set_label("\n".join(notes))
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

    # Picking the profile happens inside Lethe: the desktop's own file dialog is a separate service
    # that is not there on every system, and Lethe keeps itself closed to other programs anyway.
    PROFILE_FOLDERS = ("Downloads", "Documents", "Desktop", "")

    def _import_page(self):
        page, col = self._subpage("Import a VPN Profile", back="settings")
        col.append(margins(label("Choose a WireGuard profile, or drop one on this window. Lethe keeps its keys and "
                                 "addresses; any commands written in it are discarded.", "caption", wrap=True, chars=40),
                           start=4, bottom=14))
        self.profiles = box(css="panel divided")
        col.append(self.profiles)
        self.no_profiles = label("No WireGuard profiles found in your home, Downloads, Documents or Desktop folders.",
                                 "caption", wrap=True, chars=40)
        col.append(margins(self.no_profiles, start=4))
        col.append(margins(label("Or type where it is", "group-title"), top=20, bottom=8, start=4))
        row = box(False, 8)
        self.profile_path = Gtk.Entry(placeholder_text="/path/to/profile.conf", hexpand=True)
        self.profile_path.connect("activate", lambda e: self._import_file(os.path.expanduser(e.get_text().strip())))
        row.append(self.profile_path)
        row.append(button("Import", "quiet", lambda: self._import_file(os.path.expanduser(self.profile_path.get_text().strip()))))
        col.append(row)
        self.import_error = label("", "caption critical", wrap=True, chars=40)
        col.append(margins(self.import_error, top=10, start=4))
        drop = Gtk.DropTarget.new(Gio.File, Gdk.DragAction.COPY)
        drop.connect("drop", lambda _t, file, _x, _y: bool(file.get_path() and (self._import_file(file.get_path()) or True)))
        page.add_controller(drop)
        return page

    @classmethod
    def _find_profiles(cls):
        """WireGuard profiles in the usual places: .conf files that have an [Interface] section."""
        found = []
        for folder in cls.PROFILE_FOLDERS:
            base = os.path.join(os.path.expanduser("~"), folder)
            try:
                names = sorted(n for n in os.listdir(base) if n.lower().endswith(".conf"))
            except OSError:
                continue
            for name in names[:200]:
                path = os.path.join(base, name)
                try:
                    with open(path, "rb") as f:
                        if b"[interface]" in f.read(4096).lower():
                            found.append(path)
                except OSError:
                    pass
        return found[:12]

    def _vpn_import(self):
        if not INSTALLED:
            return self.vpn_state.set_label("Run the installer first: the VPN needs its system service")
        clear(self.profiles)
        found = self._find_profiles()
        for path in found:
            row = box(False, 12)
            text = box(spacing=3, hexpand=True)
            name = label(os.path.basename(path), "headline")
            name.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            text.append(name)
            text.append(label(os.path.dirname(path).replace(os.path.expanduser("~"), "~", 1), "caption"))
            row.append(text)
            row.append(image("chevron", 16))
            item = Gtk.Button(child=row)
            item.add_css_class("pick")
            item.connect("clicked", lambda _b, p=path: self._import_file(p))
            self.profiles.append(item)
        self.profiles.set_visible(bool(found))
        self.no_profiles.set_visible(not found)
        self.profile_path.set_text("")
        self.import_error.set_label("")
        self.show("import")

    def _import_file(self, path):
        try:
            with open(path, "rb") as f:
                data = f.read(65537)                  # read as the user; root only ever receives the bytes
        except OSError as e:
            return self.import_error.set_label(f"Could not read that file: {e.strerror}.")
        if b"[interface]" not in data.lower():
            return self.import_error.set_label("That is not a WireGuard profile.")
        self.show("settings")
        self._vpn_helper(["import", os.path.splitext(os.path.basename(path))[0]], data)

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
        cancel = button("Cancel", "quiet", self._cancel)
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
        self.pending, self.ticks = outdated, 0        # the session starts once its window has its size

    def _start(self, outdated):
        # Tails starts at the size of the area it will be shown in, in real screen pixels.
        scale = self.display.device_scale()
        width, height = self.vstack.get_width(), self.vstack.get_height()
        bar = 0 if self.viewer.is_fullscreen() else max(BAR, self.bar.measure(Gtk.Orientation.VERTICAL, width)[1])
        self.vm_size = self._fit(width * scale, (height - bar) * scale)
        self.vm_asked = 0
        cfg = {**self.cfg, "width": self.vm_size[0], "height": self.vm_size[1], "scale": scale}
        threading.Thread(target=self._run, args=(cfg, outdated), daemon=True).start()

    def _cancel(self):
        if self.pending is not None:
            self.pending = None
            self.show("home")
        else:
            self.destroy_session("You cancelled the launch")

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
        screen = rfb.Screen(self.control, fill_alpha=NEEDS_ALPHA)
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
            self.control = rfb.Control(self.session.qmp)
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
    def _viewer(self, app):
        """The session's own window: the launch steps, then Tails."""
        viewer = Gtk.ApplicationWindow(application=app, title="Lethe Session", default_width=1280, default_height=800)
        viewer.add_css_class("lethe")
        self.vstack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=180)
        self.vstack.add_named(self._launch(), "launch")
        self.vstack.add_named(self._live(), "live")
        viewer.set_child(self.vstack)
        viewer.connect("close-request", lambda *_: self._cancel() or True)   # closing it ends the session
        viewer.connect("notify::is-active", lambda *_: self.share_clipboard())
        # Full screen means the whole screen: the session bar goes away with the window's edges.
        viewer.connect("notify::fullscreened", lambda *_: self.bar.set_visible(not viewer.is_fullscreen()))
        viewer.add_tick_callback(self._frame)               # once per display refresh
        return viewer

    def _live(self):
        page = box()
        # One quiet line of window chrome: what this is and for how long, how it is protected,
        # and the two things you can do. It folds as the window narrows (see _fold).
        bar = self.bar = Gtk.CenterBox(css_classes=["bar"], height_request=BAR)
        start = box(False, 8, valign=Gtk.Align.CENTER)
        start.append(image("lethe", 16))
        self.bar_title = label("Private Session", "bar-title")
        start.append(self.bar_title)
        self.clock = label("00:00", "bar-clock")
        self.clock.set_tooltip_text("Time in this session")
        start.append(self.clock)
        bar.set_start_widget(start)

        self.capsule = box(False, 16, valign=Gtk.Align.CENTER)
        self.state_dot = dot("ok")
        self.capsule.append(self.state_dot)
        self.bar_facts = {}
        for key, icon in (("net", "isolation"), ("tor", "network"), ("sentinel", "sentinel")):
            item = box(False, 6, css="fact")
            item.append(image(icon, 14))
            text = label("", "fact-text")
            item.append(text)
            self.capsule.append(item)
            self.bar_facts[key] = (item, text)
        bar.set_center_widget(self.capsule)

        end = box(False, 6, valign=Gtk.Align.CENTER)
        end.append(icon_button("fullscreen", "Full Screen (Ctrl+Alt+F)", self._toggle_fullscreen))
        self.end_session = button("End Session", "end", lambda: self.destroy_session("You ended the session"))
        end.append(self.end_session)
        bar.set_end_widget(end)
        self.folded = None
        page.append(bar)
        self.alert = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.alert_text = label("", "banner", wrap=True, chars=80)
        self.alert.set_child(self.alert_text)
        page.append(self.alert)
        self.display = Display()
        self.display.on_paste = self.paste
        self.display.on_fullscreen = self._toggle_fullscreen
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
        self.get_clipboard().connect("changed", lambda *_: self.share_clipboard())

    def share_clipboard(self):
        """Whenever you come back to the session, what you copied on this computer is already on Tails'
        clipboard: text, or an image. Lethe hands it over on a small read-only disc; nothing can travel
        the other way."""
        session = self.session
        if not (self.cfg.get("clipboard", True) and self.viewer.is_active() and self.clip_ready and session
                and session.clipboard and self._is_live()):
            return
        clipboard = self.get_clipboard()
        if clipboard.is_local():
            return
        mimes = clipboard.get_formats().get_mime_types() or []
        if "x-kde-passwordManagerHint" in mimes:      # password managers mark what they copy: never share it
            return
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
        if self.viewer.is_fullscreen():
            self.viewer.unfullscreen()
        else:
            self.viewer.fullscreen()
            self._warn("Press Ctrl+Alt+F to leave full screen.", 4)

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

    def _warn(self, text, seconds=12):
        self.alert_text.set_label(text)
        self.alert.set_reveal_child(True)
        GLib.timeout_add_seconds(seconds, lambda: self.alert_text.get_label() == text
                                 and self.alert.set_reveal_child(False) and False)

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
        """Once per display refresh of the session window: the VM's size and picture follow it."""
        self._fold(self.viewer.get_width())
        if self.pending is not None:
            self.ticks += 1
            if self.ticks >= 6 and self.vstack.get_width() > 0:        # the window has settled at its size
                outdated, self.pending = self.pending, None
                self._start(outdated)
            return True
        screen = self.screen
        if not screen or not self._is_live():
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

    def _fold(self, width):
        """The session bar at any width: first the status loses its words, then the rest does."""
        folded = 2 if width < 560 else 1 if width < 860 else 0
        if width and folded != self.folded:
            self.folded = folded
            for _item, text in self.bar_facts.values():
                text.set_visible(folded == 0)
            self.bar_title.set_visible(folded < 2)
            self.end_session.set_label("End" if folded == 2 else "End Session")

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
        col = Column(480, valign=Gtk.Align.CENTER, vexpand=True, margin_start=22, margin_end=22)
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
        if self.session:                      # leaving Lethe ends the session
            self.session.destroy("You closed Lethe")
            deadline = time.time() + 8
            while self.session and time.time() < deadline:
                GLib.MainContext.default().iteration(False)
                time.sleep(0.02)
        self.viewer.destroy()
        return False

    # ── rendering pages without a session (development) ─────────────────────
    def preview(self, page):
        """Puts a page on screen with sample content. Returns the window it is in."""
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
            self._go_live(False, False, types.SimpleNamespace(online=True, connect=True, hardened=True))
        if page in ("launch", "live"):
            self.vstack.set_transition_type(Gtk.StackTransitionType.NONE)
            self.vstack.set_visible_child_name(page)
            return self.viewer
        self.stack.set_visible_child_name(page)
        return self


def main():
    app = Gtk.Application(application_id=APP_ID)

    def activate(app):
        if app.get_active_window():
            return app.get_active_window().present()
        setup_style()
        Window(app).present()

    def stop(*_):
        """Ctrl+C, `kill`, or the desktop logging out: end the session and wipe before leaving."""
        for win in app.get_windows():
            if isinstance(win, Window):
                win._closing()
        app.quit()
        return GLib.SOURCE_REMOVE

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, sig, stop)
    app.connect("activate", activate)
    return app.run(None)
