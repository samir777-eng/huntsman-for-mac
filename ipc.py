# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""The lighting service's local socket protocol: JSON lines over a UNIX domain socket.

Request  {"id": int, "cmd": str, "args": {...}}           one per line
Reply    {"id": int, "ok": true, "data": ...} | {"id": int, "ok": false, "error": str}
Events   after {"cmd": "subscribe", "args": {"frames": bool}} the connection only carries
         {"event": str, "args": [...]} lines (newest per event name; a slow reader misses old frames).

The socket is local and 0600, and peers must run as the same user, but input is still untrusted: lines are
size-limited, NaN/Infinity are refused, and every command's arguments are type-checked (check_args) before the
service sees them.
"""
import json
import os
import socket
import struct
import threading
import traceback

MAX_LINE = 2 * 1024 * 1024    # a 256 KB preset import, JSON-escaped, fits
MAX_CLIENTS = 16
TIMEOUT = 5.0


class ProtocolError(ValueError):
    pass


class ServiceUnavailable(OSError):
    pass


def _no_constants(name):
    raise ProtocolError(f"{name} is not allowed")


def _loads(data):
    try:
        return json.loads(data, parse_constant=_no_constants)
    except ProtocolError:
        raise
    except (ValueError, UnicodeDecodeError) as e:
        raise ProtocolError(f"not JSON: {e}") from e


def encode(obj):
    return (json.dumps(obj, separators=(",", ":"), allow_nan=False) + "\n").encode()


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def decode_request(line):
    """(id, cmd, args) from one request line, or ProtocolError."""
    req = _loads(line)
    if not isinstance(req, dict):
        raise ProtocolError("a request must be a JSON object")
    extra = set(req) - {"id", "cmd", "args"}
    if extra:
        raise ProtocolError(f"unexpected fields: {sorted(extra)}")
    rid, cmd, args = req.get("id"), req.get("cmd"), req.get("args", {})
    if not _is_int(rid):
        raise ProtocolError("id must be a whole number")
    if not isinstance(cmd, str) or not cmd or len(cmd) > 64:
        raise ProtocolError("cmd must be a command name")
    if not isinstance(args, dict):
        raise ProtocolError("args must be an object")
    return rid, cmd, args


_KINDS = {
    "bool": lambda v: isinstance(v, bool),
    "int": _is_int,
    "num": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "str": lambda v: isinstance(v, str),
    "dict": lambda v: isinstance(v, dict),
    "list": lambda v: isinstance(v, list),
    "none": lambda v: v is None,
}


def check_args(spec, args):
    """spec: {name: tuple of kinds}; a kind of None makes the argument optional. Unknown, missing or
    mistyped arguments raise ProtocolError. Values are checked further by the code that uses them."""
    unknown = set(args) - set(spec)
    if unknown:
        raise ProtocolError(f"unexpected arguments: {sorted(unknown)}")
    out = {}
    for name, kinds in spec.items():
        if name not in args:
            if None in kinds:
                continue
            raise ProtocolError(f"{name} is missing")
        v = args[name]
        if not any(k is not None and _KINDS[k](v) for k in kinds):
            raise ProtocolError(f"{name} has the wrong type")
        out[name] = v
    return out


def _peer_uid(conn):
    """The connecting process's user id (macOS LOCAL_PEERCRED), or None if the OS won't say."""
    try:
        raw = conn.getsockopt(0, 0x001, 76)   # SOL_LOCAL, LOCAL_PEERCRED -> struct xucred
        _version, uid = struct.unpack_from("=II", raw)
        return uid
    except OSError:
        return None


class EventQueue:
    """Newest event per name, waiting for one writer thread."""

    def __init__(self):
        self._slots, self._cv, self.closed = {}, threading.Condition(), False

    def put(self, name, args):
        with self._cv:
            self._slots.pop(name, None)   # keep arrival order of the newest ones
            self._slots[name] = args
            self._cv.notify()

    def take(self, timeout=None):
        with self._cv:
            if not self._slots and not self.closed:
                self._cv.wait(timeout)
            out, self._slots = list(self._slots.items()), {}
            return out

    def close(self):
        with self._cv:
            self.closed = True
            self._cv.notify()


class Server:
    """handle(cmd, args) -> {"ok", "data" | "error"}; subscribe(send(name, args), frames) -> unsubscribe()."""

    def __init__(self, path, handle, subscribe, max_line=MAX_LINE, max_clients=MAX_CLIENTS):
        self.path, self._handle, self._subscribe = path, handle, subscribe
        self._max_line, self._max_clients = max_line, max_clients
        self._sock, self._clients, self._lock, self._closed = None, set(), threading.Lock(), False

    def start(self):
        if os.path.exists(self.path) or os.path.islink(self.path):
            os.unlink(self.path)   # a stale socket; the caller holds the single-instance lock
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        old = os.umask(0o177)
        try:
            s.bind(self.path)
        finally:
            os.umask(old)
        os.chmod(self.path, 0o600)
        s.listen(8)
        self._sock = s
        threading.Thread(target=self._accept, name="huntsman-ipc-accept", daemon=True).start()

    def close(self):
        self._closed = True
        s, self._sock = self._sock, None
        if s is not None:
            try:
                s.close()
            except OSError:
                pass
        with self._lock:
            clients = list(self._clients)
        for c in clients:
            try:
                c.shutdown(socket.SHUT_RDWR)
                c.close()
            except OSError:
                pass
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def _accept(self):
        while not self._closed:
            try:
                conn, _ = self._sock.accept()
            except (OSError, AttributeError):
                return
            uid = _peer_uid(conn)
            with self._lock:
                full = len(self._clients) >= self._max_clients
                if not full and (uid is None or uid == os.getuid()):
                    self._clients.add(conn)
                    conn = (conn, True)
                else:
                    conn = (conn, False)
            if not conn[1]:
                conn[0].close()
                continue
            threading.Thread(target=self._serve, args=(conn[0],), name="huntsman-ipc-client", daemon=True).start()

    def _serve(self, conn):
        f = conn.makefile("rwb")
        try:
            while not self._closed:
                line = f.readline(self._max_line + 1)
                if not line:
                    return
                if len(line) > self._max_line or not line.endswith(b"\n"):
                    f.write(encode({"id": None, "ok": False, "error": "request too large"}))
                    f.flush()
                    return
                if not line.strip():
                    continue
                try:
                    rid, cmd, args = decode_request(line)
                except ProtocolError as e:
                    f.write(encode({"id": None, "ok": False, "error": str(e)}))
                    f.flush()
                    continue
                if cmd == "subscribe":
                    self._stream(conn, f, rid, args)
                    return
                try:
                    reply = self._handle(cmd, args)
                    out = encode({"id": rid, **reply})
                except Exception as e:
                    traceback.print_exc()
                    out = encode({"id": rid, "ok": False, "error": str(e) or type(e).__name__})
                f.write(out)
                f.flush()
        except (OSError, ValueError):
            return
        finally:
            with self._lock:
                self._clients.discard(conn)
            try:
                f.close()
                conn.close()
            except OSError:
                pass

    def _stream(self, conn, f, rid, args):
        try:
            frames = bool(check_args({"frames": ("bool", None)}, args).get("frames", False))
        except ProtocolError as e:
            f.write(encode({"id": rid, "ok": False, "error": str(e)}))
            f.flush()
            return
        q = EventQueue()
        unsubscribe = self._subscribe(q.put, frames)
        # A reader thread notices the client hanging up even when no events are flowing.
        threading.Thread(target=_wait_hangup, args=(conn, q), daemon=True).start()
        try:
            f.write(encode({"id": rid, "ok": True, "data": None}))
            f.flush()
            conn.settimeout(TIMEOUT)   # a client that stops reading is dropped, never blocks the service
            while not self._closed and not q.closed:
                for name, ev_args in q.take(1.0):
                    f.write(encode({"event": name, "args": ev_args}))
                f.flush()
        except (OSError, ValueError, TypeError):
            pass
        finally:
            unsubscribe()


def _wait_hangup(conn, q):
    while not q.closed:
        try:
            if not conn.recv(64):
                break
        except socket.timeout:
            continue
        except OSError:
            break
    q.close()


def _connect(path, timeout):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(path)
    except OSError as e:
        s.close()
        raise ServiceUnavailable(str(e)) from e
    return s


class Client:
    """One connection, requests serialized. ServiceUnavailable when the service can't be reached."""

    def __init__(self, path, timeout=TIMEOUT):
        self.path, self.timeout = path, timeout
        self._sock = self._f = None
        self._lock, self._id = threading.Lock(), 0

    def request(self, cmd, args=None):
        with self._lock:
            for attempt in (0, 1):   # one reconnect: the service may have restarted since the last call
                try:
                    if self._f is None:
                        self._sock = _connect(self.path, self.timeout)
                        self._f = self._sock.makefile("rwb")
                    self._id += 1
                    self._f.write(encode({"id": self._id, "cmd": cmd, "args": args or {}}))
                    self._f.flush()
                    line = self._f.readline(MAX_LINE + 1)
                    if not line:
                        raise ServiceUnavailable("the lighting service closed the connection")
                    reply = _loads(line)
                    if (not isinstance(reply, dict) or not isinstance(reply.get("ok"), bool)
                            or reply.get("id") != self._id):
                        raise ProtocolError("bad reply from the lighting service")
                    reply.pop("id")
                    return reply
                except ServiceUnavailable:
                    self._reset()
                    if attempt or not self._was_connected():
                        raise
                except (OSError, ProtocolError) as e:
                    self._reset()
                    if attempt:
                        raise ServiceUnavailable(str(e)) from e

    def _was_connected(self):
        return self._id > 1

    def _reset(self):
        f, s, self._f, self._sock = self._f, self._sock, None, None
        for x in (f, s):
            try:
                if x is not None:
                    x.close()
            except OSError:
                pass

    def close(self):
        with self._lock:
            self._reset()


class Subscription:
    """Keeps an event stream open on a thread, reconnecting every `retry` seconds while the service is down.
    on_event(name, args) runs on that thread."""

    def __init__(self, path, on_event, frames=True, retry=2.0):
        self.path, self._on_event, self._frames, self._retry = path, on_event, frames, retry
        self._stop, self._sock = threading.Event(), None
        threading.Thread(target=self._run, name="huntsman-ipc-events", daemon=True).start()

    def _run(self):
        while not self._stop.is_set():
            try:
                s = _connect(self.path, TIMEOUT)
                self._sock = s
                f = s.makefile("rwb")
                f.write(encode({"id": 1, "cmd": "subscribe", "args": {"frames": self._frames}}))
                f.flush()
                s.settimeout(None)
                f.readline(MAX_LINE + 1)   # the acknowledgement
                while not self._stop.is_set():
                    line = f.readline(MAX_LINE + 1)
                    if not line:
                        break
                    ev = _loads(line)
                    if isinstance(ev, dict) and isinstance(ev.get("event"), str) and isinstance(ev.get("args"), list):
                        try:
                            self._on_event(ev["event"], ev["args"])
                        except Exception:
                            traceback.print_exc()
            except (OSError, ValueError):
                pass
            finally:
                s, self._sock = self._sock, None
                if s is not None:
                    try:
                        s.close()
                    except OSError:
                        pass
            self._stop.wait(self._retry)

    def close(self):
        self._stop.set()
        s = self._sock
        if s is not None:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
