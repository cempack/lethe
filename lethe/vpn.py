"""WireGuard for the VM only. Runs as root: via pkexec (import/remove) and systemd (up/down).

The tunnel lives in its own network namespace, "lethe". The relay that carries
the VM's traffic is started inside that namespace, where the WireGuard interface
is the only route that exists. So there is nothing to leak to: if the tunnel is
down, packets have nowhere to go. The rest of the computer is not affected.

A profile is treated as data. Only the fields below are kept; PostUp/PreDown and
friends, which wg-quick would run as shell commands, are dropped.

    python3 -I vpn.py import NAME < profile.conf
    python3 -I vpn.py remove | up | down
"""
import ipaddress, json, os, re, subprocess, sys

ETC, NS, DEV = "/etc/lethe", "lethe", "lethe-wg"
KEY = re.compile(r"[A-Za-z0-9+/]{43}=")
ENDPOINT = re.compile(r"(\[[0-9a-fA-F:]+\]|[A-Za-z0-9.-]{1,253}):\d{1,5}")


def parse(text):
    """Validate a wg-quick profile. Returns (config for `wg setconf`, [ipv4 addresses], mtu)."""
    if len(text) > 65536:
        raise ValueError("profile is too large")
    section, iface, peers = None, {}, []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.lower() == "[interface]":
            section = iface
        elif line.lower() == "[peer]":
            peers.append({})
            section = peers[-1]
        elif "=" in line and section is not None:
            k, v = (p.strip() for p in line.split("=", 1))
            section[k.lower()] = v
        else:
            raise ValueError("not a WireGuard profile")
    if not KEY.fullmatch(iface.get("privatekey", "")):
        raise ValueError("missing or invalid PrivateKey")
    addrs = []
    for a in iface.get("address", "").split(","):
        try:
            net = ipaddress.ip_interface(a.strip())
        except ValueError:
            continue
        if net.version == 4:                       # the VM's relay is IPv4-only
            addrs.append(str(net))
    if not addrs:
        raise ValueError("the profile has no IPv4 Address")
    mtu = int(iface["mtu"]) if iface.get("mtu", "").isdigit() and 1280 <= int(iface["mtu"]) <= 1500 else None
    if not peers:
        raise ValueError("the profile has no [Peer]")
    out = [f"[Interface]\nPrivateKey = {iface['privatekey']}\n"]
    for p in peers:
        if not KEY.fullmatch(p.get("publickey", "")) or not ENDPOINT.fullmatch(p.get("endpoint", "")):
            raise ValueError("a peer has no valid PublicKey or Endpoint")
        allowed = [str(ipaddress.ip_network(x.strip(), strict=False)) for x in p.get("allowedips", "0.0.0.0/0").split(",")]
        out.append(f"[Peer]\nPublicKey = {p['publickey']}\nEndpoint = {p['endpoint']}\nAllowedIPs = {', '.join(allowed)}\n")
        if KEY.fullmatch(p.get("presharedkey", "")):
            out.append(f"PresharedKey = {p['presharedkey']}\n")
        if p.get("persistentkeepalive", "").isdigit():
            out.append(f"PersistentKeepalive = {min(int(p['persistentkeepalive']), 65535)}\n")
    return "".join(out), addrs, mtu


def run(*cmd, check=True):
    return subprocess.run(cmd, check=check, env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin"}, capture_output=True, text=True)


def down():
    run("ip", "link", "del", DEV, check=False)      # if it never made it into the namespace
    run("ip", "netns", "del", NS, check=False)      # takes the interface with it


def up():
    with open(f"{ETC}/wg.json") as f:
        meta = json.load(f)
    down()
    try:
        run("ip", "netns", "add", NS)
        # Created out here, so its encrypted UDP leaves through the normal network;
        # then moved inside, where it becomes the only way out.
        run("ip", "link", "add", DEV, "type", "wireguard")
        run("wg", "setconf", DEV, f"{ETC}/wg.conf")
        run("ip", "link", "set", DEV, "netns", NS)
        for a in meta["addresses"]:
            run("ip", "-n", NS, "addr", "add", a, "dev", DEV)
        if meta.get("mtu"):
            run("ip", "-n", NS, "link", "set", DEV, "mtu", str(meta["mtu"]))
        run("ip", "-n", NS, "link", "set", "lo", "up")
        run("ip", "-n", NS, "link", "set", DEV, "up")
        run("ip", "-n", NS, "route", "add", "default", "dev", DEV)
    except subprocess.CalledProcessError as e:
        down()
        sys.exit(f"lethe-vpn: {' '.join(e.cmd[:4])} failed: {e.stderr.strip()}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if os.geteuid() != 0:
        sys.exit("lethe-vpn: must run as root")
    # The caller's file mask does not apply here. Lethe keeps its own files private (mask 077), but
    # it must be able to read which profile is installed; only the key file is root's alone.
    os.umask(0o022)
    if cmd == "import":
        name = re.sub(r"[^A-Za-z0-9 ._-]", "", sys.argv[2] if len(sys.argv) > 2 else "")[:40] or "WireGuard"
        try:
            conf, addrs, mtu = parse(sys.stdin.read(65537))
        except ValueError as e:
            sys.exit(f"lethe-vpn: {e}")
        os.makedirs(ETC, mode=0o755, exist_ok=True)
        os.chmod(ETC, 0o755)
        fd = os.open(f"{ETC}/wg.conf", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)   # holds the private key
        with os.fdopen(fd, "w") as f:
            f.write(conf)
        with open(f"{ETC}/wg.json", "w") as f:
            json.dump({"addresses": addrs, "mtu": mtu}, f)
        with open(f"{ETC}/vpn.name", "w") as f:
            f.write(name + "\n")
        for public in ("wg.json", "vpn.name"):
            os.chmod(f"{ETC}/{public}", 0o644)
        run("systemctl", "restart", "lethe-vpn.service", check=False)
    elif cmd == "remove":
        run("systemctl", "stop", "lethe-vpn.service", check=False)
        for f in ("wg.conf", "wg.json", "vpn.name"):
            try:
                os.unlink(f"{ETC}/{f}")
            except OSError:
                pass
    elif cmd == "up":
        up()
    elif cmd == "down":
        down()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
