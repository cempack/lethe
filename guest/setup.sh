#!/bin/sh
# Lethe guest hardening. Runs once inside Tails, as the unprivileged "amnesia"
# user, from the read-only LETHE config disc. Everything here is stricter than
# the Tails defaults and vanishes with the session, like the rest of Tails.
g() { gsettings set "$@" 2>/dev/null; }

# Copy everything off the disc first. Lethe ejects it as soon as the wallpaper
# changes below, so nothing after this point may read from the disc.
D="$HOME/.lethe"
mkdir -p "$D" && cp /media/amnesia/LETHE/* "$D/" && chmod -R u+w "$D"

# Brand wallpaper. Changing it is also the signal that the disc can go.
cp "$D/wall.png" "$HOME/.lethe-wallpaper.png" && {
  g org.gnome.desktop.background picture-uri "file://$HOME/.lethe-wallpaper.png"
  g org.gnome.desktop.background picture-uri-dark "file://$HOME/.lethe-wallpaper.png"
  g org.gnome.desktop.background picture-options zoom
  g org.gnome.desktop.screensaver picture-uri "file://$HOME/.lethe-wallpaper.png"
}

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
# Window buttons on the left, macOS order (restyled as coloured circles in gtk.css).
g org.gnome.desktop.wm.preferences button-layout 'close,minimize,maximize:'
g org.gnome.desktop.interface enable-hot-corners true
# The VM draws without a graphics card: animations only make it feel slow.
g org.gnome.desktop.interface enable-animations false
# Drop the two GNOME Classic panels (the "Apps" menu and the bottom window list)
# for a clean desktop; Tails' own Tor status and power menu stay. Apps and open
# windows are one click away in the top-left corner.
g org.gnome.shell enabled-extensions "['status-menu-helper@tails.boum.org', 'date@tails.boum.org', 'torstatus@tails.boum.org', 'no-overview@fthx']"
# Lethe palette for every GTK app started from now on.
mkdir -p "$HOME/.config/gtk-4.0" "$HOME/.config/gtk-3.0"
cp "$D/gtk4.css" "$HOME/.config/gtk-4.0/gtk.css"
cp "$D/gtk3.css" "$HOME/.config/gtk-3.0/gtk.css"
g org.gnome.Console theme night
g org.gnome.TextEditor style-variant dark
# Launcher favourites: what makes sense in a VM (no USB installer, no Persistent Storage).
g org.gnome.shell favorite-apps "['org.boum.tails.TorBrowser.desktop', 'tca.desktop', 'org.gnome.Nautilus.desktop', 'org.gnome.Console.desktop', 'org.gnome.World.Secrets.desktop', 'thunderbird.desktop', 'tails-documentation.desktop']"

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
# site you trust needs it.
# Tails creates the profile at login; only touch it while the browser is closed.
P="$HOME/.tor-browser/profile.default"
[ -d "$P" ] || /usr/local/lib/generate-tor-browser-profile >/dev/null 2>&1
if [ -d "$P" ] && ! pgrep -f firefox.real >/dev/null; then
  cat >"$P/user.js" <<'EOF'
user_pref("browser.security_level.security_slider", 1);
user_pref("browser.security_level.security_custom", false);
EOF
fi

# Lethe already tells you, before the session starts, that the host can see inside
# the VM. Tails would repeat it once its clock is synced: cancel that for this session.
systemctl --user mask --runtime tails-virt-notify-user.service 2>/dev/null
systemctl --user stop tails-virt-notify-user.service 2>/dev/null

# Tell Lethe when Tor is connected, without any channel out of the VM: switch to a
# copy of the wallpaper that is 1.4% brighter. Invisible to you, measurable to Lethe.
cp "$D/online.png" "$HOME/.lethe-online.png"
(
  until systemctl --quiet is-active tails-tor-has-bootstrapped.target; do sleep 1; done
  g org.gnome.desktop.background picture-uri "file://$HOME/.lethe-online.png"
  g org.gnome.desktop.background picture-uri-dark "file://$HOME/.lethe-online.png"
) >/dev/null 2>&1 &

touch "$HOME/.lethe-ready"
