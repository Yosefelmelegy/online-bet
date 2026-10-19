"""
LAN multiplayer for Whispering House (بيت الهمس).

No pygame dependency, so it can be tested headless.

Design
------
* One player *hosts*: their game process runs a RoomServer (background threads) and
  connects to it through a normal NetClient over loopback. Everyone else connects the
  same way over the LAN. The game therefore has a single client code path.
* Room discovery: the host answers UDP broadcast queries on DISCOVERY_PORT, so a player
  can either tap a room found on the network or type its 6-digit room ID. Typing the
  host's IP address is a fallback for networks that block broadcast.
* Transport: newline-delimited JSON over TCP (GAME_PORT).
* The server is authoritative for room rules only (who is alive / escaped / dead and
  when a level advances or restarts). Movement is client-authoritative and simply relayed.

Rules enforced by the server
----------------------------
* Up to MAX_PLAYERS per room; nobody can join after the game has started.
* A player is 'alive', 'dead' or 'escaped'.
* When nobody is alive any more:
    - at least one player escaped  -> next level; dead players come back to life there
    - everybody is dead            -> after RESTART_DELAY the same level restarts
  Escaping the last level ends the game for the whole room ('win').
"""
import json
import queue
import random
import socket
import threading
import time

PROTO = 1
MAGIC = "BAYTALHAMS"
DISCOVERY_PORT = 47777
GAME_PORT = 47778
MAX_PLAYERS = 8
MAX_LEVEL = 10
STATE_HZ = 15
SILENCE_TIMEOUT = 10.0          # drop a connection that has been silent this long
RESTART_DELAY = 3.0             # pause between "everyone died" and the level restarting
MAX_LINE = 65536
NAME_LEN = 14


# ----------------------------------------------------------------------------- helpers
def local_ip():
    """Best-effort LAN address of this machine (works without internet access)."""
    for target in (("10.254.254.254", 1), ("192.168.254.254", 1), ("8.8.8.8", 80)):
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(target)
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127.") and ip != "0.0.0.0":
                return ip
        except OSError:
            pass
        finally:
            if s:
                s.close()
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    return "127.0.0.1"


def broadcast_targets():
    t = ["255.255.255.255"]
    ip = local_ip()
    if ip.count(".") == 3 and not ip.startswith("127."):
        t.append(ip.rsplit(".", 1)[0] + ".255")          # typical /24 directed broadcast
    return t


def clean_name(n):
    n = "".join(c for c in str(n or "") if c.isprintable()).strip()[:NAME_LEN]
    return n or "?"


def _udp_socket(bind=None, reuse=False):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    if reuse:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
    if bind is not None:
        s.bind(bind)
    return s


def _parse(data):
    try:
        m = json.loads(data.decode("utf-8"))
        return m if isinstance(m, dict) and m.get("g") == MAGIC else None
    except (ValueError, UnicodeDecodeError):
        return None


def _query_packet(room=None):
    return json.dumps({"g": MAGIC, "t": "who", "room": room}).encode()


# ----------------------------------------------------------------------------- connection
class Conn:
    """A TCP connection with its own reader and writer thread (so the game loop never blocks)."""

    def __init__(self, sock, on_msg, on_close):
        self.sock, self.on_msg, self.on_close = sock, on_msg, on_close
        self.out = queue.Queue()
        self.alive = True
        self.last_rx = time.time()
        self._closed_cb = False
        self._lock = threading.Lock()
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except OSError:
            pass
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._writer, daemon=True).start()

    def send(self, msg):
        if not self.alive:
            return
        if self.out.qsize() > 600:                  # peer is not reading: cut it loose
            self.close()
            return
        self.out.put((json.dumps(msg, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8"))

    def _reader(self):
        buf = b""
        try:
            while self.alive:
                chunk = self.sock.recv(8192)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        m = json.loads(line.decode("utf-8"))
                    except (ValueError, UnicodeDecodeError):
                        continue
                    if isinstance(m, dict):
                        self.last_rx = time.time()
                        self.on_msg(self, m)
                if len(buf) > MAX_LINE:
                    break
        except OSError:
            pass
        self.close()

    def _writer(self):
        try:
            while True:
                data = self.out.get()
                if data is None:
                    break
                self.sock.sendall(data)
        except OSError:
            pass
        self.close()

    def close(self):
        with self._lock:
            if self._closed_cb:
                return
            self._closed_cb = True
            self.alive = False
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
        self.out.put(None)
        self.on_close(self)


# ----------------------------------------------------------------------------- server
class RoomServer:
    """Hosts one room. All room state is touched only by the logic thread."""

    def __init__(self, host_name, seed, room_id, max_players=MAX_PLAYERS, port=GAME_PORT):
        self.host_name = clean_name(host_name)
        self.seed = seed
        self.room_id = str(room_id)
        self.max_players = max_players
        self.port = port
        self.host_key = "%032x" % random.getrandbits(128)       # proves "I am the host" to the server
        self.ip = local_ip()
        self.running = False
        self.error = ""
        self.discovery_ok = False
        self.inbox = queue.Queue()
        self.players = {}              # pid -> dict
        self.by_conn = {}              # Conn -> pid
        self.host_pid = None
        self.phase = "lobby"           # lobby | playing | win
        self.level = 0
        self.epoch = 0
        self.restart_at = None
        self._next_pid = 1
        self._lsock = None
        self._conns = set()

    # ---- lifecycle
    def start(self):
        try:
            self._lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                self._lsock.bind(("0.0.0.0", self.port))
            except OSError:
                self._lsock.bind(("0.0.0.0", 0))                # default port busy: any free port
            self.port = self._lsock.getsockname()[1]
            self._lsock.listen(16)
            self._lsock.settimeout(0.5)
        except OSError as ex:
            self.error = str(ex)
            return False
        self.running = True
        for fn in (self._accept_loop, self._discovery_loop, self._logic_loop):
            threading.Thread(target=fn, daemon=True).start()
        return True

    def stop(self):
        if not self.running:
            return
        self.running = False
        for c in list(self._conns):
            c.send({"t": "bye", "why": "closed"})
        time.sleep(0.05)
        for c in list(self._conns):
            c.close()
        try:
            self._lsock.close()
        except OSError:
            pass

    # ---- threads
    def _accept_loop(self):
        while self.running:
            try:
                sock, _addr = self._lsock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            sock.settimeout(None)
            c = Conn(sock, lambda c, m: self.inbox.put((c, m)), lambda c: self.inbox.put((c, None)))
            self._conns.add(c)

    def _discovery_loop(self):
        try:
            s = _udp_socket(("", DISCOVERY_PORT), reuse=True)
            s.settimeout(0.5)
        except OSError:
            return                                              # LAN discovery unavailable; manual IP still works
        self.discovery_ok = True
        while self.running:
            try:
                data, addr = s.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            m = _parse(data)
            if not m or m.get("t") != "who" or m.get("room") not in (None, "", self.room_id):
                continue
            reply = {"g": MAGIC, "t": "here", "v": PROTO, "room": self.room_id, "port": self.port,
                     "host": self.host_name, "n": len(self.players), "max": self.max_players, "st": self.phase}
            try:
                s.sendto(json.dumps(reply).encode(), addr)
            except OSError:
                pass
        s.close()

    def _logic_loop(self):
        last_state = 0.0
        while self.running:
            try:
                c, m = self.inbox.get(timeout=0.03)
                self._handle(c, m)
                while True:                                     # drain whatever else is waiting
                    c, m = self.inbox.get_nowait()
                    self._handle(c, m)
            except queue.Empty:
                pass
            now = time.time()
            if self.restart_at and now >= self.restart_at and self.phase == "playing":
                self.restart_at = None
                self._new_level("restart")
            if now - last_state >= 1.0 / STATE_HZ:
                last_state = now
                self._broadcast_state()
            for c in list(self.by_conn):                        # silent peers (phone locked, Wi-Fi gone)
                if now - c.last_rx > SILENCE_TIMEOUT:
                    c.close()

    # ---- message handling
    def _handle(self, c, m):
        if m is None:
            self._conns.discard(c)
            self._drop(c)
            return
        t = m.get("t")
        if t == "join":
            self._on_join(c, m)
            return
        pid = self.by_conn.get(c)
        p = self.players.get(pid)
        if p is None:
            return
        if t == "start":
            if pid == self.host_pid and self.phase == "lobby":
                self.phase, self.level = "playing", 1
                self._new_level("start")
        elif t == "pos":
            if p["st"] == "alive" and m.get("e") == self.epoch and self.phase == "playing":
                try:
                    p["x"], p["y"] = int(m["x"]), int(m["y"])
                    p["fx"], p["fy"] = float(m.get("fx", 0)), float(m.get("fy", -1))
                    p["fl"] = int(m.get("f", 0))
                    g = m.get("g") or []
                    p["g"] = [[int(a), int(b), float(al)] for a, b, al in g[:4]]
                    p["has_pos"] = True
                except (KeyError, ValueError, TypeError):
                    pass
        elif t == "op":
            if m.get("e") == self.epoch and isinstance(m.get("ids"), list):
                p["op"] = [str(i)[:40] for i in m["ids"][:40]]
                for q in self.players.values():
                    if q is not p:
                        q["conn"].send({"t": "op", "pid": pid, "e": self.epoch, "ids": p["op"]})
        elif t in ("die", "esc"):
            if self.phase == "playing" and p["st"] == "alive" and m.get("e") == self.epoch:
                if t == "die":
                    p["st"], p["cause"] = "dead", str(m.get("why", ""))[:12]
                    p["dx"], p["dy"] = int(m.get("x", p["x"] or 0)), int(m.get("y", p["y"] or 0))
                else:
                    p["st"] = "escaped"
                p["g"] = []
                self._roster()
                self._check_progress()
        elif t == "leave":
            c.close()

    def _on_join(self, c, m):
        if c in self.by_conn:
            return
        if m.get("v") != PROTO:
            return self._deny(c, "version")
        if self.phase != "lobby":
            return self._deny(c, "started")
        if len(self.players) >= self.max_players:
            return self._deny(c, "full")
        is_host = self.host_pid is None and m.get("key") == self.host_key
        used = {p["slot"] for p in self.players.values()}
        slot = next(i for i in range(self.max_players + 1) if i not in used)
        pid = self._next_pid
        self._next_pid += 1
        self.players[pid] = dict(pid=pid, name=clean_name(m.get("name")), slot=slot, conn=c, st="alive",
                                 x=0, y=0, fx=0.0, fy=-1.0, fl=0, g=[], op=[], dx=0, dy=0, cause="",
                                 has_pos=False)
        self.by_conn[c] = pid
        if is_host:
            self.host_pid = pid
        c.send({"t": "welcome", "pid": pid, "slot": slot, "room": self.room_id, "seed": self.seed,
                "max": self.max_players, "host": is_host, "v": PROTO})
        self._roster()

    @staticmethod
    def _deny(c, why):
        c.send({"t": "deny", "why": why})
        threading.Timer(0.3, c.close).start()

    def _drop(self, c):
        pid = self.by_conn.pop(c, None)
        if pid is None:
            return
        self.players.pop(pid, None)
        if pid == self.host_pid:                                # the room dies with its host
            for q in self.players.values():
                q["conn"].send({"t": "bye", "why": "host_left"})
            self.running = False
            time.sleep(0.05)
            for cc in list(self._conns):
                cc.close()
            try:
                self._lsock.close()
            except OSError:
                pass
            return
        self._roster()
        if self.phase == "playing":
            self._check_progress()

    # ---- game rules
    def _check_progress(self):
        if self.phase != "playing" or self.restart_at or not self.players:
            return
        if any(p["st"] == "alive" for p in self.players.values()):
            return
        if any(p["st"] == "escaped" for p in self.players.values()):
            if self.level >= MAX_LEVEL:
                self.phase = "win"
                self._send_all({"t": "win"})
            else:
                self.level += 1
                self._new_level("next")
        else:                                                   # everyone is dead
            self.restart_at = time.time() + RESTART_DELAY
            self._send_all({"t": "wipe", "n": self.level, "after": RESTART_DELAY})

    def _new_level(self, why):
        self.epoch += 1
        for p in self.players.values():
            p.update(st="alive", has_pos=False, op=[], g=[], cause="")
        self._send_all({"t": "level", "n": self.level, "e": self.epoch, "why": why})
        self._roster()

    # ---- broadcasting
    def _send_all(self, msg):
        for p in self.players.values():
            p["conn"].send(msg)

    def _roster(self):
        pl = [dict(pid=p["pid"], name=p["name"], slot=p["slot"], st=p["st"], host=p["pid"] == self.host_pid,
                   dx=p["dx"], dy=p["dy"], why=p["cause"]) for p in self.players.values()]
        self._send_all({"t": "roster", "players": pl, "n": self.level, "phase": self.phase,
                        "room": self.room_id})

    def _broadcast_state(self):
        if self.phase != "playing" or self.restart_at:
            return
        live = {pid: [p["x"], p["y"], round(p["fx"], 2), round(p["fy"], 2), p["fl"], p["g"]]
                for pid, p in self.players.items() if p["st"] == "alive" and p["has_pos"]}
        for pid, p in self.players.items():
            others = {str(k): v for k, v in live.items() if k != pid}
            if others:
                p["conn"].send({"t": "st", "e": self.epoch, "p": others})


# ----------------------------------------------------------------------------- client
class NetClient:
    """One connection to a room. Network threads fill `inbox`; the game polls it each frame."""

    def __init__(self):
        self.inbox = queue.Queue()
        self.conn = None
        self.state = "idle"            # idle | connecting | open | closed
        self._gen = 0

    def connect(self, ip, port, name, host_key=None):
        self.state = "connecting"
        self._gen += 1
        gen = self._gen

        def run():
            try:
                sock = socket.create_connection((ip, int(port)), timeout=4)
                sock.settimeout(None)
            except (OSError, ValueError):
                if gen == self._gen:
                    self.state = "closed"
                    self.inbox.put({"t": "error", "why": "unreachable"})
                return
            if gen != self._gen:
                sock.close()
                return
            self.conn = Conn(sock, lambda c, m: self.inbox.put(m), self._closed)
            self.state = "open"
            j = {"t": "join", "v": PROTO, "name": name}
            if host_key:
                j["key"] = host_key
            self.conn.send(j)
        threading.Thread(target=run, daemon=True).start()

    def _closed(self, c):
        if c is self.conn and self.state != "closed":
            self.state = "closed"
            self.inbox.put({"t": "closed"})

    def send(self, msg):
        if self.conn and self.state == "open":
            self.conn.send(msg)

    def poll(self):
        out = []
        try:
            while True:
                out.append(self.inbox.get_nowait())
        except queue.Empty:
            pass
        return out

    def close(self):
        self._gen += 1                                          # cancels a connect that is still in flight
        c, self.conn = self.conn, None
        self.state = "closed"
        if c:
            c.send({"t": "leave"})
            threading.Timer(0.15, c.close).start()


# ----------------------------------------------------------------------------- discovery (client side)
class Scanner:
    """Periodically asks the LAN 'who is hosting?' and keeps the answers in `rooms`."""

    def __init__(self, targets=None, interval=1.0):
        self.rooms = {}                # room_id -> dict(ip, port, host, n, max, st, seen)
        self.targets = targets
        self.interval = interval
        self.running = False
        self.ok = True

    def start(self):
        if self.running:
            return
        self.running = True
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self.running = False

    def _run(self):
        try:
            s = _udp_socket(("", 0))
            s.settimeout(0.2)
        except OSError:
            self.ok = False
            self.running = False
            return
        targets = self.targets or broadcast_targets()
        last = 0.0
        while self.running:
            now = time.time()
            if now - last >= self.interval:
                last = now
                for t in targets:
                    try:
                        s.sendto(_query_packet(), (t, DISCOVERY_PORT))
                    except OSError:
                        pass
            try:
                data, addr = s.recvfrom(2048)
                m = _parse(data)
                if m and m.get("t") == "here" and m.get("v") == PROTO:
                    rooms = dict(self.rooms)
                    rooms[str(m["room"])] = dict(ip=addr[0], port=int(m["port"]), host=str(m.get("host", "?")),
                                                 n=int(m.get("n", 0)), max=int(m.get("max", MAX_PLAYERS)),
                                                 st=m.get("st", "lobby"), seen=time.time())
                    self.rooms = rooms
            except socket.timeout:
                pass
            except (OSError, ValueError, KeyError):
                pass
            cutoff = time.time() - 4.0
            if any(r["seen"] < cutoff for r in self.rooms.values()):
                self.rooms = {k: r for k, r in self.rooms.items() if r["seen"] >= cutoff}
        s.close()

    def listing(self):
        return sorted(self.rooms.items())


def room_exists(room_id, wait=0.6, targets=None):
    """Blocking probe used before creating a room, so the ID is unique on this LAN."""
    try:
        s = _udp_socket(("", 0))
        s.settimeout(0.15)
    except OSError:
        return False
    pkt = _query_packet(str(room_id))
    end = time.time() + wait
    sent = 0.0
    try:
        while time.time() < end:
            if time.time() - sent > 0.25:
                sent = time.time()
                for t in (targets or broadcast_targets()):
                    try:
                        s.sendto(pkt, (t, DISCOVERY_PORT))
                    except OSError:
                        pass
            try:
                data, _addr = s.recvfrom(2048)
            except socket.timeout:
                continue
            m = _parse(data)
            if m and m.get("t") == "here" and str(m.get("room")) == str(room_id):
                return True
    except OSError:
        pass
    finally:
        s.close()
    return False


def new_room_id(targets=None):
    """6-digit room ID, checked to be unused on the local network."""
    rid = str(random.randint(100000, 999999))
    for _ in range(6):
        if not room_exists(rid, targets=targets):
            return rid
        rid = str(random.randint(100000, 999999))
    return rid
