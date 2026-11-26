#!/usr/bin/env bash
# Lethe installer. Run as your normal user; it asks for your password once.
#
#   ./install.sh               install or upgrade
#   ./install.sh --uninstall   remove everything, including the cached Tails image
#
# Arch/Omarchy, Debian 12+, Ubuntu 24.04+, Fedora, openSUSE. Works without
# hardware virtualisation too (slow software emulation).
set -euo pipefail

TARBALL="${LETHE_SRC:-https://github.com/cempack/lethe/archive/refs/heads/main.tar.gz}"
LIB=/usr/local/lib/lethe
NET_USER=lethe-net
say() { printf '\033[1;36m==>\033[0;1m %s\033[0m\n' "$*"; }
die() { printf 'install.sh: %s\n' "$*" >&2; exit 1; }

SUDO=sudo
[[ $EUID -eq 0 ]] && SUDO=
ME="${SUDO_USER:-$(id -un)}"

packages() {
  if command -v pacman >/dev/null; then
    $SUDO pacman -S --needed --noconfirm qemu-system-x86 qemu-hw-display-virtio-vga \
      qemu-hw-display-virtio-gpu qemu-hw-display-virtio-gpu-pci passt bubblewrap gnupg curl python python-gobject gtk4 \
      glib2 libnotify wireguard-tools iproute2 polkit
  elif command -v apt-get >/dev/null; then
    $SUDO apt-get update -q
    $SUDO apt-get install -y --no-install-recommends qemu-system-x86 passt bubblewrap gnupg curl ca-certificates \
      python3 python3-gi gir1.2-gtk-4.0 librsvg2-common libglib2.0-bin wireguard-tools iproute2 pkexec \
      || die "package install failed (Ubuntu 22.04 and older have no 'passt' package; 24.04+ is required)"
  elif command -v dnf >/dev/null; then
    $SUDO dnf install -y qemu-system-x86-core qemu-device-display-virtio-vga qemu-device-display-virtio-gpu \
      qemu-device-display-virtio-gpu-pci passt bubblewrap gnupg2 curl python3 python3-gobject gtk4 glib2 \
      librsvg2 wireguard-tools iproute polkit
  elif command -v zypper >/dev/null; then
    $SUDO zypper --non-interactive install qemu-x86 qemu-hw-display-virtio-vga qemu-hw-display-virtio-gpu \
      qemu-hw-display-virtio-gpu-pci passt bubblewrap gpg2 curl python3 python3-gobject \
      typelib-1_0-Gtk-4_0 glib2-tools wireguard-tools iproute2 polkit
  else
    die "unsupported distro: install qemu (x86), passt, bubblewrap, gnupg, curl, python3 + PyGObject + GTK 4, wireguard-tools, then re-run"
  fi
}

uninstall() {
  say "Removing Lethe"
  command -v lethe >/dev/null && lethe stop >/dev/null 2>&1 || true
  systemctl --user disable --now lethe-update.timer 2>/dev/null || true
  $SUDO systemctl disable --now lethe-net.socket lethe-vpn-net.socket lethe-vpn.service 2>/dev/null || true
  $SUDO rm -rf "$LIB" /etc/lethe /usr/local/bin/lethe /usr/local/share/applications/lethe.desktop \
    /usr/local/share/icons/hicolor/scalable/apps/lethe.svg /usr/local/share/icons/hicolor/256x256/apps/lethe.png \
    /etc/systemd/system/lethe-net.socket /etc/systemd/system/lethe-net@.service \
    /etc/systemd/system/lethe-vpn-net.socket /etc/systemd/system/lethe-vpn-net@.service \
    /etc/systemd/system/lethe-vpn.service /etc/systemd/user/lethe-update.service /etc/systemd/user/lethe-update.timer
  if [[ -f /etc/apparmor.d/lethe ]]; then
    $SUDO apparmor_parser -R /etc/apparmor.d/lethe 2>/dev/null || true
    $SUDO rm -f /etc/apparmor.d/lethe
  fi
  $SUDO systemctl daemon-reload 2>/dev/null || true
  id "$NET_USER" >/dev/null 2>&1 && $SUDO userdel "$NET_USER" || true
  rm -rf "${XDG_DATA_HOME:-$HOME/.local/share}/lethe" "${XDG_CONFIG_HOME:-$HOME/.config}/lethe"
  say "Done."
}

[[ ${1:-} == --uninstall ]] && { uninstall; exit 0; }
[[ $(uname -m) == x86_64 ]] || say "Note: not an x86_64 machine. Tails will run in software emulation, which is very slow."

say "Installing packages"
packages
[[ ${1:-} == --packages-only ]] && exit 0
[[ $EUID -ne 0 ]] || die "run as your normal user, not root (sudo is used where needed)"

# Use the files next to this script, or fetch them when piped from curl.
here="$(cd "$(dirname "${BASH_SOURCE[0]:-/nonexistent}")" 2>/dev/null && pwd || true)"
if [[ -z $here || ! -f $here/lethe/core.py ]]; then
  here=$(mktemp -d)
  trap 'rm -rf "$here"' EXIT
  say "Fetching Lethe"
  if command -v gh >/dev/null && gh repo clone cempack/lethe "$here/src" -- --depth 1 --quiet 2>/dev/null; then
    here="$here/src"                                    # private repository: needs your GitHub login
  else
    curl --proto =https --tlsv1.2 -fsSL "$TARBALL" | tar -xz --strip-components=1 -C "$here" || die "download failed"
  fi
fi

say "Installing Lethe (root-owned, so programs running as you cannot alter it)"
$SUDO rm -rf "$LIB"
$SUDO install -d -o root -g root -m 0755 "$LIB/lethe" "$LIB/guest" "$LIB/assets"
$SUDO install -o root -g root -m 0644 "$here"/lethe/*.py "$LIB/lethe/"
$SUDO install -o root -g root -m 0644 "$here"/guest/* "$LIB/guest/"
$SUDO install -o root -g root -m 0644 "$here"/assets/lethe.svg "$here"/assets/lethe.css \
  "$here"/assets/wallpaper.png "$here"/assets/wallpaper-online.png \
  "$here"/assets/Inter.ttf "$here"/assets/Inter-LICENSE.txt "$LIB/assets/"
$SUDO install -d -o root -g root -m 0755 "$LIB/assets/icons"
$SUDO install -o root -g root -m 0644 "$here"/assets/icons/*.svg "$LIB/assets/icons/"
$SUDO install -D -o root -g root -m 0755 "$here/lethe.py" /usr/local/bin/lethe
# The Sentinel compares Lethe's files against this list before every session.
(cd "$LIB" && find lethe guest assets -type f | sort | xargs sha256sum) | $SUDO tee "$LIB/MANIFEST" >/dev/null
$SUDO install -D -o root -g root -m 0644 "$here/assets/lethe.svg" /usr/local/share/icons/hicolor/scalable/apps/lethe.svg
$SUDO install -D -o root -g root -m 0644 "$here/assets/lethe.png" /usr/local/share/icons/hicolor/256x256/apps/lethe.png
$SUDO install -d /usr/local/share/applications
$SUDO tee /usr/local/share/applications/lethe.desktop >/dev/null <<'EOF'
[Desktop Entry]
Name=Lethe
GenericName=Private Session
Comment=An amnesic, sandboxed Tails session that leaves no memory
Exec=/usr/local/bin/lethe
Icon=lethe
Terminal=false
Type=Application
Categories=System;Security;Network;
StartupWMClass=org.lethe.App
EOF
command -v gtk-update-icon-cache >/dev/null && $SUDO gtk-update-icon-cache -q -t -f /usr/local/share/icons/hicolor 2>/dev/null || true

# Ubuntu 24.04+ forbids unprivileged user namespaces unless an AppArmor profile
# allows them; bubblewrap needs one. Only added when the sandbox cannot start.
if ! bwrap --unshare-all --ro-bind / / true 2>/dev/null; then
  if [[ $(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns 2>/dev/null) == 1 ]]; then
    say "Allowing the sandbox to create user namespaces (AppArmor profile 'lethe')"
    $SUDO tee /etc/apparmor.d/lethe >/dev/null <<'EOF'
abi <abi/4.0>,
include <tunables/global>

profile lethe flags=(unconfined) {
  userns,
  include if exists <local/lethe>
}
EOF
    $SUDO apparmor_parser -r /etc/apparmor.d/lethe
  else
    die "bubblewrap cannot create a sandbox here (unprivileged user namespaces are disabled)"
  fi
fi

if [[ -d /run/systemd/system ]]; then
  say "Installing the firewalled network relay (user '$NET_USER', public internet only)"
  id "$NET_USER" >/dev/null 2>&1 || $SUDO useradd --system --no-create-home --shell /usr/sbin/nologin "$NET_USER"
  PASST="$(command -v passt) $(/usr/local/bin/lethe _passt-args)"
  HARDENING='
NoNewPrivileges=yes
CapabilityBoundingSet=
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
ProtectClock=yes
ProtectHostname=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX AF_NETLINK
RestrictRealtime=yes
RestrictSUIDSGID=yes
LockPersonality=yes
MemoryDenyWriteExecute=yes
SystemCallArchitectures=native
UMask=0077'
  # Kernel firewall for the relay only: public internet (Tor), never this
  # machine, the LAN, VPN/Tailscale ranges or containers.
  DENY='IPAddressDeny=localhost link-local multicast 0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 172.16.0.0/12 192.0.0.0/24 192.168.0.0/16 198.18.0.0/15 240.0.0.0/4 fc00::/7 fec0::/10'

  socket_unit() {  # name, description
    $SUDO tee "/etc/systemd/system/$1.socket" >/dev/null <<EOF
[Unit]
Description=$2

[Socket]
ListenStream=/run/lethe/${1#lethe-}.sock
SocketUser=$ME
SocketMode=0600
DirectoryMode=0755
Accept=yes
MaxConnections=1

[Install]
WantedBy=sockets.target
EOF
  }
  socket_unit lethe-net "Lethe network socket"
  socket_unit lethe-vpn-net "Lethe VPN network socket"
  $SUDO sed -i 's|/run/lethe/vpn-net.sock|/run/lethe/vpn.sock|' /etc/systemd/system/lethe-vpn-net.socket

  # systemd hands each VM's already-connected socket to passt as fd 3.
  $SUDO tee /etc/systemd/system/lethe-net@.service >/dev/null <<EOF
[Unit]
Description=Lethe network relay (public internet only)
CollectMode=inactive-or-failed

[Service]
User=$NET_USER
ExecStart=$PASST
$DENY
$HARDENING
EOF
  # Same relay, started inside the WireGuard-only namespace: no tunnel, no route.
  $SUDO tee /etc/systemd/system/lethe-vpn-net@.service >/dev/null <<EOF
[Unit]
Description=Lethe network relay (WireGuard only)
Requires=lethe-vpn.service
After=lethe-vpn.service
CollectMode=inactive-or-failed

[Service]
User=$NET_USER
NetworkNamespacePath=/run/netns/lethe
ExecStart=$PASST
$HARDENING
EOF
  $SUDO tee /etc/systemd/system/lethe-vpn.service >/dev/null <<EOF
[Unit]
Description=Lethe WireGuard tunnel (VM only)
ConditionPathExists=/etc/lethe/wg.conf
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/python3 -I $LIB/lethe/vpn.py up
ExecStop=/usr/bin/python3 -I $LIB/lethe/vpn.py down

[Install]
WantedBy=multi-user.target
EOF
  $SUDO systemctl daemon-reload
  $SUDO systemctl enable --now lethe-net.socket lethe-vpn-net.socket
  $SUDO systemctl restart lethe-net.socket lethe-vpn-net.socket
  $SUDO systemctl enable lethe-vpn.service 2>/dev/null || true

  say "Enabling the daily background Tails update"
  $SUDO tee /etc/systemd/user/lethe-update.service >/dev/null <<'EOF'
[Unit]
Description=Download and verify the latest Tails image
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/lethe update
Nice=10
IOSchedulingClass=idle
EOF
  $SUDO tee /etc/systemd/user/lethe-update.timer >/dev/null <<'EOF'
[Unit]
Description=Check for new Tails releases daily

[Timer]
OnStartupSec=10min
OnUnitActiveSec=1d
RandomizedDelaySec=1h

[Install]
WantedBy=timers.target
EOF
  systemctl --user daemon-reload && systemctl --user enable --now lethe-update.timer || true
else
  say "No systemd: skipping the firewalled relay, the VPN and the update timer"
fi

if [[ -e /dev/kvm && ( ! -r /dev/kvm || ! -w /dev/kvm ) ]] && getent group kvm >/dev/null; then
  $SUDO usermod -aG kvm "$ME"
  say "Added $ME to the 'kvm' group: log out and back in for full speed"
elif [[ ! -e /dev/kvm ]]; then
  say "No hardware virtualisation found: Lethe will work, slowly. Enabling VT-x/AMD-V in your firmware fixes that."
fi

echo
/usr/local/bin/lethe doctor || true
echo
say "Installed. Open 'Lethe' from your app menu, or run: lethe"
