#!/usr/bin/env python3
"""Draws Lethe's icon theme for Tails into guest/icons/Lethe.

One language for every app, the one the Lethe mark already speaks: a graphite
tile with a hairline of light along its top edge, and a single white line
drawing on it. No colour, except where it warns (the Unsafe Browser).
Glyphs are drawn on a 24-unit grid with a 1.6-unit round stroke; a second,
fainter layer gives them depth. Folders are brushed steel, with their purpose
engraved.

Run it after changing a drawing; the SVGs it writes are what ships.
"""
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "guest", "icons", "Lethe")


def C(cx, cy, r):
    """A circle as a path."""
    return f"M{cx - r} {cy}a{r} {r} 0 1 0 {2 * r} 0a{r} {r} 0 1 0 {-2 * r} 0z"


def R(x, y, w, h, r):
    """A rounded rectangle as a path."""
    return (f"M{x + r} {y}h{w - 2 * r}a{r} {r} 0 0 1 {r} {r}v{h - 2 * r}a{r} {r} 0 0 1 {-r} {r}h{-(w - 2 * r)}"
            f"a{r} {r} 0 0 1 {-r} {-r}v{-(h - 2 * r)}a{r} {r} 0 0 1 {r} {-r}z")


def dots(*points):
    return " ".join(f"M{x} {y}h.01" for x, y in points)


GLOBE = [C(12, 12, 8.5) + " M3.5 12h17", ("M12 3.5c-2.6 2.4-3.9 5.2-3.9 8.5s1.3 6.1 3.9 8.5 M12 3.5c2.6 2.4 3.9 5.2 3.9 8.5s-1.3 6.1-3.9 8.5", 0.55)]
PAGE = "M13.5 3.5H8a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V8z M13.5 3.5V8H18"
DISC = C(12, 12, 8.5)
BOX = "M12 3.5l7.5 4.2v8.6L12 20.5l-7.5-4.2V7.7z"
LOCK = R(5.5, 10.5, 13, 9.5, 2.5)
BUBBLE = "M6 4.5h12a2.5 2.5 0 0 1 2.5 2.5v6.5A2.5 2.5 0 0 1 18 16h-5.5L8 20v-4H6a2.5 2.5 0 0 1-2.5-2.5V7A2.5 2.5 0 0 1 6 4.5z"
CYLINDER = "M4.5 6.5c0-1.7 3.4-3 7.5-3s7.5 1.3 7.5 3-3.4 3-7.5 3-7.5-1.3-7.5-3z M4.5 6.5v11c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3v-11"

# name: [layer, ...]; a layer is a path, or (path, opacity) for the fainter second voice.
APPS = {
    # ── the network ──
    "lethe-tor-browser": GLOBE,
    "lethe-unsafe-browser": GLOBE + ["M4.5 4.5l15 15"],
    "tor-connection": ["M12 6.5c-4.2 1.6-6.5 4-6.5 7.4a6.5 6.5 0 0 0 13 0c0-3.4-2.3-5.8-6.5-7.4z M12 6.5c0-1.7.9-2.8 2.4-3.3",
                       ("M12 10.2c-2 .9-3.1 2.2-3.1 3.9a3.1 3.1 0 0 0 6.2 0c0-1.7-1.1-3-3.1-3.9z", 0.55)],
    "onioncircuits": [C(12, 5.5, 2) + C(5.5, 17.5, 2) + C(18.5, 17.5, 2), ("M10.9 7.2L6.6 15.8 M13.1 7.2l4.3 8.6 M7.5 17.5h9", 0.55)],
    "org.onionshare.OnionShare": ["M12 15V4 M7.8 8.2L12 4l4.2 4.2", ("M4.5 13.5V17a3 3 0 0 0 3 3h9a3 3 0 0 0 3-3v-3.5", 0.55)],
    "thunderbird": [R(3.5, 5.5, 17, 13, 2.5), ("M4.2 7.6l7.8 5.6 7.8-5.6", 0.55)],
    "pidgin": [BUBBLE, (dots((8.5, 10.3), (12, 10.3), (15.5, 10.3)), 0.7)],
    "whisperback": [BUBBLE, "M12 7.6v3.2 " + dots((12, 13.4))],
    "electrum": [C(12, 12, 8.5), "M9.8 8h3a2 2 0 0 1 0 4h-3z M9.8 12h3.5a2 2 0 0 1 0 4H9.8z M11.4 6.5V8 M11.4 16v1.5"],
    # ── files and documents ──
    "org.gnome.Nautilus": ["M3.5 7.5a2 2 0 0 1 2-2h3.6l2 2h7.4a2 2 0 0 1 2 2v7.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z", ("M3.5 11h17", 0.5)],
    "org.gnome.TextEditor": ["M5 19l.8-3.6L16.4 4.8a1.9 1.9 0 0 1 2.8 2.8L8.6 18.2z", ("M14.4 6.8l2.8 2.8 M12.5 19.5h7", 0.55)],
    "org.gnome.Evince": ["M12 6.6C10 5.2 7.4 4.6 4 4.6v12.8c3.4 0 6 .6 8 2 2-1.4 4.600-2 8-2V4.6c-3.400 0-6 .6-8 2z", ("M12 6.600v12.800", 0.55)],
    "org.gnome.Loupe": [R(3.5, 4.5, 17, 15, 3), (C(8.6, 9.4, 1.5) + " M20.300 14.800l-4.200-4.200L6.600 19.300", 0.6)],
    "org.gnome.FileRoller": [R(3.5, 4.5, 17, 4.5, 1.5) + " M5.200 9v8.500a2 2 0 0 0 2 2h9.600a2 2 0 0 0 2-2V9", ("M10 13h4", 0.6)],
    "org.gnome.SimpleScan": [R(3.5, 12, 17, 7.500, 2.200) + " M5 9.200l14 2.800", (dots((7, 15.800)) + " M11 15.800h6", 0.6)],
    "fr.romainvigier.MetadataCleaner": ["M3.500 11.600V5.500a2 2 0 0 1 2-2h6.100l8.300 8.300a2 2 0 0 1 0 2.800l-5.300 5.300a2 2 0 0 1-2.800 0z", (dots((7.800, 7.800)), 0.9),
                                        ("M11 11l4 4 M15 11l-4 4", 0.55)],
    "bookletimposer": ["M12 6.200L5 4.500v13.300l7 1.700 7-1.700V4.500z", ("M12 6.200v13.300 M7.500 8.800l2 .5 M7.500 12l2 .5 M16.500 8.800l-2 .5 M16.500 12l-2 .5", 0.5)],
    "libreoffice-startcenter": ["M12.500 3.500H9a2 2 0 0 0-2 2V16a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V10z M12.500 3.500V10H19", ("M4.500 8v10.500a2 2 0 0 0 2 2H15", 0.5)],
    "libreoffice-writer": [PAGE, ("M9 12h6 M9 15h6 M9 18h3.500", 0.6)],
    "libreoffice-calc": [R(3.500, 4.500, 17, 15, 2.500), ("M3.500 9.500h17 M3.500 14.500h17 M9.500 9.500v10", 0.55)],
    "libreoffice-impress": [R(3.500, 4.500, 17, 11.500, 2.500) + " M12 16v4 M8.500 20h7", ("M8.500 12.500v-2 M12 12.500v-4.500 M15.500 12.500v-3", 0.65)],
    "libreoffice-draw": [C(9, 9, 5), (R(10.500, 10.500, 9.500, 9.500, 2.200), 0.6)],
    # ── media ──
    "audacity": ["M4.500 10v4 M8.200 6.500v11 M12 3.500v17 M15.800 7.500v9 M19.500 10.500v3"],
    "io.github.celluloid_player.Celluloid": [R(3.500, 5, 17, 14, 3), ("M10.200 9.200l4.800 2.800-4.800 2.800z", 0.75)],
    "org.gnome.SoundRecorder": [R(9, 3.500, 6, 10.500, 3), ("M6 11.500a6 6 0 0 0 12 0 M12 17.500v3", 0.6)],
    "org.gnome.SoundJuicer": [DISC, (C(12, 12, 2.300) + " M12 6.400a5.600 5.600 0 0 1 5.600 5.600", 0.6)],
    "brasero": [C(11, 13, 7.500), (C(11, 13, 2), 0.6), "M18.500 3.500v4 M16.500 5.500h4"],
    "gimp": ["M12 3.500a8.500 8.500 0 1 0 0 17c1.100 0 1.900-.800 1.900-1.900 0-.500-.200-.900-.500-1.300-.300-.300-.400-.700-.400-1.200 0-1 .800-1.900 1.900-1.900h1.800a3.800 3.800 0 0 0 3.800-3.800C20.500 6.600 16.700 3.500 12 3.500z",
             (dots((7.600, 11.800), (9.800, 7.900), (14.200, 7.600)), 0.9)],
    "org.inkscape.Inkscape": ["M12 20.500l-5.500-8 4-9h3l4 9z", (C(12, 12.500, 1.500) + " M12 14v6.500", 0.6)],
    # ── tools ──
    "org.gnome.Console": [R(3.500, 4.500, 17, 15, 3), ("M7.300 9.500l3 2.500-3 2.500 M12.500 14.800h4", 0.75)],
    "gvim": ["M8 7.500L3.500 12 8 16.500 M16 7.500l4.500 4.500-4.500 4.500", ("M13.600 5l-3.200 14", 0.6)],
    "org.gnome.Calculator": [R(5.500, 3.500, 13, 17, 3), "M8.800 7.500h6.400", (dots((8.800, 11.800), (12, 11.800), (15.200, 11.800), (8.800, 15.800), (12, 15.800), (15.200, 15.800)), 0.75)],
    "org.gnome.Settings": ["M4 6.500h8.800 M17.200 6.500H20 " + C(15, 6.500, 2.100) + " M4 17.500h2.800 M11.200 17.500H20 " + C(9, 17.500, 2.100),
                           ("M4 12h16", 0.5)],
    "org.gnome.SystemMonitor": ["M3.500 12.500h3.800l2.400-6.500 4.200 12.500 2.500-6h4.100"],
    "org.gnome.DiskUtility": [R(3.500, 5.500, 17, 13, 3), ("M3.500 13.500h17 " + dots((7.200, 16), (10.200, 16)), 0.6)],
    "org.gnome.Software": [R(4, 4, 6.800, 6.800, 2) + R(13.200, 4, 6.800, 6.800, 2) + R(4, 13.200, 6.800, 6.800, 2), ("M16.600 13.800v5.600 M13.800 16.600h5.600", 0.75)],
    "synaptic": [BOX, ("M12 8.500v6.500 M9.300 12.400L12 15l2.700-2.600", 0.7)],
    "lethe-additional-software": [BOX, ("M4.800 7.900L12 12l7.200-4.100 M12 12v8.300", 0.55)],
    "ibus-setup": [R(2.500, 6, 19, 12, 3), (dots((6.500, 10), (10.200, 10), (13.800, 10), (17.500, 10)) + " M8 14h8", 0.7)],
    "org.gnome.Tecla": [R(2.500, 6, 19, 12, 3), (dots((6.500, 10), (10.200, 10), (13.800, 10), (17.500, 10)) + " M8 14h8", 0.7)],
    "org.gnome.Shell.Extensions": ["M9.500 4.500h5v3a2 2 0 1 0 4 0h1v5h-1.500a2 2 0 1 0 0 4H19.500v3h-15v-5H6a2 2 0 1 0 0-4H4.500v-3h5z"],
    # ── help and about ──
    "org.gnome.Yelp": [C(12, 12, 8.500), "M9.400 9.400a2.700 2.700 0 1 1 3.900 2.500c-.900.500-1.300 1.100-1.300 2.100 " + dots((12, 16.800))],
    "lethe-about": [C(12, 12, 8.500), "M12 11v5.500 " + dots((12, 7.800))],
    # ── secrets and storage ──
    "org.gnome.World.Secrets": [C(8.200, 15.800, 4.300), "M11.300 12.700L19.500 4.500 M15.500 8.500l2.600 2.600 M18 6l1.800 1.800"],
    "kleopatra": ["M12 3.500l7 2.700v5.300c0 4.300-2.800 7.700-7 9-4.200-1.300-7-4.700-7-9V6.200z", ("M9 12l2.200 2.200 4-4.200", 0.75)],
    "unlock-veracrypt-volumes": [LOCK, "M8.500 10.500V7.800a3.500 3.500 0 0 1 6.800-1.200", ("M12 14.300v2.200", 0.75)],
    "tails-persistent-storage": [CYLINDER, ("M4.500 12c0 1.700 3.400 3 7.500 3s7.500-1.300 7.500-3", 0.55)],
    "tails-backup": ["M4.500 12a7.500 7.500 0 0 1 12.900-5.200L19.500 9 M19.500 4.500V9H15", ("M19.500 12a7.500 7.500 0 0 1-12.900 5.200L4.500 15 M4.500 19.500V15H9", 0.6)],
    "tails-installer": [R(7, 9.500, 10, 11, 2.500), "M9.500 9.500v-6h5v6", (dots((11, 6.300), (13, 6.300)) + " M10 14.500h4", 0.7)],
}
WARN = {"lethe-unsafe-browser"}

# Launchers whose icon is a file path or a generic name: setup.sh points a copy of each at these.
# (Icons named like "tails-backup.svg" need nothing: that is looked up as "tails-backup".)
LAUNCHERS = {"org.boum.tails.TorBrowser": "lethe-tor-browser", "unsafe-browser": "lethe-unsafe-browser",
             "org.boum.tails.AdditionalSoftware": "lethe-additional-software", "tails-about": "lethe-about"}


def tile(layers, warn=False):
    top, bottom, ink = ("#6a2f2f", "#321617", "#ffe6e3") if warn else ("#494a51", "#202125", "#f7f7f9")
    glyph = ""
    for layer in layers:
        d, opacity = layer if isinstance(layer, tuple) else (layer, 1)
        glyph += f'<path d="{d}" opacity="{opacity}"/>'
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="128" height="128">
<defs>
  <linearGradient id="t" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{top}"/><stop offset="1" stop-color="{bottom}"/></linearGradient>
  <linearGradient id="r" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="0.32"/><stop offset="0.5" stop-color="#fff" stop-opacity="0.05"/><stop offset="1" stop-color="#fff" stop-opacity="0.02"/></linearGradient>
  <linearGradient id="i" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="{ink}" stop-opacity="0.82"/></linearGradient>
</defs>
<rect x="7" y="7" width="114" height="114" rx="27" fill="url(#t)"/>
<rect x="7.500" y="7.500" width="113" height="113" rx="26.500" fill="none" stroke="url(#r)"/>
<g transform="translate(28 28) scale(3)" fill="none" stroke="{ink}" stroke-width="1.650" stroke-linecap="round" stroke-linejoin="round">{glyph}</g>
</svg>
"""


def folder(engraving=""):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="128" height="128">
<defs>
  <linearGradient id="b" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#5d6474"/><stop offset="1" stop-color="#4a5060"/></linearGradient>
  <linearGradient id="f" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#9aa2b6"/><stop offset="1" stop-color="#666e83"/></linearGradient>
  <linearGradient id="r" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="0.34"/><stop offset="0.4" stop-color="#fff" stop-opacity="0.04"/></linearGradient>
</defs>
<path d="M12 30a9 9 0 0 1 9-9h27l10 10h49a9 9 0 0 1 9 9v10H12z" fill="url(#b)"/>
<rect x="12" y="38" width="104" height="72" rx="10" fill="url(#f)"/>
<rect x="12.500" y="38.500" width="103" height="71" rx="9.500" fill="none" stroke="url(#r)"/>
<g transform="translate(43.600 53.600) scale(1.700)" fill="none" stroke="#1a1d25" stroke-opacity="0.7" stroke-width="1.900" stroke-linecap="round" stroke-linejoin="round">{engraving}</g>
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
    sets = (("apps", {k: tile(v, k in WARN) for k, v in APPS.items()}), ("places", {k: folder(v) for k, v in PLACES.items()}))
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
