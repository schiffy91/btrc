"""Qualify HTTPClient with the candidate Linux TLS provider before changing its default."""

import http.server
import os
import select
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
from contextlib import suppress
from pathlib import Path

import pytest

from src.tests.native_build import NativeCorpusBuild
from tools.qualification.dependencies import BinaryImports, DependencyAudit

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "src/tests/native/tls"
pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux transport")


def compile_client(directory, frontend, configure_stdlib=None):
    # Both compilers read the same temporary provider selection. The compiler's
    # normal data layout, package metadata and runtime stay intact.
    alternate = directory / "stdlib"
    shutil.copytree(ROOT / "src/stdlib", alternate)
    shutil.copyfile(FIXTURES / "HTTPQualificationProvider.btrc", alternate / "HTTP/Unix/HTTPTransportProvider.btrc")
    manifest = alternate / "TLS/btrc.toml"
    source = manifest.read_text()
    exposed = source.replace("exports = [", 'exports = ["Linux.HTTPStream", ', 1)
    assert exposed != source
    manifest.write_text(exposed)
    if configure_stdlib is not None:
        configure_stdlib(alternate)
    binary = directory / "client"
    artifact = NativeCorpusBuild(binary.with_suffix(".c"), binary.with_suffix(".json"), tuple(frontend))
    result = subprocess.run(
        [
            "bwrap",
            "--bind",
            "/",
            "/",
            "--ro-bind",
            alternate,
            ROOT / "src/stdlib",
            "--",
            *frontend,
            "--strict-imports",
            "--no-cache",
            FIXTURES / "HTTPExchangeProbe.btrc",
            "-o",
            artifact.primary,
            "--emit-link-plan",
            artifact.plan,
        ],
        env=os.environ | {"BTRC_HOME": str(ROOT / "src"), "BTRC_CACHE_DIR": str(directory / "cache")},
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0 and not result.stderr, result.stderr
    generated = artifact.primary.read_text()
    assert "LinuxTLSStream_connect" in generated and "HTTPConnect_establish" in generated
    artifact.build(binary)
    assert not DependencyAudit().binary_problems(binary, "linux-x86_64")
    assert all("curl" not in item and "ssl" not in item and "crypto" not in item for item in BinaryImports.read(binary))
    return binary


@pytest.fixture(scope="module", params=[ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_3], ids=["TLS1.2", "TLS1.3"])
def local_server(tmp_path_factory, request):
    if not shutil.which("openssl"):
        pytest.skip("requires OpenSSL for the independent test authority")
    directory = tmp_path_factory.mktemp("linux-https-certificates")

    def openssl(*args):
        subprocess.run(["openssl", *args], cwd=directory, check=True, capture_output=True, timeout=30)

    for ca in ("root", "other"):
        openssl(
            "req",
            "-x509",
            "-newkey",
            "ec",
            "-pkeyopt",
            "ec_paramgen_curve:P-256",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=" + ca,
            "-keyout",
            ca + ".key",
            "-out",
            ca + ".pem",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
            "-addext",
            "keyUsage=critical,keyCertSign",
        )
    openssl(
        "req",
        "-newkey",
        "ec",
        "-pkeyopt",
        "ec_paramgen_curve:P-256",
        "-nodes",
        "-subj",
        "/CN=localhost",
        "-keyout",
        "server.key",
        "-out",
        "server.csr",
    )
    (directory / "extensions").write_text(
        "basicConstraints=critical,CA:FALSE\nsubjectAltName=DNS:localhost,DNS:proxy-only.invalid\nextendedKeyUsage=serverAuth\nkeyUsage=critical,digitalSignature\n"
    )
    openssl(
        "x509",
        "-req",
        "-in",
        "server.csr",
        "-CA",
        "root.pem",
        "-CAkey",
        "root.key",
        "-set_serial",
        "200",
        "-days",
        "1",
        "-extfile",
        "extensions",
        "-out",
        "server.pem",
    )
    seen = []

    class Peer(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            data = self.rfile.read(int(self.headers["Content-Length"]))
            seen.append(self.path)
            if self.path == "/credentials":
                assert self.headers.get("Authorization") == "Basic dXNlcjpvcmk="
                assert "Proxy-Authorization" not in self.headers
            if self.path == "/slow":
                time.sleep(4)
            content = self.headers["X-Test"].encode() + b":" + data
            self.send_response(201)
            if self.path != "/truncated":
                self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            with suppress(OSError):
                self.wfile.write(content)

        def log_message(self, *args):
            pass

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = context.maximum_version = request.param
    context.set_alpn_protocols(["http/1.1"])
    context.load_cert_chain(directory / "server.pem", directory / "server.key")
    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), Peer) as server:
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield directory, server.server_port, seen
        finally:
            server.shutdown()
            thread.join()


_CLIENT_BINARIES = pytest.StashKey[dict[str, Path]]()


@pytest.fixture(scope="session")
def compiled_clients(pytestconfig):
    # HTTP, proxy and certificate modules all execute the same public program.
    return pytestconfig.stash.setdefault(_CLIENT_BINARIES, {})


@pytest.fixture
def client(tmp_path_factory, compiled_clients, request, compiler):
    if not shutil.which("bwrap"):
        pytest.skip("requires a private mount namespace for the candidate provider")
    frontend = (
        [sys.executable, "-m", "src.compiler.python.main"]
        if compiler == "python"
        else [str(request.getfixturevalue("immutable_btrcc"))]
    )
    if compiler not in compiled_clients:
        compiled_clients[compiler] = compile_client(tmp_path_factory.mktemp(f"tls-http-{compiler}"), frontend)
    return compiled_clients[compiler]


def test_http_client_over_first_party_tls(client, local_server):
    binary = client
    directory, port, seen = local_server
    for mode, host, ca, reaches_peer, expected in (
        ("ok", "localhost", "root", True, ""),
        ("name", "127.0.0.1", "root", False, "TLS handshake failed"),
        ("untrusted", "localhost", "other", False, "TLS handshake failed"),
        ("limit", "localhost", "root", True, "response body is too large"),
        ("truncated", "localhost", "root", True, "connection failed"),
        ("slow", "localhost", "root", True, "request timed out"),
    ):
        before = len(seen)
        environment = os.environ | {
            "CURL_CA_BUNDLE": str(directory / (ca + ".pem")),
            "PATH": "/no-curl",
            "NO_PROXY": "*",
            "SSL_CERT_DIR": "",
            "SSL_CERT_FILE": "",
        }
        start = time.monotonic()
        result = subprocess.run(
            [binary, f"https://{host}:{port}/{mode}", mode], env=environment, capture_output=True, text=True, timeout=8
        )
        elapsed = time.monotonic() - start
        assert (result.returncode, result.stdout.strip(), result.stderr) == (0, expected, "")
        assert seen[before:] == (["/" + mode] if reaches_peer else [])
        if mode == "slow":
            assert 1.5 <= elapsed < 3.5


@pytest.mark.parametrize("secure_proxy", [False, True], ids=["http-proxy", "https-proxy"])
def test_https_connect_proxy(client, local_server, tmp_path, secure_proxy):
    directory, port, seen = local_server
    records = []
    delay = [0]
    response = [b"HTTP/1.1 100 Continue\r\n\r\nHTTP/1.1 200 Connected\r\n\r\n"]

    class Proxy(http.server.BaseHTTPRequestHandler):
        def do_CONNECT(self):
            records.append((self.path, self.headers))
            reply = response[0]
            if reply is None:
                time.sleep(3)
                return
            if delay[0]:
                time.sleep(delay[0])
            self.connection.sendall(reply)
            if not reply.endswith(b"200 Connected\r\n\r\n"):
                return
            with socket.create_connection(("127.0.0.1", port), timeout=5) as peer:
                connections = [self.connection, peer]
                try:
                    while True:
                        ready, _, _ = select.select(connections, [], [], 5)
                        if not ready:
                            return
                        for source in ready:
                            data = source.recv(16384)
                            if not data:
                                return
                            (peer if source is self.connection else self.connection).sendall(data)
                except OSError:
                    pass

        def log_message(self, *args):
            pass

    system_cas = tmp_path / "system-cas"
    system_cas.mkdir()
    system_bundle = system_cas / "ca-certificates.crt"
    shutil.copyfile(directory / "other.pem", system_bundle)
    command = (
        [
            shutil.which("bwrap"),
            "--ro-bind",
            "/",
            "/",
            "--bind",
            tmp_path,
            tmp_path,
            "--ro-bind",
            system_cas,
            "/etc/ssl/certs",
            "--",
        ]
        if secure_proxy
        else []
    )
    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), Proxy) as proxy:
        if secure_proxy:
            # The proxy has its own key and a CA distinct from the origin's CA.
            extensions = tmp_path / "proxy-extensions"
            extensions.write_text(
                "basicConstraints=CA:FALSE\nsubjectAltName=DNS:localhost\nextendedKeyUsage=serverAuth\n"
            )
            key = tmp_path / "proxy.key"
            csr = tmp_path / "proxy.csr"
            cert = tmp_path / "proxy.pem"
            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-new",
                    "-newkey",
                    "ec",
                    "-pkeyopt",
                    "ec_paramgen_curve:P-256",
                    "-nodes",
                    "-subj",
                    "/CN=localhost",
                    "-keyout",
                    key,
                    "-out",
                    csr,
                ],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "openssl",
                    "x509",
                    "-req",
                    "-in",
                    csr,
                    "-CA",
                    directory / "other.pem",
                    "-CAkey",
                    directory / "other.key",
                    "-set_serial",
                    "900",
                    "-days",
                    "1",
                    "-extfile",
                    extensions,
                    "-out",
                    cert,
                ],
                check=True,
                capture_output=True,
            )
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert, key)
            proxy.socket = context.wrap_socket(proxy.socket, server_side=True)
        serving = threading.Thread(target=proxy.serve_forever, daemon=True)
        serving.start()
        environment = {key: value for key, value in os.environ.items() if not key.lower().endswith("_proxy")}
        environment.update(
            CURL_CA_BUNDLE=str(directory / "root.pem"), SSL_CERT_FILE="", SSL_CERT_DIR="", PATH="/no-curl"
        )
        proxy_url = f"{'https' if secure_proxy else 'http'}://p%40xy:pw@localhost:{proxy.server_port}"
        dead_proxy = "http://127.0.0.1:1"

        def probe(
            mode, *, host="proxy-only.invalid", path="credentials", expected="", destination_port=port, **settings
        ):
            authority = host if destination_port is None else f"{host}:{destination_port}"
            url = f"https://user:ori@{authority}/{path}"
            result = subprocess.run(
                [*command, client, url, mode],
                env=environment | settings,
                capture_output=True,
                text=True,
                timeout=20 if mode == "header-limit" else 6,
            )
            assert (result.returncode, result.stdout.strip(), result.stderr) == (0, expected, "")

        try:
            if secure_proxy:
                # With only the origin CA installed, even an explicit override that
                # trusts the proxy cannot authorize sending it CONNECT credentials.
                shutil.copyfile(directory / "root.pem", system_bundle)
                probe(
                    "error",
                    https_proxy=proxy_url,
                    CURL_CA_BUNDLE=str(directory / "other.pem"),
                    expected="proxy TLS handshake failed",
                )
                shutil.copyfile(directory / "other.pem", system_bundle)
                probe(
                    "error",
                    https_proxy=proxy_url.replace("localhost", "127.0.0.1"),
                    expected="proxy TLS handshake failed",
                )
                assert not records
            for mode, auth, settings in (
                ("ok", "Basic cEB4eTpwdw==", {"https_proxy": proxy_url, "HTTPS_PROXY": dead_proxy}),
                ("explicit", "Bearer tunnel", {"https_proxy": "", "HTTPS_PROXY": proxy_url, "all_proxy": dead_proxy}),
                ("ok", "Basic cEB4eTpwdw==", {"all_proxy": "", "ALL_PROXY": proxy_url.removeprefix("http://")}),
            ):
                probe(mode, **settings)
                authority, fields = records[-1]
                assert authority == f"proxy-only.invalid:{port}" and fields["Host"] == authority
                assert fields.get_all("Proxy-Authorization") == [auth]
                assert "Authorization" not in fields and "X-Test" not in fields
            probe("ok", https_proxy=proxy_url, destination_port=None)
            assert len(records) == 4 and records[-1][0] == "proxy-only.invalid:443"
            before = len(seen)
            probe("name", host="unlisted.invalid", https_proxy=proxy_url, expected="TLS handshake failed")
            probe("name", host="[2001:db8::10]", https_proxy=proxy_url, expected="TLS handshake failed")
            assert records[-1][0] == f"[2001:db8::10]:{port}"
            assert len(records) == 6 and len(seen) == before
            probe("direct", host="localhost", https_proxy=proxy_url, no_proxy="", NO_PROXY="localhost")
            probe("direct", host="localhost", http_proxy=proxy_url)
            probe(
                "name", host="127.0.0.1", https_proxy=proxy_url, no_proxy="127.0.0.0/8", expected="TLS handshake failed"
            )
            assert len(records) == 6 and len(seen) == before + 2
            delay[0] = 1.2
            start = time.monotonic()
            probe("slow", path="slow", https_proxy=proxy_url, expected="request timed out")
            assert 1.5 <= time.monotonic() - start < 3.0
            assert seen[-1] == "/slow"
            delay[0] = 0
            before = len(seen)
            for reply, error in (
                (b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n", "proxy CONNECT returned 407"),
                (b"HTTP/1.1 101 Switching Protocols\r\n\r\n", "invalid proxy response"),
                (b"HTTP/1.1 200 Connected\r\n\r\nstray", "invalid proxy response"),
                (b"HTTP/1.1 200 Connected\r\nX-Long: " + b"a" * 65536, "proxy headers are too large"),
            ):
                response[0] = reply
                probe("header-limit" if len(reply) > 65536 else "error", https_proxy=proxy_url, expected=error)
            response[0] = None
            start = time.monotonic()
            probe("error", https_proxy=proxy_url, expected="request timed out")
            assert 1.5 <= time.monotonic() - start < 3.5
            assert len(seen) == before
            before = len(records)
            # Unsupported schemes still invoke the legacy process. A fixture
            # executable records delegation without requiring that dependency.
            fake = tmp_path / "curl"
            fake.write_text(
                "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$INVOCATION\"\nprintf 'trust:payload\\n__BTRC_HTTP_STATUS__:201'\n"
            )
            fake.chmod(0o755)
            for scheme in ("socks5h", "ftp"):
                invocation = tmp_path / scheme
                probe(
                    "ok",
                    HTTPS_PROXY=f"{scheme}://127.0.0.1:{proxy.server_port}",
                    PATH=str(tmp_path),
                    INVOCATION=str(invocation),
                )
                assert (
                    invocation.read_text().splitlines()[-1] == f"https://user:ori@proxy-only.invalid:{port}/credentials"
                )
            for settings in ({"HTTPS_PROXY": proxy_url}, {"NO_PROXY": "*"}):
                invocation = tmp_path / "explicit-header"
                invocation.unlink(missing_ok=True)
                probe("explicit", PATH=str(tmp_path), INVOCATION=str(invocation), **settings)
                assert "pRoXy-AuThOrIzAtIoN: Bearer tunnel" in invocation.read_text().splitlines()
            assert len(records) == before
        finally:
            proxy.shutdown()
            serving.join()
