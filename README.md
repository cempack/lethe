# Lethe

A private session that leaves no memory. Lethe runs [Tails](https://tails.net) in a sealed, amnesic virtual machine inside one window, and erases it when you are done.

```sh
gh repo clone cempack/lethe && ./lethe/install.sh    # Arch/Omarchy, Debian 12+, Ubuntu 24.04+, Fedora, openSUSE
lethe             # open the app          (or "Lethe" in your app menu)
lethe start       # open and start a session right away
lethe stop        # destroy the running session immediately
lethe doctor      # audit every protection layer on this machine
```

## What happens when you press Start

1. The Tails image is checked against the Tails signing key (fingerprint pinned in the code). This happens on download and again before every start.
2. A sandbox is built and Tails boots inside it. No virtual disk exists.
3. Lethe passes the Tails Welcome Screen for you (English, US keyboard, the defaults most Tails users have), applies stricter settings and the Lethe appearance, and connects to Tor automatically (can be turned off in Preferences, e.g. to use bridges). It does this by pressing keys, like a person: the image stays byte-for-byte the signed original.
4. Your keyboard layout is translated as you type, so an AZERTY `a` is still an `a`.
5. **Clipboard, one way.** Copy text or an image on your computer, come back to the session and paste: it is already on Tails' clipboard. What a password manager copies is never shared (they mark it, and Lethe honours the mark). Lethe hands it over on a small read-only disc that the Lethe desktop reads; nothing copied in Tails ever leaves it. **Ctrl+Alt+V** types your clipboard's text instead, for places the clipboard cannot reach (the Welcome Screen). Turn sharing off under Session.
6. **The Lethe desktop** inside Tails: GNOME's own dock kept on the desktop (drag to reorder, right-click menus, running dots), Lethe's icon set for every app and folder (graphite tiles, each app drawn in its own colour), a graphite palette and a dusk wallpaper. The dock shrinks with the session window. It is a GNOME Shell extension that Lethe copies in and loads through Looking Glass right after login; the extension then switches Looking Glass off for the rest of the session.
7. The session has a window of its own. Tails runs at your screen's real resolution and follows that window as you resize it; text is scaled to match your screen. **Ctrl+Alt+F** switches to full screen and back; in full screen nothing of Lethe is drawn over Tails.
8. When the session ends, its memory is overwritten with zeros.

## Protection

| Layer | What it does |
|---|---|
| **Amnesia** | No virtual disk. Guest RAM is locked, kept out of swap and crash dumps, and zero-filled on exit. A separate guard process does the wipe if Lethe itself crashes or is killed. The session is destroyed before the computer suspends or hibernates. |
| **Integrity** | Signature check on every start. Lethe's own files are root-owned and compared against a manifest before each session. Once installed, Lethe finds QEMU, the sandbox and its other tools in system folders only, and ignores environment variables that would load foreign code into it. |
| **Network** | The VM has no network of its own. A separate relay (`passt`) carries its traffic: IPv4/TCP only, no inbound, no host DNS, fake addressing. Installed system-wide it runs as its own user behind a kernel firewall that only allows the public internet. |
| **VPN before Tor** | Optional WireGuard profile, for the VM only. The tunnel lives in its own network namespace and is the VM's only route: if it drops, nothing leaves. Profiles are treated as data; `PostUp`-style commands are dropped. |
| **Sandbox** | bubblewrap. The VM process sees its own binary, libraries, firmware and the image. No home folder, no D-Bus, no capabilities, no nested user namespaces, seccomp filter on. |
| **Memory privacy** | Lethe, the VM and the wipe guard are closed to your other programs: they cannot attach a debugger, read the processes' memory, or open the guest's memory through `/proc`. |
| **Display** | The VM never touches your desktop. QEMU shares the picture with Lethe over a private peer-to-peer D-Bus link (frames as fast as Tails draws them, shared memory, no copying), or over a private VNC socket where that is unavailable. Clipboard in one direction only (a read-only disc into the VM), no audio, USB or shared folders. |
| **Sentinel** | Watches the host during a session and destroys it if a debugger attaches, someone logs in remotely, or a new keyboard appears. Hides the session while the screen is being captured (Hyprland). |

## What it cannot do

- **Protect you from a compromised computer.** If the host's kernel or firmware is already controlled by someone else, they see everything. The Sentinel is a tripwire for realistic attacks, not an antivirus, and malware in the kernel can hide from it. For that threat, boot Tails from a USB stick on a machine you trust.
- **Hide that you use it.** The Tails image and Lethe are on your disk. Session content is not.
- **Wipe everything.** Main guest memory is zero-filled; small device buffers are freed, not wiped. Booting the host with `init_on_free=1` closes that gap.
- **Hide Tor from the network**, unless you use the VPN option or Tor bridges.

## Notes

- Tor Browser starts at the Safest level.
- Without hardware virtualisation Lethe still works, in slow software emulation.
- On mains power Lethe holds the "performance" power profile while a session runs, and releases it afterwards.
- Settings live in `~/.config/lethe/settings.json`. Uninstall with `./install.sh --uninstall`.

Inter typeface: SIL Open Font License, see `assets/Inter-LICENSE.txt`.
