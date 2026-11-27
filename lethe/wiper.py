"""The memory wipe, and the guard that performs it if Lethe itself is killed.

Lethe overwrites the guest's memory when a session ends. If Lethe dies first
(a crash, `kill -9`, the desktop logging out), nobody would be left to do it:
the kernel would hand the pages back as they are. So every session also has a
guard, this file run as a tiny separate process. It holds the memory file and
two pipes, and sleeps:

  ctl    from Lethe. One byte = "I wiped it, you can go". Closed without that
         byte = Lethe is gone.
  life   held open by the VM's processes. Closed = the VM is really dead, so
         nothing can write to the memory any more.

    python3 -I wiper.py RAM_FD CTL_FD LIFE_FD
"""
import os, select, signal, sys


def wipe(fd, progress=lambda fraction: None):
    """Overwrite every page the guest ever touched with zeros. Returns the bytes written."""
    size, zeros, off, wiped = os.fstat(fd).st_size, memoryview(bytes(8 << 20)), 0, 0
    try:
        while off < size:
            off = os.lseek(fd, off, os.SEEK_DATA)        # skip pages the guest never touched
            end = os.lseek(fd, off, os.SEEK_HOLE)
            while off < end:
                n = os.pwrite(fd, zeros[:min(len(zeros), end - off)], off)
                off, wiped = off + n, wiped + n
                progress(off / size)
    except OSError:
        pass                                             # ENXIO: no more data
    return wiped


def hide():
    """Close this process to the user's other programs: no debugger, no /proc/<pid>/mem,
    no /proc/<pid>/fd (which would otherwise hand out the guest's memory file)."""
    try:
        import ctypes
        ctypes.CDLL(None, use_errno=True).prctl(4, 0, 0, 0, 0)       # PR_SET_DUMPABLE, off
    except (OSError, AttributeError):
        pass


def main():
    hide()
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGPIPE):
        signal.signal(sig, signal.SIG_IGN)               # a logout must not stop the wipe
    ram, ctl, life = (int(a) for a in sys.argv[1:4])
    try:
        done = os.read(ctl, 1)
    except OSError:
        done = b""
    if done:
        return
    select.select([life], [], [], 20)                    # normally instant: the VM dies with Lethe
    wipe(ram)


if __name__ == "__main__":
    main()
