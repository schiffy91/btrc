"""A TLS 1.3 peer can request a client certificate. BTRC has none and authenticates its empty response."""

import hashlib
import hmac
import os
import shutil
import socket
import ssl
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from src.tests.python.test_linux_tls_http import compile_client
from src.tests.python.test_linux_tls_http import local_server as local_server
from src.tests.python.test_network_runtime import _transpile
from tools.native_plan import NativePlanBuilder

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="candidate Linux TLS provider")


def verify_finished(trace, keylog):
    secret = bytes.fromhex(
        next(
            line.split()[2]
            for line in keylog.read_text().splitlines()
            if line.startswith("CLIENT_HANDSHAKE_TRAFFIC_SECRET ")
        )
    )
    digest = {32: hashlib.sha256, 48: hashlib.sha384}[len(secret)]
    # Derive-Secret with the independent TLS engine's logged handshake traffic
    # secret; the client Finished proves its transcript includes empty Certificate.
    info = len(secret).to_bytes(2, "big") + b"\x0etls13 finished\x00"
    finished_key = hmac.digest(secret, info + b"\x01", digest)
    prior = bytearray()
    for direction, msg_type, message in trace:
        if direction == "read" and msg_type == 20:
            assert message[4:] == hmac.digest(finished_key, digest(prior).digest(), digest)
            return
        prior.extend(message)
    pytest.fail("OpenSSL never received a client Finished")


def exercise_request(binary, root, tmp_path, required):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_3
    context.set_alpn_protocols(["http/1.1"])
    context.load_cert_chain(root / "server.pem", root / "server.key")
    context.load_verify_locations(cafile=root / "root.pem")
    context.verify_mode = ssl.CERT_REQUIRED if required else ssl.CERT_OPTIONAL
    keylog = tmp_path / f"{required}.keys"
    context.keylog_filename = str(keylog)
    trace = []

    def message_callback(conn, direction, version, content_type, msg_type, data):
        if int(content_type) == 22:
            trace.append((direction, int(msg_type), bytes(data)))

    context._msg_callback = message_callback
    observed, unexpected = [], []
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(6)

        def serve():
            try:
                with listener.accept()[0] as conn:
                    conn.settimeout(5)
                    try:
                        tls = context.wrap_socket(conn, server_side=True)
                    except ssl.SSLError as err:
                        observed.append(err.reason)
                        return
                    with tls:
                        request = bytearray()
                        while b"\r\n\r\n" not in request:
                            chunk = tls.recv(4096)
                            if not chunk:
                                break
                            request.extend(chunk)
                        assert bytes(request).startswith(b"POST /ok HTTP/1.1\r\n")
                        observed.append("request")
                        tls.sendall(
                            b"HTTP/1.1 201 Created\r\nContent-Length: 13\r\nConnection: close\r\n\r\ntrust:payload"
                        )
            except Exception as exc:
                unexpected.append(exc)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        mode = "required" if required else "ok"
        result = subprocess.run(
            [binary, f"https://localhost:{listener.getsockname()[1]}/{mode}", mode],
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
        thread.join(timeout=6)
    assert not thread.is_alive() and not unexpected, unexpected
    assert result.returncode == 0 and not result.stderr, (result.stdout, result.stderr)
    assert sum(kind == 13 and direction == "write" for direction, kind, _ in trace) == 1
    certs = [data for direction, kind, data in trace if direction == "read" and kind == 11]
    assert certs == [bytes.fromhex("0b00000400000000")]
    assert not any(direction == "read" and kind == 15 for direction, kind, _ in trace)
    if required:
        assert observed == ["PEER_DID_NOT_RETURN_A_CERTIFICATE"] and result.stdout.strip()
    else:
        assert observed == ["request"] and result.stdout == ""
        verify_finished(trace, keylog)


def test_client_certificate_request(tmp_path, request, compiler, local_server):
    if not shutil.which("bwrap"):
        pytest.skip("requires private mounts for candidate provider qualification")
    frontend = (
        [sys.executable, "-m", "src.compiler.python.main"]
        if compiler == "python"
        else [str(request.getfixturevalue("immutable_btrcc"))]
    )
    binary = compile_client(tmp_path, frontend)
    root, _, _ = local_server
    for required in [False, True]:
        exercise_request(binary, root, tmp_path, required)


def test_certificate_request_encoding(tmp_path, request, compiler):
    for path in [
        ROOT / "src/stdlib/TLS/TLS13CertificateRequest.btrc",
        ROOT / "src/tests/native/tls/CertificateRequest.btrc",
    ]:
        shutil.copy(path, tmp_path)
    generated = tmp_path / "Program.c"
    plan = _transpile(compiler, tmp_path / "CertificateRequest.btrc", generated, request)
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

    def body(*extensions):
        return b"\0" + vector(b"".join(extensions))

    sig = ext(13, vector(b"\x08\x04"))
    author = ext(47, vector(vector(b"dn")))
    filt = ext(48, vector(b"\x03\x06\x01\x2a" + vector(b"")))
    extra = ext(0x1A1A, b"opaque")
    good = [
        body(sig),
        body(sig, author, filt, extra, ext(5, b""), ext(46, b"unknown")),
        body(ext(50, vector(b"\x04\x03")), sig),
        body(sig, ext(48, vector(b""))),
    ]
    bad = [
        b"",
        b"\1" + body(sig),
        body(),
        body(extra),
        body(sig, sig),
        body(sig, extra, extra),
        body(ext(13, b"\0\0")),
        body(ext(13, b"\0\1\0")),
        body(sig, ext(47, b"\0\0")),
        body(sig, ext(47, vector(b"\0\x02a"))),
        body(sig, ext(48, vector(b"\x01x\0"))),
        body(sig, ext(51, b"")),
        body(sig, ext(5, b"invalid")),
        body(sig, ext(17, b"")),
        body(sig) + b"z",
    ]
    bad.extend(good[1][:i] for i in range(len(good[1])))
    run = subprocess.run(
        [exe, *[value.hex() for value in good + bad]], capture_output=True, text=True, timeout=8, check=True
    )
    assert not run.stderr and run.stdout.splitlines() == ["valid"] * len(good) + ["invalid"] * len(bad)
