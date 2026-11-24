"""Exercise HTTPClient with a local forward proxy, bypass rules and a stalled resolver."""

import http.server
import os
import socketserver
import subprocess
import sys
import threading

import pytest

from src.compiler.python.frontend.packages import PackageTarget
from src.tests.c_toolchains import configured_c_compiler
from src.tests.native.http.socks_peer import SocksPeer
from src.tests.native_build import NativeCorpusBuild
from src.tests.native_targets import stub_sysroot
from tools.native_plan import NativePlanError, TargetToolchain
from tools.qualification.dependencies import STDLIB, DependencyAudit

PROBE = """import Library.HTTP.HTTPClient;
import Library.Platform;
import Library.Vector;

int main() {
    Vector<string> fields = [];
    if (Environment.has("TEST_HEADER")) { fields.push(Environment.get("TEST_HEADER", "")); }
    HTTPClientResponse result = HTTPClient().timeout(1).get(Environment.get("TEST_URL", ""), fields);
    print(f"{result.status}|{result.body}|{result.error}");
    return 0;
}
"""

# Linked into a second copy of the same public client. If the calling thread
# ever waits for this resolver, the outer test times out.
SLOW_RESOLVER = """#define _POSIX_C_SOURCE 200809L
#include <netdb.h>
#include <unistd.h>

int getaddrinfo(const char *name, const char *service, const struct addrinfo *hints, struct addrinfo **found) {
    (void)name;
    (void)service;
    (void)hints;
    *found = NULL;
    sleep(30);
    return EAI_AGAIN;
}
"""


class RoutingPeer(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        fields = (self.path, self.headers["Host"], self.headers.get("Proxy-Authorization", ""))
        if self.path == "/socks":
            fields += (self.headers.get("Authorization", ""),)
        body = "|".join(fields).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


def test_public_http_proxy_bypass_and_resolver_deadline(compiler, request, tmp_path, monkeypatch):
    if sys.platform not in {"linux", "darwin"}:
        pytest.skip("requires the desktop BSD socket HTTP provider")
    # Build with no pkg-config modules, including libcurl and its resolver.
    modules = tmp_path / "pkgconfig"
    modules.mkdir()
    monkeypatch.setenv("PKG_CONFIG_LIBDIR", str(modules))
    monkeypatch.delenv("PKG_CONFIG_PATH", raising=False)
    source = tmp_path / "RouteProbe.btrc"
    source.write_text(PROBE)
    frontend = (
        [sys.executable, "-m", "src.compiler.python.main"]
        if compiler == "python"
        else [str(request.getfixturevalue("immutable_btrcc"))]
    )
    artifact = NativeCorpusBuild(tmp_path / "route.c", tmp_path / "route.json", tuple(frontend))
    subprocess.run(
        [
            *frontend,
            str(source),
            "--strict-imports",
            "-o",
            str(artifact.primary),
            "--emit-link-plan",
            str(artifact.plan),
        ],
        check=True,
        timeout=120,
    )
    cc = configured_c_compiler()
    if sys.platform == "darwin" and cc == ["cc"]:
        cc = ["clang"]
    program = tmp_path / "route"
    artifact.build(program, cc=cc)
    assert DependencyAudit().binary_problems(program, PackageTarget.parse(None).label) == []
    empty_path = tmp_path / "empty-path"
    empty_path.mkdir()
    environment = {
        k: v for k, v in os.environ.items() if k.lower() not in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}
    }
    environment["PATH"] = str(empty_path)

    def run(executable, **settings):
        result = subprocess.run(
            [str(executable)], env={**environment, **settings}, capture_output=True, text=True, timeout=6, check=True
        )
        return result.stdout.strip()

    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), RoutingPeer) as peer:
        serving = threading.Thread(target=peer.serve_forever)
        serving.start()
        try:
            endpoint = f"127.0.0.1:{peer.server_port}"
            proxy = f"http://user:pass@{endpoint}"
            target = "http://unresolvable.invalid/test?q=1"
            assert run(program, TEST_URL=target, http_proxy=proxy) == (
                f"200|{target}|unresolvable.invalid|Basic dXNlcjpwYXNz|"
            )
            for host, rule in (("127.0.0.1", "127.0.0.0/8"), ("localhost", ".localhost"), ("localhost", "*")):
                authority = f"{host}:{peer.server_port}"
                assert run(program, TEST_URL=f"http://{authority}/direct", all_proxy=proxy, NO_PROXY=rule) == (
                    f"200|/direct|{authority}||"
                )
            assert run(program, TEST_URL=f"http://{endpoint}/direct", HTTP_PROXY=proxy) == f"200|/direct|{endpoint}||"
            check_socks(program, run, peer, tmp_path)
        finally:
            peer.shutdown()
            serving.join()

    slow_source = tmp_path / "slow.c"
    slow_object = tmp_path / "slow.o"
    slow_source.write_text(SLOW_RESOLVER)
    subprocess.run([*cc, "-std=c11", "-c", str(slow_source), "-o", str(slow_object)], check=True, timeout=60)
    slow_client = tmp_path / "slow"
    artifact.build(slow_client, cc=cc, link_flags=[str(slow_object)])
    assert run(slow_client, TEST_URL="http://slow.invalid/") == "0||request timed out"


def check_socks(program, run, origin, directory):
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), SocksPeer) as proxy:
        proxy.daemon_threads = True
        proxy.origin = origin.server_address
        proxy.observed = []
        serving = threading.Thread(target=proxy.serve_forever, daemon=True)
        serving.start()
        endpoint = f"127.0.0.1:{proxy.server_address[1]}"
        header = "Proxy-Authorization: Bearer caller"
        try:
            for scheme, host, auth, version, kind, address, credentials in (
                ("socks4", "127.0.0.1", False, 4, 1, "127.0.0.1", b""),
                ("socks4a", "proxy-only.invalid", True, 4, 3, "proxy-only.invalid", b"u:s"),
                ("socks5", "[::1]", True, 5, 4, "::1", (b"u:s", b"p+w")),
                ("socks5h", "proxy-only.invalid", True, 5, 3, "proxy-only.invalid", (b"u:s", b"p+w")),
            ):
                proxy.require_auth = auth
                authority = f"{host}:54321"
                user = "u%3As:p%2Bw@" if auth else ""
                result = run(
                    program,
                    TEST_URL=f"http://user:ori@{authority}/socks",
                    TEST_HEADER=header,
                    http_proxy=f"{scheme}://{user}{endpoint}",
                )
                assert result == f"200|/socks|{authority}||Basic dXNlcjpvcmk=|"
                assert proxy.observed[-1] == (version, kind, address, 54321, credentials)
            proxy.require_auth = True
            target = "http://proxy-only.invalid:54321/socks"
            assert run(program, TEST_URL=target, http_proxy=f"socks5h://{endpoint}") == "0||SOCKS connection failed"
            # Linux has retired curl completely: SOCKS4/5 and explicit Proxy-Authorization
            # stay first-party even when a curl executable exists on PATH.
            fake = directory / "curl"
            fake.write_text("#!/bin/sh\nexit 42\n")
            fake.chmod(0o755)
            assert (
                run(program, TEST_URL=target, http_proxy=f"socks4a://{endpoint}", PATH=str(directory))
                == "200|/socks|proxy-only.invalid:54321|||"
            )
            assert (
                run(
                    program,
                    TEST_URL=target,
                    TEST_HEADER=header,
                    http_proxy=f"socks4a://{endpoint}",
                    PATH=str(directory),
                )
                == "200|/socks|proxy-only.invalid:54321|||"
            )
            assert (
                run(
                    program,
                    TEST_URL=target,
                    TEST_HEADER=header,
                    http_proxy=f"socks5h://u%3As:p%2Bw@{endpoint}",
                    PATH=str(directory),
                )
                == "200|/socks|proxy-only.invalid:54321|||"
            )
            assert (
                run(program, TEST_URL=target, http_proxy=f"socks5h://{endpoint}", PATH=str(directory))
                == "0||SOCKS connection failed"
            )
        finally:
            proxy.shutdown()
            serving.join()


def test_android_http_client_policy_and_reachability():
    """Android HTTPClient never reaches HTTPCurlTransport and has zero curl dependency findings."""
    audit = DependencyAudit()
    curl_module = (STDLIB / "HTTP" / "HTTPCurlTransport.btrc").resolve()
    for android_target in ("android-aarch64", "android-x86_64"):
        assert curl_module not in audit._reachable(android_target)
    android_curl = [
        item for item in audit.third_party() if item.operating_system == "android" and item.dependency == "curl"
    ]
    assert android_curl == []


JNI_STUB = """typedef int jint;
typedef jint jsize;
typedef unsigned short jchar;
typedef void *jobject;
typedef jobject jclass;
typedef jobject jstring;
typedef struct _jmethodID *jmethodID;
typedef struct _jfieldID *jfieldID;
typedef struct JNIEnv_ JNIEnv;
typedef struct JavaVM_ JavaVM;
typedef struct { char *name; char *signature; void *fnPtr; } JNINativeMethod;
"""


@pytest.mark.parametrize("android_target", ["android-aarch64", "android-x86_64"])
def test_android_http_client_never_references_curl(compiler, request, tmp_path, monkeypatch, android_target):
    """Cross-compile HTTPClient for Android and prove curl/HTTPCurlTransport are absent in C and ELF."""
    target = PackageTarget.parse(android_target)
    have_ndk = True
    try:
        sysroot = TargetToolchain(target.row).sysroot()
    except NativePlanError:
        have_ndk = False
        sysroot = tmp_path / f"sysroot-{android_target}"
        stub_sysroot(sysroot, android_target)
        (sysroot / "usr" / "include" / "jni.h").write_text(JNI_STUB, encoding="utf-8")
    monkeypatch.setenv("BTRC_NATIVE_TARGET", target.row.triple)
    monkeypatch.setenv("BTRC_NATIVE_SYSROOT", str(sysroot))
    source = tmp_path / "AndroidRouteProbe.btrc"
    source.write_text(PROBE)
    frontend = (
        [sys.executable, "-m", "src.compiler.python.main"]
        if compiler == "python"
        else [str(request.getfixturevalue("immutable_btrcc"))]
    )
    artifact = NativeCorpusBuild(tmp_path / f"{android_target}.c", tmp_path / f"{android_target}.json", tuple(frontend))
    subprocess.run(
        [
            *frontend,
            str(source),
            "--target",
            android_target,
            "--strict-imports",
            "-o",
            str(artifact.primary),
            "--emit-link-plan",
            str(artifact.plan),
        ],
        check=True,
        timeout=120,
    )
    generated = artifact.primary.read_text(encoding="utf-8")
    for forbidden in ("HTTPCurlTransport", "__BTRC_HTTP_STATUS__:", "--proto-redir", "ChildProcessExecutable"):
        assert forbidden not in generated, f"{android_target} emitted C still references {forbidden!r}"
    assert "btrcJSSEConnect" in generated
    assert "HTTPS on Android requires an Android application VM" in generated
    plan_text = artifact.plan.read_text(encoding="utf-8")
    for required_unit in ("JSSESocket.c", "JSSETrust.c", "JSSEEngine.c", "JSSEName.c"):
        assert required_unit in plan_text, f"{android_target} link plan missing {required_unit}"
    if have_ndk:
        executable = tmp_path / f"probe-{android_target}"
        artifact.build(executable)
        assert DependencyAudit().binary_problems(executable, android_target) == []
        raw = executable.read_bytes()
        for forbidden in (b"HTTPCurlTransport", b"__BTRC_HTTP_STATUS__:", b"--proto-redir"):
            assert forbidden not in raw, f"{android_target} ELF still contains {forbidden!r}"
