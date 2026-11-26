"""Autopilot: gets a fresh Tails from power-on to a hardened desktop, hands-free.

It only ever looks at the VM's screen and presses keys, exactly as a person
would, so the Tails image stays byte-for-byte the signed original:

  1. waits for the Welcome Screen and presses Enter ("Start Tails" has focus;
     language and keyboard stay on the English/US defaults);
  2. waits for the desktop, opens GNOME's run prompt (Alt+F2) and runs the
     hardening script from the read-only LETHE config disc;
  3. confirms it worked by watching the wallpaper change.

Nothing is timed: every step waits for what is actually on screen, so a slow
machine just takes longer. If a step cannot be recognised the autopilot stops
and hands the session to the user as-is.
"""
import threading, time

TAILS_BLUE = (32, 74, 135)       # Tails desktop / greeter background
SELECTED = bytes((228, 132, 53, 255))   # GNOME selection blue, as BGRA
DISC = "/dev/disk/by-label/LETHE"   # mounted for the script, ejected right after
COMMAND = f'sh -c "udisksctl mount -b {DISC}; sh /media/amnesia/LETHE/setup.sh; udisksctl unmount -b {DISC}"'
EDGES = [(0.004, 0.3), (0.004, 0.55), (0.004, 0.8), (0.996, 0.3), (0.996, 0.55), (0.996, 0.8)]


class Pilot(threading.Thread):
    def __init__(self, screen, control, session, harden, connect, report):
        super().__init__(daemon=True)
        self.screen, self.control, self.session, self.report = screen, control, session, report
        self.harden, self.connect = harden, connect
        self.hardened = self.online = False

    # -- reading the screen --------------------------------------------------
    def _look(self):
        self.w, self.h, self.px = self.screen.peek()
        return self.w >= 800 and self.h >= 600      # firmware and boot menu use smaller text modes

    def _at(self, fx, fy):
        o = (int(fy * (self.h - 1)) * self.w + int(fx * (self.w - 1))) * 4
        return self.px[o + 2], self.px[o + 1], self.px[o]

    def _near(self, a, b, tol=12):
        return all(abs(x - y) <= tol for x, y in zip(a, b))

    def _welcome(self):
        # Light top bar + a wide selected row: the Welcome Screen and nothing else.
        return self._look() and min(self._at(0.3, 0.008)) > 200 and SELECTED * 100 in self.px

    def _desktop(self):
        # Black top bar on both sides of the clock, Tails blue at the screen edge.
        return (self._look() and max(self._at(0.3, 0.008)) < 60 and max(self._at(0.7, 0.008)) < 60
                and self._near(self._at(0.004, 0.5), TAILS_BLUE))

    def _edge(self):
        """Mean colour along both screen edges: only the wallpaper shows there."""
        if not self._look():
            return (0, 0, 0)
        pts = [self._at(x, y) for x, y in EDGES]
        return tuple(sum(p[i] for p in pts) / len(pts) for i in range(3))

    def _wait(self, test, timeout, every=0.5):
        end = time.time() + timeout
        while time.time() < end and self.session.alive():
            if test():
                return True
            time.sleep(every)
        return False

    # -- the flight plan -----------------------------------------------------
    def run(self):
        slow = 1 if self.session.kvm else 12      # software emulation is an order of magnitude slower
        self.report("booting")
        if not self._wait(self._welcome, 240 * slow):
            return self.report("manual")
        self.report("welcome")
        for _ in range(6):                        # Enter = "Start Tails"
            self.control.tap("ret")
            if self._wait(lambda: not self._welcome(), 6 * slow):
                break
        if not self._wait(self._desktop, 180 * slow):
            return self.report("manual")
        if self.harden:
            self.report("hardening")
            self._harden(slow)
        if self.connect and self.hardened:
            self.report("tor")
            self._connect_tor(slow)
        self.report("ready")

    def _connect_tor(self, slow):
        """Tor Connection: "Connect to Tor automatically" (Alt+A), then Connect (Alt+C).
        Inside Tails, setup.sh swaps to an imperceptibly brighter copy of the wallpaper
        once Tor has bootstrapped: that change is the signal. Then the window is closed."""
        before = self._edge()
        self.control.tap("alt", "a")
        time.sleep(0.8 * slow)
        self.control.tap("alt", "c")
        self.online = self._wait(lambda: max(abs(a - b) for a, b in zip(self._edge(), before)) >= 1.5, 180 * slow, 1)
        if self.online:
            time.sleep(1.5 * slow)                 # let the success page draw before closing it
            for _ in range(3):                     # the window sits in the middle: wait to see it go
                window = self._look() and self._at(0.5, 0.5)
                self.control.tap("alt", "f4")
                if self._wait(lambda: not self._near(self._at(0.5, 0.5), window, 6) if self._look() else False,
                              3 * slow, 0.3):
                    break

    def _harden(self, slow):
        edge = lambda: self._look() and self._at(0.004, 0.5)
        # Let the session settle: Tails opens the Tor Connection assistant by itself.
        self._wait(lambda: self._look() and min(self._at(0.5, 0.5)) > 225, 25 * slow)
        time.sleep(1.5 * slow)
        for _ in range(3):
            self.control.tap("alt", "f2")
            # The run prompt dims the whole screen: wait to see that before typing.
            if self._wait(lambda: not self._near(edge(), TAILS_BLUE), 8 * slow, 0.2):
                break
        else:
            return
        time.sleep(0.4 * slow)
        dimmed = edge()
        self.control.type(COMMAND, 0.012 * slow)
        time.sleep(0.4 * slow)
        self.control.tap("ret")
        # An Enter pressed while the prompt is still busy can be lost: if it is still open, press it again.
        if not self._wait(lambda: not self._near(edge(), dimmed, 4), 4 * slow, 0.2):
            self.control.tap("ret")
        # Success = the edge of the screen is neither Tails blue nor the dimmed prompt: our wallpaper.
        self.hardened = self._wait(
            lambda: self._desktop_bar() and not self._near(edge(), TAILS_BLUE) and not self._near(edge(), dimmed, 4),
            40 * slow)
        if not self.hardened:
            self.control.tap("esc")
        time.sleep(1.5 * slow)                 # the command's last step unmounts the disc
        self.control.eject("cfgdisc")          # then it leaves the VM for good

    def _desktop_bar(self):
        return self._look() and max(self._at(0.3, 0.008)) < 60
