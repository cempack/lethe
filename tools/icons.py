"""Draws Lethe's icon theme for Tails into guest/icons/Lethe.

Every app keeps what makes it recognisable: its own emblem and its own colour (Tor Browser's
purple rings, Thunderbird's blue envelope, the green sheet of Calc, GIMP's Wilber). What changes
is the drawing. Each emblem is redrawn flat and simple, in white, on a tile of the app's colour
with the outline of the Lethe mark: one shape, one weight, one light from above, for all of them.
A second colour appears only where the original depends on it (the pencil, the flame, the star).

Emblems are drawn on a 24-unit grid. "{cut}" in a drawing is the tile's own colour, for details
cut into a white shape. Folders are steel blue, with their purpose engraved.

Run it after changing a drawing; the SVGs it writes are what ships.
"""
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "guest", "icons", "Lethe")
CUT = "{cut}"


def C(cx, cy, r):
    """A circle as a path."""
    return f"M{cx - r} {cy}a{r} {r} 0 1 0 {2 * r} 0a{r} {r} 0 1 0 {-2 * r} 0z"


def R(x, y, w, h, r):
    """A rounded rectangle as a path."""
    return (f"M{x + r} {y}h{w - 2 * r}a{r} {r} 0 0 1 {r} {r}v{h - 2 * r}a{r} {r} 0 0 1 {-r} {r}h{-(w - 2 * r)}"
            f"a{r} {r} 0 0 1 {-r} {-r}v{-(h - 2 * r)}a{r} {r} 0 0 1 {r} {-r}z")


def P(d, fill="#fff", o=1):
    """A filled shape."""
    return f'<path d="{d}" fill="{fill}" opacity="{o}"/>'


def S(d, w=1.8, stroke="#fff", o=1, more=""):
    """A line."""
    return (f'<path d="{d}" fill="none" stroke="{stroke}" stroke-width="{w}" stroke-linecap="round" '
            f'stroke-linejoin="round" opacity="{o}" {more}/>')


def dots(points, r, fill=CUT):
    return "".join(P(C(x, y, r), fill) for x, y in points)


GOLD = "#ffd257"
PAGE = "M13.500 3.500H8a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V8z M13.500 3.500V8H18"      # engraved on the Documents folder
BULB = "M12 6.2c-4.3 1.7-6.6 4.2-6.6 7.6a6.6 6.6 0 0 0 13.2 0c0-3.4-2.3-5.900-6.600-7.600z"
SHEET = "M7 3.800h7.200l4.300 4.300v10.100a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5.800a2 2 0 0 1 2-2z"       # LibreOffice's page
EAR = P("M14.200 3.800v2.800a1.500 1.500 0 0 0 1.500 1.500h2.800z", CUT, 0.5)
ENVELOPE = lambda x, y, w, h: P(R(x, y, w, h, 2.1)) + S(f"M{x + 0.7} {y + 1.7}l{w / 2 - 0.7} {h * 0.44} {w / 2 - 0.7} {-h * 0.44}", 1.35, CUT)
BUBBLE = "M6 4.500h12a2.500 2.500 0 0 1 2.500 2.500v6.500A2.500 2.500 0 0 1 18 16h-5.500L8 20v-4H6a2.500 2.500 0 0 1-2.500-2.500V7A2.500 2.500 0 0 1 6 4.500z"
STAR = "M12 3.800l2.500 5.200 5.700.800-4.100 4 1 5.700-5.100-2.700-5.100 2.700 1-5.700-4.100-4 5.700-.800z"
PADLOCK = (S("M8.300 10.500V8.200a3.700 3.700 0 0 1 7.400 0v2.300", 1.9) + P(R(5.800, 10.300, 12.400, 9.500, 2.400))
           + P(C(12, 14.200, 1.400), CUT) + P("M11.300 14.800h1.400l.500 2.600h-2.400z", CUT))
GEAR = ('<g transform="translate(12 12)">'
        + "".join(f'<rect x="-1.900" y="-8.700" width="3.800" height="5" rx="1.100" fill="#fff" transform="rotate({a})"/>' for a in range(0, 360, 45))
        + f'<circle r="6.100" fill="#fff"/><circle r="2.600" fill="{CUT}"/></g>')

# name: (tile colour at the top, at the bottom, the emblem)
APPS = {
    # ── Tor and the network ──
    "lethe-tor-browser": ("#9257c9", "#4f2488",        # the Tor Browser mark: rings, the right half filled in
        S(C(12, 12, 7.600), 1.500) + P("M12 4.400a7.600 7.600 0 0 1 0 15.200z", o=0.30) + S(C(12, 12, 4.600), 1.500)
        + P("M12 7.400a4.600 4.600 0 0 1 0 9.200z", o=0.50) + P(C(12, 12, 1.900))),
    "tor-connection": ("#7b4a96", "#3d1f52",           # the onion
        P(BULB) + S("M12 9.400c-2.200 1.200-3.400 2.700-3.400 4.500a3.400 3.400 0 0 0 6.800 0c0-1.800-1.200-3.300-3.400-4.500z M12 12.500v4.700", 1.300, CUT)
        + S("M12 6.200c0-1.900.900-3 2.600-3.600", 1.700)),
    "onioncircuits": ("#8552a8", "#45225e",            # an onion under the magnifying glass
        S("M10.300 6.300c-3.500 1.400-5.300 3.400-5.300 6.200 0 2.600 1.800 4.700 4.300 5.200 M10.300 6.300c2.300.900 4 2.100 4.800 3.600 M10.300 6.300c0-1.500.700-2.400 2-2.800", 1.600)
        + P(C(15.200, 14.700, 3.300), o=0.25) + S(C(15.200, 14.700, 3.300), 1.700) + S("M17.700 17.200l2.600 2.600", 2.100)),
    "org.onionshare.OnionShare": ("#9146a6", "#501f60",
        S("M5.800 12a6.200 6.200 0 0 1 10.500-4.500", 2) + P("M17.900 4.300v4.600h-4.600z")
        + S("M18.200 12a6.200 6.200 0 0 1-10.500 4.500", 2) + P("M6.100 19.700v-4.600h4.600z") + P(C(12, 12, 1.600))),
    "lethe-unsafe-browser": ("#e6a626", "#a86c0a",     # the warning sign
        P("M12 4.200c.600 0 1.100.300 1.400.800l6.700 11.600c.600 1.100-.200 2.400-1.400 2.400H5.300c-1.200 0-2-1.300-1.400-2.400l6.700-11.600c.300-.500.800-.800 1.400-.800z")
        + S("M12 9.300v4.300", 2, CUT) + P(C(12, 16.200, 1.100), CUT)),
    "thunderbird": ("#3f97ee", "#1757c0",              # the envelope under the bird's wing
        ENVELOPE(4, 8, 16, 11) + S("M4.800 6.300c3-3.200 9.500-3.600 13.800.200", 1.800, o=0.75)),
    "pidgin": ("#8163c8", "#47308e",                   # the pigeon, talking
        P(BUBBLE) + dots([(9.500, 9.700), (14.500, 9.700)], 1.150) + P("M10.500 12h3L12 14.200z", "#ffb02e")),
    "whisperback": ("#9da43e", "#5d621a",
        ENVELOPE(3.600, 8.200, 14.500, 10.500)
        + f'<path transform="translate(11.300 0.800) scale(0.520)" d="{STAR}" fill="{GOLD}"/>'),
    "electrum": ("#3a93dc", "#165c9e",                 # the atom, with the coin at its heart
        '<g transform="translate(12 12)" fill="none" stroke="#fff" stroke-width="1.150" opacity="0.8"><ellipse rx="8.300" ry="3.300"/>'
        '<ellipse rx="8.300" ry="3.300" transform="rotate(60)"/><ellipse rx="8.300" ry="3.300" transform="rotate(120)"/></g>'
        + P(C(12, 12, 4.100)) + S("M10.700 9.800h1.700a1.100 1.100 0 0 1 0 2.200h-1.700z M10.700 12h2.100a1.100 1.100 0 0 1 0 2.200h-2.100z M11.500 9v.800 M11.500 14.200v.800", 1.050, CUT)),
    # ── files and documents ──
    "org.gnome.Nautilus": ("#4a9bf0", "#1f5fc4",       # the filing cabinet
        P(R(5.500, 3.800, 13, 16.400, 2.400)) + S("M5.500 12h13", 1.200, CUT) + S("M10.200 8h3.600 M10.200 16h3.600", 1.600, CUT)),
    "org.gnome.TextEditor": ("#4fa8ee", "#1f6cc6",     # the page and the pencil
        P(R(4.800, 3.800, 11.600, 16.400, 2)) + S("M7.500 8h6.200 M7.500 11h4.200 M7.500 14h2.500", 1.250, CUT)
        + P("M12.600 18.900l.800-3.500 5.900-5.900a1.800 1.800 0 0 1 2.600 2.600l-5.900 5.900z", GOLD)),
    "org.gnome.Evince": ("#e44c42", "#a8211c",
        P(R(5.500, 3.800, 13, 16.400, 2)) + S("M8.300 8.300h4 M8.300 11.500h7.400 M8.300 14.700h7.400", 1.300, CUT)),
    "org.gnome.Loupe": ("#d4548e", "#8c2462",
        P(R(3.800, 5, 16.400, 14, 2.600)) + P(C(8.600, 9.600, 1.500), CUT) + P("M5.600 16.800l4.300-4.800 2.800 2.900 2.200-2 3.500 3.900z", CUT)),
    "org.gnome.FileRoller": ("#b58050", "#744c24",     # the box with a zip
        P(R(4.500, 5, 15, 14.500, 2.200)) + S("M4.500 9.800h15", 1.200, CUT)
        + S("M12 5v4.800", 1.500, CUT, more='stroke-dasharray="0.01 2.200"') + P(R(10.900, 10.500, 2.200, 3.800, 0.800), CUT)),
    "org.gnome.SimpleScan": ("#33a79e", "#136a62",
        S("M5 8.600l13.600 2.800", 1.900) + P(R(3.800, 11.500, 16.400, 7.500, 2.200)) + S("M6.800 15.300h7", 1.300, CUT) + P(C(16.800, 15.300, 0.900), CUT)),
    "fr.romainvigier.MetadataCleaner": ("#dba93e", "#9c6c14",   # a fingerprint, wiped clean
        S("M7.200 16.600c-.500-1.300-.700-2.700-.700-4.100a5.500 5.500 0 0 1 11 0c0 1.800-.200 3.500-.700 5", 1.600)
        + S("M9.500 18.300c-.500-1.800-.800-3.700-.800-5.800a3.300 3.300 0 0 1 6.600 0c0 2.300-.300 4.400-1 6.300", 1.600) + S("M12 12.500c0 2.300-.200 4.400-.700 6.300", 1.600)
        + '<path transform="translate(15.200 1.300) scale(0.300)" d="M12 1l3 8 8 3-8 3-3 8-3-8-8-3 8-3z" fill="#fff"/>'),
    "bookletimposer": ("#cb3a44", "#811a22",
        P("M12 6.400C10.200 5.200 7.800 4.700 4.500 4.700v12.600c3.300 0 5.700.500 7.500 1.700 1.800-1.200 4.200-1.700 7.500-1.700V4.700c-3.300 0-5.700.500-7.500 1.700z")
        + S("M12 6.400v12.500", 1.200, CUT) + S("M7 9c1 0 2 .200 2.800.500 M7 12c1 0 2 .200 2.800.500 M17 9c-1 0-2 .200-2.800.500 M17 12c-1 0-2 .200-2.800.500", 1.100, CUT, 0.7)),
    "libreoffice-startcenter": ("#858b97", "#4b505b", P(SHEET) + EAR),
    "libreoffice-writer": ("#3294e6", "#1560b4", P(SHEET) + EAR + S("M8 11.300h7.500 M8 14.200h7.500 M8 17.100h4.500", 1.300, CUT)),
    "libreoffice-calc": ("#43b556", "#1c7a30", P(SHEET) + EAR + S("M8 11.200h7.500v6H8z M8 14.200h7.500 M11.750 11.200v6", 1.200, CUT)),
    "libreoffice-impress": ("#ee6a30", "#b83f14", P(SHEET) + EAR + S("M8.400 17.300v-2.300 M11.750 17.300v-5.800 M15.100 17.300v-4", 1.700, CUT)),
    "libreoffice-draw": ("#e6b53c", "#a87c12", P(SHEET) + EAR + P(C(10.300, 13.300, 2.400), CUT) + P(R(11.500, 13.300, 4.300, 4.300, 0.700), CUT, 0.7)),
    # ── media ──
    "audacity": ("#3b68ea", "#1c309e",                 # headphones around a waveform
        S("M5.300 14.600v-2.400a6.700 6.700 0 0 1 13.400 0v2.400", 1.900) + P(R(3.600, 13, 3.700, 6.300, 1.500)) + P(R(16.700, 13, 3.700, 6.300, 1.500))
        + S("M9.300 15.200v1.800 M11.100 13v6.200 M12.900 14.200v3.800 M14.700 15.400v1.400", 1.300, "#ffb02e")),
    "io.github.celluloid_player.Celluloid": ("#5263d6", "#2a3090",
        P(R(3.800, 5.500, 16.400, 13, 2.600)) + P("M10.200 9l5 3-5 3z", CUT)),
    "org.gnome.SoundRecorder": ("#cf4a42", "#7d201a",
        P(R(9, 3.600, 6, 10.400, 3)) + S("M6 11.300a6 6 0 0 0 12 0 M12 17.300v3 M9.300 20.300h5.400", 1.700)),
    "org.gnome.SoundJuicer": ("#f29a30", "#ba5e10",    # a slice of orange
        P(C(12, 12, 8)) + S(C(12, 12, 6.100), 1, CUT) + S("M12 6.200v11.600 M7 9.100l10 5.800 M7 14.900l10-5.800", 1.050, CUT) + P(C(12, 12, 1.300), CUT)),
    "brasero": ("#ee8a30", "#b55412",                  # a disc, and the fire that writes it
        P(C(11.300, 11.800, 7.500)) + P(C(11.300, 11.800, 2.300), CUT) + S("M11.300 6.900a4.900 4.900 0 0 1 4.900 4.900", 1.100, CUT, 0.45)
        + P("M18.600 12.800c1.700 1.600 2.500 3.200 2.500 4.700a3.100 3.100 0 0 1-6.200 0c0-1.100.500-2 1.300-2.800.300.800.800 1.300 1.400 1.300.300-1.300.400-2.200 1-3.200z", GOLD)),
    "gimp": ("#7d7468", "#463e35",                     # Wilber
        P("M4.200 12.900c0-3.600 2.900-6.100 6.700-6.100 1.700 0 2.900.600 4.300.600 1.800 0 2.800-1.700 4.600-1.900.300 2.800-1.300 4.300-1.300 7.100 0 3.500-3.100 6-7.400 6s-6.900-2.300-6.900-5.700z")
        + dots([(10.400, 11.100), (15, 11.100)], 2.150) + dots([(10.900, 11.300), (15.500, 11.300)], 0.850, "#fff")
        + P("M5.400 14.400a1.600 1.250 0 1 0 3.200 0a1.600 1.250 0 1 0-3.200 0z", CUT)),
    "org.inkscape.Inkscape": ("#535a68", "#1f2229",    # the mountain of ink
        P("M12 3.700c.500 0 1 .200 1.400.600l6.400 6.400c.900.900.300 2.400-1 2.400H5.200c-1.300 0-1.900-1.500-1-2.400l6.400-6.400c.400-.400.900-.600 1.400-.600z")
        + S("M8.600 9l1.800 1.300 1.600-1.500 1.600 1.500 1.800-1.300", 1.200, CUT)
        + P("M7.300 15.300h9.400c.800 0 1.200.900.600 1.500-1.100 1-3 1.200-5.300 1.200s-4.200-.200-5.300-1.200c-.600-.600-.200-1.500.600-1.500z") + P(C(12, 20, 1))),
    # ── tools ──
    "org.gnome.Console": ("#474b56", "#17181c",
        P(R(3.500, 5, 17, 14, 2.800), o=0.14) + S(R(3.500, 5, 17, 14, 2.800), 1.500) + S("M7.300 9.700l3.200 2.500-3.200 2.500 M12.700 15h4", 1.900)),
    "gvim": ("#35a455", "#17682e", P("M4.500 5.500h4.800l2.700 8.200 2.700-8.200h4.800l-5.300 13.500H9.800z")),
    "org.gnome.Calculator": ("#4d5766", "#262c36",
        P(R(5.800, 3.800, 12.400, 16.400, 2.600)) + P(R(7.800, 5.800, 8.400, 3.500, 1), CUT)
        + dots([(8.900, 12.300), (12, 12.300), (15.100, 12.300), (8.900, 16), (12, 16)], 1.150) + P(C(15.100, 16, 1.150), "#ff9f2e")),
    "org.gnome.Settings": ("#939aa8", "#555b68", GEAR),
    "org.gnome.SystemMonitor": ("#434956", "#1b1d24",
        P(R(3.800, 5, 16.400, 13, 2.600), o=0.14) + S(R(3.800, 5, 16.400, 13, 2.600), 1.500)
        + S("M6.300 12.300h2.600l1.600-3.500 2.900 6.700 1.700-3.200h2.600", 1.600, "#62e08c")),
    "org.gnome.DiskUtility": ("#7f8795", "#454b57",
        P(R(5, 3.800, 14, 16.400, 2.400)) + P(C(12, 10.300, 4.300), CUT) + P(C(12, 10.300, 1.100)) + S("M12.800 11.200l3.200 4.300", 1.300, CUT) + P(C(8.200, 17.500, 0.800), CUT)),
    "org.gnome.Software": ("#5c72d4", "#2f4098",       # the shopping bag
        S("M9 8.500V7a3 3 0 0 1 6 0v1.500", 1.700) + P("M6 8.300h12l1.200 10.400a1.500 1.500 0 0 1-1.500 1.700H6.300a1.500 1.500 0 0 1-1.500-1.700z")
        + P(C(9.700, 13.300, 1.500), CUT) + P(R(12.600, 11.800, 3, 3, 0.500), CUT) + P("M10.400 18.200l1.700-2.900 1.700 2.900z", CUT)),
    "synaptic": ("#c75a3e", "#7d2c18",
        P("M12 3.700l7.400 4.100v8.400L12 20.300l-7.400-4.100V7.800z") + S("M4.900 8l7.100 3.900 7.100-3.900 M12 11.900v8", 1.200, CUT)),
    "lethe-additional-software": ("#bd9058", "#7b5628",
        P("M6.300 3.800h11.400l1.800 3.200h-15z", o=0.6) + P(R(4.500, 7, 15, 12.800, 2)) + S("M12 7v4.700", 2.400, CUT)),
    "ibus-setup": ("#6d7686", "#3a404c",
        P(R(2.800, 6.500, 18.400, 11, 2.400)) + dots([(6.500, 10.200), (9.250, 10.200), (12, 10.200), (14.750, 10.200), (17.500, 10.200)], 0.900) + S("M8 14h8", 1.700, CUT)),
    # ── help and about ──
    "org.gnome.Yelp": ("#ef5b4f", "#b62a22",           # the lifebuoy
        S(C(12, 12, 6.100), 4.400) + f'<path d="{C(12, 12, 6.100)}" fill="none" stroke="{CUT}" stroke-width="4.400" stroke-dasharray="4.790 4.790" stroke-dashoffset="2.400"/>'),
    "lethe-about": ("#6a4a9a", "#38205c", P(STAR, GOLD)),
    # ── secrets and storage ──
    "org.gnome.World.Secrets": ("#8560d6", "#46298f",  # the safe
        P(R(4.500, 4.500, 15, 15, 3)) + S(C(12, 12, 3.900), 1.200, CUT) + P(C(12, 11.300, 1.300), CUT) + P("M11.350 11.800h1.300l.500 2.500h-2.300z", CUT)),
    "kleopatra": ("#d94a3e", "#981f1a",                # the face under its fringe
        P("M12 3.800a7.200 7.200 0 0 1 7.200 7.200v6.800c0 .900-.700 1.600-1.600 1.600H6.400c-.900 0-1.600-.700-1.600-1.600V11A7.200 7.200 0 0 1 12 3.800z", o=0.42)
        + P("M8 11.500h8v2.700a4 4 0 0 1-8 0z") + P("M8 11.500c2.700 0 5-.900 6.300-2.800.500 1.300 1.100 2.200 1.700 2.800z", o=0.85)),
    "unlock-veracrypt-volumes": ("#3e8fa0", "#1c5360",
        S(C(8.300, 15.700, 3.200), 2.200) + S("M10.700 13.300l8.100-8.100 M15.800 8.200l2.300 2.300 M18.100 5.900l1.700 1.700", 2.200)),
    "tails-persistent-storage": ("#8a4bb0", "#481f66", PADLOCK),
    "tails-backup": ("#7a4aa8", "#3f2060",
        f'<g transform="translate(-1.200 -1.600) scale(0.780)" opacity="0.5">{PADLOCK}</g><g transform="translate(6.400 6.200) scale(0.780)">{PADLOCK}</g>'),
    "tails-installer": ("#5f9270", "#2e5540",          # the USB stick being written
        P(R(9.300, 3.600, 5.400, 4.800, 0.900), o=0.7) + P(R(7.500, 7.600, 9, 12.800, 2.400)) + S("M12 11v5.300 M9.700 14.200l2.300 2.300 2.300-2.300", 1.600, CUT)),
    # ── the dock's own button ──
    "lethe-apps": ("#494a51", "#202125", dots([(x, y) for y in (7, 12, 17) for x in (7, 12, 17)], 1.250, "#fff")),
}

# Launchers whose icon is a file path or a general-purpose name: setup.sh points a copy of each at
# these. (An icon named like "tails-backup.svg" needs nothing: that is looked up as "tails-backup".)
LAUNCHERS = {"org.boum.tails.TorBrowser": "lethe-tor-browser", "unsafe-browser": "lethe-unsafe-browser",
             "org.boum.tails.AdditionalSoftware": "lethe-additional-software", "tails-about": "lethe-about"}


def mix(a, b, t):
    """Colour `a` moved a fraction `t` of the way to colour `b`."""
    pa, pb = (int(a[i:i + 2], 16) for i in (1, 3, 5)), (int(b[i:i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(pa, pb))


def tile(top, bottom, emblem):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="128" height="128">
<defs>
  <linearGradient id="t" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{top}"/><stop offset="1" stop-color="{bottom}"/></linearGradient>
  <linearGradient id="r" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="0.34"/><stop offset="0.5" stop-color="#fff" stop-opacity="0.06"/><stop offset="1" stop-color="#000" stop-opacity="0.10"/></linearGradient>
  <filter id="s" x="-20%" y="-20%" width="140%" height="150%"><feDropShadow dx="0" dy="0.450" stdDeviation="0.450" flood-color="#000" flood-opacity="0.22"/></filter>
</defs>
<rect x="7" y="7" width="114" height="114" rx="27" fill="url(#t)"/>
<rect x="7.500" y="7.500" width="113" height="113" rx="26.500" fill="none" stroke="url(#r)"/>
<g transform="translate(19.600 19.600) scale(3.700)" filter="url(#s)">{emblem.replace(CUT, mix(top, bottom, 0.55))}</g>
</svg>
"""


def folder(engraving=""):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="128" height="128">
<defs>
  <linearGradient id="b" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#566587"/><stop offset="1" stop-color="#45526f"/></linearGradient>
  <linearGradient id="f" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#8fa3cc"/><stop offset="1" stop-color="#5b6c93"/></linearGradient>
  <linearGradient id="r" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="0.34"/><stop offset="0.4" stop-color="#fff" stop-opacity="0.04"/></linearGradient>
</defs>
<path d="M12 30a9 9 0 0 1 9-9h27l10 10h49a9 9 0 0 1 9 9v10H12z" fill="url(#b)"/>
<rect x="12" y="38" width="104" height="72" rx="10" fill="url(#f)"/>
<rect x="12.500" y="38.500" width="103" height="71" rx="9.500" fill="none" stroke="url(#r)"/>
<g transform="translate(43.600 53.600) scale(1.700)" fill="none" stroke="#141b2b" stroke-opacity="0.72" stroke-width="1.900" stroke-linecap="round" stroke-linejoin="round">{engraving}</g>
</svg>
"""


def e(d):
    return f'<path d="{d}"/>'


PLACES = {
    "folder": "", "inode-directory": "", "folder-open": "", "folder-drag-accept": "",
    "user-home": e("M4 11.500L12 4.500l8 7 M6.500 9.800V19.500h11V9.800"),
    "user-desktop": e(R(3.500, 5, 17, 11.500, 2) + " M12 16.500v3 M8.500 19.500h7"),
    "folder-documents": e(PAGE + " M9 13h6 M9 16.500h4"),
    "folder-download": e("M12 4.500v10.500 M7.800 11L12 15.200 16.200 11 M5 19.500h14"),
    "folder-pictures": e(R(3.500, 5, 17, 14, 2.500) + " " + C(8.600, 9.800, 1.400) + " M20 15l-4-4-9 8"),
    "folder-music": e("M9.500 17.500V6l9-2v11.500 " + C(7.200, 17.500, 2.300) + " " + C(16.200, 15.500, 2.300)),
    "folder-videos": e(R(3.500, 6, 12.500, 12, 2.500) + " M16 10.500l4.500-2.500v8l-4.500-2.500"),
    "folder-templates": e(R(5, 4, 14, 16, 2.500) + " M5 9.500h14 M10 9.500V20"),
    "folder-publicshare": e(C(6.500, 12, 2.300) + " " + C(17, 6.500, 2.300) + " " + C(17, 17.500, 2.300) + " M8.600 10.900l6.300-3.300 M8.600 13.100l6.300 3.300"),
}

INDEX = """[Icon Theme]
Name=Lethe
Comment=Lethe's icons for Tails, over Adwaita
Inherits=Adwaita,hicolor
Directories=scalable/apps,scalable/places

[scalable/apps]
Size=128
MinSize=8
MaxSize=512
Type=Scalable
Context=Applications

[scalable/places]
Size=128
MinSize=8
MaxSize=512
Type=Scalable
Context=Places
"""


def main():
    import shutil
    shutil.rmtree(OUT, ignore_errors=True)
    sets = (("apps", {k: tile(*v) for k, v in APPS.items()}), ("places", {k: folder(v) for k, v in PLACES.items()}))
    for sub, items in sets:
        d = os.path.join(OUT, "scalable", sub)
        os.makedirs(d, exist_ok=True)
        for name, svg in items.items():
            with open(os.path.join(d, name + ".svg"), "w") as f:
                f.write(svg)
    with open(os.path.join(OUT, "index.theme"), "w") as f:
        f.write(INDEX)
    with open(os.path.join(OUT, "launchers"), "w") as f:       # read by guest/setup.sh
        f.write("".join(f"{app} {icon}\n" for app, icon in LAUNCHERS.items()))
    print(f"{len(APPS)} apps, {len(PLACES)} places -> {os.path.normpath(OUT)}")


if __name__ == "__main__":
    main()
