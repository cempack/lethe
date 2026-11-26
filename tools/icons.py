#!/usr/bin/env python3
"""Draws Lethe's icon theme for Tails into guest/icons/Lethe.

One grid for everything, the way macOS icons are made: a 112 px rounded square
on a 128 px canvas, a top-lit gradient, a hairline rim, one simple white glyph.
Folders follow macOS too: a blue folder with the place embossed on it.
Run it after changing a drawing; the SVGs it writes are what ships.
"""
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "guest", "icons", "Lethe")
W = "#ffffff"


def tile(top, bottom, glyph, rim=0.20):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="128" height="128">
<defs>
  <linearGradient id="b" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{top}"/><stop offset="1" stop-color="{bottom}"/></linearGradient>
  <linearGradient id="r" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="{rim}"/><stop offset="0.5" stop-color="#fff" stop-opacity="0.03"/><stop offset="1" stop-color="#000" stop-opacity="0.18"/></linearGradient>
  <filter id="s" x="-10%" y="-10%" width="120%" height="130%"><feDropShadow dx="0" dy="2" stdDeviation="2.2" flood-color="#000" flood-opacity="0.35"/></filter>
</defs>
<g filter="url(#s)"><rect x="8" y="8" width="112" height="112" rx="26" fill="url(#b)"/></g>
<rect x="8.5" y="8.5" width="111" height="111" rx="25.5" fill="none" stroke="url(#r)"/>
{glyph}
</svg>
"""


def stroke(d, color=W, width=6, opacity=1):
    return (f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="round" '
            f'stroke-linejoin="round" opacity="{opacity}"/>')


APPS = {
    # Tor Browser: a globe on violet.
    "org.boum.tails.TorBrowser": tile("#7b5be0", "#3b2390",
        stroke("M64 36a28 28 0 1 0 0.01 0z M64 36c-9 8-13 18-13 28s4 20 13 28 M64 36c9 8 13 18 13 28s-4 20-13 28"
               " M37 56h54 M37 72h54", width=5)),
    # Tor Connection: the layers of an onion.
    "tor-connection": tile("#45454c", "#1d1d21",
        stroke("M64 38a26 26 0 1 0 0.01 0z", width=5) + stroke("M64 50a14 14 0 1 0 0.01 0z", width=5, opacity=0.7)
        + '<circle cx="64" cy="64" r="5" fill="#fff" opacity="0.5"/>' + stroke("M64 38c0-8 5-12 11-13", width=5)),
    # Files: a blue folder on a light tile.
    "org.gnome.Nautilus": tile("#f7f8fa", "#d5d9e0",
        '<path d="M30 44a6 6 0 0 1 6-6h17l7 7h32a6 6 0 0 1 6 6v33a6 6 0 0 1-6 6H36a6 6 0 0 1-6-6z" fill="#2f86f6"/>'
        '<path d="M30 54a6 6 0 0 1 6-6h56a6 6 0 0 1 6 6v30a6 6 0 0 1-6 6H36a6 6 0 0 1-6-6z" fill="#5aa9ff"/>', rim=0.6),
    # Terminal.
    "org.gnome.Console": tile("#38383d", "#0f0f11",
        stroke("M38 50l14 14-14 14", width=6) + stroke("M60 80h28", width=6, opacity=0.85)),
    # Secrets (passwords): a key on deep green.
    "org.gnome.World.Secrets": tile("#2fbf8f", "#0f6b50",
        stroke("M48 52a13 13 0 1 0 0.01 0z", width=6) + stroke("M58 73l24 24 M74 89l7-7 M81 96l6-6", width=6)),
    # Mail: an envelope on sky blue.
    "thunderbird": tile("#5bbcff", "#1d6fe0",
        '<rect x="32" y="42" width="64" height="44" rx="8" fill="#fff"/>'
        + stroke("M35 46l29 21 29-21", color="#2a7fe8", width=5)),
    # Help.
    "org.gnome.Yelp": tile("#ffb240", "#ef7212",
        stroke("M64 36a28 28 0 1 0 0.01 0z", width=5) + stroke("M54 56a10 10 0 1 1 14 9c-3 1.5-4 3.5-4 6.5", width=6)
        + '<circle cx="64" cy="82" r="3.8" fill="#fff"/>'),
    # Text Editor: a sheet of paper with a yellow band.
    "org.gnome.TextEditor": tile("#fbfbfc", "#e2e3e6",
        '<rect x="8" y="8" width="112" height="26" rx="0" fill="#ffd34d" clip-path="url(#c)"/>'
        '<clipPath id="c"><rect x="8" y="8" width="112" height="112" rx="26"/></clipPath>'
        + "".join(stroke(f"M32 {y}h{64 if i < 3 else 40}", color="#b8bcc4", width=4) for i, y in enumerate((52, 66, 80, 94))),
        rim=0.6),
    # Settings: a gear on steel.
    "org.gnome.Settings": tile("#a3a6ae", "#5a5d66",
        '<g transform="translate(64 64)">' + "".join(
            f'<rect x="-5.5" y="-33" width="11" height="14" rx="3" fill="#fff" transform="rotate({a})"/>' for a in range(0, 360, 45))
        + '<circle r="22" fill="#fff"/><circle r="9" fill="#7c7f88"/></g>'),
    # Calculator.
    "org.gnome.Calculator": tile("#404046", "#18181b",
        "".join(f'<rect x="{34 + c * 22}" y="{34 + r * 22}" width="16" height="16" rx="8" '
                f'fill="{"#ff9f0a" if c == 2 else "#fff"}" opacity="{1 if c == 2 else 0.85}"/>'
                for r in range(3) for c in range(3))),
    # Image Viewer: a landscape.
    "org.gnome.Loupe": tile("#74c8ff", "#2f7be8",
        '<circle cx="80" cy="46" r="8" fill="#fff"/>'
        '<path d="M28 90l24-30 16 19 10-11 22 22z" fill="#fff"/>'),
    # Document Viewer.
    "org.gnome.Evince": tile("#ff6f61", "#cf3024",
        '<path d="M42 30h30l16 16v48a4 4 0 0 1-4 4H42a4 4 0 0 1-4-4V34a4 4 0 0 1 4-4z" fill="#fff"/>'
        '<path d="M72 30v12a4 4 0 0 0 4 4h12" fill="#f3b3ad"/>'
        + "".join(stroke(f"M48 {y}h{28 if i else 32}", color="#e0574b", width=4) for i, y in enumerate((62, 72, 82)))),
    # System Monitor.
    "org.gnome.SystemMonitor": tile("#38383d", "#0f0f11",
        stroke("M28 72h14l8-20 12 36 10-26 8 10h20", color="#30d158", width=5)),
    # Unsafe Browser: the globe, in red.
    "unsafe-browser": tile("#ff6159", "#b4231a",
        stroke("M64 36a28 28 0 1 0 0.01 0z M64 36c-9 8-13 18-13 28s4 20 13 28 M64 36c9 8 13 18 13 28s-4 20-13 28"
               " M37 56h54 M37 72h54", width=5)),
}


def folder(emboss=""):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="128" height="128">
<defs>
  <linearGradient id="f" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7cc3ff"/><stop offset="1" stop-color="#3d97f0"/></linearGradient>
  <filter id="s" x="-10%" y="-10%" width="120%" height="130%"><feDropShadow dx="0" dy="2" stdDeviation="2" flood-color="#000" flood-opacity="0.3"/></filter>
</defs>
<path d="M10 28a8 8 0 0 1 8-8h30l9 9h53a8 8 0 0 1 8 8v8H10z" fill="#3a8be6"/>
<g filter="url(#s)"><rect x="10" y="36" width="108" height="76" rx="9" fill="url(#f)"/></g>
<rect x="10.5" y="36.5" width="107" height="75" rx="8.5" fill="none" stroke="#fff" stroke-opacity="0.3"/>
<g transform="translate(64 75)" fill="none" stroke="#1f6fc9" stroke-width="5" stroke-linecap="round" stroke-linejoin="round" opacity="0.75">{emboss}</g>
</svg>
"""


PLACES = {
    "folder": "", "inode-directory": "",
    "user-home": '<path d="M-17 2l17-15 17 15 M-12 -2v16h24v-16"/>',
    "user-desktop": '<rect x="-17" y="-13" width="34" height="22" rx="3"/><path d="M-8 16h16"/>',
    "folder-documents": '<path d="M-11 -16h14l9 9v23h-23z M-5 1h11 M-5 8h11"/>',
    "folder-download": '<path d="M0 -16v26 M-11 -1l11 11 11-11 M-15 17h30"/>',
    "folder-pictures": '<rect x="-17" y="-13" width="34" height="26" rx="3"/><path d="M-13 9l9-10 7 7 4-4 9 7"/>',
    "folder-music": '<path d="M-6 10v-24l17-4v24"/><circle cx="-10" cy="11" r="4.5"/><circle cx="7" cy="7" r="4.5"/>',
    "folder-videos": '<rect x="-17" y="-12" width="25" height="24" rx="3"/><path d="M8 -4l10-6v20l-10-6"/>',
    "folder-templates": '<rect x="-14" y="-15" width="28" height="30" rx="3"/><path d="M-7 -5h14 M-7 3h14"/>',
    "folder-publicshare": '<circle cx="-9" cy="0" r="5"/><circle cx="10" cy="-10" r="5"/><circle cx="10" cy="10" r="5"/>'
                          '<path d="M-4 -3l9-5 M-4 3l9 5"/>',
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
    for sub, items in (("apps", APPS), ("places", {k: folder(v) for k, v in PLACES.items()})):
        d = os.path.join(OUT, "scalable", sub)
        os.makedirs(d, exist_ok=True)
        for name, svg in items.items():
            with open(os.path.join(d, name + ".svg"), "w") as f:
                f.write(svg)
    with open(os.path.join(OUT, "index.theme"), "w") as f:
        f.write(INDEX)
    print(f"{len(APPS)} apps, {len(PLACES)} places -> {os.path.normpath(OUT)}")


if __name__ == "__main__":
    main()
