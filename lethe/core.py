"""Lethe core: verified Tails images and the sandboxed, amnesic VM session.

Layers, outside in:
  1. Amnesia     no virtual disk. Guest RAM lives in a memory file that is locked,
                 kept out of swap and core dumps, and overwritten with zeros when
                 the session ends. The VM dies before the host sleeps.
  2. Integrity   the Tails image is checked against the pinned Tails signing key
                 on download and before every single boot.
  3. Network     QEMU has no network. A separate passt process relays traffic:
                 IPv4/TCP only, no inbound, no DNS, fake addressing; as a system
                 service it sits behind a kernel firewall (public internet only),
                 optionally inside a WireGuard-only network namespace.
  4. Sandbox     bubblewrap: QEMU sees its own binary, libraries, firmware and
                 the image. No home, no desktop socket, no D-Bus, no capabilities.
  5. Display     QEMU never touches the desktop. It exposes raw pixels on a
                 private socket; the Lethe window draws them and feeds input back.
"""
import fcntl, hashlib, json, os, re, resource, shutil, signal, socket, struct, subprocess, sys, threading, time

APP = "lethe"
DATA = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), APP)
CONFIG = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), APP, "settings.json")
RUNTIME = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
RT = os.path.join(RUNTIME, APP)
LIB = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
NET_SOCK, VPN_SOCK = "/run/lethe/net.sock", "/run/lethe/vpn.sock"   # created by install.sh
META_URL = "https://tails.net/install/v2/Tails/amd64/stable/latest.json"
KEY_URL = "https://tails.net/tails-signing.key"
# Tails signing key, pinned: https://tails.net/doc/about/openpgp_keys/
TAILS_FPR = "A490D0F4D311A4153E2BB7CADBB802B258ACD84F"
CURL = ["curl", "--proto", "=https", "--proto-redir", "=https", "--tlsv1.2", "-fL", "--retry", "3"]
# cpus 0 = automatic: half the cores, at most 4
DEFAULTS = {"ram_mb": 4096, "cpus": 0, "width": 1920, "height": 1080, "skip_welcome": True,
            "harden_guest": True, "auto_tor": True, "vpn": False, "sentinel": True}


class LetheError(Exception):
    pass


def read(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def settings():
    try:
        with open(CONFIG) as f:
            return {**DEFAULTS, **{k: v for k, v in json.load(f).items() if k in DEFAULTS}}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save_settings(cfg):
    os.makedirs(os.path.dirname(CONFIG), mode=0o700, exist_ok=True)
    with open(CONFIG, "w") as f:
        json.dump(cfg, f, indent=2)


# ── Tails image: download and verification ───────────────────────────────────

def current_version():
    return read(os.path.join(DATA, "current"))


def iso_path(version):
    return os.path.join(DATA, f"tails-amd64-{version}.iso")


def current_iso():
    v = current_version()
    return iso_path(v) if v and os.path.isfile(iso_path(v)) else None


def latest(timeout=30):
    """(version, url, sha256, size) of the latest stable image, from tails.net."""
    out = subprocess.run([*CURL, "-sS", "--max-time", str(timeout), META_URL], capture_output=True, check=True).stdout
    inst = json.loads(out)["installations"][0]
    f = next(p for p in inst["installation-paths"] if p["type"] == "iso")["target-files"][0]
    version, url, sha = str(inst["version"]), f["url"], f["sha256"]
    if not (re.fullmatch(r"[0-9a-z.~]+", version) and url.startswith("https://download.tails.net/")
            and re.fullmatch(r"[0-9a-f]{64}", sha)):
        raise ValueError("unexpected release metadata")
    return version, url, sha, int(f.get("size", 0))


def signed_by_tails(iso, sig, key):
    """True only if `sig` is a valid signature of `iso` made by the pinned Tails key.

    The key file is untrusted input: whatever it holds, the result counts only
    when gpg reports the pinned primary-key fingerprint.
    """
    home = os.path.join(RUNTIME, f"{APP}-gpg-{os.getpid()}-{threading.get_ident()}")
    os.makedirs(home, mode=0o700, exist_ok=True)
    try:
        env = {"GNUPGHOME": home, "PATH": "/usr/bin:/bin", "LC_ALL": "C"}
        subprocess.run(["gpg", "--batch", "--quiet", "--no-autostart", "--import", key], env=env, capture_output=True)
        out = subprocess.run(["gpg", "--batch", "--no-autostart", "--status-fd", "1", "--verify", sig, iso],
                             env=env, capture_output=True, text=True).stdout
        # "[GNUPG:] VALIDSIG <signing-subkey-fpr> ... <primary-key-fpr>"
        return any(len(l.split()) > 2 and l.split()[1] == "VALIDSIG" and l.split()[-1] == TAILS_FPR
                   for l in out.splitlines())
    finally:
        shutil.rmtree(home, ignore_errors=True)


def update(progress=lambda text, fraction: None):
    """Download and verify the latest Tails image. Returns its version."""
    os.makedirs(DATA, mode=0o700, exist_ok=True)
    lock = open(os.path.join(DATA, ".lock"), "w")
    fcntl.flock(lock, fcntl.LOCK_EX)   # the daily timer and the app can overlap
    try:
        progress("Checking for the latest Tails release", None)
        try:
            version, url, sha, size = latest()
        except Exception as e:
            raise LetheError(f"Could not reach tails.net ({e})")
        iso, key = iso_path(version), os.path.join(DATA, "tails-signing.key")
        sig, part = iso + ".sig", iso + ".part"
        if current_version() == version and os.path.isfile(iso) and os.path.isfile(sig):
            return version
        if not os.path.isfile(iso):
            dl = subprocess.Popen([*CURL, "-sS", "-C", "-", "-o", part, url])
            while dl.poll() is None:
                have = os.path.getsize(part) if os.path.exists(part) else 0
                progress(f"Downloading Tails {version}", have / size if size else None)
                time.sleep(0.3)
            if dl.returncode != 0 and not (os.path.exists(part) and os.path.getsize(part) == size):
                raise LetheError("Download failed. Check your connection and try again.")
            progress("Checking the download fingerprint", None)
            h = hashlib.sha256()
            with open(part, "rb") as f:
                while chunk := f.read(1 << 20):
                    h.update(chunk)
            if h.hexdigest() != sha:
                os.unlink(part)
                raise LetheError("The download was corrupted or tampered with. It has been discarded.")
        else:
            part = iso
        progress("Verifying the Tails signature", None)
        subprocess.run([*CURL, "-sS", "-o", key, KEY_URL], check=True)
        subprocess.run([*CURL, "-sS", "-o", sig + ".part", url + ".sig"], check=True)
        if not signed_by_tails(part, sig + ".part", key):
            os.unlink(part)
            raise LetheError("The image is NOT signed by the Tails developers. It has been discarded.")
        os.replace(sig + ".part", sig)
        os.replace(part, iso)
        os.chmod(iso, 0o400)
        with open(os.path.join(DATA, "current"), "w") as f:
            f.write(version + "\n")
        for name in os.listdir(DATA):
            if name.startswith("tails-amd64-") and not name.startswith(f"tails-amd64-{version}.iso"):
                os.unlink(os.path.join(DATA, name))
        return version
    finally:
        lock.close()


# ── Config disc: a tiny read-only ISO 9660 image handed to the guest ─────────

def build_iso(label, files):
    """Minimal single-directory ISO 9660 image. `files` maps 8.3 NAMES to bytes."""
    SEC = 2048
    both32 = lambda v: struct.pack("<I", v) + struct.pack(">I", v)
    both16 = lambda v: struct.pack("<H", v) + struct.pack(">H", v)
    stamp = bytes([120, 1, 1, 0, 0, 0, 0])   # fixed date: the disc never reveals the host clock

    def record(name, extent, size, is_dir):
        name += b"" if len(name) % 2 else b"\0"
        return (bytes([33 + len(name), 0]) + both32(extent) + both32(size) + stamp
                + bytes([2 if is_dir else 0, 0, 0]) + both16(1) + bytes([len(name.rstrip(b"\0")) or 1]) + name)

    names = sorted(files)
    extent, layout = 21, {}
    for n in names:
        layout[n] = extent
        extent += -(-len(files[n]) // SEC) or 1
    root = record(b"\0", 20, SEC, True) + record(b"\1", 20, SEC, True)
    root += b"".join(record(n.encode() + b";1", layout[n], len(files[n]), False) for n in names)
    pad = lambda b, n=SEC: b + b"\0" * (n - len(b))
    text = lambda s, n: s.encode().ljust(n, b" ")
    pvd = (b"\x01CD001\x01\0" + text("", 32) + text(label, 32) + b"\0" * 8 + both32(extent) + b"\0" * 32
           + both16(1) + both16(1) + both16(SEC) + both32(10) + struct.pack("<II", 18, 0) + struct.pack(">II", 19, 0)
           + record(b"\0", 20, SEC, True) + text("", 128) * 4 + text("", 37) * 3 + (b"0" * 16 + b"\0") * 4 + b"\x01\0")
    ptable = lambda fmt: bytes([1, 0]) + struct.pack(fmt + "IH", 20, 1) + b"\0\0"
    img = b"\0" * (16 * SEC) + pad(pvd) + pad(b"\xffCD001\x01") + pad(ptable("<")) + pad(ptable(">")) + pad(root)
    for n in names:
        img += pad(files[n], (-(-len(files[n]) // SEC) or 1) * SEC)
    return img


# ── Host checks ──────────────────────────────────────────────────────────────

def disk_swap():
    return [l.split()[0] for l in read("/proc/swaps").splitlines()[1:] if "zram" not in l.split()[0]]


def cgroup_noswap():
    cg = read("/proc/self/cgroup").split("::")[-1]
    return read(f"/sys/fs/cgroup{cg}/memory.swap.max") == "0"


def enter_noswap_scope(argv):
    """Re-exec inside a cgroup that the kernel may never swap. Everything Lethe
    holds (guest RAM, the copy of the guest screen) then stays off the disk."""
    if cgroup_noswap() or "LETHE_SCOPED" in os.environ or not shutil.which("systemd-run"):
        return
    scope = ["systemd-run", "--user", "--scope", "--quiet", "--collect", "-p", "MemorySwapMax=0"]
    if subprocess.run([*scope, "true"], capture_output=True).returncode == 0:
        os.execvpe(scope[0], [*scope, "--", *argv], {**os.environ, "LETHE_SCOPED": "1"})


def memlock_ok(ram_mb):
    soft, hard = resource.getrlimit(resource.RLIMIT_MEMLOCK)
    try:
        resource.setrlimit(resource.RLIMIT_MEMLOCK, (hard, hard))
    except (ValueError, OSError):
        hard = soft
    return hard == resource.RLIM_INFINITY or hard >= (ram_mb + 2048) << 20


def passt_args(fd):
    """Flags for passt, limited to what the installed version understands."""
    h = subprocess.run(["passt", "--help"], capture_output=True, text=True)
    h = h.stdout + h.stderr
    args = ["passt", "-f", "--fd", str(fd), "-4",
            "-a", "10.0.2.15", "-n", "255.255.255.0", "-g", "10.0.2.2",   # fake addressing: hide the real LAN
            "-D", "none",                  # no DNS from the host: Tails resolves through Tor
            "--no-map-gw",                 # the "gateway" is not this machine
            "-t", "none", "-u", "none"]    # nothing can connect inwards
    for flag, value in (("--no-icmp", None), ("--no-udp", None), ("--map-guest-addr", "none")):
        if flag in h:                      # Tor only needs TCP; newer passt can drop the rest
            args += [flag] + ([value] if value else [])
    return args


def vpn_profile():
    """Name of the imported WireGuard profile, or None."""
    return read("/etc/lethe/vpn.name") or None


def vpn_up():
    """The WireGuard-only namespace exists (created by lethe-vpn.service) and its relay socket is there."""
    return os.path.exists("/run/netns/lethe") and os.path.exists(VPN_SOCK)


MODULES = os.environ.get("LETHE_QEMU_MODULE_DIR")     # developer override: extra QEMU modules to load


def fast_display():
    """True if QEMU's virtio display is usable here. It lets the VM follow the window
    size and hand its pointer to us to draw without lag. Plain VGA is the fallback.

    Decided by looking, never by trying: on distros that ship the display as separate
    modules, QEMU crashes outright when one of the three is missing.
    """
    dirs = [d for d in ("/usr/lib/qemu", "/usr/lib64/qemu", "/usr/lib/x86_64-linux-gnu/qemu", MODULES) if d and os.path.isdir(d)]
    have = {name.split(".")[0] for d in dirs for name in os.listdir(d)}
    if "hw-display-virtio-vga" in have:                      # modular build: all three parts must be present
        return {"hw-display-virtio-gpu", "hw-display-virtio-gpu-pci"} <= have
    try:                                                     # built in, or not there at all: the device list says which
        out = subprocess.run(["qemu-system-x86_64", "-device", "help"], capture_output=True, text=True, timeout=10).stdout
        return '"virtio-vga"' in out
    except (OSError, subprocess.SubprocessError):
        return False


def dbus_display():
    """True if QEMU can hand frames over D-Bus (immediate, shared memory) instead of VNC (30 ms polling)."""
    try:
        out = subprocess.run(["qemu-system-x86_64", "-display", "help"], capture_output=True, text=True, timeout=10,
                             env={**os.environ, **({"QEMU_MODULE_DIR": MODULES} if MODULES else {})}).stdout
        return "dbus" in out.split()
    except (OSError, subprocess.SubprocessError):
        return False


def has_kvm():
    return os.access("/dev/kvm", os.R_OK | os.W_OK)


def running():
    pid = read(os.path.join(RT, "pid"))
    return int(pid) if pid.isdigit() and os.path.exists(f"/proc/{pid}") else None


# ── The session ──────────────────────────────────────────────────────────────

class Session:
    """One amnesic VM, from sandbox construction to memory wipe."""

    def __init__(self, cfg, stage=lambda name: None):
        self.cfg, self.stage = cfg, stage
        self.vm = self.ram_fd = None
        self.kvm, self.virtio, self.dbus = True, False, False
        self.helpers, self.why, self.started = [], None, None
        self.vnc_path, self.qmp_path = os.path.join(RT, "q", "vnc.sock"), os.path.join(RT, "q", "qmp.sock")

    def start(self):
        cfg = self.cfg
        if running():
            raise LetheError("Another session is already running. End it first.")
        iso = current_iso()
        if not iso:
            raise LetheError("No verified Tails image yet.")
        for tool in ("qemu-system-x86_64", "bwrap", "passt", "gpg"):
            if not shutil.which(tool):
                raise LetheError(f"{tool} is not installed. Run the Lethe installer again.")
        # Any computer: without KVM fall back to software emulation (slow, still sandboxed),
        # and size the VM to what this machine can actually spare.
        self.kvm = has_kvm()
        free_mb = int(re.search(r"MemAvailable:\s+(\d+)", read("/proc/meminfo")).group(1)) // 1024
        if free_mb < 2600:
            raise LetheError(f"Only {free_mb} MB of memory is free. Tails needs about 2 GB: close some apps and retry.")
        cfg = self.cfg = {**cfg, "ram_mb": max(2048, min(cfg["ram_mb"], free_mb - 1024)),
                          "cpus": max(1, min(cfg["cpus"] or 4, (os.cpu_count() or 2) // 2 or 1))}
        locked = memlock_ok(cfg["ram_mb"])
        if not (locked or cgroup_noswap()) and disk_swap():
            raise LetheError("Guest memory could leak into the on-disk swap; refusing to start.")

        self.stage("integrity")
        if not signed_by_tails(iso, iso + ".sig", os.path.join(DATA, "tails-signing.key")):
            raise LetheError("The Tails image on disk was modified after it was verified. Download it again.")

        self.stage("sandbox")
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))   # a crash must never write guest RAM to disk
        shutil.rmtree(RT, ignore_errors=True)
        os.makedirs(os.path.join(RT, "q"), mode=0o700)
        with open(os.path.join(RT, "passwd"), "w") as f:
            f.write("vm:x:1000:1000::/:/usr/bin/false\n")
        size = cfg["ram_mb"] << 20
        self.ram_fd = os.memfd_create("lethe-ram")           # guest RAM: ours to wipe afterwards
        os.ftruncate(self.ram_fd, size)
        os.set_inheritable(self.ram_fd, True)

        self.virtio = fast_display()
        self.dbus = self.virtio and dbus_display()
        # D-Bus normally identifies a peer by its process ID, which does not exist inside the
        # sandbox's process namespace. Instead, the two sides prove themselves with a secret
        # cookie in a folder only this session can read (and which is deleted with it).
        self.keyring = os.path.join(RT, "q", "keyring")
        if self.dbus:
            os.makedirs(self.keyring, mode=0o700)
        qemu_bin = os.path.realpath(shutil.which("qemu-system-x86_64"))
        bwrap = ["bwrap", "--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL", "--clearenv",
                 "--hostname", "localhost", "--uid", "1000", "--gid", "1000", "--setenv", "PATH", "/usr/bin",
                 "--proc", "/proc", "--dev", "/dev", *(["--dev-bind", "/dev/kvm", "/dev/kvm"] if self.kvm else []),
                 "--tmpfs", "/tmp", "--tmpfs", "/run", "--bind", os.path.join(RT, "q"), "/run/q",
                 "--tmpfs", "/etc", "--ro-bind", os.path.join(RT, "passwd"), "/etc/passwd",
                 "--dir", "/usr/bin", "--ro-bind", qemu_bin, qemu_bin, "--ro-bind", iso, "/tails.iso",
                 *(["--setenv", "G_DBUS_COOKIE_SHA1_KEYRING_DIR", "/run/q/keyring"] if self.dbus else [])]
        for d in ("/usr/lib", "/usr/lib32", "/usr/lib64", "/usr/libx32", "/lib", "/lib32", "/lib64", "/libx32", "/bin"):
            if os.path.islink(d):                               # mirror the host's /usr layout
                bwrap += ["--symlink", os.readlink(d), d]
            elif os.path.isdir(d):
                bwrap += ["--ro-bind", d, d]
        for p in ("/usr/share/qemu", "/usr/share/seabios", "/usr/share/seavgabios", "/usr/share/qemu-kvm",
                  "/etc/ld.so.cache", "/etc/ld.so.conf", "/etc/ld.so.conf.d"):
            if os.path.exists(p):
                bwrap += ["--ro-bind", p, p]

        if MODULES:
            bwrap += ["--ro-bind", MODULES, MODULES, "--setenv", "QEMU_MODULE_DIR", MODULES]

        drives = ["-drive", "if=none,id=cd,media=cdrom,readonly=on,format=raw,file=/tails.iso",
                  "-device", "ide-cd,drive=cd,bus=ide.0,bootindex=0"]
        if cfg["harden_guest"]:
            disc = os.path.join(RT, "config.iso")
            files = {"SETUP.SH": "guest/setup.sh", "GTK4.CSS": "guest/gtk4.css", "GTK3.CSS": "guest/gtk3.css",
                     "WALL.PNG": "assets/wallpaper.png",
                     "ONLINE.PNG": "assets/wallpaper-online.png", "INTER.TTF": "assets/Inter.ttf"}
            with open(disc, "wb") as f:
                f.write(build_iso("LETHE", {n: open(os.path.join(LIB, p), "rb").read() for n, p in files.items()}))
            bwrap += ["--ro-bind", disc, "/config.iso"]
            drives += ["-drive", "if=none,id=cfg,media=cdrom,readonly=on,format=raw,file=/config.iso",
                       "-device", "ide-cd,drive=cfg,bus=ide.1,id=cfgdisc"]

        self.stage("network")
        net, vpn = self._network()
        os.set_inheritable(net.fileno(), True)

        self.stage("boot")
        qemu = [qemu_bin, "-name", "vm,process=lethe-qemu",
                "-machine", f"q35,accel={'kvm' if self.kvm else 'tcg'},vmport=off,dump-guest-core=off,"
                            "mem-merge=off,memory-backend=ram",
                "-object", f"memory-backend-file,id=ram,size={size},mem-path=/proc/self/fd/{self.ram_fd},share=on",
                "-cpu", f"{'host' if self.kvm else 'max'},model-id=Virtual CPU",   # hide the real CPU name "-smp", str(cfg["cpus"]), "-m", f"{cfg['ram_mb']}M",
                *(["-overcommit", "mem-lock=on"] if locked else []),
                "-nodefaults", "-no-user-config", *drives,
                "-netdev", f"socket,id=net0,fd={net.fileno()}", "-device", "virtio-net-pci,netdev=net0,romfile=",
                "-device", "virtio-rng-pci",
                "-device", "virtio-tablet-pci",      # absolute pointer without emulating a USB controller
                "-device", "virtio-keyboard-pci",    # keys arrive in a queue, not through an emulated 8042 chip
                # virtio: resizable, pointer drawn by us. VGA: smallest possible device, fixed size.
                "-device", (f"virtio-vga,xres={cfg['width']},yres={cfg['height']}" if self.virtio
                            else f"VGA,vgamem_mb=32,xres={cfg['width']},yres={cfg['height']}"),
                *(["-display", "dbus,p2p=on"] if self.dbus else ["-display", "none", "-vnc", "unix:/run/q/vnc.sock"]),
                "-qmp", "unix:/run/q/qmp.sock,server=on,wait=off",
                "-serial", "none", "-parallel", "none",
                "-sandbox", "on,obsolete=deny,elevateprivileges=deny,spawn=deny,resourcecontrol=deny"]
        aa = ["aa-exec", "-p", "lethe", "--"] if os.path.exists("/etc/apparmor.d/lethe") and shutil.which("aa-exec") else []
        self.helpers += self._sleep_guard()
        # On mains power, hold the "performance" power profile for the life of the session.
        # The hold belongs to this helper process, so it ends when the session does.
        mains = [read(f"/sys/class/power_supply/{d}/online") for d in os.listdir("/sys/class/power_supply")
                 if read(f"/sys/class/power_supply/{d}/type") == "Mains"] if os.path.isdir("/sys/class/power_supply") else []
        if shutil.which("powerprofilesctl") and "0" not in mains:
            self.helpers.append(subprocess.Popen(
                ["powerprofilesctl", "launch", "-p", "performance", "-r", "Private session", "-i", "org.lethe.App",
                 "sleep", "infinity"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        self.vm = subprocess.Popen([*aa, *bwrap, "--", *qemu], pass_fds=[net.fileno(), self.ram_fd],
                                   stdin=subprocess.DEVNULL, stderr=subprocess.PIPE)
        net.close()
        self.started = time.time()
        with open(os.path.join(RT, "pid"), "w") as f:
            f.write(str(self.vm.pid))
        for _ in range(100):                                    # wait for QEMU's sockets
            if os.path.exists(self.qmp_path) and (self.dbus or os.path.exists(self.vnc_path)):
                return vpn
            if self.vm.poll() is not None:
                err = self.vm.stderr.read().decode(errors="replace").strip().splitlines()
                raise LetheError("The virtual machine failed to start" + (f": {err[-1]}" if err else "."))
            time.sleep(0.05)
        raise LetheError("The virtual machine did not come up in time.")

    def _network(self):
        """Returns (connected socket for QEMU, vpn_in_use)."""
        if self.cfg["vpn"]:
            # Fail closed: with the VPN switched on there is no fallback route.
            if not vpn_up():
                raise LetheError("VPN is switched on but the WireGuard tunnel is not up. Nothing was sent unprotected.")
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                s.connect(VPN_SOCK)
            except OSError as e:
                raise LetheError(f"The VPN tunnel is not available ({e.strerror}). Nothing was sent unprotected.")
            return s, True
        if os.path.exists(NET_SOCK):
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(NET_SOCK)
            return s, False
        ours, theirs = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)   # not installed system-wide
        self.helpers.append(subprocess.Popen(passt_args(theirs.fileno()), pass_fds=[theirs.fileno()],
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        theirs.close()
        return ours, False

    def _sleep_guard(self):
        """Destroy the VM before the host suspends or hibernates: hibernation
        writes all RAM, locked or not, to disk."""
        if not shutil.which("systemd-inhibit"):
            return []
        inhibit = ["systemd-inhibit", "--what=sleep", "--who=Lethe", "--why=Destroying the session before sleeping"]
        if shutil.which("gdbus"):
            mon = ["gdbus", "monitor", "--system", "--dest", "org.freedesktop.login1",
                   "--object-path", "/org/freedesktop/login1"]
        elif shutil.which("dbus-monitor"):
            mon = ["dbus-monitor", "--system",
                   "type='signal',interface='org.freedesktop.login1.Manager',member='PrepareForSleep'"]
        else:   # cannot watch for sleep, so forbid it while the session lives
            return [subprocess.Popen([*inhibit, "--mode=block", "sleep", "infinity"])]
        holder = subprocess.Popen([*inhibit, "--mode=delay", "sleep", "infinity"])
        watcher = subprocess.Popen(mon, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

        def watch():
            armed = False
            for line in watcher.stdout:
                armed = armed or "PrepareForSleep" in line
                if armed and re.search(r"\(true,\)|boolean true", line):
                    self.destroy("The computer was going to sleep")
                    holder.kill()
                    return
                if armed and re.search(r"\(false,\)|boolean false", line):
                    armed = False

        threading.Thread(target=watch, daemon=True).start()
        return [holder, watcher]

    def alive(self):
        return self.vm is not None and self.vm.poll() is None

    def destroy(self, why=None):
        self.why = self.why or why
        if self.alive():
            self.vm.kill()

    def finish(self, progress=lambda fraction: None):
        """Reap the VM, overwrite its memory with zeros, remove every trace."""
        self.destroy()
        if self.vm:
            self.vm.wait()
        for h in self.helpers:
            h.kill()
        wiped = 0
        if self.ram_fd is not None:
            size, zeros, off = os.fstat(self.ram_fd).st_size, memoryview(bytes(8 << 20)), 0
            try:
                while off < size:
                    off = os.lseek(self.ram_fd, off, os.SEEK_DATA)    # skip pages the guest never touched
                    end = os.lseek(self.ram_fd, off, os.SEEK_HOLE)
                    while off < end:
                        n = os.pwrite(self.ram_fd, zeros[:min(len(zeros), end - off)], off)
                        off, wiped = off + n, wiped + n
                        progress(off / size)
            except OSError:
                pass                                                  # ENXIO: no more data
            os.close(self.ram_fd)
            self.ram_fd = None
        shutil.rmtree(RT, ignore_errors=True)
        return wiped


# ── Audit ────────────────────────────────────────────────────────────────────

class Check:
    """One protection layer. state: ok | warn | bad. value: one word for the UI. detail: one sentence."""
    __slots__ = ("key", "state", "title", "value", "detail")

    def __init__(self, key, state, title, value, detail):
        self.key, self.state, self.title, self.value, self.detail = key, state, title, value, detail

    def __iter__(self):                      # (state, title, detail), for plain listings
        return iter((self.state, self.title, self.detail))


def audit(cfg=None):
    """Every protection layer on this machine, in the order the UI shows them."""
    cfg = cfg or settings()
    checks = []

    def add(key, ok, title, good, bad, sev="bad"):
        checks.append(Check(key, "ok" if ok else sev, title, *(good if ok else bad)))

    missing = [t for t in ("qemu-system-x86_64", "bwrap", "passt", "gpg", "curl") if not shutil.which(t)]
    if missing:
        add("components", False, "Components", None, ("Missing", "Not installed: " + ", ".join(missing)))
    v = current_version()
    add("image", bool(current_iso()), "Tails image", ("Verified", f"Tails {v}. The signature is checked before every start."),
        ("Not yet", "Downloaded and verified the first time you start."), "warn")
    add("isolation", has_kvm(), "Isolation", ("Hardware", "Sealed virtual machine with no disk, inside a sandbox."),
        ("Software", "No hardware virtualisation: sealed, but slow."), "warn")
    safe = memlock_ok(cfg["ram_mb"]) or cgroup_noswap() or not disk_swap() or bool(shutil.which("systemd-run"))
    add("memory", safe, "Memory", ("Locked", "Never swapped to disk. Overwritten with zeros when the session ends."),
        ("Exposed", "Session memory could be written to the swap file."))
    if cfg["vpn"]:
        add("network", vpn_up(), "Network", (vpn_profile() or "VPN", "WireGuard is the only route. If it drops, nothing leaves."),
            ("VPN down", "The VPN is on but its tunnel is not up. Sessions will not start."))
    else:
        add("network", os.path.exists(NET_SOCK), "Network", ("Firewalled", "Public internet only. Your network and this computer are unreachable."),
            ("Open", "Not walled off from your local network. Run the installer to fix this."), "warn")
    add("display", True, "Display", ("Isolated", "No access to your desktop, clipboard, camera or microphone."), None)
    add("sleep", bool(shutil.which("systemd-inhibit")), "Sleep", ("Guarded", "The session is destroyed before the computer sleeps."),
        ("Unguarded", "Sleep cannot be intercepted on this system."), "warn")
    add("integrity", os.stat(os.path.join(LIB, "lethe", "core.py")).st_uid == 0, "Integrity",
        ("Sealed", "Lethe's own files are root-owned and checked before each session."),
        ("Unsealed", "Running from a folder your user can modify."), "warn")
    return checks
