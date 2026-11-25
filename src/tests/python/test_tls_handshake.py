"""Exercise the TLS 1.3 negotiation and first encrypted record against an independent server."""

import hashlib
import select
import shutil
import socket
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import PackageTarget
from src.tests.dependencies import DependencyAudit
from src.tests.native_build import NativeCorpusBuild
from src.tests.python.test_network_runtime import _transpile

ROOT = Path(__file__).resolve().parents[3]
SUITES = ("TLS_AES_128_GCM_SHA256", "TLS_AES_256_GCM_SHA384", "TLS_CHACHA20_POLY1305_SHA256")
RETRY_RANDOM = bytes.fromhex("cf21ad74e59a6111be1d8c021e65b891c2a211167abb8c5e079e09e2c8a8339c")


def read_exact(stream, size):
    data = bytearray()
    while len(data) < size:
        part = stream.recv(size - len(data))
        if not part:
            raise EOFError(f"peer closed after {len(data)} of {size} bytes")
        data.extend(part)
    return bytes(data)


def read_record(stream):
    header = read_exact(stream, 5)
    size = int.from_bytes(header[3:], "big")
    assert 0 < size <= 16640
    return header + read_exact(stream, size)


@contextmanager
def openssl_server(directory, suite, retry, group="X25519"):
    command = [
        "openssl",
        "s_server",
        "-accept",
        "127.0.0.1:0",
        "-num_tickets",
        "0",
        "-tls1_3",
        "-groups",
        group,
        "-cert",
        "cert.pem",
        "-key",
        "key.pem",
        "-alpn",
        "http/1.1",
        "-ciphersuites",
        suite,
    ]
    if retry:
        command.append("-stateless")
    with subprocess.Popen(
        command, cwd=directory, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0
    ) as server:
        try:
            while select.select([server.stdout], [], [], 10)[0]:
                line = server.stdout.readline()
                assert line, server.stderr.read().decode()
                if line.startswith(b"ACCEPT 127.0.0.1:"):
                    port = int(line.split(b":")[-1])
                    break
            else:
                raise TimeoutError("OpenSSL did not announce its listener")
            with socket.create_connection(("127.0.0.1", port), timeout=10) as upstream:
                yield upstream, server.stdin
        finally:
            server.terminate()


@contextmanager
def client_connection(binary, pin, mutation):
    local, child = socket.socketpair()
    with (
        local,
        child,
        subprocess.Popen([binary, pin, mutation or ""], stdin=child, stdout=child, stderr=subprocess.PIPE) as client,
    ):
        child.close()
        local.settimeout(10)
        try:
            yield local, client
        finally:
            client.kill()


def hello_extensions(frame):
    # Skip the record header, handshake header, version, random and session id.
    end = len(frame)
    pos = 44 + frame[43]
    if frame[5] == 1:
        pos += 2 + int.from_bytes(frame[pos : pos + 2], "big")
        pos += 1 + frame[pos]
    else:
        assert frame[5] == 2
        pos += 3
    assert end == pos + 2 + int.from_bytes(frame[pos : pos + 2], "big")
    result = {}
    pos += 2
    while pos < end:
        kind = int.from_bytes(frame[pos : pos + 2], "big")
        size = int.from_bytes(frame[pos + 2 : pos + 4], "big")
        assert kind not in result and pos + 4 + size <= end
        result[kind] = slice(pos + 4, pos + 4 + size)
        pos += 4 + size
    return result


def check_client_hello(frame, group):
    ext = hello_extensions(frame)
    assert frame[ext[10]] == bytes.fromhex("0006001d00170018")
    for kind in [13, 50]:
        offered = frame[ext[kind]]
        assert int.from_bytes(offered[:2], "big") == len(offered) - 2
        words = {int.from_bytes(offered[i : i + 2], "big") for i in range(2, len(offered), 2)}
        assert {0x0809, 0x080A, 0x080B} <= words
    length = {29: 32, 23: 65, 24: 97}[group]
    share = frame[ext[51]]
    assert share[:6] == (4 + length).to_bytes(2, "big") + group.to_bytes(2, "big") + length.to_bytes(2, "big")
    assert len(share) == 6 + length
    if group != 29:
        assert share[6] == 4
    return {kind: frame[position] for kind, position in ext.items()}


def server_flight(binary, directory, suite, pin, *, retry=False, mutation=None, group="X25519"):
    with (
        openssl_server(directory, suite, retry, group) as (upstream, server_input),
        client_connection(binary, "0" * 64 if mutation == "pin" else pin, mutation) as (local, client),
    ):
        first = read_record(local)
        original = check_client_hello(first, 29)
        upstream.sendall(first)
        hello = read_record(upstream)
        assert hello[0] == 22 and hello[5] == 2
        assert (hello[11:43] == RETRY_RANDOM) == (retry or group != "X25519")
        if retry or group != "X25519":
            retry_extensions = hello_extensions(hello)
            local.sendall(hello)
            second = read_record(local)
            chosen = {"X25519": 29, "P-256": 23, "P-384": 24}[group]
            next_offer = check_client_hello(second, chosen)
            assert first[9:76] == second[9:76]  # version, random and session id
            for kind, data in original.items():
                if kind != 51:
                    assert next_offer[kind] == data
            if group == "X25519":
                assert next_offer[51] == original[51]
            else:
                assert hello[retry_extensions[51]] == chosen.to_bytes(2, "big")
            if 44 in retry_extensions:
                assert next_offer[44] == hello[retry_extensions[44]]
            upstream.sendall(second)
            hello = read_record(upstream)
            if hello == bytes.fromhex("140303000101"):
                local.sendall(hello)
                hello = read_record(upstream)
        if mutation == "session":
            hello = hello[:44] + bytes([hello[44] ^ 1]) + hello[45:]
        elif mutation == "suite":
            hello = hello[:76] + b"\x13\xff" + hello[78:]
        elif mutation == "version":
            hello = hello[:9] + b"\x03\x01" + hello[11:]
        local.sendall(hello)
        sent = 0
        if mutation not in {"session", "suite", "version"}:
            while True:
                ready, _, _ = select.select([local, upstream], [], [], 10)
                assert ready, "TLS peers stalled"
                if local in ready:
                    if local.recv(1, socket.MSG_PEEK) != bytes([23]):
                        break
                    upstream.sendall(read_record(local))
                    sent += 1
                    if sent == 2:
                        server_input.write(b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\nok")
                        server_input.flush()
                elif upstream in ready:
                    frame = read_record(upstream)
                    if mutation == "tag" and frame[0] == 23:
                        frame = frame[:-1] + bytes([frame[-1] ^ 1])
                        local.sendall(frame)
                        break
                    local.sendall(frame)
                    if sent == 2 or (mutation in {"pin", "signature", "finished"} and client.poll() is not None):
                        break
        code = client.wait(timeout=10)
        try:
            message = local.recv(4096)
        except ConnectionResetError:
            message = b""
        error = client.stderr.read()
        if mutation:
            assert code != 0 and not message and sent == 0
            diagnoses = {
                "tag": b"authenticate server record",
                "pin": b"untrusted test certificate",
                "signature": b"invalid CertificateVerify",
                "finished": b"invalid Finished",
            }
            assert diagnoses.get(mutation, b"invalid ServerHello") in error
        else:
            assert (sent, code, message.strip(), error) == (2, 0, b"PASS TLS HTTP exchange", b"")


def malformed_retry(binary, directory, pin, mutation):
    with (
        openssl_server(directory, SUITES[0], False, "P-256") as (upstream, _),
        client_connection(binary, pin, None) as (local, client),
    ):
        upstream.sendall(read_record(local))
        retry = bytearray(read_record(upstream))
        assert retry[11:43] == RETRY_RANDOM
        slot = hello_extensions(retry)[51]
        if mutation in {"already shared", "unsupported"}:
            retry[slot] = (29 if mutation == "already shared" else 25).to_bytes(2, "big")
            local.sendall(retry)
        else:
            local.sendall(retry)
            upstream.sendall(read_record(local))
            if mutation == "second retry":
                local.sendall(retry)
            else:
                reply = bytearray(read_record(upstream))
                if reply[0] == 20:
                    reply = bytearray(read_record(upstream))
                pos = hello_extensions(reply)[51].start
                if mutation == "changed group":
                    reply[pos : pos + 2] = bytes.fromhex("0018")
                elif mutation == "off curve":
                    reply[pos + 4 : pos + 69] = b"\x04" + bytes(64)
                local.sendall(reply)
        assert client.wait(timeout=10) != 0
        assert b"invalid ServerHello" in client.stderr.read()


def test_server_flight(tmp_path, request, compiler):
    if sys.platform != "linux" or not shutil.which("openssl"):
        pytest.skip("Linux TLS qualification requires an OpenSSL TLS 1.3 server")
    for filename in (
        "TLS13Hello.btrc",
        "TLS13HandshakeKeys.btrc",
        "TLS13PeerMessages.btrc",
        "TLS13PeerAuthentication.btrc",
        "ECDSASignature.btrc",
        "DER.btrc",
    ):
        shutil.copy(ROOT / "src/stdlib/TLS" / filename, tmp_path / filename)
    for path in (ROOT / "src/stdlib/TLS").glob("X509*.btrc"):
        shutil.copy(path, tmp_path / path.name)
    source = tmp_path / "ServerFlight.btrc"
    shutil.copy(ROOT / "src/tests/native/tls" / source.name, source)
    generated = tmp_path / "program.c"
    plan = _transpile(compiler, source, generated, request)
    binary = tmp_path / "program"
    NativeCorpusBuild(generated, plan).build(binary)
    assert DependencyAudit().binary_problems(binary, PackageTarget.parse(None).label) == []
    for name, options in (
        ("p256", ["-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256"]),
        ("p384", ["-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-384"]),
        ("rsa", ["-newkey", "rsa:2048"]),
        ("ed25519", ["-newkey", "ed25519"]),
    ):
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                *options,
                "-nodes",
                "-days",
                "1",
                "-subj",
                "/CN=localhost",
                "-out",
                "cert.pem",
                "-keyout",
                "key.pem",
            ],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            timeout=20,
        )
        der = subprocess.check_output(["openssl", "x509", "-in", "cert.pem", "-outform", "DER"], cwd=tmp_path)
        pin = hashlib.sha256(der).hexdigest()
        for suite in SUITES:
            server_flight(binary, tmp_path, suite, pin)
        if name == "p256":
            server_flight(binary, tmp_path, SUITES[0], pin, retry=True)
            for group in ("P-256", "P-384"):
                for suite in SUITES:
                    server_flight(binary, tmp_path, suite, pin, group=group)
                server_flight(binary, tmp_path, SUITES[0], pin, group=group, retry=True)
            for bad in ("already shared", "unsupported", "second retry", "changed group", "off curve"):
                malformed_retry(binary, tmp_path, pin, bad)
            for mutation in ("session", "suite", "version", "tag", "pin", "signature", "finished"):
                server_flight(binary, tmp_path, SUITES[0], pin, mutation=mutation)
