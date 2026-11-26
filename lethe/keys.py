"""Keyboard translation: any host layout in, plain US keystrokes out.

The guest always runs the default US layout, like most Tails sessions. What the
user types is translated by *character*: pressing the key that makes "a" on
AZERTY sends the US "a" key, whatever its physical position. If the character
needs a different Shift state on a US keyboard (AZERTY types "1" with Shift, US
without), Shift is corrected for the duration of that key.

Characters a US keyboard cannot type (é, ç, €) go through the guest's Unicode
entry sequence: Ctrl+Shift+U, hex code, Space.
"""
import unicodedata

_PLAIN = "`1234567890-=qwertyuiop[]\\asdfghjkl;'zxcvbnm,./"
_SHIFT = "~!@#$%^&*()_+QWERTYUIOP{}|ASDFGHJKL:\"ZXCVBNM<>?"
_QCODE = (["grave_accent"] + list("1234567890") + ["minus", "equal"] + list("qwertyuiop")
          + ["bracket_left", "bracket_right", "backslash"] + list("asdfghjkl") + ["semicolon", "apostrophe"]
          + list("zxcvbnm") + ["comma", "dot", "slash"])
US = {c: (q, False) for c, q in zip(_PLAIN, _QCODE)}
US.update({c: (q, True) for c, q in zip(_SHIFT, _QCODE)})
US[" "] = ("spc", False)

# Keys whose meaning does not depend on the layout, by X11 keysym name.
NAMED = {
    "Return": "ret", "KP_Enter": "kp_enter", "Escape": "esc", "BackSpace": "backspace", "Tab": "tab",
    "ISO_Left_Tab": "tab", "Delete": "delete", "Insert": "insert", "Home": "home", "End": "end",
    "Page_Up": "pgup", "Page_Down": "pgdn", "Left": "left", "Right": "right", "Up": "up", "Down": "down",
    "Shift_L": "shift", "Shift_R": "shift_r", "Control_L": "ctrl", "Control_R": "ctrl_r", "Alt_L": "alt",
    "Meta_L": "alt", "Super_L": "meta_l", "Super_R": "meta_r", "Menu": "menu", "Print": "print",
    "Pause": "pause", "Scroll_Lock": "scroll_lock",
    "KP_Left": "left", "KP_Right": "right", "KP_Up": "up", "KP_Down": "down", "KP_Home": "home", "KP_End": "end",
    "KP_Page_Up": "pgup", "KP_Page_Down": "pgdn", "KP_Insert": "insert", "KP_Delete": "delete",
    **{f"F{n}": f"f{n}" for n in range(1, 13)},
}
# Host-only keys: they pick characters on the host layout and mean nothing to the guest.
SWALLOW = {"ISO_Level3_Shift", "ISO_Level5_Shift", "Mode_switch", "Multi_key", "Caps_Lock", "Num_Lock", "Alt_R"}
DEAD = {"dead_grave": "̀", "dead_acute": "́", "dead_circumflex": "̂", "dead_tilde": "̃",
        "dead_diaeresis": "̈", "dead_cedilla": "̧"}
SHIFTS = ("shift", "shift_r")
MODS = ("ctrl", "ctrl_r", "alt", "meta_l", "meta_r")


class Translator:
    """Turns host key events into guest (qcode, down) events."""

    def __init__(self):
        self.shifts = set()      # shift keys the user physically holds
        self.mods = set()        # ctrl/alt/super the user physically holds
        self.held = {}           # host keycode -> (qcode, forced shift state or None)
        self.dead = None

    def _shift_to(self, want):
        """Events that put the guest's Shift into state `want`."""
        if want and not self.shifts:
            return [("shift", True)]
        if not want and self.shifts:
            return [(s, False) for s in sorted(self.shifts)]
        return []

    def _shift_restore(self, forced):
        if forced and not self.shifts:
            return [("shift", False)]
        if not forced and self.shifts:
            return [(s, True) for s in sorted(self.shifts)]
        return []

    def _unicode(self, ch):
        ev = [(k, False) for k in sorted(self.shifts | self.mods)]
        ev += [("ctrl", True), ("shift", True), ("u", True), ("u", False), ("shift", False), ("ctrl", False)]
        for d in f"{ord(ch):x}":
            ev += [(US[d][0], True), (US[d][0], False)]
        ev += [("spc", True), ("spc", False)]
        return ev + [(k, True) for k in sorted(self.shifts | self.mods)]

    def press(self, keycode, name, char):
        if name in SWALLOW:
            return []
        if name in DEAD:
            self.dead = DEAD[name]
            return []
        if name in NAMED and not (name.startswith("KP_") and char):
            q = NAMED[name]
            (self.shifts if q in SHIFTS else self.mods if q in MODS else set()).add(q)
            self.held[keycode] = (q, None)
            return [(q, True)]
        if not char or not char.isprintable():
            return []
        if self.dead:
            char, self.dead = unicodedata.normalize("NFC", char + self.dead), None
            if len(char) != 1:
                return []
        # With Ctrl/Alt/Super held this is a shortcut: send the letter's key, leave Shift alone.
        if self.mods and char.lower() in US:
            q = US[char.lower()][0]
            self.held[keycode] = (q, None)
            return [(q, True)]
        if char not in US:
            return self._unicode(char)
        q, shift = US[char]
        if keycode in self.held:                 # auto-repeat
            return [(q, True)]
        self.held[keycode] = (q, shift)
        return self._shift_to(shift) + [(q, True)]

    def release(self, keycode, name):
        if keycode not in self.held:
            return []
        q, forced = self.held.pop(keycode)
        self.shifts.discard(q)
        self.mods.discard(q)
        return [(q, False)] + ([] if forced is None else self._shift_restore(forced))

    def release_all(self):
        """On focus loss: nothing may stay pressed inside the guest."""
        ev = [(q, False) for q, _ in self.held.values()] + [(s, False) for s in SHIFTS]
        self.held.clear(), self.shifts.clear(), self.mods.clear()
        return ev


def typed(text):
    """Events that type `text` on a US keyboard (used to drive the guest ourselves)."""
    ev = []
    for ch in text:
        q, shift = ("ret", False) if ch == "\n" else US[ch]
        ev += ([("shift", True)] if shift else []) + [(q, True), (q, False)] + ([("shift", False)] if shift else [])
    return ev
