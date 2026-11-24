"""Exercise public HTTPClient over Android's checked JNI on a connected device.

Supply a local server key and localhost-only certificate that the driver can
trust privately, plus adb, javac, the NDK and d8 from the Android dev shell.
"""

import argparse
import http.server
import os
import select
import shlex
import socket
import socketserver
import ssl
import subprocess
import sys
import threading
import time
import uuid
from contextlib import ExitStack
from pathlib import Path

from src.compiler.python.frontend.packages import PackageTarget
from src.tests.native.http.socks_peer import SocksPeer, check_android_tunnels
from src.tests.native_build import NativeCorpusBuild
from src.tests.python.jni_adoption_fixtures import SharedLibraryRunner
from tools.qualification.dependencies import DependencyAudit

FIXTURES = Path(__file__).resolve().parent
ROOT = FIXTURES.parents[3]


class Peer(http.server.BaseHTTPRequestHandler):
    def reply(self, status, body, *, location=None):
        if self.headers.get("Proxy-Authorization"):
            self.server.leaked_proxy_credentials = True
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        if location:
            self.send_header("Location", location)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_POST(self):
        data = self.rfile.read(int(self.headers["Content-Length"]))
        self.reply(201, self.headers["X-Check"].encode() + b"/" + data)

    def do_PATCH(self):
        data = self.rfile.read(int(self.headers["Content-Length"]))
        self.reply(200, b"PATCH:" + data)

    def do_GET(self):
        if self.path == "/proxy-header":
            self.reply(403 if self.headers.get("Proxy-Authorization") else 204, b"")
        elif self.path == "/explicit":
            ok = self.headers.get("Authorization") == "Basic Y2FsbGVyOnNlY3JldA=="
            self.reply(200 if ok else 403, b"caller" if ok else b"")
        elif self.path == "/challenge":
            authorized = self.headers.get("Authorization") is not None
            self.server.challenges.append(authorized)
            self.send_response(200 if authorized else 401)
            self.send_header("Content-Length", "0")
            if not authorized:
                self.send_header("WWW-Authenticate", 'Basic realm="https-fixture"')
            self.end_headers()
        elif self.path == "/cookie-check":
            self.server.cookie_requests.append(self.headers.get("Cookie"))
            self.reply(200, b"clean" if not self.headers.get("Cookie") else b"shared")
        elif self.path == "/redirect":
            self.reply(302, b"", location="/missing")
        elif self.path == "/large":
            self.reply(200, b"12345")
        elif self.path == "/slow":
            time.sleep(3)
            self.reply(200, b"")
        else:
            self.reply(404, b"missing")


class ConnectPeer(http.server.BaseHTTPRequestHandler):
    """Tunnel only to this test's local TLS server, independent of DNS."""

    def do_CONNECT(self):
        if self.path not in self.server.authorities:
            self.send_error(403)
            return
        expected = getattr(self.server, "expected_proxy_header", None)
        if self.server.require_credentials:
            expected = "Basic dXNlcjpwYXNz"
        if expected is not None and self.headers.get("Proxy-Authorization") != expected:
            self.send_error(407)
            return
        self.server.tunnels.append(self.path)
        with socket.create_connection(self.server.origin, timeout=5) as origin:
            if getattr(self.server, "interim", False):
                self.connection.sendall(b"HTTP/1.1 103 Early Hints\r\n\r\n")
            self.send_response(200)
            self.end_headers()
            while True:
                if isinstance(self.connection, ssl.SSLSocket) and self.connection.pending():
                    ready = [self.connection]
                else:
                    ready, _, _ = select.select([self.connection, origin], [], [], 10)
                if not ready:
                    return
                for source in ready:
                    try:
                        data = source.recv(8192)
                        if not data:
                            return
                        destination = origin if source is self.connection else self.connection
                        destination.sendall(data)
                    except (BrokenPipeError, ConnectionResetError, ssl.SSLEOFError):
                        # Identity rejection and the timeout fixture deliberately close a tunnel in flight.
                        return


class ForwardPeer(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.requests.append((self.path, self.headers.get("Proxy-Authorization")))
        accepted = self.server.requests[-1] == ("http://btrc.invalid/forward", "Basic dXNlcjpwYXNz")
        self.send_response(200 if accepted else 403)
        self.send_header("Content-Length", "7" if accepted else "0")
        self.end_headers()
        if accepted:
            self.wfile.write(b"forward")


FORBIDDEN_CURL_MARKERS = ("HTTPCurlTransport", "__BTRC_HTTP_STATUS__:", "--proto-redir")


def ndk_prebuilt() -> Path:
    host = "darwin-x86_64" if sys.platform == "darwin" else "linux-x86_64"
    return Path(os.environ["ANDROID_NDK_HOME"]) / "toolchains/llvm/prebuilt" / host


def assert_no_curl_artifacts(c_source: Path, binary: Path, target: str) -> None:
    generated = c_source.read_text(encoding="utf-8")
    for marker in FORBIDDEN_CURL_MARKERS:
        assert marker not in generated, f"{c_source.name} still references {marker!r}"
    raw = binary.read_bytes()
    for marker in FORBIDDEN_CURL_MARKERS:
        assert marker.encode("ascii") not in raw, f"{binary.name} still contains {marker!r}"
    assert not (problems := DependencyAudit().binary_problems(binary, target)), problems


def build_libraries(args):
    ndk = ndk_prebuilt()
    target = PackageTarget.parse(args.target)
    os.environ["BTRC_NATIVE_TARGET"] = target.row.triple
    os.environ["BTRC_NATIVE_SYSROOT"] = str(ndk / "sysroot")
    architecture = target.architecture
    cc = ndk / "bin" / f"{architecture}-linux-android29-clang"
    harness = args.output / "harness.o"
    subprocess.run(
        [cc, "-fPIC", "-iquote", ROOT / "src/stdlib/Java", "-c", FIXTURES / "AndroidHTTPSHarness.c", "-o", harness],
        check=True,
    )
    for name, compiler in (
        ("reference", [sys.executable, "-m", "src.compiler.python.main"]),
        ("selfhost", [args.btrcc]),
    ):
        artifact = NativeCorpusBuild(args.output / f"{name}.c", args.output / f"{name}.json", tuple(compiler))
        subprocess.run(
            [
                *compiler,
                FIXTURES / "AndroidHTTPS.btrc",
                "--target",
                args.target,
                "--strict-imports",
                "-o",
                artifact.primary,
                "--emit-link-plan",
                artifact.plan,
            ],
            check=True,
        )
        library = args.output / f"lib{name}.so"
        runner = SharedLibraryRunner(artifact.primary, os.environ.copy(), link_flags=[str(harness)])
        artifact.build(library, runner=runner)
        assert_no_curl_artifacts(artifact.primary, library, args.target)
        yield library


def build_standalone_binaries(args):
    ndk = ndk_prebuilt()
    target = PackageTarget.parse(args.target)
    os.environ["BTRC_NATIVE_TARGET"] = target.row.triple
    os.environ["BTRC_NATIVE_SYSROOT"] = str(ndk / "sysroot")
    standalone_source = ROOT / "src/tests/stdlib/HttpClientLocal.btrc"
    for name, compiler in (
        ("reference", [sys.executable, "-m", "src.compiler.python.main"]),
        ("selfhost", [args.btrcc]),
    ):
        artifact = NativeCorpusBuild(
            args.output / f"standalone-{name}.c", args.output / f"standalone-{name}.json", tuple(compiler)
        )
        subprocess.run(
            [
                *compiler,
                standalone_source,
                "--target",
                args.target,
                "--strict-imports",
                "-o",
                artifact.primary,
                "--emit-link-plan",
                artifact.plan,
            ],
            check=True,
        )
        executable = args.output / f"standalone-{name}"
        artifact.build(executable)
        assert_no_curl_artifacts(artifact.primary, executable, args.target)
        yield executable


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, choices=["android-x86_64", "android-aarch64"])
    parser.add_argument("--btrcc", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compile-only", action="store_true")
    parser.add_argument(
        "--local-trust-only", action="store_true", help="run the trust peer inside the AVD without adb port forwarding"
    )
    parser.add_argument(
        "--observe-authenticator",
        action="store_true",
        help="also record whether ART sends an installed authenticator's credentials",
    )
    parser.add_argument("--serial", help="connected device on which to execute the checked-JNI fixture")
    parser.add_argument(
        "--cert", type=Path, help="localhost-only certificate; the fixture sets its process-local trust"
    )
    parser.add_argument("--key", type=Path, help="TLS server private key")
    parser.add_argument("--d8", help="Android build-tools d8 executable")
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    if not args.compile_only and not all((args.serial, args.cert, args.key, args.d8)):
        parser.error("execution requires --serial, --cert, --key and --d8")
    libraries = list(build_libraries(args))
    standalones = list(build_standalone_binaries(args))
    if args.compile_only:
        return
    # Start a fresh process with the fixture system roots for positive cases.
    # Negative cases use the normal device store. The bind mounts are private
    # to the helper process and its descendants.
    ndk = ndk_prebuilt() / "bin"
    arch = PackageTarget.parse(args.target).architecture
    helper = args.output / "trust-root"
    subprocess.run(
        [
            ndk / f"{arch}-linux-android29-clang",
            "-Wall",
            "-Wextra",
            "-Werror",
            FIXTURES / "AndroidTrustRoot.c",
            "-o",
            helper,
        ],
        check=True,
    )
    classes = args.output / "classes"
    classes.mkdir(exist_ok=True)
    subprocess.run(
        ["javac", "--release", "8", "-d", classes, FIXTURES / "AndroidHTTPS.java", FIXTURES / "AndroidHTTPSLocal.java"],
        check=True,
    )
    dex = args.output / "driver.jar"
    subprocess.run(
        [args.d8, "--min-api", "29", "--output", dex, *sorted(classes.glob("AndroidHTTPS*.class"))], check=True
    )

    def adb(*arguments, **kwargs):
        return subprocess.run(["adb", "-s", args.serial, *arguments], check=True, **kwargs)

    if adb("shell", "id", "-u", text=True, capture_output=True).stdout.strip() != "0":
        adb("root")
        adb("wait-for-device", timeout=60)
    if adb("shell", "id", "-u", text=True, capture_output=True).stdout.strip() != "0":
        raise RuntimeError("this qualifier requires a rootable disposable AVD for private test trust mounts")
    directory = "/data/local/tmp/btrc-https-" + uuid.uuid4().hex
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(args.cert, args.key)
    with ExitStack() as stack:
        adb("shell", "mkdir", directory)
        stack.callback(adb, "shell", "rm", "-rf", directory)
        android_ca_hash = subprocess.check_output(
            ["openssl", "x509", "-in", args.cert, "-subject_hash_old", "-noout"], text=True
        ).strip()
        assert len(android_ca_hash) == 8 and all(c in "0123456789abcdef" for c in android_ca_hash)
        adb("shell", "mkdir", directory + "/platform")
        adb("push", args.cert, f"{directory}/platform/{android_ca_hash}.0")
        adb("push", helper, directory + "/trust-root")
        adb("shell", "chmod", "755", directory + "/trust-root")
        adb("push", args.cert, directory + "/test.pem")
        adb("push", dex, directory + "/driver.jar")
        adb("shell", "chmod", "444", directory + "/driver.jar")
        if args.local_trust_only:
            der = args.output / "server-key.der"
            subprocess.run(
                ["openssl", "pkcs8", "-topk8", "-nocrypt", "-in", args.key, "-outform", "DER", "-out", der], check=True
            )
            adb("push", der, directory + "/key.der")
            for library in libraries:
                adb("push", library, directory + "/" + library.name)
                for mode in ("rejected", "trusted"):
                    command = [
                        "/system/bin/env",
                        "PATH=/no-curl",
                        "no_proxy=*",
                        "CURL_CA_BUNDLE=",
                        "SSL_CERT_FILE=",
                        "SSL_CERT_DIR=",
                        "CLASSPATH=" + directory + "/driver.jar",
                        "/system/bin/app_process",
                        "-Xcheck:jni",
                        "/system/bin",
                        "AndroidHTTPSLocal",
                        directory + "/" + library.name,
                        directory + "/test.pem",
                        directory + "/key.der",
                        mode,
                    ]
                    if mode == "trusted":
                        command = [directory + "/trust-root", directory + "/platform", *command]
                    result = adb("shell", shlex.join(command), text=True, capture_output=True, timeout=45)
                    assert result.returncode == 0 and result.stdout.splitlines() == [
                        f"PASS isolated {mode} platform trust"
                    ], result
                    assert "JNI DETECTED ERROR" not in result.stderr, result
                    print(f"{library.name}: {result.stdout.strip()}", flush=True)
            return
        server = stack.enter_context(http.server.ThreadingHTTPServer(("127.0.0.1", 0), Peer))
        proxy = stack.enter_context(http.server.ThreadingHTTPServer(("127.0.0.1", 0), ConnectPeer))
        tunnel = stack.enter_context(http.server.ThreadingHTTPServer(("127.0.0.1", 0), ConnectPeer))
        tunnel.socket = tls.wrap_socket(tunnel.socket, server_side=True)
        tunnel.origin = server.server_address
        tunnel.tunnels = []
        tunnel.require_credentials = True
        forward_peer = stack.enter_context(http.server.ThreadingHTTPServer(("127.0.0.1", 0), ForwardPeer))
        forward_peer.socket = tls.wrap_socket(forward_peer.socket, server_side=True)
        forward_peer.requests = []
        server.socket = tls.wrap_socket(server.socket, server_side=True)
        server.leaked_proxy_credentials = False
        server.cookie_requests = []
        server.challenges = []
        proxy.origin = server.server_address
        proxy.tunnels = []
        proxy.require_credentials = False
        clear = stack.enter_context(http.server.ThreadingHTTPServer(("127.0.0.1", 0), Peer))
        clear.challenges = []
        clear.leaked_proxy_credentials = False
        socks = stack.enter_context(socketserver.ThreadingTCPServer(("127.0.0.1", 0), SocksPeer))
        socks.observed = []
        for peer in (server, proxy, forward_peer, tunnel, clear, socks):
            thread = threading.Thread(target=peer.serve_forever, daemon=True)
            thread.start()
            stack.callback(thread.join)
            stack.callback(peer.shutdown)

        def forward(local):
            # platform-tools 37.0.1's adb server aborts on reverse connections
            # registered via tcp:0; bind an explicit remote port instead.
            for offset in range(16):
                remote = 10000 + ((local + offset - 10000) % 50000)
                attempt = subprocess.run(
                    ["adb", "-s", args.serial, "reverse", f"tcp:{remote}", f"tcp:{local}"],
                    capture_output=True,
                    text=True,
                )
                if attempt.returncode == 0:
                    port = str(remote)
                    stack.callback(adb, "reverse", "--remove", "tcp:" + port)
                    return port
            raise RuntimeError(f"could not reserve adb reverse port for local tcp:{local}")

        port = forward(server.server_port)
        proxy_port = forward(proxy.server_port)
        forward_port = forward(forward_peer.server_port)
        tunnel_port = forward(tunnel.server_port)
        socks_port = forward(socks.server_address[1])
        listing = adb(
            "shell",
            "for path in /apex/com.android.conscrypt/cacerts/* /system/etc/security/cacerts/*; "
            'do if [ -f "$path" ]; then echo "$path"; break; fi; done',
            capture_output=True,
            text=True,
        ).stdout.strip()
        if not listing:
            raise RuntimeError("the Android system trust store contains no control certificate")
        system_ca = directory + "/unrelated.pem"
        adb("shell", "cp", listing, system_ca)
        proxy.authorities = {f"localhost:{port}", f"127.0.0.1:{port}"}
        tunnel.authorities = proxy.authorities
        ca_hash = subprocess.check_output(
            ["openssl", "x509", "-in", args.cert, "-subject_hash", "-noout"], text=True
        ).strip()
        assert len(ca_hash) == 8 and all(c in "0123456789abcdef" for c in ca_hash)
        for name, filename in (("indexed", ca_hash + ".0"), ("raw", "ca.pem"), ("gap", ca_hash + ".1")):
            adb("shell", "mkdir", directory + "/" + name)
            adb("push", args.cert, directory + "/" + name + "/" + filename)
        adb("shell", "mkdir", directory + "/empty", directory + "/dir-multi", directory + "/tmp")
        unrelated_pem = adb("shell", "cat", system_ca, capture_output=True, text=True).stdout
        cert_pem = args.cert.read_text(encoding="ascii")
        multi_local = args.output / "multi.pem"
        multi_local.write_text("# comment header\n" + unrelated_pem + "\n" + cert_pem.rstrip("\r\n"), encoding="ascii")
        adb("push", multi_local, directory + "/multi.pem")
        dir_multi_local = args.output / "dir-multi.pem"
        dir_multi_local.write_text(unrelated_pem + "\n" + cert_pem, encoding="ascii")
        adb("push", dir_multi_local, f"{directory}/dir-multi/{ca_hash}.0")
        trusted_aux_local = args.output / "trusted-aux.pem"
        trusted_aux_local.write_text(cert_pem.replace("CERTIFICATE-----", "TRUSTED CERTIFICATE-----"), encoding="ascii")
        adb("push", trusted_aux_local, directory + "/trusted-aux.pem")
        # Place an executable curl stand-in on PATH returning status 218.
        # Android HTTPClient must never invoke it on any route.
        marker = args.output / "curl"
        marker.write_text(
            "#!/system/bin/sh\n/system/bin/toybox printf '\\n__BTRC_HTTP_STATUS__:218'\n", encoding="ascii"
        )
        adb("push", marker, directory + "/curl")
        adb("shell", "chmod", "755", directory + "/curl")
        for standalone in standalones:
            remote_bin = directory + "/" + standalone.name
            adb("push", standalone, remote_bin)
            adb("shell", "chmod", "755", remote_bin)
            result = adb(
                "shell",
                shlex.join(
                    [
                        "/system/bin/env",
                        "PATH=" + directory + ":/system/bin",
                        "TMPDIR=" + directory + "/tmp",
                        remote_bin,
                    ]
                ),
                text=True,
                capture_output=True,
                timeout=45,
            )
            assert result.returncode == 0 and result.stdout.splitlines() == ["PASS: test_stdlib_http_client_local"], (
                result
            )
            print(f"{standalone.name} on {args.target}: standalone zero-curl refusal passed", flush=True)
        for library in libraries:
            adb("push", library, directory + "/" + library.name)
            for mode in (
                "challenge",
                "bypass",
                "proxy",
                "cookies",
                "isolated",
                "isolated-proxy",
                "authenticated-proxy",
                "system-proxy",
                "system-bypass",
                "system-stalled",
                "untrusted",
                "ambient-origin",
                "ambient-proxy",
                "ambient-proxy-dir",
                "bundle-file",
                "bundle-multi",
                "bundle-curl",
                "bundle-curl-dir",
                "bundle-invalid",
                "bundle-trusted-aux-invalid",
                "bundle-indexed",
                "dir-only",
                "dir-multi",
                "dir-only-raw-invalid",
                "dir-only-gap-invalid",
                "dir-only-missing-invalid",
                "dir-only-empty-invalid",
                "installed-curl",
                "installed-header",
                "explicit-direct",
                "explicit-proxy",
                "bundle-raw-invalid",
                "bundle-gap-invalid",
                "nested-valid",
                "nested-bad-proxy",
                "nested-bad-root",
                "nested-records",
                "forward-valid",
                "forward-bad-host",
            ):
                proxy.require_credentials = mode == "authenticated-proxy"
                proxy.expected_proxy_header = (
                    "Bearer caller" if mode in {"explicit-proxy", "installed-header"} else None
                )
                proxy.interim = mode in {"system-proxy", "explicit-proxy", "installed-header"}
                credentials = "user:pass@" if proxy.require_credentials else ""
                bypass = (
                    ""
                    if mode
                    in {
                        "proxy",
                        "isolated-proxy",
                        "authenticated-proxy",
                        "system-proxy",
                        "system-stalled",
                        "explicit-proxy",
                        "installed-header",
                    }
                    else "*"
                )
                before = len(proxy.tunnels)
                ca_file = directory + "/test.pem"
                missing = directory + "/missing.pem"
                proxy_host = "127.0.0.1" if mode == "forward-bad-host" else "localhost"
                if mode.startswith("forward-"):
                    bypass = ""
                before_nested = len(tunnel.tunnels)
                proxy_setting = "" if mode.startswith("system-") else f"http://{credentials}127.0.0.1:{proxy_port}"
                if mode.startswith("nested-"):
                    bypass = ""
                    proxy_host = "127.0.0.1" if mode == "nested-bad-proxy" else "localhost"
                    proxy_setting = f"https://user:pass@{proxy_host}:{tunnel_port}"
                if mode in {"ambient-proxy", "ambient-proxy-dir"}:
                    # Origin trusts its explicitly configured root. Neither the
                    # app's default nor the origin's explicit bundle/dir may
                    # authenticate the TLS proxy.
                    bypass = ""
                    proxy_setting = f"https://user:pass@localhost:{tunnel_port}"
                cert_file = {
                    "bundle-file": ca_file,
                    "bundle-multi": directory + "/multi.pem",
                    "ambient-proxy": ca_file,
                    "installed-curl": ca_file,
                    "bundle-invalid": missing,
                    "bundle-trusted-aux-invalid": directory + "/trusted-aux.pem",
                    "bundle-curl": missing,
                    "bundle-curl-dir": missing,
                    "nested-bad-root": system_ca,
                    "bundle-indexed": system_ca,
                    "bundle-raw-invalid": system_ca,
                    "bundle-gap-invalid": system_ca,
                }.get(mode, "")
                curl_bundle = {
                    "bundle-curl": ca_file,
                    "bundle-curl-dir": system_ca,
                }.get(mode, "")
                cert_dir = {
                    "bundle-indexed": directory + "/raw:" + directory + "/indexed",
                    "bundle-curl-dir": directory + "/indexed",
                    "dir-only": directory + "/raw:" + directory + "/indexed",
                    "dir-multi": directory + "/dir-multi",
                    "ambient-proxy-dir": directory + "/indexed",
                    "dir-only-raw-invalid": directory + "/raw",
                    "dir-only-gap-invalid": directory + "/gap",
                    "dir-only-missing-invalid": directory + "/no-such-dir",
                    "dir-only-empty-invalid": directory + "/empty",
                    "bundle-raw-invalid": directory + "/raw",
                    "bundle-gap-invalid": directory + "/gap",
                }.get(mode, "")
                before_forward = len(forward_peer.requests)
                command = [
                    "env",
                    "PATH=" + directory,
                    "https_proxy=" + proxy_setting,
                    "HTTPS_PROXY=",
                    "http_proxy="
                    + (f"https://user:pass@{proxy_host}:{forward_port}" if mode.startswith("forward-") else ""),
                    "all_proxy=",
                    "ALL_PROXY=",
                    "no_proxy=" + bypass,
                    "NO_PROXY=",
                    "CURL_CA_BUNDLE=" + curl_bundle,
                    "SSL_CERT_FILE=" + cert_file,
                    "SSL_CERT_DIR=" + cert_dir,
                    "CLASSPATH=" + directory + "/driver.jar",
                    "/system/bin/app_process",
                    "-Xcheck:jni",
                    "/system/bin",
                    "AndroidHTTPS",
                    directory + "/" + library.name,
                    directory + "/test.pem",
                    ("http://btrc.invalid" if mode.startswith("forward-") else f"https://localhost:{port}"),
                    f"https://127.0.0.1:{port}",
                    mode,
                    proxy_port,
                ]
                if not (mode.startswith(("ambient-", "bundle-", "dir-")) or mode in {"untrusted", "installed-curl"}):
                    command = [directory + "/trust-root", directory + "/platform", "/system/bin/env", *command[1:]]
                if mode in {"challenge", "installed-curl"}:
                    server.challenges.clear()
                result = adb("shell", shlex.join(command), text=True, capture_output=True, timeout=45)
                if mode in {"challenge", "installed-curl"}:
                    assert result.stdout.strip() == "Android challenge status 401", result
                    assert server.challenges == [False], server.challenges
                    if mode == "challenge" and args.observe_authenticator:
                        print(
                            f"{library.name} on {args.target}: {result.stdout.strip()}, Authorization absent",
                            flush=True,
                        )
                    server.challenges.clear()
                    continue
                expected = {
                    "installed-header": "Android explicit header status 204",
                    "explicit-direct": "Android explicit header status 204",
                    "explicit-proxy": "Android explicit header status 204",
                    "ambient-origin": "PASS Android HTTPS untrusted issuer",
                    "ambient-proxy": "PASS Android HTTPS untrusted issuer",
                    "ambient-proxy-dir": "PASS Android HTTPS untrusted issuer",
                    "cookies": "PASS Android HTTPS cookie isolation",
                    "system-stalled": "PASS Android HTTPS proxy deadline",
                    "untrusted": "PASS Android HTTPS untrusted issuer",
                    "bundle-invalid": "PASS Android HTTPS untrusted issuer",
                    "bundle-trusted-aux-invalid": "PASS Android HTTPS untrusted issuer",
                    "bundle-raw-invalid": "PASS Android HTTPS untrusted issuer",
                    "bundle-gap-invalid": "PASS Android HTTPS untrusted issuer",
                    "dir-only-raw-invalid": "PASS Android HTTPS untrusted issuer",
                    "dir-only-gap-invalid": "PASS Android HTTPS untrusted issuer",
                    "dir-only-missing-invalid": "PASS Android HTTPS untrusted issuer",
                    "dir-only-empty-invalid": "PASS Android HTTPS untrusted issuer",
                    "forward-bad-host": "PASS Android HTTPS untrusted issuer",
                    "forward-valid": "PASS Android HTTPS forward proxy",
                    "nested-bad-root": "PASS Android HTTPS untrusted issuer",
                    "nested-bad-proxy": "PASS Android HTTPS untrusted issuer",
                    "nested-records": "PASS Android HTTPS multi-record echo",
                }.get(mode, "PASS Android HTTPS")
                assert result.stdout.splitlines() == [expected], result
                assert not server.leaked_proxy_credentials
                assert not any(server.cookie_requests), server.cookie_requests
                assert "JNI DETECTED ERROR" not in result.stderr, result
                if mode.startswith("forward-"):
                    assert len(forward_peer.requests) - before_forward == int(mode == "forward-valid")
                if mode.startswith("nested-"):
                    if mode == "nested-bad-proxy":
                        assert len(tunnel.tunnels) == before_nested
                    else:
                        assert len(tunnel.tunnels) > before_nested
                if mode in {"ambient-proxy", "ambient-proxy-dir"}:
                    assert len(tunnel.tunnels) == before_nested
                if (
                    bypass
                    or mode in {"system-stalled", "ambient-proxy", "ambient-proxy-dir"}
                    or mode.startswith(("forward-", "nested-"))
                ):
                    assert len(proxy.tunnels) == before, proxy.tunnels[before:]
                else:
                    assert len(proxy.tunnels) > before, "no CONNECT reached the configured proxy"
            check_android_tunnels(adb, directory, library, socks, socks_port, clear, server)
            print(f"{library.name} on {args.target}: HTTPS, proxy, bypass and binary imports passed", flush=True)


if __name__ == "__main__":
    main()
