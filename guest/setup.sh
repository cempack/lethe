#!/bin/sh
# Lethe guest hardening. Runs once inside Tails, as the unprivileged "amnesia"
# user, from a copy of the read-only LETHE config disc (the disc itself is gone by
# now). Everything here is stricter than the Tails defaults and vanishes with the
# session, like the rest of Tails.
g() { gsettings set "$@" 2>/dev/null; }

D="$HOME/.lethe"
chmod -R u+w "$D"
DISC=$(readlink -f /dev/disk/by-label/LETHE)

# Appearance. Stock GNOME settings plus a typeface; websites cannot see any of
# it, because Tor Browser reports the same theme and fonts for everyone.
mkdir -p "$HOME/.local/share/fonts"
cp "$D/inter.ttf" "$HOME/.local/share/fonts/Inter.ttf" && fc-cache -f "$HOME/.local/share/fonts" 2>/dev/null
g org.gnome.desktop.interface font-name 'Inter 11'
g org.gnome.desktop.interface document-font-name 'Inter 11'
g org.gnome.desktop.wm.preferences titlebar-font 'Inter Semi-Bold 11'
g org.gnome.desktop.interface color-scheme prefer-dark
g org.gnome.desktop.interface gtk-theme Adwaita-dark
g org.gnome.desktop.interface accent-color slate
g org.gnome.desktop.interface clock-show-weekday true
# The accessibility menu stays in Settings; it does not need a permanent place in the top bar.
g org.gnome.desktop.a11y always-show-universal-access-status false
g org.gnome.desktop.wm.preferences button-layout ':minimize,maximize,close'
g org.gnome.desktop.interface enable-hot-corners true
# No animations while Lethe's autopilot is at work (it reads the screen, and wants each one whole).
# The Lethe desktop turns them back on when it loads.
g org.gnome.desktop.interface enable-animations false
# Drop the two GNOME Classic panels (the "Apps" menu and the bottom window list)
# for a clean desktop; Tails' own Tor status and power menu stay. Apps and open
# windows are one click away in the top-left corner.
g org.gnome.shell enabled-extensions "['status-menu-helper@tails.boum.org', 'date@tails.boum.org', 'torstatus@tails.boum.org', 'no-overview@fthx', 'lethe@lethe']"
# The Lethe desktop: a dock, a quieter top bar and the receiving end of the one-way clipboard.
# Lethe loads it right after this script (GNOME would otherwise wait for the next login).
X="$HOME/.local/share/gnome-shell/extensions/lethe@lethe"
mkdir -p "$X"
cp "$D/ext.js" "$X/extension.js"
cp "$D/ext.css" "$X/stylesheet.css"
cp "$D/ext.jsn" "$X/metadata.json"
cp "$D/mark.svg" "$X/mark.svg"
# Text at the size you are used to: Lethe shows Tails pixel for pixel, at your screen's scale.
S=$(cat "$D/scale.txt" 2>/dev/null)
[ -n "$S" ] && g org.gnome.desktop.interface text-scaling-factor "$S"
# Lethe palette for every GTK app started from now on.
mkdir -p "$HOME/.config/gtk-4.0" "$HOME/.config/gtk-3.0"
cp "$D/gtk4.css" "$HOME/.config/gtk-4.0/gtk.css"
cp "$D/gtk3.css" "$HOME/.config/gtk-3.0/gtk.css"
# Title bars of older apps (Tor Connection, Tor Browser) are drawn by a helper that GNOME started
# before this stylesheet existed. GNOME starts it again at once, now in the Lethe palette.
pkill -u "$(id -u)" -x mutter-x11-frames 2>/dev/null
# The Tor Connection window was opened by Tails before any of this existed, in Tails' own colours.
# Nothing has been done in it yet: open it again, in Lethe's.
systemctl --user --quiet is-active tca && timeout 15 systemctl --user restart tca
g org.gnome.Console theme night
g org.gnome.nautilus.window-state initial-size '(1080, 700)'
g org.gnome.nautilus.icon-view default-zoom-level 'large'
g org.gnome.TextEditor style-variant dark
# Launcher favourites: what makes sense in a VM (no USB installer, no Persistent Storage).
g org.gnome.shell favorite-apps "['org.boum.tails.TorBrowser.desktop', 'tca.desktop', 'org.gnome.Nautilus.desktop', 'org.gnome.Console.desktop', 'org.gnome.World.Secrets.desktop', 'org.gnome.TextEditor.desktop', 'tails-documentation.desktop']"

# Keep no history of what was opened or used.
g org.gnome.desktop.privacy remember-recent-files false
g org.gnome.desktop.privacy remember-app-usage false
g org.gnome.desktop.privacy remove-old-temp-files true
g org.gnome.desktop.privacy remove-old-trash-files true
g org.gnome.desktop.privacy old-files-age 0
g org.gnome.desktop.privacy hide-identity true
g org.gnome.desktop.privacy send-software-usage-stats false
g org.gnome.desktop.privacy report-technical-problems false

# The VM has no camera or microphone; make sure nothing can ask for one.
g org.gnome.desktop.privacy disable-camera true
g org.gnome.desktop.privacy disable-microphone true

# Never open or run anything from media automatically.
g org.gnome.desktop.media-handling automount false
g org.gnome.desktop.media-handling automount-open false
g org.gnome.desktop.media-handling autorun-never true

# Nothing readable on a locked screen, no search leaving the machine.
g org.gnome.desktop.notifications show-in-lock-screen false
g org.gnome.desktop.search-providers disable-external true

# Tor Browser starts at the "Safest" security level: no JavaScript on any site,
# no remote fonts, media is click-to-play. Lower it from the shield icon if a
# site you trust needs it. The level is more than its one setting: the browser checks at start
# that every setting the level controls already has the level's value, and asks to restart if
# not. So all of them are written here, exactly as the browser itself writes them for "Safest".
# Tails creates the profile at login; only touch it while the browser is closed.
P="$HOME/.tor-browser/profile.default"
[ -d "$P" ] || /usr/local/lib/generate-tor-browser-profile >/dev/null 2>&1
if [ -d "$P" ] && ! pgrep -f firefox.real >/dev/null; then
  cat >"$P/user.js" <<'EOF'
user_pref("browser.security_level.security_slider", 1);
user_pref("browser.security_level.security_custom", false);
user_pref("javascript.options.ion", false);
user_pref("javascript.options.baselinejit", false);
user_pref("javascript.options.native_regexp", false);
user_pref("javascript.options.asmjs", false);
user_pref("javascript.options.wasm", true);
user_pref("mathml.disabled", true);
user_pref("svg.disabled", true);
user_pref("gfx.font_rendering.graphite.enabled", false);
user_pref("gfx.font_rendering.opentype_svg.enabled", false);
EOF
fi

# Lethe already tells you, before the session starts, that the host can see inside
# the VM. Tails would repeat it once its clock is synced: cancel that for this session.
systemctl --user mask --runtime tails-virt-notify-user.service 2>/dev/null
systemctl --user stop tails-virt-notify-user.service 2>/dev/null

# Lethe's wallpaper, last of all: Lethe is watching for it. When it appears, everything above is
# in place, and Lethe goes on (it takes the disc out and loads the Lethe desktop).
cp "$D/wall.png" "$HOME/.lethe-wallpaper.png" && {
  g org.gnome.desktop.background picture-uri "file://$HOME/.lethe-wallpaper.png"
  g org.gnome.desktop.background picture-uri-dark "file://$HOME/.lethe-wallpaper.png"
  # Centred, never scaled: the picture is dithered, cell by cell, and is larger than any screen.
  g org.gnome.desktop.background picture-options centered
  g org.gnome.desktop.background primary-color '#07080b'
  g org.gnome.desktop.screensaver picture-uri "file://$HOME/.lethe-wallpaper.png"
}

# Tell Lethe when Tor is connected, without any channel out of the VM: switch to a
# copy of the wallpaper that is 1.4% brighter. Invisible to you, measurable to Lethe.
cp "$D/online.png" "$HOME/.lethe-online.png"
(
  until systemctl --quiet is-active tails-tor-has-bootstrapped.target; do sleep 1; done
  g org.gnome.desktop.background picture-uri "file://$HOME/.lethe-online.png"
  g org.gnome.desktop.background picture-uri-dark "file://$HOME/.lethe-online.png"
) >/dev/null 2>&1 &

# Lethe takes the config disc out of its drive as soon as the wallpaper above appears. Tails still
# has it mounted then: let go of it a moment later, and it disappears from Files as well.
(sleep 6; udisksctl unmount -f -b "$DISC") >/dev/null 2>&1 &

touch "$HOME/.lethe-ready"
