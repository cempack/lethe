"""Sealing: how a session is closed to the user's other programs.

Linux lets a user's programs look into one another: open each other's files through /proc, read
each other's memory, attach a debugger. For a session, that would mean any program of yours could
read Tails' memory. Four things together prevent it:

  1. Every program of a session runs from a copy that can be executed but not read. The kernel
     treats such a process like a privileged one: your other programs may not look inside.
  2. A sandbox made without root is a "user namespace" that belongs to you, and the kernel lets
     its owner inspect anything running in it, protected or not, unless the program came from
     outside it. So the copy of QEMU belongs to a group the sandbox does not know.
  3. The sandbox builder (bubblewrap) opens itself up again as it starts. A filter set before it
     runs turns that request into a no-op. Closed, it cannot make its own user namespace: a
     helper that holds nothing makes one beforehand, and the builder joins it.
  4. The copies are memory files that only these processes hold, sealed against writing: there
     is no path through which another program could swap or change one.

So from the moment Lethe starts a session to the moment its memory is wiped, nothing that holds
the guest's memory or its controls can be opened by another program.

    python3 -I seal.py PROGRAM ARGS...     pin this process closed, then become PROGRAM
"""
import ctypes, fcntl, os, struct, subprocess, sys

MFD_EXEC = 0x10                       # Linux 6.3+: this memory file may be executed
SEALS = fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE
# seccomp filter, x86-64: prctl(PR_SET_DUMPABLE, ...) returns success without doing anything.
PIN = [(0x20, 0, 0, 4), (0x15, 0, 5, 0xc000003e),      # other architecture: allow
       (0x20, 0, 0, 0), (0x15, 0, 3, 157),             # not prctl: allow
       (0x20, 0, 0, 16), (0x15, 0, 1, 4),              # not PR_SET_DUMPABLE: allow
       (0x06, 0, 0, 0x00050000), (0x06, 0, 0, 0x7fff0000)]


def copy(source, name, group=None, mode=0o111):
    """An unchangeable copy, in memory, of the file at `source` (or of `source` itself, if bytes).
    Returns its descriptor: the only way to reach it. `group` hands it to that group of yours."""
    try:
        fd = os.memfd_create(name, os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING | MFD_EXEC)
    except OSError:                                    # older kernels do not know the flag
        fd = os.memfd_create(name, os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    try:
        if isinstance(source, bytes):
            done = 0
            while done < len(source):
                done += os.write(fd, source[done:done + (1 << 20)])
        else:
            with open(source, "rb") as src:
                size, done = os.fstat(src.fileno()).st_size, 0
                while done < size:
                    done += os.sendfile(fd, src.fileno(), done, size - done)
        if group is not None:
            os.fchown(fd, -1, group)
        os.fchmod(fd, mode)
        fcntl.fcntl(fd, fcntl.F_ADD_SEALS, SEALS)
    except OSError:
        os.close(fd)
        raise
    return fd


def spare_group():
    """A group of yours that the sandbox will not know (it only knows your main one), or None."""
    return next((g for g in sorted(os.getgroups()) if g not in (os.getgid(), os.getegid())), None)


def possible():
    """True if a session can be sealed on this system."""
    def setting(name):
        try:
            with open(name) as f:
                return f.read().strip()
        except OSError:
            return ""
    return (os.uname().machine == "x86_64" and spare_group() is not None
            and setting("/proc/sys/fs/suid_dumpable") != "1"       # "debug" mode: nothing is ever closed
            and setting("/proc/sys/vm/memfd_noexec") != "2")       # memory files may never be executed


def namespace(prefix, nested, leash):
    """The sandbox's user namespace, made by a helper process that is given nothing else and lives
    until `leash` closes. Returns (helper, descriptor of the namespace)."""
    helper = subprocess.Popen([*prefix, "bwrap", "--unshare-user", *(["--disable-userns"] if nested else []),
                               "--uid", "1000", "--gid", "1000", "--die-with-parent", "--ro-bind", "/", "/",
                               "--", "sh", "-c", "echo $$; exec cat"],
                              stdin=leash, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        pid = int(helper.stdout.readline())
        return helper, os.open(f"/proc/{pid}/ns/user", os.O_RDONLY | os.O_CLOEXEC)
    except (OSError, ValueError):
        helper.kill()
        raise OSError("no user namespace")


def tree(pid):
    """`pid` and every process below it."""
    found, todo = [], [pid]
    while todo:
        pid = todo.pop()
        found.append(pid)
        try:
            for task in os.listdir(f"/proc/{pid}/task"):
                with open(f"/proc/{pid}/task/{task}/children") as f:
                    todo += [int(p) for p in f.read().split()]
        except OSError:
            pass
    return found


def reachable(pid):
    """True if a program of yours could look inside process `pid`. Lethe asks as any of them would."""
    try:
        os.readlink(f"/proc/{pid}/root")
        return True
    except PermissionError:
        return False
    except OSError:                                    # gone
        return False


def pin():
    """Keep this process closed across everything it becomes: see point 3 above."""
    libc = ctypes.CDLL(None, use_errno=True)
    code = ctypes.create_string_buffer(b"".join(struct.pack("HBBI", *i) for i in PIN))

    class Program(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ushort), ("filter", ctypes.c_void_p)]

    program = Program(len(PIN), ctypes.cast(code, ctypes.c_void_p))
    libc.prctl(4, 0, 0, 0, 0)                                      # PR_SET_DUMPABLE, off
    libc.prctl(38, 1, 0, 0, 0)                                     # PR_SET_NO_NEW_PRIVS: filters need it
    if libc.prctl(22, 2, ctypes.byref(program), 0, 0) != 0:        # PR_SET_SECCOMP, filter mode
        raise OSError(ctypes.get_errno(), "could not pin the process closed")


if __name__ == "__main__":
    try:
        pin()
        os.execvp(sys.argv[1], sys.argv[1:])
    except (OSError, IndexError) as e:
        sys.exit(f"lethe: sealed launch failed: {e}")
