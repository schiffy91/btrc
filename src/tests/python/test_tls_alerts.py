"""Observe public HTTPClient closure and TLS alerts at an independent OpenSSL peer."""

import os
import socket
import ssl
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from src.tests.native_build import NativeCorpusBuild
from src.tests.python.test_linux_tls_http import client as client
from src.tests.python.test_linux_tls_http import compiled_clients as compiled_clients
from src.tests.python.test_linux_tls_http import local_server as local_server
from src.tests.python.test_network_runtime import _transpile

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux TLS provider")


class Peer:
    def __init__(self, root, version, mode):
        self.damage_handshake = mode == "bad-handshake"
        self.changed_cipher = False
        self.fragment = mode if mode in ("fragmented-warning", "interleaved-alert") else None
        self.version = version
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ctx.maximum_version = version
        ctx.load_cert_chain(root / "server.pem", root / "server.key")
        ctx.set_ciphers("ECDHE-ECDSA-AES128-GCM-SHA256")
        self.alerts = []
        self.incoming = ssl.MemoryBIO()
        self.outgoing = ssl.MemoryBIO()
        self.received = bytearray()

        def record(conn, direction, tls_version, kind, message, data):
            if int(kind) == 21:
                self.alerts.append((direction, bytes(data)))

        ctx._msg_callback = record
        self.tls = ctx.wrap_bio(self.incoming, self.outgoing, server_side=True)

    def flush(self, conn):
        while self.outgoing.pending:
            wire = bytearray(self.outgoing.read())
            offset = 0
            while self.damage_handshake and offset < len(wire):
                end = offset + 5 + int.from_bytes(wire[offset + 3 : offset + 5], "big")
                assert end <= len(wire)
                kind = wire[offset]
                # Send a bad-tag conformance record in the server's first
                # protected handshake epoch. Both OpenSSL read keys remain valid.
                if (self.version == ssl.TLSVersion.TLSv1_3 and kind == 23) or (
                    self.version == ssl.TLSVersion.TLSv1_2 and self.changed_cipher and kind == 22
                ):
                    wire[end - 1] ^= 1
                    self.damage_handshake = False
                self.changed_cipher |= kind == 20
                offset = end
            if self.fragment and wire[0] == 22 and wire[5] == 2:
                # Place a fragmented TLS 1.2 warning after the real ServerHello.
                # The interleaved case omits its final byte before Certificate.
                end = 5 + int.from_bytes(wire[3:5], "big")
                fragments = bytes.fromhex("150303000101")
                if self.fragment == "fragmented-warning":
                    fragments += bytes.fromhex("150303000164")
                wire[end:end] = fragments
                self.fragment = None
            conn.sendall(wire)

    def drive(self, conn, operation):
        while True:
            try:
                return operation()
            except ssl.SSLWantReadError:
                self.flush(conn)
                wire = conn.recv(65536)
                assert wire, "unexpected transport EOF before the TLS exchange completed"
                self.received.extend(wire)
                self.incoming.write(wire)
            finally:
                self.flush(conn)

    def serve(self, conn, mode):
        conn.settimeout(4)
        if mode == "bad-handshake":
            with pytest.raises(ssl.SSLError):
                self.drive(conn, self.tls.do_handshake)
                self.drive(conn, self.tls.read)
            return
        if mode in ("name", "untrusted", "interleaved-alert"):
            with pytest.raises(ssl.SSLError):
                self.drive(conn, self.tls.do_handshake)
            return
        self.drive(conn, self.tls.do_handshake)
        request = bytearray()
        while not request.endswith(b"\r\n\r\npayload"):
            part = self.drive(conn, self.tls.read)
            assert part
            request.extend(part)
        assert request.startswith(f"POST /{mode} HTTP/1.1\r\n".encode())
        headers = b"HTTP/1.1 201 Created\r\nConnection: close\r\n"
        if mode in ("client-close", "fragmented-warning"):
            headers += b"Content-Length: 13\r\n"
        self.drive(conn, lambda: self.tls.write(headers + b"\r\ntrust:payload"))
        if mode == "peer-close":
            self.drive(conn, self.tls.unwrap)
        elif mode in ("client-close", "fragmented-warning"):
            assert self.drive(conn, self.tls.read) == b""
        elif mode == "fatal":
            # OpenSSL itself generates and protects a fatal alert. Supply a
            # bad-tag test record to its in-memory input, then forward only
            # its genuine outgoing records to the HTTP client.
            self.incoming.write(bytes.fromhex("170303001e") + bytes(30))
            with pytest.raises(ssl.SSLError):
                self.tls.read()
            self.flush(conn)
            assert conn.recv(1024) == b""
        # In the truncated case, return without a TLS close_notify.


def exercise_alert(binary, root, version, mode):
    peer = Peer(root, version, mode)
    errors = []
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(5)

        def serve():
            try:
                with listener.accept()[0] as conn:
                    peer.serve(conn, mode)
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        host = "127.0.0.1" if mode == "name" else "localhost"
        expected_ok = mode in ("peer-close", "client-close", "fragmented-warning")
        result = subprocess.run(
            [binary, f"https://{host}:{listener.getsockname()[1]}/{mode}", "ok" if expected_ok else mode],
            env=os.environ
            | {
                "CURL_CA_BUNDLE": str(root / ("other.pem" if mode == "untrusted" else "root.pem")),
                "SSL_CERT_FILE": "",
                "SSL_CERT_DIR": "",
                "PATH": "/no-curl",
                "NO_PROXY": "*",
            },
            capture_output=True,
            text=True,
            timeout=8,
        )
        thread.join(6)
    assert not thread.is_alive() and not errors, (errors, peer.alerts, result)
    alerts = peer.alerts
    expected = ""
    if mode == "peer-close":
        assert alerts == [("write", b"\1\0"), ("read", b"\1\0")]
    elif mode in ("client-close", "fragmented-warning"):
        assert alerts == [("read", b"\1\0")]
    elif mode in ("name", "untrusted", "bad-handshake", "interleaved-alert"):
        descriptions = {"name": 42, "untrusted": 48, "bad-handshake": 20, "interleaved-alert": 10}
        assert alerts == [("read", bytes([2, descriptions[mode]]))]
        types = []
        start = 0
        while start < len(peer.received):
            types.append((peer.received[start], int.from_bytes(peer.received[start + 3 : start + 5], "big")))
            start += 5 + int.from_bytes(peer.received[start + 3 : start + 5], "big")
        assert start == len(peer.received)
        # TLS 1.2 hasn't sent ChangeCipherSpec yet; TLS 1.3 has handshake keys.
        assert types[-1][0] == (21 if version == ssl.TLSVersion.TLSv1_2 else 23)
        if version == ssl.TLSVersion.TLSv1_2:
            assert (types[-1][1] > 2) == (mode == "bad-handshake")
        expected = "TLS handshake failed"
    elif mode == "fatal":
        assert alerts == [("write", bytes([2, 20]))]
        expected = "connection failed"
    else:
        assert mode == "truncated" and not alerts
        expected = "connection failed"
    assert (result.returncode, result.stdout.strip(), result.stderr) == (0, expected, "")


def test_http_tls_alerts(client, request, local_server, tmp_path, compiler):
    version = request.node.callspec.params["local_server"]
    for mode in ("peer-close", "client-close", "fatal", "truncated", "name", "untrusted", "bad-handshake"):
        exercise_alert(client, local_server[0], version, mode)
    if version == ssl.TLSVersion.TLSv1_2:
        for mode in ("fragmented-warning", "interleaved-alert"):
            exercise_alert(client, local_server[0], version, mode)
    else:
        exercise_choose_protocol_flood(client, local_server[0])
        exercise_empty_app_data_flood(client, local_server[0], tmp_path, request, compiler)


def exercise_choose_protocol_flood(binary, root):
    # H3: > 16 fragmented 1-byte records before ServerHello suite must abort with decode_error (50).
    received = bytearray()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(5)

        def serve():
            with listener.accept()[0] as conn:
                conn.settimeout(4)
                # Read ClientHello header + body
                head = conn.recv(5)
                if len(head) == 5:
                    need = int.from_bytes(head[3:5], "big")
                    got = 0
                    while got < need:
                        chunk = conn.recv(need - got)
                        if not chunk:
                            break
                        got += len(chunk)
                # Drip 17 1-byte ServerHello header fragments.
                fake_hello = b"\x02\x00\x00\x46" + b"\x03\x03" + bytes(40)
                for i in range(17):
                    try:
                        conn.sendall(b"\x16\x03\x03\x00\x01" + fake_hello[i : i + 1])
                    except OSError:
                        break
                try:
                    while True:
                        chunk = conn.recv(1024)
                        if not chunk:
                            break
                        received.extend(chunk)
                except OSError:
                    pass

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        result = subprocess.run(
            [binary, f"https://localhost:{listener.getsockname()[1]}/flood", "flood"],
            env=os.environ
            | {
                "CURL_CA_BUNDLE": str(root / "root.pem"),
                "SSL_CERT_FILE": "",
                "SSL_CERT_DIR": "",
                "PATH": "/no-curl",
                "NO_PROXY": "*",
            },
            capture_output=True,
            text=True,
            timeout=8,
        )
        thread.join(6)
    assert not thread.is_alive()
    assert (result.returncode, result.stdout.strip(), result.stderr) == (0, "TLS handshake failed", "")
    assert received == bytes.fromhex("15030300020232")


def exercise_empty_app_data_flood(binary, root, tmp_path, request, compiler):
    # H3: > 32 consecutive empty TLS 1.3 application_data records must abort with unexpected_message (10).
    generated = tmp_path / "seal_empty.c"
    sealer = tmp_path / "seal_empty"
    plan = _transpile(compiler, ROOT / "src/tests/native/tls/SealEmpty.btrc", generated, request)
    NativeCorpusBuild(generated, plan).build(sealer)
    keylog = tmp_path / "empty-flood.keys"
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ctx.maximum_version = ssl.TLSVersion.TLSv1_3
    ctx.load_cert_chain(root / "server.pem", root / "server.key")
    ctx.keylog_filename = str(keylog)
    alerts = []

    def observe(conn, direction, tls_version, kind, msg, data):
        if direction == "read" and int(kind) == 21:
            alerts.append(bytes(data))

    ctx._msg_callback = observe
    errors = []
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(5)

        def serve():
            try:
                with listener.accept()[0] as raw:
                    raw.settimeout(4)
                    incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
                    tls = ctx.wrap_bio(incoming, outgoing, server_side=True)

                    def flush():
                        while outgoing.pending:
                            raw.sendall(outgoing.read())

                    def drive(fn):
                        while True:
                            try:
                                return fn()
                            except ssl.SSLWantReadError:
                                flush()
                                data = raw.recv(65536)
                                assert data
                                incoming.write(data)
                            finally:
                                flush()

                    drive(tls.do_handshake)
                    req = bytearray()
                    while not req.endswith(b"\r\n\r\npayload"):
                        part = drive(lambda: tls.read(4096))
                        assert part
                        req.extend(part)
                    secret_hex = next(
                        line.split()[2]
                        for line in keylog.read_text().splitlines()
                        if line.startswith("SERVER_TRAFFIC_SECRET_0 ")
                    )
                    suite_code = {
                        "TLS_AES_128_GCM_SHA256": "0x1301",
                        "TLS_AES_256_GCM_SHA384": "0x1302",
                        "TLS_CHACHA20_POLY1305_SHA256": "0x1303",
                    }[tls.cipher()[0]]
                    records = subprocess.check_output(
                        [sealer, suite_code, secret_hex, "33"], text=True, timeout=10
                    ).splitlines()
                    for rec in records:
                        try:
                            raw.sendall(bytes.fromhex(rec))
                        except OSError:
                            break
                    # Feed client's fatal alert back into OpenSSL so observe() verifies [2, 10].
                    with pytest.raises(ssl.SSLError):
                        drive(lambda: tls.read(1024))
            except BaseException as exc:
                errors.append(exc)

        ctx.num_tickets = 0
        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        result = subprocess.run(
            [binary, f"https://localhost:{listener.getsockname()[1]}/empty-flood", "empty-flood"],
            env=os.environ
            | {
                "CURL_CA_BUNDLE": str(root / "root.pem"),
                "SSL_CERT_FILE": "",
                "SSL_CERT_DIR": "",
                "PATH": "/no-curl",
                "NO_PROXY": "*",
            },
            capture_output=True,
            text=True,
            timeout=8,
        )
        thread.join(6)
    assert not thread.is_alive() and not errors, (errors, alerts, result)
    assert (result.returncode, result.stdout.strip(), result.stderr) == (0, "connection failed", "")
    assert alerts == [bytes([2, 10])]
