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
                 Everything in it is closed to the user's other programs (seal.py).
  5. Display     QEMU never touches the desktop. It exposes raw pixels on a
                 private socket; the Lethe window draws them and feeds input back.
"""
import errno, fcntl, hashlib, json, os, re, resource, select, shutil, signal, socket, struct, subprocess, sys
import threading, time, types

from . import seal
from .wiper import clear, hide, scrub, wipe

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
# -q: ignore ~/.curlrc, which could redirect or weaken any of this.
CURL = ["curl", "-q", "--proto", "=https", "--proto-redir", "=https", "--tlsv1.2", "-fL", "--retry", "3"]
# cpus 0 = automatic: half the cores, at most 4
DEFAULTS = {"ram_mb": 4096, "cpus": 0, "width": 1920, "height": 1080, "skip_welcome": True,
            "harden_guest": True, "auto_tor": True, "vpn": False, "sentinel": True,
            "clipboard": True}


class LetheError(Exception):
    pass


def read(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def settings():
    """Saved settings over the defaults. The file is the user's to edit, so it is only data:
    unknown keys and values of the wrong type are ignored (they end up on QEMU's command line)."""
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG) as f:
            saved = json.load(f)
        cfg.update({k: v for k, v in saved.items() if k in DEFAULTS and type(v) is type(DEFAULTS[k])})
    except (OSError, ValueError, AttributeError):
        pass
    return cfg


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


def signed_by_tails(iso, sig, key, fresh=False):
    """True only if `sig` is a valid signature of `iso` made by the pinned Tails key.

    The key file is untrusted input: whatever it holds, the result counts only
    when gpg reports the pinned primary-key fingerprint, and nothing else about
    the signature is wrong. `fresh` (a new download) also refuses an expired key;
    an image already on disk may outlive the key it was verified with.
    `iso` is a path, or an open descriptor: then exactly what it holds is checked,
    whatever happens to the name it was opened by.
    """
    home = os.path.join(RUNTIME, f"{APP}-gpg-{os.getpid()}-{threading.get_ident()}")
    os.makedirs(home, mode=0o700, exist_ok=True)
    try:
        env = {"GNUPGHOME": home, "PATH": "/usr/bin:/bin", "LC_ALL": "C"}
        subprocess.run(["gpg", "--batch", "--quiet", "--no-autostart", "--import", key], env=env, capture_output=True)
        if isinstance(iso, int):
            os.lseek(iso, 0, os.SEEK_SET)
        out = subprocess.run(["gpg", "--batch", "--no-autostart", "--status-fd", "1", "--verify", sig,
                              "-" if isinstance(iso, int) else iso], env=env, text=True, stderr=subprocess.DEVNULL,
                             stdin=iso if isinstance(iso, int) else subprocess.DEVNULL, stdout=subprocess.PIPE).stdout
        # "[GNUPG:] VALIDSIG <signing-subkey-fpr> ... <primary-key-fpr>"
        status = [l.split() for l in out.splitlines() if l.startswith("[GNUPG:] ") and len(l.split()) > 1]
        wrong = {"BADSIG", "ERRSIG", "REVKEYSIG"} | ({"EXPKEYSIG", "EXPSIG"} if fresh else set())
        return (any(s[1] == "VALIDSIG" and s[-1] == TAILS_FPR for s in status if len(s) > 2)
                and not any(s[1] in wrong for s in status))
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
        if not signed_by_tails(part, sig + ".part", key, fresh=True):
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


def image_version(fd):
    """The Tails version an image itself states, in its volume label ("TAILS 7.18 - 20261124"), or None.
    The label is part of what the signature covers; the file's name is not."""
    try:
        m = re.match(rb"TAILS ([0-9][0-9.]*) - \d{8}\s*$", os.pread(fd, 32, 0x8028))
        return m.group(1).decode() if m else None
    except OSError:
        return None


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
    # Tor only needs TCP; newer passt can drop the rest. And nothing of this computer's own DNS
    # setup (its servers, its search domains, which often name the network it is on) goes to Tails.
    for flag, value in (("--no-icmp", None), ("--no-udp", None), ("--map-guest-addr", "none"),
                        ("--no-dhcp-dns", None), ("--no-dhcp-search", None)):
        if flag in h:
            args += [flag] + ([value] if value else [])
    return args


def vpn_profile():
    """Name of the imported WireGuard profile, or None."""
    return read("/etc/lethe/vpn.name") or None


def vpn_up():
    """The WireGuard-only namespace exists (created by lethe-vpn.service) and its relay socket is there."""
    return os.path.exists("/run/netns/lethe") and os.path.exists(VPN_SOCK)


# Installed by install.sh: the code is root-owned, and nothing a program running as the user can
# set (environment, PATH) may change what gets run.
SEALED = os.stat(os.path.realpath(__file__)).st_uid == 0 and os.getuid() != 0
SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
# Variables that make GTK, GLib or the graphics stack load code from a folder of the caller's choosing.
LOADERS = ("GTK_PATH", "GTK_EXE_PREFIX", "GTK_DATA_PREFIX", "GTK_IM_MODULE_FILE", "GTK_MODULES", "GIO_EXTRA_MODULES",
           "GIO_MODULE_DIR", "GI_TYPELIB_PATH", "GDK_PIXBUF_MODULE_FILE", "GDK_PIXBUF_MODULEDIR",
           "GSETTINGS_SCHEMA_DIR", "GSETTINGS_BACKEND", "LIBGL_DRIVERS_PATH", "GBM_BACKENDS_PATH",
           "__EGL_VENDOR_LIBRARY_DIRS", "__EGL_VENDOR_LIBRARY_FILENAMES", "VK_ICD_FILENAMES", "VK_DRIVER_FILES",
           "VK_LAYER_PATH", "VK_ADD_LAYER_PATH", "VK_INSTANCE_LAYERS", "LIBVA_DRIVERS_PATH", "QEMU_MODULE_DIR",
           "G_DBUS_COOKIE_SHA1_KEYRING_DIR", "CURL_HOME", "GNUPGHOME")
# Developer override, honoured only when running from a source folder: extra QEMU modules to load.
MODULES = None if SEALED else os.environ.get("LETHE_QEMU_MODULE_DIR")
MODULE_DIRS = ("/usr/lib/qemu", "/usr/lib64/qemu", "/usr/lib/x86_64-linux-gnu/qemu")   # where distros put QEMU's modules


def lock_down():
    """Called first thing by the app. Makes this process find its tools in system folders only,
    drops variables that would load foreign code into it, keeps new files private, and closes
    the process to the user's other programs (see wiper.hide)."""
    os.umask(0o077)
    if SEALED:
        os.environ["PATH"] = SAFE_PATH
        for name in LOADERS:
            os.environ.pop(name, None)
    hide()


def fast_display():
    """True if QEMU's virtio display is usable here. It lets the VM follow the window
    size and hand its pointer to us to draw without lag. Plain VGA is the fallback.

    Decided by looking, never by trying: on distros that ship the display as separate
    modules, QEMU crashes outright when one of the three is missing.
    """
    dirs = [d for d in (*MODULE_DIRS, MODULES) if d and os.path.isdir(d)]
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


def vm_hidden():
    """True if a session can be closed to the user's other programs here (see seal.py). Session.sealed
    says whether a running one really is."""
    return seal.possible()


def has_kvm():
    return os.access("/dev/kvm", os.R_OK | os.W_OK)


def born(pid):
    """When process `pid` started, as the kernel counts it: together with the number, this names one
    process and no later one. Readable for any process, sealed ones included."""
    return read(f"/proc/{pid}/stat").rpartition(")")[2].split()[19:20]


def running():
    """PID of the running session's sandbox, or None. The number alone is not trusted: after a
    crash it may belong to something else by now."""
    pid, _, since = read(os.path.join(RT, "pid")).partition(" ")
    try:
        return int(pid) if born(int(pid)) == [since] else None
    except ValueError:
        return None


# ── The session ──────────────────────────────────────────────────────────────

class Session:
    """One amnesic VM, from sandbox construction to memory wipe."""

    def __init__(self, cfg, stage=lambda name: None):
        self.cfg, self.stage = cfg, stage
        self.vm = self.ram_fd = None
        self.kvm, self.virtio, self.dbus = True, False, False
        self.helpers, self.why, self.started = [], None, None
        self.guard = self.guard_ctl = self.leash = None
        self.clipboard, self.clips = False, 0
        self.qmp = None                  # our end of the VM's control channel
        self.image, self._leased = None, False   # the verified Tails image, held open and unchanged
        self.sealed = False              # closed to the user's other programs (seal.py)

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
        self.image = self._hold(iso)
        if not signed_by_tails(self.image, iso + ".sig", os.path.join(DATA, "tails-signing.key")):
            raise LetheError("The Tails image on disk was modified after it was verified. Download it again.")
        # A genuine but older Tails under the newest one's name would pass the signature check.
        inside, named = image_version(self.image), current_version()
        if inside and re.fullmatch(r"[0-9.]+", named) and inside != named:
            for stale in (iso, iso + ".sig", os.path.join(DATA, "current")):
                try:
                    os.unlink(stale)
                except OSError:
                    pass
            raise LetheError(f"The image on disk was Tails {inside}, under the name of Tails {named}. "
                             "It has been discarded: start again to fetch the current release.")

        self.stage("sandbox")
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))   # a crash must never write guest RAM to disk
        shutil.rmtree(RT, ignore_errors=True)
        os.makedirs(RT, mode=0o700)
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
        # Helpers hold something for as long as the session lives (the sleep delay, the power profile).
        # Each one just reads from this pipe: it ends when Lethe closes it, or when Lethe dies.
        self.leash = os.pipe()
        aa = ["aa-exec", "-p", "lethe", "--"] if os.path.exists("/etc/apparmor.d/lethe") and shutil.which("aa-exec") else []
        # No user namespaces inside the sandbox: they are how most kernel exploits get started.
        nested = "--disable-userns" in subprocess.run(["bwrap", "--help"], capture_output=True, text=True).stdout
        bwrap = ["--die-with-parent", "--new-session", "--cap-drop", "ALL", "--clearenv",
                 "--hostname", "localhost", "--setenv", "PATH", "/usr/bin",
                 "--proc", "/proc", "--dev", "/dev", *(["--dev-bind", "/dev/kvm", "/dev/kvm"] if self.kvm else []),
                 "--tmpfs", "/tmp", "--tmpfs", "/run", "--bind", os.path.join(RT, "q"), "/run/q",
                 "--tmpfs", "/etc", "--ro-bind", os.path.join(RT, "passwd"), "/etc/passwd", "--dir", "/usr/bin",
                 *(["--setenv", "G_DBUS_COOKIE_SHA1_KEYRING_DIR", "/run/q/keyring"] if self.dbus else [])]
        for d in ("/usr/lib", "/usr/lib32", "/usr/lib64", "/usr/libx32", "/lib", "/lib32", "/lib64", "/libx32", "/bin"):
            if os.path.islink(d):                               # mirror the host's /usr layout
                bwrap += ["--symlink", os.readlink(d), d]
            elif os.path.isdir(d):
                bwrap += ["--ro-bind", d, d]
        # QEMU finds its firmware and its modules relative to where its program file is. The sealed
        # copy is in no folder at all, so it is told where they are.
        listed = subprocess.run([qemu_bin, "-L", "help"], capture_output=True, text=True, timeout=10).stdout.split("\n")
        firmware = [d for d in dict.fromkeys([os.path.normpath(l.strip()) for l in listed if l.startswith("/")]
                                             + ["/usr/share/qemu", "/usr/share/seabios", "/usr/share/seavgabios",
                                                "/usr/share/qemu-kvm"]) if os.path.isdir(d)]
        for p in (*firmware, "/etc/ld.so.cache", "/etc/ld.so.conf", "/etc/ld.so.conf.d"):
            if os.path.exists(p):
                bwrap += ["--ro-bind", p, p]
        modules = MODULES or next((d for d in MODULE_DIRS if os.path.isdir(d)), None)
        if modules:
            bwrap += ["--setenv", "QEMU_MODULE_DIR", modules]

        if MODULES:
            bwrap += ["--ro-bind", MODULES, MODULES]

        # QEMU is handed the image and the config disc as open files, not as names: what it reads is
        # what was verified, and what Lethe wrote, whatever another program does to the folders.
        drives = ["-drive", f"if=none,id=cd,media=cdrom,readonly=on,format=raw,file=/proc/self/fd/{self.image}",
                  "-device", "ide-cd,drive=cd,bus=ide.0,bootindex=0"]
        spare = []                                              # handles only the VM needs: closed once it has them
        if cfg["harden_guest"]:
            files = {"SETUP.SH": "guest/setup.sh", "GTK4.CSS": "guest/gtk4.css", "GTK3.CSS": "guest/gtk3.css",
                     "WALL.PNG": "assets/wallpaper.png",
                     "ONLINE.PNG": "assets/wallpaper-online.png", "INTER.TTF": "assets/Inter.ttf",
                     "EXT.JS": "guest/extension/extension.js", "EXT.CSS": "guest/extension/stylesheet.css",
                     "EXT.JSN": "guest/extension/metadata.json", "MARK.SVG": "guest/extension/mark.svg"}
            data = {n: open(os.path.join(LIB, p), "rb").read() for n, p in files.items()
                    if os.path.exists(os.path.join(LIB, p))}
            # The host's display scale, so text in Tails comes out the size you are used to.
            data["SCALE.TXT"] = f"{max(1.0, min(3.0, float(cfg.get('scale', 1)))):.2f}\n".encode()
            disc = seal.copy(build_iso("LETHE", data), "lethe-config", mode=0o444)
            spare.append(disc)
            drives += ["-drive", f"if=none,id=cfg,media=cdrom,readonly=on,format=raw,file=/proc/self/fd/{disc}",
                       "-device", "ide-cd,drive=cfg,bus=ide.1,id=cfgdisc"]
            # An empty drive for the one-way clipboard: Lethe inserts a small read-only disc into it
            # with what you copied on your computer, and the Lethe shell extension reads it.
            drives += ["-drive", "if=none,id=clip,media=cdrom,readonly=on",
                       "-device", "ide-cd,drive=clip,bus=ide.2,id=clipdisc"]
            self.clipboard = True

        self.stage("network")
        net, vpn = self._network()
        os.set_inheritable(net.fileno(), True)

        self.stage("boot")
        self.qmp, theirs = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        sealed = self._seal(qemu_bin, aa, nested, bwrap)
        qemu = [sealed.qemu if sealed else qemu_bin, "-name", "vm,process=lethe-qemu",
                "-machine", f"q35,accel={'kvm' if self.kvm else 'tcg'},vmport=off,dump-guest-core=off,"
                            "mem-merge=off,memory-backend=ram",
                "-object", f"memory-backend-file,id=ram,size={size},mem-path=/proc/self/fd/{self.ram_fd},share=on",
                "-cpu", f"{'host' if self.kvm else 'max'},model-id=Virtual CPU",   # hide the real CPU name
                "-smp", str(cfg["cpus"]), "-m", f"{cfg['ram_mb']}M",
                *(["-overcommit", "mem-lock=on"] if locked else []),
                "-nodefaults", "-no-user-config", *(a for d in firmware for a in ("-L", d)), *drives,
                "-netdev", f"socket,id=net0,fd={net.fileno()}", "-device", "virtio-net-pci,netdev=net0,romfile=",
                "-device", "virtio-rng-pci",
                "-device", "virtio-tablet-pci",      # absolute pointer without emulating a USB controller
                "-device", "virtio-keyboard-pci",    # keys arrive in a queue, not through an emulated 8042 chip
                # virtio: resizable, pointer drawn by us. VGA: smallest possible device, fixed size.
                "-device", (f"virtio-vga,xres={cfg['width']},yres={cfg['height']}" if self.virtio
                            else f"VGA,vgamem_mb=32,xres={cfg['width']},yres={cfg['height']}"),
                # The picture and the controls travel over sockets that exist only as open handles
                # between Lethe and QEMU: there is no socket file for anything else to connect to.
                *(["-display", "dbus,p2p=on"] if self.dbus else ["-display", "none", "-vnc", "none"]),
                "-chardev", f"socket,id=qmp,fd={theirs.fileno()}", "-mon", "chardev=qmp,mode=control",
                "-serial", "none", "-parallel", "none",
                "-sandbox", "on,obsolete=deny,elevateprivileges=deny,spawn=deny,resourcecontrol=deny"]
        self.helpers += self._sleep_guard()
        # On mains power, hold the "performance" power profile for the life of the session.
        # The hold belongs to this helper process, so it ends when the session does.
        mains = [read(f"/sys/class/power_supply/{d}/online") for d in os.listdir("/sys/class/power_supply")
                 if read(f"/sys/class/power_supply/{d}/type") == "Mains"] if os.path.isdir("/sys/class/power_supply") else []
        if shutil.which("powerprofilesctl") and "0" not in mains:
            self.helpers.append(subprocess.Popen(
                ["powerprofilesctl", "launch", "-p", "performance", "-r", "Private session", "-i", "org.lethe.App",
                 "cat"], stdin=self.leash[0], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        # The guard wipes the guest's memory if Lethe dies before doing it (see wiper.py). It knows
        # the VM is gone when `life`, a pipe only the VM's processes hold open, closes.
        ctl_r, self.guard_ctl = os.pipe()
        life_r, life_w = os.pipe()
        folder = os.open(RT, os.O_RDONLY | os.O_DIRECTORY)
        # Both the guard and the VM are handed the guest's memory. Sealed, they start from the unreadable
        # copies: at no moment is there a process holding that memory which another program could open.
        python = f"/proc/self/fd/{sealed.python}" if sealed else None
        self.guard = subprocess.Popen([sys.executable, "-I", os.path.join(LIB, "lethe", "wiper.py"),
                                       str(self.ram_fd), str(ctl_r), str(life_r), str(folder)], executable=python,
                                      pass_fds=[self.ram_fd, ctl_r, life_r, folder, *([sealed.python] if sealed else [])],
                                      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      start_new_session=True)
        os.close(ctl_r), os.close(life_r), os.close(folder)
        if sealed:
            launch = [*sealed.launch, *bwrap, "--", *qemu]
        else:
            launch = [*aa, "bwrap", "--unshare-all", *(["--unshare-user", "--disable-userns"] if nested else []),
                      "--uid", "1000", "--gid", "1000", *bwrap, "--ro-bind", qemu_bin, qemu_bin, "--", *qemu]
        spare += sealed.fds if sealed else []
        try:
            self.vm = subprocess.Popen(launch, executable=python, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                       pass_fds=[net.fileno(), self.ram_fd, life_w, theirs.fileno(), self.image, *spare])
        finally:
            os.close(life_w)
            net.close()
            theirs.close()
            for fd in spare:
                os.close(fd)
        self.started = time.time()
        with open(os.path.join(RT, "pid"), "w") as f:
            f.write(" ".join([str(self.vm.pid), *born(self.vm.pid)]))
        threading.Thread(target=self._watch_image, daemon=True).start()
        for _ in range(100):                                    # QEMU says hello on the control channel
            if select.select([self.qmp], [], [], 0.05)[0]:
                if self.qmp.recv(1, socket.MSG_PEEK):           # its greeting; nothing = it hung up
                    # Sealed means: Lethe, asking as any other program of yours would, is refused by
                    # every process of the sandbox.
                    self.sealed = bool(sealed) and not any(seal.reachable(p) for p in seal.tree(self.vm.pid))
                    return vpn
                self.vm.wait(5)
            if self.vm.poll() is not None:
                err = self.vm.stderr.read().decode(errors="replace").strip().splitlines()
                raise LetheError("The virtual machine failed to start" + (f": {err[-1]}" if err else "."))
        raise LetheError("The virtual machine did not come up in time.")

    def _hold(self, iso):
        """Open the Tails image and keep it as it is for the whole session. The file is the user's, so
        another program of theirs could rewrite it after the signature check, even while Tails is
        reading from it. A lease makes the kernel hold any writer back and tell us first: the session
        is destroyed before a changed byte can reach it (see _watch_image)."""
        fd = os.open(iso, os.O_RDONLY | os.O_CLOEXEC)
        try:
            fcntl.fcntl(fd, fcntl.F_SETSIG, signal.SIGURG)      # how the kernel tells us: a signal nobody minds
            fcntl.fcntl(fd, fcntl.F_SETLEASE, fcntl.F_RDLCK)
            self._leased = True
        except OSError as e:
            self._leased = False
            if e.errno == errno.EAGAIN:
                os.close(fd)
                raise LetheError("Another program has the Tails image open for writing. Nothing was started.")
            # No leases here (a network folder), or the file is not ours to lease, so not ours to change.
        return fd

    def _watch_image(self):
        """The kernel is holding a writer back from the image (see _hold): end the session first."""
        image = self.image
        while self._leased and self.alive() and image == self.image:
            try:
                if fcntl.fcntl(image, fcntl.F_GETLEASE) != fcntl.F_RDLCK:
                    return self.destroy("Another program tried to change the Tails image")
            except OSError:
                return
            time.sleep(0.25)

    def _seal(self, qemu_bin, aa, nested, bwrap):
        """What a launch needs for nothing else to be able to look into it (see seal.py): unreadable
        copies of QEMU, of the sandbox builder and of Python, and a user namespace made beforehand.
        The whole chain is rehearsed once, with QEMU only naming its version. Returns None where
        that does not work: the session then starts the ordinary way, and says that it is not sealed."""
        if not vm_hidden():
            return None
        held, helper = [], None
        try:
            for name, path, group in (("qemu", qemu_bin, seal.spare_group()), ("python", os.path.realpath(sys.executable), None),
                                      ("bwrap", os.path.realpath(shutil.which("bwrap")), None)):
                held.append(seal.copy(path, f"lethe-{name}", group))
            helper, userns = seal.namespace(aa, nested, self.leash[0])
            held.append(userns)
            qemu, python, builder = (f"/proc/self/fd/{fd}" for fd in held[:3])
            launch = [sys.executable, "-I", os.path.join(LIB, "lethe", "seal.py"), *aa, builder, "--userns", str(userns),
                      "--unshare-ipc", "--unshare-pid", "--unshare-net", "--unshare-uts", "--unshare-cgroup-try"]
            subprocess.run([*launch, *bwrap, "--", qemu, "--version"], executable=python, pass_fds=held, timeout=20,
                           stdin=subprocess.DEVNULL, capture_output=True, check=True)
        except (OSError, subprocess.SubprocessError):
            for fd in held:
                os.close(fd)
            if helper:
                helper.kill()
            return None
        self.helpers.append(helper)
        return types.SimpleNamespace(launch=launch, qemu=qemu, python=held[1], fds=held)

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
            return [subprocess.Popen([*inhibit, "--mode=block", "cat"], stdin=self.leash[0], stdout=subprocess.DEVNULL)]
        holder = subprocess.Popen([*inhibit, "--mode=delay", "cat"], stdin=self.leash[0], stdout=subprocess.DEVNULL)
        # The monitor never reads its input, so a shell waits on the leash for it.
        watcher = subprocess.Popen(["sh", "-c", '"$@" & cat >/dev/null; kill $!', "sh", *mon], stdin=self.leash[0],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

        def watch():
            armed = False
            for line in watcher.stdout:
                armed = armed or "PrepareForSleep" in line
                if armed and re.search(r"\(true,\)|boolean true", line):
                    self.destroy("The computer was going to sleep")
                    holder.kill()                               # let the computer sleep now
                    return
                if armed and re.search(r"\(false,\)|boolean false", line):
                    armed = False

        threading.Thread(target=watch, daemon=True).start()
        return [holder, watcher]

    def clip_disc(self, mime, data):
        """Write the next clipboard disc; returns its path as QEMU sees it. Only one exists at a time:
        the previous one is overwritten with zeros, then removed."""
        self.clips += 1
        for old in os.listdir(os.path.join(RT, "q")):
            if old.startswith("clip-"):
                scrub(os.path.join(RT, "q", old))
        name = f"clip-{self.clips}.iso"
        fd = os.open(os.path.join(RT, "q", name), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(build_iso(f"LETHECLIP-{self.clips}", {"MIME.TXT": mime.encode(), "DATA.BIN": data}))
        return f"/run/q/{name}"

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
        for fd in self.leash or ():
            os.close(fd)
        self.leash = None
        for h in self.helpers:
            try:
                h.wait(2)
            except subprocess.TimeoutExpired:
                h.kill()
        self.helpers = []
        if self.qmp:
            self.qmp.close()
            self.qmp = None
        wiped = 0
        if self.ram_fd is not None:
            wiped = wipe(self.ram_fd, progress)
            os.close(self.ram_fd)
            self.ram_fd = None
        if self.guard_ctl is not None:                   # wiped: the guard can stand down
            try:
                os.write(self.guard_ctl, b"1")
            except OSError:
                pass
            os.close(self.guard_ctl)
            self.guard_ctl = None
            self.guard.wait()
        if self.image is not None:                       # only now may the image be written to again
            os.close(self.image)
            self.image = None
        try:                                             # the clipboard discs live in RAM too
            folder = os.open(RT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            clear(folder)
            os.close(folder)
        except OSError:
            pass
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
    add("integrity", SEALED, "Integrity",
        ("Sealed", "Lethe's own files are root-owned and checked before each session."),
        ("Unsealed", "Running from a folder your user can modify."), "warn")
    return checks
