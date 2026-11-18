# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""The lighting service's local protocol: JSON lines over a UNIX domain socket (Mac) or a named pipe (Windows).

Request  {"id": int, "cmd": str, "args": {...}}           one per line
Reply    {"id": int, "ok": true, "data": ...} | {"id": int, "ok": false, "error": str}
Events   after {"cmd": "subscribe", "args": {"frames": bool}} the connection only carries
         {"event": str, "args": [...]} lines (newest per event name; a slow reader misses old frames).

Endpoints: UnixEndpoint (the Mac: a 0600 socket file, peers must run as the same user) and PipeEndpoint (Windows,
experimental: multiprocessing.connection Listener/Client on a per-user named pipe, each side proving it knows the
authkey the service writes at every start into a file in the user's data folder; one message per line). Server,
Client and Subscription take either (a plain path means a UnixEndpoint); service_endpoint() picks the platform's.
Input is untrusted either way: lines are size-limited, NaN/Infinity are refused, and every command's arguments are
type-checked (check_args) before the service sees them.
"""
import json
import os
import re
import secrets
import socket
import struct
import threading
import time
import traceback

import platforms

MAX_LINE = 2 * 1024 * 1024    # a 256 KB preset import, JSON-escaped, fits
MAX_CLIENTS = 16
TIMEOUT = 5.0


class ProtocolError(ValueError):
    pass


class ServiceUnavailable(OSError):
    pass


class RequestTooLarge(ProtocolError):
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


# ---------- streams: one connection, read and written by lines ----------

def _peer_uid(conn):
    """The connecting process's user id (macOS LOCAL_PEERCRED), or None if the OS won't say."""
    try:
        raw = conn.getsockopt(0, 0x001, 76)   # SOL_LOCAL, LOCAL_PEERCRED -> struct xucred
        _version, uid = struct.unpack_from("=II", raw)
        return uid
    except OSError:
        return None


class _SocketStream:
    """A connected UNIX socket. readline(limit) returns at most limit bytes (b"" at the end)."""

    def __init__(self, sock):
        self.sock, self.f = sock, sock.makefile("rwb")

    def admit(self):
        uid = _peer_uid(self.sock)
        return uid is None or uid == os.getuid()

    def readline(self, limit):
        return self.f.readline(limit)

    def write(self, data):
        self.f.write(data)

    def flush(self):
        self.f.flush()

    def settimeout(self, t):
        self.sock.settimeout(t)

    def wait_hangup(self, q):
        while not q.closed:
            try:
                if not self.sock.recv(64):
                    break
            except socket.timeout:
                continue
            except OSError:
                break
        q.close()

    def shutdown(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def close(self):
        for x in (self.f, self.sock):
            try:
                x.close()
            except OSError:
                pass


class _Timed:
    """A Connection whose recv_bytes waits at most until deadline (for the authkey handshake, which
    multiprocessing would otherwise wait on forever)."""

    def __init__(self, conn, deadline):
        self._conn, self._deadline = conn, deadline

    def send_bytes(self, data):
        self._conn.send_bytes(data)

    def recv_bytes(self, maxlength=None):
        if not self._conn.poll(max(0.0, self._deadline - time.monotonic())):
            raise socket.timeout("the other side didn't answer the handshake in time")
        return self._conn.recv_bytes(maxlength)


def _handshake(conn, key, serving, timeout=None):
    """Both sides prove they know key (multiprocessing's HMAC challenge), within timeout (default TIMEOUT)."""
    from multiprocessing.connection import answer_challenge, deliver_challenge
    t = _Timed(conn, time.monotonic() + (TIMEOUT if timeout is None else timeout))
    if serving:
        deliver_challenge(t, key)
        answer_challenge(t, key)
    else:
        answer_challenge(t, key)
        deliver_challenge(t, key)


class _ConnStream:
    """A multiprocessing.connection Connection carrying one line per message. Reads poll in short steps so a
    timeout and close() from another thread work on a named pipe too (it has no socket timeouts). Writes have no
    timeout: a subscriber that stops reading blocks only its own stream thread (EventQueue keeps the newest)."""
    STEP = 0.25

    def __init__(self, conn, key=None):
        self.conn, self._key, self.timeout, self._closed = conn, key, None, False

    def admit(self):
        """The authkey handshake both ways (the service proves it knows the key too), in the client's own thread
        and bounded by TIMEOUT, so a client that stalls holds its slot for at most that long."""
        from multiprocessing import AuthenticationError
        try:
            _handshake(self.conn, self._key, serving=True)
            return True
        except (AuthenticationError, OSError, EOFError, ValueError):
            return False

    def readline(self, limit):
        deadline = None if self.timeout is None else time.monotonic() + self.timeout
        while True:
            if self._closed:
                return b""
            step = self.STEP if deadline is None else max(0.0, min(self.STEP, deadline - time.monotonic()))
            try:
                if self.conn.poll(step):
                    break
            except (OSError, EOFError, ValueError):
                return b""
            if deadline is not None and time.monotonic() >= deadline:
                raise socket.timeout("timed out")
        try:
            return self.conn.recv_bytes(limit)
        except EOFError:
            return b""
        except OSError as e:
            if "message length" in str(e):
                raise RequestTooLarge("request too large") from e
            raise

    def write(self, data):
        self.conn.send_bytes(data)

    def flush(self):
        pass

    def settimeout(self, t):
        self.timeout = t

    def wait_hangup(self, q):
        while not q.closed and not self._closed:
            try:
                if self.conn.poll(1.0):
                    self.conn.recv_bytes(MAX_LINE)   # a subscriber sends nothing more; read and drop it
            except (OSError, EOFError, ValueError):
                break
        q.close()

    def shutdown(self):
        self._closed = True

    def close(self):
        self._closed = True
        try:
            self.conn.close()
        except OSError:
            pass


# ---------- endpoints ----------

class UnixEndpoint:
    """The Mac's: a UNIX socket file at path, 0600, peers checked to be this user."""

    def __init__(self, path):
        self.path = path

    def listen(self):
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
        return _UnixListener(s, self.path)

    def connect(self, timeout):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect(self.path)
        except OSError as e:
            s.close()
            raise ServiceUnavailable(str(e)) from e
        return _SocketStream(s)


class _UnixListener:
    def __init__(self, sock, path):
        self._sock, self._path = sock, path

    def accept(self):
        conn, _ = self._sock.accept()
        conn.settimeout(None)
        return _SocketStream(conn)

    def close(self):
        try:
            self._sock.close()
        except OSError:
            pass
        try:
            os.unlink(self._path)
        except OSError:
            pass


def write_authkey(path):
    """A new random authkey in a file only this user can read (0600; on Windows the user's own AppData folder)."""
    key = secrets.token_bytes(32)
    tmp = f"{path}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
    try:
        os.write(fd, key)
    finally:
        os.close(fd)
    try:
        for attempt in range(20):   # Windows refuses the replace while a client has the old key open
            try:
                os.replace(tmp, path)
                return key
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.05)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


class PipeEndpoint:
    """Windows' (experimental): multiprocessing.connection at address (family "AF_PIPE" on Windows; tests use
    "AF_UNIX"), authenticated with the key in key_path, which listen() renews at every service start."""

    def __init__(self, address, key_path, family=None):
        self.address, self.key_path, self.family = address, key_path, family

    def listen(self):
        from multiprocessing.connection import Listener
        key = write_authkey(self.key_path)
        return _PipeListener(Listener(self.address, family=self.family, backlog=8), key)

    def connect(self, timeout):
        from multiprocessing import AuthenticationError
        from multiprocessing.connection import Client
        try:
            with open(self.key_path, "rb") as f:
                key = f.read()
        except OSError as e:
            raise ServiceUnavailable(f"no service key: {e}") from e
        try:
            conn = Client(self.address, family=self.family)   # no authkey here: its handshake has no timeout
        except (OSError, EOFError) as e:
            raise ServiceUnavailable(str(e) or type(e).__name__) from e
        try:
            _handshake(conn, key, serving=False, timeout=timeout or TIMEOUT)
        except (AuthenticationError, OSError, EOFError, ValueError) as e:
            conn.close()
            raise ServiceUnavailable(f"the lighting service refused the connection: {e or type(e).__name__}") from e
        stream = _ConnStream(conn)
        stream.settimeout(timeout)
        return stream


class _PipeListener:
    def __init__(self, listener, key):
        self._l, self._key = listener, key

    def accept(self):
        return _ConnStream(self._l.accept(), self._key)

    def close(self):
        try:
            self._l.close()
        except OSError:
            pass


def _pipe_name():
    user = os.environ.get("USERNAME") or os.environ.get("USER") or "user"
    domain = os.environ.get("USERDOMAIN", "")
    name = f"{domain}.{user}" if domain else user   # DOMAIN\\bob and a local bob get different pipes
    return "huntsman-for-mac-" + (re.sub(r"[^A-Za-z0-9_.-]", "_", name)[:96] or "user")


def service_endpoint(data_dir):
    """The lighting service's endpoint on this platform: data_dir/service.sock on the Mac; on Windows the named
    pipe \\\\.\\pipe\\huntsman-for-mac-<user> with its authkey in data_dir/service.key."""
    if platforms.is_windows():
        return PipeEndpoint("\\\\.\\pipe\\" + _pipe_name(), os.path.join(data_dir, "service.key"), family="AF_PIPE")
    return UnixEndpoint(os.path.join(data_dir, "service.sock"))


def as_endpoint(endpoint):
    return UnixEndpoint(endpoint) if isinstance(endpoint, (str, os.PathLike)) else endpoint


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
    """handle(cmd, args) -> {"ok", "data" | "error"}; subscribe(send(name, args), frames) -> unsubscribe().
    endpoint: a UnixEndpoint / PipeEndpoint, or a socket path."""

    def __init__(self, endpoint, handle, subscribe, max_line=MAX_LINE, max_clients=MAX_CLIENTS):
        self.endpoint = as_endpoint(endpoint)
        self.path = getattr(self.endpoint, "path", None)
        self._handle, self._subscribe = handle, subscribe
        self._max_line, self._max_clients = max_line, max_clients
        self._listener, self._clients, self._lock, self._closed = None, set(), threading.Lock(), False

    def start(self):
        self._listener = self.endpoint.listen()
        threading.Thread(target=self._accept, name="huntsman-ipc-accept", daemon=True).start()

    def close(self):
        self._closed = True
        lst, self._listener = self._listener, None
        if lst is not None:
            lst.close()
        with self._lock:
            clients = list(self._clients)
        for c in clients:
            c.shutdown()
            c.close()

    def _accept(self):
        while not self._closed:
            lst = self._listener
            try:
                conn = lst.accept()
            except (OSError, AttributeError, EOFError):
                return
            if self._closed:   # a pipe accept isn't woken by close(); don't serve whoever came after it
                conn.close()
                return
            with self._lock:
                ok = len(self._clients) < self._max_clients
                if ok:
                    self._clients.add(conn)
            if not ok:
                conn.close()
                continue
            threading.Thread(target=self._serve, args=(conn,), name="huntsman-ipc-client", daemon=True).start()

    def _serve(self, conn):
        try:
            if not conn.admit():
                return
            while not self._closed:
                try:
                    line = conn.readline(self._max_line + 1)
                except RequestTooLarge:
                    line = b"x" * (self._max_line + 1)
                if not line:
                    return
                if len(line) > self._max_line or not line.endswith(b"\n"):
                    conn.write(encode({"id": None, "ok": False, "error": "request too large"}))
                    conn.flush()
                    return
                if not line.strip():
                    continue
                try:
                    rid, cmd, args = decode_request(line)
                except ProtocolError as e:
                    conn.write(encode({"id": None, "ok": False, "error": str(e)}))
                    conn.flush()
                    continue
                if cmd == "subscribe":
                    self._stream(conn, rid, args)
                    return
                try:
                    reply = self._handle(cmd, args)
                    out = encode({"id": rid, **reply})
                except Exception as e:
                    traceback.print_exc()
                    out = encode({"id": rid, "ok": False, "error": str(e) or type(e).__name__})
                conn.write(out)
                conn.flush()
        except (OSError, ValueError, EOFError):
            return
        finally:
            with self._lock:
                self._clients.discard(conn)
            conn.close()

    def _stream(self, conn, rid, args):
        try:
            frames = bool(check_args({"frames": ("bool", None)}, args).get("frames", False))
        except ProtocolError as e:
            conn.write(encode({"id": rid, "ok": False, "error": str(e)}))
            conn.flush()
            return
        q = EventQueue()
        unsubscribe = self._subscribe(q.put, frames)
        # A reader thread notices the client hanging up even when no events are flowing.
        threading.Thread(target=conn.wait_hangup, args=(q,), daemon=True).start()
        try:
            conn.write(encode({"id": rid, "ok": True, "data": None}))
            conn.flush()
            conn.settimeout(TIMEOUT)   # a client that stops reading is dropped, never blocks the service
            while not self._closed and not q.closed:
                for name, ev_args in q.take(1.0):
                    conn.write(encode({"event": name, "args": ev_args}))
                conn.flush()
        except (OSError, ValueError, TypeError, EOFError):
            pass
        finally:
            unsubscribe()


def _connect(endpoint, timeout):
    return as_endpoint(endpoint).connect(timeout)


class Client:
    """One connection, requests serialized. ServiceUnavailable when the service can't be reached.
    endpoint: a UnixEndpoint / PipeEndpoint, or a socket path."""

    def __init__(self, endpoint, timeout=TIMEOUT):
        self.endpoint, self.timeout = as_endpoint(endpoint), timeout
        self.path = getattr(self.endpoint, "path", None)
        self._f = None
        self._lock, self._id = threading.Lock(), 0

    def request(self, cmd, args=None):
        with self._lock:
            for attempt in (0, 1):   # one reconnect: the service may have restarted since the last call
                try:
                    if self._f is None:
                        self._f = _connect(self.endpoint, self.timeout)
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
                except (OSError, ProtocolError, EOFError) as e:
                    self._reset()
                    if attempt:
                        raise ServiceUnavailable(str(e)) from e

    def _was_connected(self):
        return self._id > 1

    def _reset(self):
        f, self._f = self._f, None
        if f is not None:
            f.close()

    def close(self):
        with self._lock:
            self._reset()


class Subscription:
    """Keeps an event stream open on a thread, reconnecting every `retry` seconds while the service is down.
    on_event(name, args) runs on that thread."""

    def __init__(self, endpoint, on_event, frames=True, retry=2.0):
        self.endpoint, self._on_event, self._frames, self._retry = as_endpoint(endpoint), on_event, frames, retry
        self.path = getattr(self.endpoint, "path", None)
        self._stop, self._sock = threading.Event(), None
        threading.Thread(target=self._run, name="huntsman-ipc-events", daemon=True).start()

    def _run(self):
        while not self._stop.is_set():
            try:
                f = _connect(self.endpoint, TIMEOUT)
                self._sock = f
                f.write(encode({"id": 1, "cmd": "subscribe", "args": {"frames": self._frames}}))
                f.flush()
                f.settimeout(None)
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
            except (OSError, ValueError, EOFError):
                pass
            finally:
                s, self._sock = self._sock, None
                if s is not None:
                    s.close()
            self._stop.wait(self._retry)

    def close(self):
        self._stop.set()
        s = self._sock
        if s is not None:
            s.shutdown()
