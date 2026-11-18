# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""The Windows IPC endpoint (ipc.PipeEndpoint): multiprocessing.connection Listener/Client with an authkey kept in
a user-only file, carrying the same JSON-lines protocol as the Mac's UNIX socket. On Windows its address is a named
pipe (AF_PIPE); here the same code path runs over an AF_UNIX address in a short temporary folder. Also: the endpoint
the app and the service pick per platform."""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from multiprocessing.connection import Client as MpClient

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ipc  # noqa: E402


@pytest.fixture
def folder():
    d = tempfile.mkdtemp(prefix="hp", dir="/tmp")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def endpoint(folder, key="service.key"):
    return ipc.PipeEndpoint(os.path.join(folder, "p.sock"), os.path.join(folder, key), family="AF_UNIX")


def start(ep, handle=None, **kw):
    subs = []

    def subscribe(send, frames):
        subs.append((send, frames))
        return lambda: subs.remove((send, frames)) if (send, frames) in subs else None
    srv = ipc.Server(ep, handle or (lambda cmd, args: {"ok": True, "data": [cmd, args]}), subscribe, **kw)
    srv.start()
    return srv, subs


def test_round_trip_over_the_pipe_endpoint(folder):
    ep = endpoint(folder)
    srv, _ = start(ep)
    try:
        c = ipc.Client(ep)
        assert c.request("set_fps", {"fps": 30}) == {"ok": True, "data": ["set_fps", {"fps": 30}]}
        assert c.request("ping") == {"ok": True, "data": ["ping", {}]}
        c.close()
    finally:
        srv.close()


def test_the_authkey_file_is_private_and_new_at_every_start(folder):
    ep = endpoint(folder)
    srv, _ = start(ep)
    key_path = os.path.join(folder, "service.key")
    first = open(key_path, "rb").read()
    assert len(first) >= 32 and os.stat(key_path).st_mode & 0o777 == 0o600
    srv.close()
    srv, _ = start(endpoint(folder))
    try:
        assert open(key_path, "rb").read() != first
        assert ipc.Client(ep).request("ping")["ok"] is True   # the client reads the key again
    finally:
        srv.close()


def test_a_client_with_the_wrong_key_is_refused_and_others_still_served(folder):
    ep = endpoint(folder)
    srv, _ = start(ep)
    try:
        with open(os.path.join(folder, "wrong.key"), "wb") as f:
            f.write(b"x" * 32)
        bad = ipc.PipeEndpoint(ep.address, os.path.join(folder, "wrong.key"), family="AF_UNIX")
        with pytest.raises(ipc.ServiceUnavailable):
            ipc.Client(bad).request("ping")
        from multiprocessing import AuthenticationError
        with pytest.raises((AuthenticationError, EOFError, OSError)):   # a raw client without the key: no reply
            conn = MpClient(ep.address, family="AF_UNIX", authkey=b"y" * 32)
            conn.send_bytes(b'{"id": 1, "cmd": "ping"}\n')
            conn.recv_bytes()
        assert ipc.Client(ep).request("ping")["ok"] is True
    finally:
        srv.close()


def test_a_missing_key_file_means_the_service_is_not_running(folder):
    with pytest.raises(ipc.ServiceUnavailable):
        ipc.Client(endpoint(folder)).request("ping")


def test_no_listener_means_the_service_is_not_running(folder):
    with open(os.path.join(folder, "service.key"), "wb") as f:
        f.write(os.urandom(32))
    with pytest.raises(ipc.ServiceUnavailable):
        ipc.Client(endpoint(folder)).request("ping")


def test_malformed_and_oversized_messages(folder):
    ep = endpoint(folder)
    srv, _ = start(ep, max_line=1024)
    key = open(ep.key_path, "rb").read()
    try:
        conn = MpClient(ep.address, family="AF_UNIX", authkey=key)
        conn.send_bytes(b"garbage\n")
        assert json.loads(conn.recv_bytes())["ok"] is False
        conn.send_bytes(b'{"id": 2, "cmd": "ping"}\n')
        assert json.loads(conn.recv_bytes()) == {"id": 2, "ok": True, "data": ["ping", {}]}
        conn.send_bytes(b'{"id": 3, "cmd": "' + b"a" * 4096 + b'"}\n')
        assert "too large" in json.loads(conn.recv_bytes())["error"]
        with pytest.raises((EOFError, OSError)):
            conn.recv_bytes()   # closed
        conn.close()
    finally:
        srv.close()


def test_handler_errors_become_error_replies(folder):
    def handle(cmd, args):
        raise RuntimeError("boom")
    ep = endpoint(folder)
    srv, _ = start(ep, handle)
    try:
        r = ipc.Client(ep).request("x")
        assert r["ok"] is False and "boom" in r["error"]
    finally:
        srv.close()


def test_concurrent_clients(folder):
    def handle(cmd, args):
        time.sleep(0.01)
        return {"ok": True, "data": args["n"]}
    ep = endpoint(folder)
    srv, _ = start(ep, handle)
    out, errors = {}, []

    def worker(i):
        try:
            c = ipc.Client(ep)
            out[i] = [c.request("echo", {"n": i * 100 + j})["data"] for j in range(5)]
            c.close()
        except Exception as e:   # pragma: no cover - reported below
            errors.append(e)
    try:
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
        [t.start() for t in threads]
        [t.join(10) for t in threads]
        assert not errors and out == {i: [i * 100 + j for j in range(5)] for i in range(6)}
    finally:
        srv.close()


def test_client_reconnects_after_a_service_restart(folder):
    ep = endpoint(folder)
    srv, _ = start(ep)
    c = ipc.Client(ep)
    assert c.request("ping")["ok"] and c.request("ping")["ok"]
    srv.close()
    srv, _ = start(endpoint(folder))
    try:
        assert c.request("ping")["ok"] is True
    finally:
        srv.close()
        c.close()


def test_subscription_carries_events_and_unsubscribes_on_hangup(folder):
    ep = endpoint(folder)
    srv, subs = start(ep)
    got, ready = [], threading.Event()

    def on_event(name, args):
        got.append((name, args))
        ready.set()
    sub = ipc.Subscription(ep, on_event, frames=True, retry=0.05)
    try:
        deadline = time.monotonic() + 5
        while not subs and time.monotonic() < deadline:
            time.sleep(0.01)
        assert subs and subs[0][1] is True
        subs[0][0]("onStudioFrame", [[1, 2, 3]])
        assert ready.wait(5) and got == [("onStudioFrame", [[1, 2, 3]])]
    finally:
        sub.close()
    deadline = time.monotonic() + 5
    while subs and time.monotonic() < deadline:
        time.sleep(0.02)
    assert subs == []
    srv.close()


# ---------- the endpoint per platform ----------

def test_the_mac_endpoint_is_the_unix_socket(tmp_path):
    ep = ipc.service_endpoint(str(tmp_path))
    assert isinstance(ep, ipc.UnixEndpoint) and ep.path == os.path.join(str(tmp_path), "service.sock")


def test_the_windows_endpoint_is_a_named_pipe_per_user(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("USERNAME", "Some User\\x")
    ep = ipc.service_endpoint(str(tmp_path))
    assert isinstance(ep, ipc.PipeEndpoint) and ep.family == "AF_PIPE"
    assert ep.address.startswith("\\\\.\\pipe\\huntsman-for-mac-") and "\\x" not in ep.address[9:]
    assert ep.key_path == os.path.join(str(tmp_path), "service.key")


def test_app_and_service_use_the_platform_endpoint(tmp_path, monkeypatch):
    import app as appmod
    import huntsman_core as hc
    import service
    monkeypatch.setattr(hc, "data_dir", lambda: str(tmp_path))
    assert appmod.service_endpoint().path == appmod.service_socket() == service.socket_path()
    monkeypatch.setattr(sys, "platform", "win32")
    assert isinstance(appmod.service_endpoint(), ipc.PipeEndpoint)
    assert isinstance(service.service_endpoint(), ipc.PipeEndpoint)


def test_a_client_that_stalls_in_the_handshake_loses_its_slot(folder, monkeypatch):
    import socket
    monkeypatch.setattr(ipc, "TIMEOUT", 0.3)
    ep = endpoint(folder)
    srv, _ = start(ep, max_clients=1)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(ep.address)    # takes the only slot and never answers the challenge
        time.sleep(0.05)
        deadline = time.monotonic() + 5
        while True:
            try:
                assert ipc.Client(ep, timeout=1).request("ping")["ok"] is True
                break
            except ipc.ServiceUnavailable:
                assert time.monotonic() < deadline, "the stalled client kept its slot"
                time.sleep(0.1)
    finally:
        s.close()
        srv.close()


def test_connecting_to_a_listener_that_never_answers_times_out(folder):
    from multiprocessing.connection import Listener
    addr = os.path.join(folder, "q.sock")
    with open(os.path.join(folder, "service.key"), "wb") as f:
        f.write(os.urandom(32))
    lst = Listener(addr, family="AF_UNIX")   # accepts, then sends no challenge
    held = []
    threading.Thread(target=lambda: held.append(lst.accept()), daemon=True).start()
    try:
        t0 = time.monotonic()
        with pytest.raises(ipc.ServiceUnavailable):
            ipc.Client(ipc.PipeEndpoint(addr, os.path.join(folder, "service.key"), family="AF_UNIX"),
                       timeout=0.3).request("ping")
        assert time.monotonic() - t0 < 3
    finally:
        lst.close()


def test_pipe_names_differ_per_domain(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("USERNAME", "bob")
    monkeypatch.setenv("USERDOMAIN", "WORK")
    a = ipc.service_endpoint(str(tmp_path)).address
    monkeypatch.setenv("USERDOMAIN", "HOMEPC")
    assert a != ipc.service_endpoint(str(tmp_path)).address
