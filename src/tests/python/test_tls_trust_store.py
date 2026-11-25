"""Check Linux PEM trust bundles, hashed certificate directories and independent OpenSSL name hashes."""

import base64
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import PackageTarget
from src.tests.dependencies import DependencyAudit
from src.tests.python.test_network_runtime import _transpile
from src.tests.python.test_tls_server_path import chains as chains
from tools.native_plan import NativePlanBuilder

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
    # Explicit SSL_CERT_DIR alone must fail closed instead of merging system CA bundles.
    run(
        *selection,
        expected=1,
        environment={"CURL_CA_BUNDLE": "", "SSL_CERT_FILE": "", "SSL_CERT_DIR": str(empty)},
    )
    if shutil.which("bwrap"):
        # H1: Setting ONLY CURL_CA_BUNDLE, SSL_CERT_FILE, or SSL_CERT_DIR must not
        # merge the system /etc/ssl/certs bundle or hashed directory.
        system_certs = tmp_path / "fake-etc-ssl-certs"
        system_certs.mkdir()
        shutil.copyfile(root, system_certs / "ca-certificates.crt")
        (system_certs / (hash_name + ".0")).symlink_to(root)
        other_dir = tmp_path / "other-dir"
        other_dir.mkdir()
        other_hash = (
            subprocess.check_output(["openssl", "x509", "-in", other, "-subject_hash", "-noout"]).strip().decode()
        )
        (other_dir / (other_hash + ".0")).symlink_to(other)

        def run_isolated(expected, environment):
            result = subprocess.run(
                [
                    "bwrap",
                    "--ro-bind",
                    "/",
                    "/",
                    "--ro-bind",
                    system_certs,
                    "/etc/ssl/certs",
                    "--",
                    client,
                    *selection,
                ],
                cwd=chains,
                capture_output=True,
                timeout=20,
                env=env | environment,
            )
            assert result.returncode == expected and not result.stderr, (environment, result.stderr)

        # No overrides: system store trusts root.
        run_isolated(0, {"CURL_CA_BUNDLE": "", "SSL_CERT_FILE": "", "SSL_CERT_DIR": ""})
        # Explicit CURL_CA_BUNDLE=other: must reject root even though /etc/ssl/certs/<hash>.0 has root.
        run_isolated(1, {"CURL_CA_BUNDLE": str(other), "SSL_CERT_FILE": "", "SSL_CERT_DIR": ""})
        # Explicit SSL_CERT_FILE=other: must reject root even though /etc/ssl/certs/<hash>.0 has root.
        run_isolated(1, {"CURL_CA_BUNDLE": "", "SSL_CERT_FILE": str(other), "SSL_CERT_DIR": ""})
        # Explicit SSL_CERT_DIR=other_dir: must reject root even though /etc/ssl/certs/ca-certificates.crt has root.
        run_isolated(1, {"CURL_CA_BUNDLE": "", "SSL_CERT_FILE": "", "SSL_CERT_DIR": str(other_dir)})

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

    # Unsupported well-formed P-521 anchor coexisting in a bundle with a supported root:
    # hashes output both anchors, P-256/RSA chains still verify, P-521-signed chains fail
    # closed, and malformed/truncated/H2-mismatched anchors still reject the whole bundle.
    p521_key = tmp_path / "p521-root.key"
    p521_root = tmp_path / "p521-root.pem"
    p521_leaf_key = tmp_path / "p521-leaf.key"
    p521_leaf_csr = tmp_path / "p521-leaf.csr"
    p521_leaf = tmp_path / "p521-leaf.pem"
    p521_ext = tmp_path / "p521-leaf.ext"
    p521_ext.write_text(
        "basicConstraints=critical,CA:FALSE\n"
        "keyUsage=critical,digitalSignature\n"
        "extendedKeyUsage=serverAuth\n"
        "subjectAltName=DNS:service.example.test\n"
    )
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-521", "-out", p521_key],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-new",
            "-key",
            p521_key,
            "-sha512",
            "-days",
            "3",
            "-subj",
            "/O=btrc/CN=P-521 Trust Bundle Root",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
            "-addext",
            "keyUsage=critical,keyCertSign,cRLSign",
            "-out",
            p521_root,
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256", "-out", p521_leaf_key],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["openssl", "req", "-new", "-key", p521_leaf_key, "-subj", "/CN=service.example.test", "-out", p521_leaf_csr],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "openssl",
            "x509",
            "-req",
            "-in",
            p521_leaf_csr,
            "-CA",
            p521_root,
            "-CAkey",
            p521_key,
            "-CAcreateserial",
            "-sha512",
            "-days",
            "3",
            "-extfile",
            p521_ext,
            "-out",
            p521_leaf,
        ],
        check=True,
        capture_output=True,
    )
    mixed_bundle = tmp_path / "p521-plus-root.pem"
    mixed_bundle.write_bytes(p521_root.read_bytes() + root.read_bytes())
    p521_hash = subprocess.check_output(["openssl", "x509", "-in", p521_root, "-subject_hash", "-noout"]).strip()
    assert run("hashes", mixed_bundle).splitlines() == [p521_hash, index]
    verify(mixed_bundle, "")
    run(
        "verify",
        str(mixed_bundle),
        "",
        "service.example.test",
        now,
        str(p521_leaf),
        expected=1,
    )
    # Malformed DER, truncated PEM, and H2 outer/inner algorithm mismatch must still fail closed.
    bad_der_bundle = tmp_path / "bad-der-bundle.pem"
    bad_der_bundle.write_bytes(root.read_bytes() + b"-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n")
    run("hashes", bad_der_bundle, expected=1)
    truncated_bundle = tmp_path / "truncated-bundle.pem"
    truncated_bundle.write_bytes(root.read_bytes() + p521_root.read_bytes()[:-40])
    run("hashes", truncated_bundle, expected=1)
    p521_der = subprocess.check_output(["openssl", "x509", "-in", p521_root, "-outform", "DER"])
    # Mutate the outer signatureAlgorithm OID (ecdsa-with-SHA512 -> ecdsa-with-SHA384) without touching TBS.
    oid512 = bytes.fromhex("2a8648ce3d040304")
    oid384 = bytes.fromhex("2a8648ce3d040303")
    last_oid = p521_der.rfind(oid512)
    assert last_oid > p521_der.find(oid512)
    h2_der = p521_der[:last_oid] + oid384 + p521_der[last_oid + len(oid512) :]
    h2_pem = b"-----BEGIN CERTIFICATE-----\n" + base64.encodebytes(h2_der) + b"-----END CERTIFICATE-----\n"
    h2_bundle = tmp_path / "h2-mismatch-bundle.pem"
    h2_bundle.write_bytes(root.read_bytes() + h2_pem)
    run("hashes", h2_bundle, expected=1)

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
