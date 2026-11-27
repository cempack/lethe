"""The memory wipe, and the guard that performs it if Lethe itself is killed.

Lethe overwrites the guest's memory when a session ends. If Lethe dies first
(a crash, `kill -9`, the desktop logging out), nobody would be left to do it:
the kernel would hand the pages back as they are. So every session also has a
guard, this file run as a tiny separate process. It holds the memory file, the
session's runtime folder (where the clipboard discs are) and two pipes, and sleeps:

  ctl    from Lethe. One byte = "I wiped it, you can go". Closed without that
         byte = Lethe is gone.
  life   held open by the VM's processes. Closed = the VM is really dead, so
         nothing can write to the memory any more.

    python3 -I wiper.py RAM_FD CTL_FD LIFE_FD FOLDER_FD
"""
import os, select, signal, stat, sys


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


def scrub(name, folder=None):
    """Overwrite a file of ours with zeros and remove it. These files sit in a folder the VM's side
    can write to as well: never follow a link out of it, never wait on something that is not a file."""
    try:
        fd = os.open(name, os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=folder)
        try:
            info = os.fstat(fd)
            if stat.S_ISREG(info.st_mode):
                os.pwrite(fd, bytes(min(info.st_size, 64 << 20)), 0)
        finally:
            os.close(fd)
    except OSError:
        pass
    try:
        os.unlink(name, dir_fd=folder)
    except OSError:
        pass


def clear(folder):
    """Scrub everything in the session's runtime folder. It is given as an open folder, not by name:
    if a new session has put another folder under that name since, that one is not touched."""
    for _path, folders, files, here in os.fwalk(".", topdown=False, dir_fd=folder):
        for name in files:
            scrub(name, here)
        for name in folders:
            try:
                os.rmdir(name, dir_fd=here)
            except OSError:
                scrub(name, here)                        # a link made to look like a folder


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
    ram, ctl, life, folder = (int(a) for a in sys.argv[1:5])
    try:
        done = os.read(ctl, 1)
    except OSError:
        done = b""
    if done:
        return
    select.select([life], [], [], 20)                    # normally instant: the VM dies with Lethe
    wipe(ram)
    clear(folder)


if __name__ == "__main__":
    main()
