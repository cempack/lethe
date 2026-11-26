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
3. Lethe passes the Tails Welcome Screen for you (English, US keyboard, the defaults most Tails users have) and applies stricter settings and the Lethe appearance. It does this by pressing keys, like a person: the image stays byte-for-byte the signed original.
4. Your keyboard layout is translated as you type, so an AZERTY `a` is still an `a`.
5. When the session ends, its memory is overwritten with zeros.

## Protection

| Layer | What it does |
|---|---|
| **Amnesia** | No virtual disk. Guest RAM is locked, kept out of swap and crash dumps, and zero-filled on exit. The session is destroyed before the computer suspends or hibernates. |
| **Integrity** | Signature check on every start. Lethe's own files are root-owned and compared against a manifest before each session. |
| **Network** | The VM has no network of its own. A separate relay (`passt`) carries its traffic: IPv4/TCP only, no inbound, no host DNS, fake addressing. Installed system-wide it runs as its own user behind a kernel firewall that only allows the public internet. |
| **VPN before Tor** | Optional WireGuard profile, for the VM only. The tunnel lives in its own network namespace and is the VM's only route: if it drops, nothing leaves. Profiles are treated as data; `PostUp`-style commands are dropped. |
| **Sandbox** | bubblewrap. The VM process sees its own binary, libraries, firmware and the image. No home folder, no D-Bus, no capabilities, seccomp filter on. |
| **Display** | The VM never touches your desktop. It exposes pixels on a private socket; Lethe draws them and feeds input back. No clipboard, audio, USB or shared folders. |
| **Sentinel** | Watches the host during a session and destroys it if a debugger attaches, someone logs in remotely, or a new keyboard appears. Hides the session while the screen is being captured (Hyprland). |

## What it cannot do

- **Protect you from a compromised computer.** If the host's kernel or firmware is already controlled by someone else, they see everything. The Sentinel is a tripwire for realistic attacks, not an antivirus, and malware in the kernel can hide from it. For that threat, boot Tails from a USB stick on a machine you trust.
- **Hide that you use it.** The Tails image and Lethe are on your disk. Session content is not.
- **Wipe everything.** Main guest memory is zero-filled; small device buffers are freed, not wiped. Booting the host with `init_on_free=1` closes that gap.
- **Hide Tor from the network**, unless you use the VPN option or Tor bridges.

## Notes

- Tor Browser starts at the Safest level. On first launch it asks once to restart to finish applying it.
- Without hardware virtualisation Lethe still works, in slow software emulation.
- On mains power Lethe holds the "performance" power profile while a session runs, and releases it afterwards.
- Settings live in `~/.config/lethe/settings.json`. Uninstall with `./install.sh --uninstall`.

Inter typeface: SIL Open Font License, see `assets/Inter-LICENSE.txt`.
