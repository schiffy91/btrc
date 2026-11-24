"""Check Linux PEM trust bundles, hashed certificate directories and independent OpenSSL name hashes."""

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import PackageTarget
from src.tests.python.test_network_runtime import _transpile
from src.tests.python.test_tls_server_path import chains as chains
from tools.native_plan import NativePlanBuilder
from tools.qualification.dependencies import DependencyAudit

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("sanitized", [False, True])
def test_linux_tls_trust_store(tmp_path, compiler, request, sanitized, chains):
    if sys.platform != "linux":
        pytest.skip("requires Linux CA path interfaces")
    if not shutil.which("clang"):
        pytest.skip("clang is unavailable")
    stdlib = ROOT / "src/stdlib/TLS"
    for path in stdlib.glob("*.btrc"):
        if path.name.startswith("X509") or path.name in ("DER.btrc", "ECDSASignature.btrc"):
            shutil.copy(path, tmp_path / path.name)
    shutil.copytree(stdlib / "Linux", tmp_path / "Linux")
    source = tmp_path / "X509Trust.btrc"
    shutil.copy(ROOT / "src/tests/native/tls" / source.name, source)
    generated = tmp_path / "Program.c"
    plan = _transpile(compiler, source, generated, request)
    client = tmp_path / "Program"
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitized else []
    NativePlanBuilder().build(
        plan_path=plan,
        generated_c=generated,
        output=client,
        cc="clang",
        optimization=1 if sanitized else 2,
        compile_flags=["-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", *flags],
        link_flags=flags,
    )
    assert DependencyAudit().binary_problems(client, PackageTarget.parse(None).label) == []
    env = os.environ | {"ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1", "UBSAN_OPTIONS": "halt_on_error=1"}

    def run(*args, expected=0, environment=None):
        result = subprocess.run(
            [client, *map(str, args)], cwd=chains, capture_output=True, timeout=20, env=env | (environment or {})
        )
        assert result.returncode == expected, (args, result.stderr)
        assert not result.stderr
        return result.stdout

    root = chains / "root.pem"
    other = chains / "root-other.pem"
    index = subprocess.check_output(["openssl", "x509", "-in", root, "-subject_hash", "-noout"]).strip()
    paired = tmp_path / "anchors.pem"
    paired.write_bytes(b"# local CA list\r\n" + root.read_bytes().replace(b"\n", b"\r\n") + other.read_bytes())
    assert run("hashes", paired).splitlines()[0] == index
    assert run("hashes", chains / "case-root.pem").strip() == index
    run("expired", paired, expected=1)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    run("hashes", fifo, expected=1)
    trusted = subprocess.check_output(["openssl", "x509", "-in", root, "-addreject", "serverAuth", "-trustout"])
    for value in (
        b"",
        b"truncated",
        root.read_bytes()[:-20],
        root.read_bytes() + trusted.replace(b"END TRUSTED CERTIFICATE", b"END CERTIFICATE"),
        root.read_bytes() + b"-----BEGIN CERTIFICATE-----\n!",
        root.read_bytes().replace(b"\n", b"\0", 1),
    ):
        malformed = tmp_path / "malformed.pem"
        malformed.write_bytes(value)
        run("hashes", malformed, expected=1)

    directory = tmp_path / "certs"
    directory.mkdir()
    now = str(int(time.time()))

    def verify(file, directories, expected=0, **extra):
        run("verify", file, directories, "service.example.test", now, "leaf.pem", "ca.pem", expected=expected, **extra)

    policy = tmp_path / "policy.pem"
    for options, accepted in (
        ([], True),
        (["-setalias", "Company CA"], True),
        (["-addtrust", "serverAuth"], True),
        (["-addtrust", "anyExtendedKeyUsage"], True),
        (["-addtrust", "clientAuth"], False),
        (["-addreject", "serverAuth"], False),
        (["-addreject", "anyExtendedKeyUsage"], False),
        (["-addreject", "clientAuth"], True),
        (["-addtrust", "serverAuth", "-addreject", "serverAuth"], False),
    ):
        policy.write_bytes(subprocess.check_output(["openssl", "x509", "-in", root, *options, "-trustout"]))
        verify(policy, "", 0 if accepted else 1)
        verdict = subprocess.run(
            [
                "openssl",
                "verify",
                "-purpose",
                "sslserver",
                "-trusted",
                policy,
                "-partial_chain",
                "-untrusted",
                chains / "ca.pem",
                chains / "leaf.pem",
            ],
            capture_output=True,
        )
        assert (verdict.returncode == 0) == accepted, (options, verdict.stderr)
    # A second local copy must not silently erase explicit server distrust.
    for copies in ([trusted, root.read_bytes()], [root.read_bytes(), trusted]):
        policy.write_bytes(b"".join(copies))
        verify(policy, "", 1)
    blocked_intermediate = subprocess.check_output(
        ["openssl", "x509", "-in", chains / "ca.pem", "-addreject", "serverAuth", "-trustout"]
    )
    policy.write_bytes(root.read_bytes() + blocked_intermediate)
    verify(policy, "", 1)
    verify(paired, "")
    verify(other, "", 1)
    verify("", directory, 1)
    verify("", tmp_path / "missing", 1)
    (directory / "unhashed.pem").symlink_to(root)
    hash_name = index.decode()
    first = directory / (hash_name + ".0")
    second = directory / (hash_name + ".1")
    second.symlink_to(root)
    verify("", directory, 1)
    first.symlink_to(other)
    verify("", directory)
    second.unlink()
    verify("", directory, 1)
    first.unlink()
    first.symlink_to(root)
    verify(other, directory)
    empty = tmp_path / "empty"
    empty.mkdir()
    verify(other, str(empty) + ":" + str(directory))
    verify(tmp_path / "missing-file", directory, 1)
    selection = ("configured", "", "", "service.example.test", now, "leaf.pem", "ca.pem")
    run(*selection, environment={"CURL_CA_BUNDLE": "", "SSL_CERT_FILE": str(other), "SSL_CERT_DIR": str(directory)})
    run(*selection, environment={"CURL_CA_BUNDLE": str(root), "SSL_CERT_FILE": str(other), "SSL_CERT_DIR": str(empty)})
    run(
        *selection,
        expected=1,
        environment={"CURL_CA_BUNDLE": str(other), "SSL_CERT_FILE": str(root), "SSL_CERT_DIR": str(directory)},
    )

    test_env = {"CURL_CA_BUNDLE": str(root), "SSL_CERT_FILE": "", "SSL_CERT_DIR": ""}
    for host in (
        "Service.Example.Test.",
        "192.0.2.3",
        "0300.00.02.03",
        "0xc0000203",
        "192.515",
        "2001:db8::3",
        "[2001:db8::3]",
        "[2001:db8::3%25test0]",
    ):
        run("server", "", "", host, now, "leaf.pem", "ca.pem", environment=test_env)
        result = run("sni", host).decode().strip()
        assert result == ("service.example.test" if host == "Service.Example.Test." else "")
    for host in (
        "wrong.test",
        "192.0.2.4",
        "[192.0.2.3]",
        "2001:db8::4",
        "[2001:db8::3%25]",
        "0x100000000",
        "1.2.3.999",
    ):
        run("server", "", "", host, now, "leaf.pem", "ca.pem", expected=1, environment=test_env)
    run("timeout", "", "", "service.example.test", now, "leaf.pem", "ca.pem", expected=1, environment=test_env)

    # Check every complete ordinary certificate in a readily available distro bundle.
    system = Path("/etc/ssl/certs/ca-certificates.crt")
    if system.is_file():
        data = system.read_bytes()
        records = re.findall(rb"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", data, re.S)
        if records and b"-----BEGIN TRUSTED CERTIFICATE-----" not in data:
            expected = [
                subprocess.check_output(["openssl", "x509", "-subject_hash", "-noout"], input=pem).strip()
                for pem in records
            ]
            assert run("hashes", system).splitlines() == expected
