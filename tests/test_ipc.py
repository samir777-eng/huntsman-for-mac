# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""The lighting service's socket protocol (ipc.py): framing, validation, round trips, subscriptions and several
clients at once, on a real UNIX socket in a short temporary folder (socket paths are limited to 104 bytes)."""
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ipc  # noqa: E402

pytestmark = pytest.mark.mac_only   # the Mac's UNIX socket (Windows uses the named pipe: test_ipc_pipe.py)


@pytest.fixture
def sock_path():
    d = tempfile.mkdtemp(prefix="hm", dir="/tmp")
    yield os.path.join(d, "s.sock")
    shutil.rmtree(d, ignore_errors=True)


# ---------- validation ----------

@pytest.mark.parametrize("line", [b"not json", b"[1,2]", b'{"cmd": 3}', b'{"id": "x", "cmd": "a"}',
                                  b'{"id": 1, "cmd": "a", "args": []}', b'{"id": 1, "cmd": "a", "extra": 1}',
                                  b'{"id": 1, "cmd": "a", "args": {"x": NaN}}', b'{"id": 1, "cmd": ""}',
                                  b'{"id": true, "cmd": "a"}'])
def test_bad_requests_are_refused(line):
    with pytest.raises(ipc.ProtocolError):
        ipc.decode_request(line)


def test_good_request_decodes():
    assert ipc.decode_request(b'{"id": 7, "cmd": "set_fps", "args": {"fps": 30}}') == (7, "set_fps", {"fps": 30})
    assert ipc.decode_request(b'{"id": 1, "cmd": "ping"}') == (1, "ping", {})


def test_check_args_types_required_and_unknown():
    spec = {"on": ("bool",), "restore": ("bool", None)}
    assert ipc.check_args(spec, {"on": True}) == {"on": True}
    assert ipc.check_args(spec, {"on": False, "restore": False}) == {"on": False, "restore": False}
    for bad in ({}, {"on": 1}, {"on": True, "x": 1}, {"on": True, "restore": "no"}):
        with pytest.raises(ipc.ProtocolError):
            ipc.check_args(spec, bad)
    num = {"level": ("num",), "device": ("int", "none")}
    assert ipc.check_args(num, {"level": 0.5, "device": None}) == {"level": 0.5, "device": None}
    with pytest.raises(ipc.ProtocolError):
        ipc.check_args(num, {"level": True, "device": None})    # a bool is not a number


# ---------- a running server ----------

def start(sock_path, handle=None, **kw):
    subs = []

    def subscribe(send, frames):
        subs.append((send, frames))
        return lambda: subs.remove((send, frames)) if (send, frames) in subs else None
    srv = ipc.Server(sock_path, handle or (lambda cmd, args: {"ok": True, "data": [cmd, args]}), subscribe, **kw)
    srv.start()
    return srv, subs


def test_round_trip_and_socket_is_private(sock_path):
    srv, _ = start(sock_path)
    try:
        assert os.stat(sock_path).st_mode & 0o777 == 0o600
        c = ipc.Client(sock_path)
        assert c.request("set_fps", {"fps": 30}) == {"ok": True, "data": ["set_fps", {"fps": 30}]}
        assert c.request("ping") == {"ok": True, "data": ["ping", {}]}
        c.close()
    finally:
        srv.close()
    assert not os.path.exists(sock_path)


def test_handler_errors_become_error_replies(sock_path):
    def handle(cmd, args):
        raise RuntimeError("boom")
    srv, _ = start(sock_path, handle)
    try:
        r = ipc.Client(sock_path).request("x")
        assert r["ok"] is False and "boom" in r["error"]
    finally:
        srv.close()


def test_malformed_line_gets_an_error_and_the_connection_stays_usable(sock_path):
    srv, _ = start(sock_path)
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(sock_path)
        f = s.makefile("rwb")
        f.write(b"garbage\n")
        f.flush()
        assert json.loads(f.readline())["ok"] is False
        f.write(b'{"id": 2, "cmd": "ping"}\n')
        f.flush()
        assert json.loads(f.readline()) == {"id": 2, "ok": True, "data": ["ping", {}]}
        s.close()
    finally:
        srv.close()


def test_oversized_line_is_refused_and_closed(sock_path):
    srv, _ = start(sock_path, max_line=1024)
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(sock_path)
        s.sendall(b'{"id": 1, "cmd": "' + b"a" * 4096 + b'"}\n')
        f = s.makefile("rb")
        assert "too large" in json.loads(f.readline())["error"]
        assert f.readline() == b""    # closed
        s.close()
    finally:
        srv.close()


def test_concurrent_clients(sock_path):
    def handle(cmd, args):
        time.sleep(0.01)
        return {"ok": True, "data": args["n"]}
    srv, _ = start(sock_path, handle)
    out, errors = {}, []

    def worker(i):
        try:
            c = ipc.Client(sock_path)
            out[i] = [c.request("echo", {"n": i * 100 + j})["data"] for j in range(5)]
            c.close()
        except Exception as e:   # pragma: no cover - reported below
            errors.append(e)
    try:
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        [t.start() for t in threads]
        [t.join(10) for t in threads]
        assert not errors
        assert out == {i: [i * 100 + j for j in range(5)] for i in range(8)}
    finally:
        srv.close()


def test_client_reports_a_missing_service(sock_path):
    with pytest.raises(ipc.ServiceUnavailable):
        ipc.Client(sock_path).request("ping")


def test_subscription_receives_events_and_unsubscribes_on_close(sock_path):
    srv, subs = start(sock_path)
    got, seen = [], threading.Event()

    def on_event(name, args):
        got.append((name, args))
        seen.set()
    sub = ipc.Subscription(sock_path, on_event, frames=True, retry=0.05)
    try:
        deadline = time.monotonic() + 3
        while not subs and time.monotonic() < deadline:
            time.sleep(0.01)
        send, frames = subs[0]
        assert frames is True
        send("onStudioChanged", [{"enabled": True}])
        assert seen.wait(3)
        assert got == [("onStudioChanged", [{"enabled": True}])]
    finally:
        sub.close()
        srv.close()
    deadline = time.monotonic() + 3
    while subs and time.monotonic() < deadline:
        time.sleep(0.01)
    assert subs == []


def test_slow_subscriber_keeps_only_the_newest_event_per_name(sock_path):
    q = ipc.EventQueue()
    for i in range(100):
        q.put("onStudioFrame", [i])
    q.put("onStudioChanged", [1])
    assert q.take(0) == [("onStudioFrame", [99]), ("onStudioChanged", [1])]


def test_stale_socket_file_is_replaced(sock_path):
    open(sock_path, "w").close()
    srv, _ = start(sock_path)
    try:
        assert ipc.Client(sock_path).request("ping")["ok"]
    finally:
        srv.close()


def test_reply_that_cannot_be_encoded_becomes_an_error(sock_path):
    srv, _ = start(sock_path, lambda cmd, args: {"ok": True, "data": float("nan")})
    try:
        c = ipc.Client(sock_path)
        r = c.request("x")
        assert r["ok"] is False
        assert c.request("x")["ok"] is False     # the connection is still usable
    finally:
        srv.close()
