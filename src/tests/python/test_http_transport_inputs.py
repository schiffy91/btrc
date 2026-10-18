"""The dev shell's inputs for Library.HTTP's native transports and TLS fixtures (CL-P2-04).

docs/design/http-transport.md fixes them. The Linux transport links libcurl
>= 7.85.0 through ``pkg-config libcurl``, on a pinned OpenSSL 3.x backend with
the c-ares resolver (Native providers; Linux resolver, TLS and revocation
profiles). CURL_VERSION_ASYNCHDNS alone does not prove c-ares, because the
threaded resolver sets it too, so the probe reads curl_version_info's ares
fields. Every host that serves the TLS fixtures mints a per-run CA with a
pinned OpenSSL 3.x CLI (Curl-free endpoint and trust fixture plan), never
macOS's LibreSSL /usr/bin/openssl. flake.nix supplies both, and the
devcontainer shares its packages.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.process_limits import C_COMPILE_TIMEOUT, TOOL_TIMEOUT

LIBCURL_FLOOR = (7, 85, 0)
# Every flake dev shell exports the native header reader (flake.nix,
# nativeHeaderEnvironment); outside one these inputs are not promised.
DEV_SHELL_MARKER = "BTRC_NATIVE_HEADER_READER"

# The fields the transport's resolver and TLS profiles depend on. Built with
# the adapter's own strict flags and CURL_DISABLE_TYPECHECK, so it also proves
# the headers compose under them.
VERSION_PROBE = r"""#define CURL_DISABLE_TYPECHECK
#include <curl/curl.h>
#include <stdio.h>

static const char* text(const char* value) {
	return value != NULL ? value : "";
}

int main(void) {
	const curl_version_info_data* info = curl_version_info(CURLVERSION_NOW);
	if (info == NULL || info->age < CURLVERSION_NINTH) {
		return 1;
	}
	printf("version=%s\n", text(info->version));
	printf("version_num=%u\n", info->version_num);
	printf("ssl_version=%s\n", text(info->ssl_version));
	printf("ares=%s\n", text(info->ares));
	printf("ares_num=%d\n", info->ares_num);
	printf("ssl=%d\n", (info->features & CURL_VERSION_SSL) != 0);
	printf("asynchdns=%d\n", (info->features & CURL_VERSION_ASYNCHDNS) != 0);
	printf("cainfo=%s\n", text(info->cainfo));
	printf("capath=%s\n", text(info->capath));
	for (const char* const* protocol = info->protocols; *protocol != NULL; ++protocol) {
		printf("protocol=%s\n", *protocol);
	}
	return 0;
}
"""

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


def _version(text: str) -> tuple[int, int, int]:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    assert match, text
    return (int(match[1]), int(match[2]), int(match[3]))


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


def test_linux_libcurl_is_openssl_3_with_c_ares(tmp_path, record_property):
    if not sys.platform.startswith("linux"):
        pytest.skip("requires Linux: only the Linux dev shell carries the HTTP transport's libcurl")
    openssl = str(_dev_shell_openssl())
    assert shutil.which("pkg-config"), "the dev shell provides pkg-config"

    def module(*arguments: str) -> str:
        return _output(["pkg-config", *arguments]).strip()

    libcurl = module("--modversion", "libcurl")
    assert _version(libcurl) >= LIBCURL_FLOOR, libcurl
    include = Path(module("--variable=includedir", "libcurl"))
    library = Path(module("--variable=libdir", "libcurl"))
    for directory in (include, library):
        assert directory.is_relative_to("/nix/store"), f"libcurl resolves outside the pinned store: {directory}"
    # The transport needs no curl executable: the dev output propagates the
    # library (and its TLS, resolver and compression inputs), not curl's bin.
    propagated = (include.parent / "nix-support" / "propagated-build-inputs").read_text(encoding="utf-8").split()
    assert [path for path in propagated if re.search(r"-curl-[^/]*-bin$", path)] == [], propagated

    source = tmp_path / "CurlVersionProbe.c"
    source.write_text(VERSION_PROBE, encoding="utf-8")
    probe = tmp_path / "CurlVersionProbe"
    compiler = os.environ.get("CC") or "cc"
    _output(
        [compiler, "-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror"]
        + shlex.split(module("--cflags", "libcurl"))
        + [str(source), "-o", str(probe), f"-Wl,-rpath,{library}"]
        + shlex.split(module("--libs", "libcurl")),
        timeout=C_COMPILE_TIMEOUT,
    )
    fields: dict[str, str] = {}
    protocols: set[str] = set()
    for line in _output([str(probe)]).splitlines():
        name, _, value = line.partition("=")
        if name == "protocol":
            protocols.add(value)
        else:
            fields[name] = value

    openssl_cli = _output([openssl, "version"]).strip()
    observed = (
        f"libcurl {fields['version']}, TLS {fields['ssl_version']}, c-ares {fields['ares']}"
        f" (ares_num {int(fields['ares_num']):#08x}), cainfo {fields['cainfo'] or '-'},"
        f" capath {fields['capath'] or '-'}; openssl CLI {openssl_cli}"
    )
    print(observed)
    record_property("http_transport_inputs", observed)

    # The library the probe loaded is the one pkg-config resolved.
    assert fields["version"] == libcurl, fields
    assert int(fields["version_num"]) >= (LIBCURL_FLOOR[0] << 16 | LIBCURL_FLOOR[1] << 8 | LIBCURL_FLOOR[2]), fields
    # TLS through the pinned OpenSSL 3.x, the same release as the CLI.
    assert fields["ssl"] == "1", fields
    libssl = module("--modversion", "libssl")
    assert fields["ssl_version"] == f"OpenSSL/{libssl}", (fields, libssl)
    assert _version(libssl)[0] == 3, libssl
    assert re.match(rf"OpenSSL {re.escape(libssl)}\b", openssl_cli), (openssl_cli, libssl)
    # c-ares, not the threaded resolver: ares names the linked c-ares release.
    libcares = module("--modversion", "libcares")
    major, minor, patch = _version(libcares)
    assert fields["ares"] == libcares, (fields, libcares)
    assert int(fields["ares_num"]) == (major << 16 | minor << 8 | patch), (fields, libcares)
    assert fields["asynchdns"] == "1", fields
    assert {"http", "https"} <= protocols, protocols
