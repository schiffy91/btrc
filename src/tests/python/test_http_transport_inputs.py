"""Verify the OpenSSL CLI used by native HTTP test hosts to mint TLS fixtures."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.tests.process_limits import TOOL_TIMEOUT

# Every flake dev shell exports the native header reader (flake.nix,
# nativeHeaderEnvironment); outside one these inputs are not promised.
DEV_SHELL_MARKER = "BTRC_NATIVE_HEADER_READER"

# A fixture-shaped CA and leaf: RSA 2048, SHA-256, a SAN for the exact
# loopback address, serverAuth usage and a short validity interval.
FIXTURE_CA_CONFIG = """[req]
distinguished_name = subject
prompt = no

[subject]
CN = btrc HTTP fixture CA

[ca]
basicConstraints = critical, CA:TRUE
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always

[leaf]
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = IP:127.0.0.1
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid
"""


def _output(command: list[str], *, cwd: Path | None = None, timeout: float = TOOL_TIMEOUT) -> str:
    completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False, timeout=timeout)
    assert completed.returncode == 0, (command, completed.stdout, completed.stderr)
    return completed.stdout


def _dev_shell_openssl() -> Path:
    if not os.environ.get(DEV_SHELL_MARKER):
        pytest.skip(f"requires the flake's dev shell ({DEV_SHELL_MARKER} is unset)")
    found = shutil.which("openssl")
    assert found, "the dev shell puts an openssl CLI on PATH"
    resolved = Path(found).resolve()
    assert resolved.is_relative_to("/nix/store"), f"openssl resolves outside the pinned store: {resolved}"
    return resolved


def test_dev_shell_openssl_cli_is_pinned_openssl_3(record_property):
    openssl = _dev_shell_openssl()
    version = _output([str(openssl), "version"]).strip()

    print(f"openssl: {version} ({openssl})")
    record_property("openssl_cli", version)
    # Not LibreSSL, whose `version` line macOS's /usr/bin/openssl prints.
    assert re.match(r"OpenSSL 3\.\d+\.\d+\b", version), version


def test_dev_shell_openssl_mints_a_verifiable_fixture_ca(tmp_path):
    openssl = str(_dev_shell_openssl())
    config = tmp_path / "fixture-ca.cnf"
    config.write_text(FIXTURE_CA_CONFIG, encoding="utf-8")
    common = ["-config", str(config)]

    _output(
        [openssl, "req", "-x509", *common, "-extensions", "ca", "-newkey", "rsa:2048", "-sha256", "-days", "1"]
        + ["-nodes", "-keyout", "ca.key", "-out", "ca.pem"],
        cwd=tmp_path,
    )
    _output(
        [openssl, "req", "-new", *common, "-newkey", "rsa:2048", "-nodes", "-keyout", "leaf.key"]
        + ["-subj", "/CN=127.0.0.1", "-out", "leaf.csr"],
        cwd=tmp_path,
    )
    _output(
        [openssl, "x509", "-req", "-in", "leaf.csr", "-CA", "ca.pem", "-CAkey", "ca.key", "-sha256", "-days", "1"]
        + ["-extfile", str(config), "-extensions", "leaf", "-out", "leaf.pem"],
        cwd=tmp_path,
    )

    verify = [openssl, "verify", "-x509_strict", "-purpose", "sslserver", "-CAfile", "ca.pem"]
    assert _output([*verify, "-verify_ip", "127.0.0.1", "leaf.pem"], cwd=tmp_path).strip() == "leaf.pem: OK"
    # The SAN binds the leaf to its exact address, as the wrong-host fixture relies on.
    mismatch = subprocess.run(
        [*verify, "-verify_ip", "127.0.0.2", "leaf.pem"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=TOOL_TIMEOUT,
    )
    assert mismatch.returncode != 0, mismatch.stdout
    assert "IP address mismatch" in mismatch.stdout + mismatch.stderr, (mismatch.stdout, mismatch.stderr)
    # Remove the private keys, as the fixtures' teardown will.
    for key in ("ca.key", "leaf.key"):
        (tmp_path / key).unlink()
