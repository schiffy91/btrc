"""Exercise the Linux HTTP client across OpenSSL TLS 1.3 traffic-key changes."""

import _ssl
import ctypes as C
import os
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from src.tests.python.test_linux_tls_http import compile_client
from src.tests.python.test_linux_tls_http import local_server as local_server
from src.tests.python.test_network_runtime import _transpile
from tools.native_plan import NativePlanBuilder

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux TLS provider")


class OpenSSLPeer:
    """Use the test interpreter's OpenSSL; Python's ssl module doesn't expose SSL_key_update."""

    def __init__(self, root, num_tickets=2):
        lib = C.CDLL(_ssl.__file__)
        self.lib = lib
        ptr, integer = C.c_void_p, C.c_int
        callback = C.CFUNCTYPE(None, integer, integer, integer, ptr, C.c_size_t, ptr, ptr)
        for name, result, args in [
            ("TLS_server_method", ptr, []),
            ("SSL_CTX_new", ptr, [ptr]),
            ("SSL_CTX_use_certificate_chain_file", integer, [ptr, C.c_char_p]),
            ("SSL_CTX_use_PrivateKey_file", integer, [ptr, C.c_char_p, integer]),
            ("SSL_CTX_set_num_tickets", integer, [ptr, C.c_size_t]),
            ("SSL_CTX_set_msg_callback", None, [ptr, callback]),
            ("SSL_new", ptr, [ptr]),
            ("SSL_set_fd", integer, [ptr, integer]),
            ("SSL_accept", integer, [ptr]),
            ("SSL_version", integer, [ptr]),
            ("SSL_read", integer, [ptr, ptr, integer]),
            ("SSL_write", integer, [ptr, ptr, integer]),
            ("SSL_key_update", integer, [ptr, integer]),
            ("SSL_do_handshake", integer, [ptr]),
            ("SSL_shutdown", integer, [ptr]),
            ("SSL_free", None, [ptr]),
            ("SSL_CTX_free", None, [ptr]),
        ]:
            func = getattr(lib, name)
            func.restype = result
            func.argtypes = args
        self.messages = []

        @callback
        def observe(writing, version, kind, data, size, connection, argument):
            if kind in (21, 22):
                self.messages.append((writing, kind, C.string_at(data, size)))

        self.observe = observe
        self.ctx = lib.SSL_CTX_new(lib.TLS_server_method())
        assert self.ctx
        assert lib.SSL_CTX_use_certificate_chain_file(self.ctx, os.fsencode(root / "server.pem")) == 1
        assert lib.SSL_CTX_use_PrivateKey_file(self.ctx, os.fsencode(root / "server.key"), 1) == 1
        assert lib.SSL_CTX_set_num_tickets(self.ctx, num_tickets) == 1
        lib.SSL_CTX_set_msg_callback(self.ctx, observe)

    def serve(self, sock, mode):
        lib = self.lib
        tls = lib.SSL_new(self.ctx)
        assert tls
        try:
            for option in (socket.SO_RCVTIMEO, socket.SO_SNDTIMEO):
                sock.setsockopt(socket.SOL_SOCKET, option, struct.pack("ll", 4, 0))
            assert lib.SSL_set_fd(tls, sock.fileno()) == 1
            assert lib.SSL_accept(tls) == 1 and lib.SSL_version(tls) == 0x0304
            request = bytearray()
            buf = C.create_string_buffer(4096)
            while not request.endswith(b"\r\n\r\npayload"):
                length = lib.SSL_read(tls, buf, len(buf))
                assert length > 0
                request.extend(buf.raw[:length])
            assert request.startswith(f"POST /{mode} HTTP/1.1\r\n".encode())

            def update(requested):
                assert lib.SSL_key_update(tls, requested) == 1
                assert lib.SSL_do_handshake(tls) == 1

            def write(data):
                assert lib.SSL_write(tls, data, len(data)) == len(data)

            if mode == "ticket-flood":
                # Client must abort with fatal unexpected_message after > 32 NewSessionTickets.
                lib.SSL_read(tls, buf, len(buf))
                return
            if mode == "key-update-flood":
                # Client must abort with fatal unexpected_message after > 8 consecutive KeyUpdates.
                for _ in range(9):
                    if lib.SSL_key_update(tls, 0) != 1 or lib.SSL_do_handshake(tls) != 1:
                        break
                lib.SSL_read(tls, buf, len(buf))
                return
            if mode == "slow":
                # Regular authenticated control traffic must not reset the HTTP deadline.
                for _ in range(5):
                    update(0)
                    time.sleep(0.32)
                time.sleep(0.75)
                return
            write(b"HTTP/1.1 201 Created\r\nConnection: close\r\n\r\n")
            if mode != "auto":
                update(0)
            write(b"trust:")
            if mode != "auto":
                update(1)
            write(b"payload")
            if mode in ("ok", "auto"):
                assert lib.SSL_shutdown(tls) == 0
                assert lib.SSL_shutdown(tls) == 1
            # For truncated, close the underlying socket without close_notify.
        finally:
            lib.SSL_free(tls)

    def close(self):
        self.lib.SSL_CTX_free(self.ctx)


def exercise_updates(binary, root, mode):
    peer = OpenSSLPeer(root, num_tickets=33 if mode == "ticket-flood" else 2)
    failures = []
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(5)

        def serve():
            try:
                with listener.accept()[0] as conn:
                    peer.serve(conn, mode)
            except Exception as exc:
                failures.append(exc)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        start = time.monotonic()
        result = subprocess.run(
            [binary, f"https://localhost:{listener.getsockname()[1]}/{mode}", "ok" if mode == "auto" else mode],
            env=os.environ
            | {
                "CURL_CA_BUNDLE": str(root / "root.pem"),
                "SSL_CERT_FILE": "",
                "SSL_CERT_DIR": "",
                "PATH": "/no-curl",
                "NO_PROXY": "*",
            },
            capture_output=True,
            timeout=8,
            text=True,
        )
        elapsed = time.monotonic() - start
        thread.join(6)
    assert not thread.is_alive()
    peer.close()
    trace = peer.messages
    assert not failures, (failures, [(d, k, data[:5]) for d, k, data in trace], result)
    expected = {
        "ok": "",
        "auto": "",
        "truncated": "connection failed",
        "slow": "request timed out",
        "ticket-flood": "connection failed",
        "key-update-flood": "connection failed",
    }[mode]
    assert (result.returncode, result.stdout.strip(), result.stderr) == (0, expected, "")
    if mode in ("ticket-flood", "key-update-flood"):
        assert (0, 21, bytes([2, 10])) in trace
        return
    assert sum(d == 1 and k == 22 and data[0] == 4 for d, k, data in trace) == 2
    sent = [data for d, k, data in trace if d == 1 and k == 22 and data[0] == 24]
    requests = {"slow": [0] * 5, "auto": [], "ok": [0, 1], "truncated": [0, 1]}
    assert sent == [b"\x18\0\0\1" + bytes([flag]) for flag in requests[mode]]
    if mode in ("ok", "auto"):
        # OpenSSL decrypted the client's KeyUpdate and its close_notify under the new key.
        assert [data for d, k, data in trace if d == 0 and k == 22 and data[0] == 24] == [b"\x18\0\0\1\0"]
        assert (0, 21, b"\1\0") in trace
    if mode == "slow":
        assert 1.5 <= elapsed < 3.5


def test_key_updates(tmp_path, request, compiler, local_server):
    frontend = (
        [sys.executable, "-m", "src.compiler.python.main"]
        if compiler == "python"
        else [str(request.getfixturevalue("immutable_btrcc"))]
    )
    binary = compile_client(tmp_path, frontend)
    for mode in ("ok", "truncated", "slow", "ticket-flood", "key-update-flood"):
        exercise_updates(binary, local_server[0], mode)


def test_automatic_key_update(tmp_path, request, compiler, local_server):
    if not shutil.which("bwrap"):
        pytest.skip("requires a private mount namespace for the candidate provider")
    frontend = (
        [sys.executable, "-m", "src.compiler.python.main"]
        if compiler == "python"
        else [str(request.getfixturevalue("immutable_btrcc"))]
    )

    def accelerate(stdlib):
        # Reserve the second application record for rekeying in this disposable
        # copy. Keep the production AEAD hard limit and all keys/nonces intact.
        path = stdlib / "TLS/TLS13Records.btrc"
        source = path.read_text()
        threshold = "self.sequence >= TLS13_RECORD_LIMIT - 1ULL"
        assert source.count(threshold) == 1
        path.write_text(source.replace(threshold, "self.sequence >= 1ULL"))

    binary = compile_client(tmp_path, frontend, accelerate)
    exercise_updates(binary, local_server[0], "auto")


def test_ticket_encoding(tmp_path, request, compiler):
    for path in [ROOT / "src/stdlib/TLS/TLS13SessionTicket.btrc", ROOT / "src/tests/native/tls/SessionTicket.btrc"]:
        shutil.copy(path, tmp_path)
    generated = tmp_path / "Program.c"
    plan = _transpile(compiler, tmp_path / "SessionTicket.btrc", generated, request)
    exe = tmp_path / "Program"
    flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
    NativePlanBuilder().build(
        plan_path=plan,
        generated_c=generated,
        output=exe,
        cc="clang",
        optimization=1,
        compile_flags=["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic-errors", *flags],
        link_flags=flags,
    )

    def vector(data):
        return len(data).to_bytes(2, "big") + data

    def ext(kind, data):
        return kind.to_bytes(2, "big") + vector(data)

    def ticket(raw=b"secret", nonce=b"", extensions=b""):
        body = bytes.fromhex("00093a8001020304") + bytes([len(nonce)]) + nonce + vector(raw) + vector(extensions)
        return b"\x04" + len(body).to_bytes(3, "big") + body

    early = ext(42, bytes(4))
    extra = ext(0x1A1A, b"opaque")
    good = [ticket(), ticket(nonce=b"a" * 255, extensions=early + extra), ticket(extensions=extra)]
    bad = [
        ticket(raw=b""),
        ticket(extensions=early + early),
        ticket(extensions=extra + extra),
        ticket(extensions=ext(42, b"")),
        ticket(extensions=ext(42, bytes(5))),
        ticket(extensions=ext(51, b"")),
        ticket(extensions=extra[:-1]),
        ticket(extensions=extra + b"x"),
        bytes([24]) + good[0][1:],
        good[0] + b"x",
        good[0][:12] + b"\xff" + good[0][13:],
    ]
    bad.extend(good[2][:i] for i in range(len(good[2])))
    run = subprocess.run(
        [exe, *[value.hex() for value in good + bad]], capture_output=True, text=True, timeout=12, check=True
    )
    assert not run.stderr and run.stdout.splitlines() == ["valid"] * len(good) + ["invalid"] * len(bad)
