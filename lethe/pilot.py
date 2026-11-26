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
COMMAND = f'sh -c "udisksctl mount -b {DISC}; sh /media/amnesia/LETHE/setup.sh; udisksctl unmount -b {DISC}"\n'


class Pilot(threading.Thread):
    def __init__(self, screen, control, session, harden, report):
        super().__init__(daemon=True)
        self.screen, self.control, self.session, self.harden, self.report = screen, control, session, harden, report
        self.hardened = False

    # -- reading the screen --------------------------------------------------
    def _look(self):
        self.w, self.h, self.px, _ = self.screen.snapshot()
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
        self.report("ready")

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
