"""Sentinel: host tripwires that destroy the session when something touches it.

What it is: a set of cheap, high-signal checks on the machine Lethe runs on,
taken before a session starts and once a second while it lives.

What it is not: an antivirus. Malware that already controls the kernel can hide
from any program running on that kernel, this one included. The Sentinel raises
the cost of the realistic attacks: someone attaching a debugger to read the VM's
memory, logging in remotely, plugging in a keystroke-injecting USB device, or
replacing Lethe's own files.

Severities:
  critical  the session is destroyed immediately
  warning   shown to the user, session continues
  capture   something is recording the screen: the VM display is hidden meanwhile
"""
import hashlib, os, socket, subprocess, threading, time

from .core import LIB, SEALED, read, vm_hidden

# Tools whose presence next to a private session deserves a warning.
SNOOPS = {"strace", "ltrace", "gdb", "lldb", "frida", "frida-server", "tcpdump", "wireshark", "tshark", "dumpcap",
          "ettercap", "bettercap", "mitmproxy", "mitmdump", "logkeys", "avml", "volatility", "scanmem", "gcore"}
MANIFEST = os.path.join(LIB, "MANIFEST")


def _status(pid, field):
    for line in read(f"/proc/{pid}/status").splitlines():
        if line.startswith(field + ":"):
            return line.split(":", 1)[1].strip()
    return ""


def _procs():
    """{pid: (comm, ppid)} for every process we can see."""
    out = {}
    for p in os.listdir("/proc"):
        if p.isdigit():
            stat = read(f"/proc/{p}/stat")
            if ")" in stat:
                out[int(p)] = (stat[stat.index("(") + 1:stat.rindex(")")], int(stat[stat.rindex(")") + 2:].split()[1]))
    return out


def _family(root):
    """`root` and all its descendants."""
    procs, family, grew = _procs(), {root}, True
    while grew:
        more = {pid for pid, (_, ppid) in procs.items() if ppid in family} - family
        family, grew = family | more, bool(more)
    return family


def _keyboards():
    """Input devices that can type, as {sysfs name: description}."""
    found, base = {}, "/sys/class/input"
    for dev in os.listdir(base) if os.path.isdir(base) else []:
        if dev.startswith("input"):
            keys = read(f"{base}/{dev}/capabilities/key").split()
            # A real keyboard reports the letter keys (bits 16..50 of the key bitmap).
            if keys and int(keys[-1], 16) & 0x7fffe0000:
                found[dev] = read(f"{base}/{dev}/name") or dev
    return found


def _usb():
    base = "/sys/bus/usb/devices"
    return {d: read(f"{base}/{d}/product") or d for d in (os.listdir(base) if os.path.isdir(base) else [])
            if ":" not in d and not d.startswith("usb")}


def _remote_logins():
    try:
        out = subprocess.run(["loginctl", "list-sessions", "--no-legend"], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    remote = set()
    for line in out.splitlines():
        sid = line.split()[0] if line.split() else ""
        if sid and subprocess.run(["loginctl", "show-session", sid, "-p", "Remote", "--value"],
                                  capture_output=True, text=True).stdout.strip() == "yes":
            remote.add(sid)
    return remote


def _gateway():
    """(gateway ip, its MAC address) of the default route, to notice ARP spoofing."""
    for line in read("/proc/net/route").splitlines()[1:]:
        f = line.split()
        if len(f) > 2 and f[1] == "00000000":
            ip = ".".join(str(int(f[2][i:i + 2], 16)) for i in (6, 4, 2, 0))
            for arp in read("/proc/net/arp").splitlines()[1:]:
                a = arp.split()
                if a and a[0] == ip:
                    return ip, a[3]
    return None, None


def _modules():
    """Names of the loaded kernel modules (names only: the usage counters next to them change all the time)."""
    return {line.split()[0] for line in read("/proc/modules").splitlines() if line.split()}


def tampered():
    """Files that differ from the root-owned manifest written at install time."""
    bad = []
    if SEALED and not read(MANIFEST):
        return ["the list of Lethe's files (MANIFEST) is missing"]
    for line in read(MANIFEST).splitlines():
        digest, _, rel = line.partition("  ")
        try:
            with open(os.path.join(LIB, rel), "rb") as f:
                if hashlib.sha256(f.read()).hexdigest() != digest:
                    bad.append(rel)
        except OSError:
            bad.append(rel)
    return bad


def preflight():
    """Checks before a session may start: [(severity, title, detail)]."""
    found = []
    inject = [v for v in ("LD_PRELOAD", "LD_AUDIT", "LD_LIBRARY_PATH", "LD_DEBUG_OUTPUT", "LD_PROFILE", "GTK_MODULES",
                          "GTK_PATH", "GIO_EXTRA_MODULES", "GI_TYPELIB_PATH") if os.environ.get(v)]
    if inject or read("/etc/ld.so.preload"):
        found.append(("critical", "Code injection is configured",
                      "Libraries are being forced into every program (" + ", ".join(inject or ["/etc/ld.so.preload"]) + ")."))
    if _status("self", "TracerPid") not in ("", "0"):
        found.append(("critical", "Lethe is being debugged", "Another process is attached to Lethe and can read its memory."))
    bad = tampered()
    if bad:
        found.append(("critical", "Lethe's own files were modified", "Changed since installation: " + ", ".join(bad[:4])))
    snoops = sorted({comm for comm, _ in _procs().values()} & SNOOPS)
    if snoops:
        found.append(("warning", "Inspection tools are running", ", ".join(snoops) + " can observe other programs or the network."))
    if _remote_logins():
        found.append(("warning", "Someone is logged in remotely", "A remote session (SSH or similar) is open on this computer."))
    if not vm_hidden():
        found.append(("warning", "The session's memory is not sealed off",
                      "This system does not let Lethe close the virtual machine to your other programs."))
    return found


class Sentinel(threading.Thread):
    """Watches the host while a session lives. `report(severity, title, detail)`."""

    def __init__(self, vm_pid, report):
        super().__init__(daemon=True)
        self.vm_pid, self.report, self.active = vm_pid, report, True

    def stop(self):
        self.active = False

    def _capture_watch(self):
        """Hyprland announces screen sharing on its event socket."""
        sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
        path = os.path.join(os.environ.get("XDG_RUNTIME_DIR", ""), "hypr", sig or "", ".socket2.sock")
        if not sig or not os.path.exists(path):
            return
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(path)
            for line in s.makefile(errors="replace"):
                if not self.active:
                    return
                if line.startswith("screencast>>"):
                    on = line.split(">>")[1].split(",")[0].strip() == "1"
                    self.report("capture" if on else "capture-end", "Screen capture",
                                "Something started recording your screen. The session is hidden until it stops.")
        except OSError:
            pass

    def run(self):
        threading.Thread(target=self._capture_watch, daemon=True).start()
        keyboards, usb, remote = _keyboards(), _usb(), _remote_logins()
        snoops = {comm for comm, _ in _procs().values()} & SNOOPS
        modules, gateway = _modules(), _gateway()
        tick = 0
        while self.active:
            time.sleep(1)
            tick += 1
            # 1. Nothing may attach to Lethe or to the VM (this is how memory gets read).
            for pid in _family(self.vm_pid) | {os.getpid()}:
                tracer = _status(pid, "TracerPid")
                if tracer not in ("", "0"):
                    who = read(f"/proc/{tracer}/comm") or "an unknown process"
                    return self.report("critical", "A debugger attached to the session",
                                       f"{who} (pid {tracer}) tried to inspect the session's memory.")
            # 2. A keyboard that appears mid-session may be a keystroke-injecting USB device.
            now = _keyboards()
            if set(now) - set(keyboards):
                name = now[next(iter(set(now) - set(keyboards)))]
                return self.report("critical", "A new keyboard was connected", f"“{name}” appeared during the session.")
            if tick % 3:
                continue
            # 3. Slower checks, every three seconds.
            new_remote = _remote_logins() - remote
            if new_remote:
                return self.report("critical", "Someone logged in remotely", "A remote session opened on this computer.")
            new_usb = {k: v for k, v in _usb().items() if k not in usb}
            if new_usb:
                usb.update(new_usb)
                self.report("warning", "USB device connected", f"“{next(iter(new_usb.values()))}” was plugged in.")
            new_snoops = ({comm for comm, _ in _procs().values()} & SNOOPS) - snoops
            if new_snoops:
                snoops |= new_snoops
                self.report("warning", "Inspection tool started", ", ".join(sorted(new_snoops)) + " is now running.")
            mods = _modules()
            if mods - modules:
                name = next(iter(mods - modules))
                modules = mods
                self.report("warning", "Kernel module loaded", f"“{name}” was loaded into the kernel during the session.")
            gw = _gateway()
            if gateway[1] and gw[0] == gateway[0] and gw[1] and gw[1] != gateway[1]:
                gateway = gw
                self.report("warning", "Your network gateway changed identity",
                            "Possible interception on the local network. Tor still encrypts your traffic.")
