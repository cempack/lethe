"""lethe            open the app
lethe start      open the app and start a session right away
lethe update     download and verify the latest Tails image
lethe stop       destroy the running session immediately
lethe status     image version and session state
lethe doctor     audit every protection layer on this machine"""
import os, signal, sys

from . import core, sentinel


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "open"
    if cmd in ("open", "start"):
        if cmd == "start":
            os.environ["LETHE_AUTOSTART"] = "1"
        # Everything Lethe holds in memory (guest RAM, the copy of its screen) must stay off the disk.
        core.enter_noswap_scope([os.path.realpath(sys.argv[0])])
        try:
            from . import gui
        except (ImportError, ValueError) as e:
            sys.exit(f"lethe: the app needs GTK 4 and PyGObject ({e}). Run the installer again.")
        sys.exit(gui.main())
    elif cmd == "update":
        try:
            version = core.update(lambda text, f: print(f"\r{text}" + (f" {f:5.1%}" if f else "      "), end="", flush=True))
            print(f"\nTails {version} is downloaded and verified.")
        except core.LetheError as e:
            sys.exit(f"\nlethe: {e}")
    elif cmd == "stop":
        pid = core.running()
        if pid:
            os.kill(pid, signal.SIGKILL)       # the app notices, wipes the memory and cleans up
        print("Session destroyed." if pid else "No session is running.")
    elif cmd == "status":
        print(f"Tails image: {core.current_version() or 'not downloaded'}")
        print("Session:     " + ("running" if core.running() else "none"))
        print("VPN profile: " + (core.vpn_profile() or "none"))
    elif cmd == "doctor":
        mark = {"ok": "\033[32m✓\033[0m", "warn": "\033[33m!\033[0m", "bad": "\033[31m✗\033[0m",
                "warning": "\033[33m!\033[0m", "critical": "\033[31m✗\033[0m"}
        rows = [tuple(c) for c in core.audit()] + sentinel.preflight()
        print("Lethe protection audit\n")
        for state, title, detail in rows:
            print(f"  {mark[state]} {title + ':':<17} {detail}")
        print("\n  ✓ in place   ! weaker than it could be   ✗ sessions will refuse to start")
        sys.exit(any(s in ("bad", "critical") for s, _, _ in rows))
    elif cmd == "_passt-args":                  # used by install.sh to write the system services
        print(" ".join(core.passt_args(3)[1:]))
    else:
        print(__doc__)
        sys.exit(cmd not in ("help", "-h", "--help"))
