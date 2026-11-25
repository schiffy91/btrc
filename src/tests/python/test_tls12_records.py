"""Exchange authenticated TLS 1.2 flights with a live OpenSSL engine for all six X25519 AEAD suites."""

import hashlib
import hmac
import shutil
import ssl
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import PackageTarget
from src.tests.dependencies import BinaryImports, DependencyAudit
from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.test_network_runtime import _transpile
from tools.native_plan import NativePlanBuilder

ROOT = Path(__file__).resolve().parents[3]
SUITES = {
    0xC02B: "ECDHE-ECDSA-AES128-GCM-SHA256",
    0xC02C: "ECDHE-ECDSA-AES256-GCM-SHA384",
    0xC02F: "ECDHE-RSA-AES128-GCM-SHA256",
    0xC030: "ECDHE-RSA-AES256-GCM-SHA384",
    0xCCA8: "ECDHE-RSA-CHACHA20-POLY1305",
    0xCCA9: "ECDHE-ECDSA-CHACHA20-POLY1305",
}


def records(wire):
    result = []
    while wire:
        assert len(wire) >= 5
        end = 5 + int.from_bytes(wire[3:5], "big")
        assert end <= len(wire)
        result.append(wire[:end])
        wire = wire[end:]
    return result


@pytest.fixture(scope="module")
def credentials(tmp_path_factory):
    if not shutil.which("openssl"):
        pytest.skip("OpenSSL is required as an independent TLS 1.2 peer")
    root = tmp_path_factory.mktemp("tls12-peer")
    for name, args in [
        ("RSA", ["-newkey", "rsa:2048"]),
        ("ECDSA", ["-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256"]),
    ]:
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                *args,
                "-nodes",
                "-subj",
                "/CN=loopback.test",
                "-days",
                "1",
                "-keyout",
                root / f"{name}.key",
                "-out",
                root / f"{name}.pem",
            ],
            check=True,
            capture_output=True,
        )
    return root


def flight(suite, name, root, keylog):
    """Finish the real TLS handshake and retain its records, before either endpoint sends an application message."""
    client = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    credential = name.split("-")[1]
    server.load_cert_chain(root / f"{credential}.pem", root / f"{credential}.key")
    client.load_verify_locations(cafile=root / f"{credential}.pem")
    client.keylog_filename = str(keylog)
    for context in (client, server):
        context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_2
        context.options |= ssl.OP_NO_TICKET
        context.set_ciphers(name)
    # Restrict the ephemeral server key to X25519. OpenSSL also uses the
    # client supported_groups list to admit ECDSA certificate curves.
    server.set_ecdh_curve("X25519")
    to_client, from_client = ssl.MemoryBIO(), ssl.MemoryBIO()
    to_server, from_server = ssl.MemoryBIO(), ssl.MemoryBIO()
    initiator = client.wrap_bio(to_client, from_client, server_hostname="loopback.test")
    responder = server.wrap_bio(to_server, from_server, server_side=True)
    messages = []
    protected = {"client": False, "server": False}
    finished = {}
    randoms = {}
    ready = set()
    for _ in range(10):
        for side, engine, outgoing, incoming in [
            ("client", initiator, from_client, to_server),
            ("server", responder, from_server, to_client),
        ]:
            try:
                engine.do_handshake()
                ready.add(side)
            except ssl.SSLWantReadError:
                pass
            wire = outgoing.read()
            if wire:
                incoming.write(wire)
            for record in records(wire):
                header, content = record[0], record[5:]
                if header == 20:
                    assert content == b"\x01"
                    protected[side] = True
                elif header == 22 and protected[side]:
                    finished[side] = record
                else:
                    assert header == 22 and not protected[side]
                    messages.append(content)
                    if side not in randoms:
                        assert content[0] == (1 if side == "client" else 2)
                        randoms[side] = content[6:38]
        if len(ready) == 2:
            break
    assert len(ready) == len(finished) == 2 and initiator.cipher()[0] == name
    # Check the ServerKeyExchange named group and key-share length.
    assert any(content[:1] == b"\x0c" and content[4:8] == b"\x03\x00\x1d\x20" for content in messages)
    entry = next(line.split() for line in keylog.read_text().splitlines() if line.startswith("CLIENT_RANDOM "))
    assert entry[1] == randoms["client"].hex()
    return responder, to_server, from_server, bytes.fromhex(entry[2]), randoms, finished, b"".join(messages)


def command(exe, mode, suite, *args, check=True, env=None):
    argv = [arg.hex() if isinstance(arg, bytes) else str(arg) for arg in args]
    result = subprocess.run(
        [exe, str(mode), str(suite), *argv], capture_output=True, text=True, timeout=20, check=check, env=env
    )
    assert not result.stderr
    return result


def exercise(exe, suite, name, root, tmp_path, *, env=None):
    server, incoming, outgoing, master, randoms, finished, transcript = flight(
        suite, name, root, tmp_path / f"{suite}.keys"
    )
    server_msg = b"OpenSSL to btrc\x00" + bytes(range(256))
    client_msg = b"btrc to OpenSSL\x00" + bytes(range(255, -1, -1))
    assert server.write(server_msg) == len(server_msg)
    (ciphertext,) = records(outgoing.read())
    materials = (master, randoms["client"], randoms["server"])
    result = command(
        exe,
        1,
        suite,
        *materials,
        finished["client"],
        finished["server"],
        ciphertext,
        client_msg,
        transcript,
        env=env,
    )
    received, encrypted = (bytes.fromhex(line) for line in result.stdout.splitlines())
    assert received == server_msg
    incoming.write(encrypted)
    assert server.read(16384) == client_msg
    command(exe, 5, suite, *materials, env=env)
    valid = finished["server"]
    for invalid in [
        valid[:-1],
        valid + b"x",
        bytes([23]) + valid[1:],
        valid[:2] + b"\x01" + valid[3:],
        valid[:-1] + bytes([valid[-1] ^ 1]),
        ciphertext,
    ]:
        command(exe, 3, suite, *materials, valid, invalid, env=env)
    # Independent P_hash construction for the extended-master-secret
    # transcript through ClientKeyExchange; no legacy master-secret mode.
    digest = hashlib.sha384 if suite in [0xC02C, 0xC030] else hashlib.sha256
    session_hash = digest(transcript).digest()
    shared = bytes(range(32))
    seed = b"extended master secret" + session_hash
    a = hmac.digest(shared, seed, digest)
    block = hmac.digest(shared, a + seed, digest)
    a = hmac.digest(shared, a, digest)
    expected = (block + hmac.digest(shared, a + seed, digest))[:48]
    assert bytes.fromhex(command(exe, 2, suite, shared, session_hash, env=env).stdout) == expected
    assert command(exe, 2, suite, bytes(32), session_hash, check=False, env=env).returncode == 1
    assert command(exe, 2, suite, shared, session_hash[:-1], check=False, env=env).returncode == 1


@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "asan-ubsan"])
def test_tls12_aead(tmp_path, request, compiler, sanitized, credentials):
    cc = ("/usr/bin/clang" if sys.platform == "darwin" else "clang") if sanitized else "cc"
    if not shutil.which(cc):
        pytest.skip(f"{cc} is required to build the TLS 1.2 record probe")
    for module in ["TLS12Keys", "TLS12Records"]:
        shutil.copy(ROOT / f"src/stdlib/TLS/{module}.btrc", tmp_path)
    source = tmp_path / "TLS12Probe.btrc"
    shutil.copy(ROOT / "src/tests/native/tls" / source.name, source)
    generated, exe = tmp_path / "Program.c", tmp_path / "Program"
    plan = _transpile(compiler, source, generated, request)
    flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitized else []
    builder, toolchain = NativePlanBuilder(), {"cc": cc}
    run_env = None
    if sanitized and sys.platform == "darwin":

        def run(command, **options):
            return subprocess.run(command, **{**options, "env": apple_environment(options.get("env"))})

        builder = NativePlanBuilder(runner=run)
        toolchain = {"cc": "/usr/bin/clang", "cxx": "/usr/bin/clang++"}
        run_env = apple_environment()
    builder.build(
        plan_path=plan,
        generated_c=generated,
        output=exe,
        optimization=1 if sanitized else 2,
        compile_flags=["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic-errors", *flags],
        link_flags=flags,
        **toolchain,
    )
    assert not DependencyAudit().binary_problems(exe, PackageTarget.parse(None).label)
    assert all("ssl" not in library.lower() and "crypto" not in library.lower() for library in BinaryImports.read(exe))
    # TLS working group published TLS 1.2 PRF test vector (SHA-256).
    seed = bytes.fromhex("a0ba9f936cda311827a6f796ffd5198c")
    secret = bytes.fromhex("9bbe436ba940f017b17652849a71db35")
    expected = "e3f229ba727be17b8d122620557cd453c2aab21d07c3d495329b52d4e61edb5a6b301791e90d35c9c9a46b4e14baf9af0fa022f7077def17abfd3797c0564bab4fbc91666e9def9b97fce34f796789baa48082d122ee42c5a72e5a5110fff70187347b66"
    assert command(exe, 4, 0xC02F, secret, seed, 100, "test label", env=run_env).stdout.strip() == expected
    # Mbed TLS test_suite_ssl.data: TLS_PRF_SHA384, 48-byte secret and 64-byte seed.
    unit = bytes.fromhex("1234567890abcdef")
    assert (
        command(exe, 4, 0xC030, unit * 6, unit * 8, 16, "test tls_prf label", env=run_env).stdout.strip()
        == "a4206a36eef93f496611c2b7806625c3"
    )
    for suite, name in SUITES.items():
        exercise(exe, suite, name, credentials, tmp_path, env=run_env)
