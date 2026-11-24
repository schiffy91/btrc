"""A local SOCKS4/5 test peer that can tunnel only to its configured fixture."""

import ipaddress
import select
import socket
import socketserver


class SocksPeer(socketserver.StreamRequestHandler):
    def take(self, size):
        data = self.rfile.read(size)
        if len(data) != size:
            raise EOFError("incomplete SOCKS request")
        return data

    def cstring(self):
        data = bytearray()
        while len(data) <= 65536:
            byte = self.take(1)
            if byte == b"\0":
                return bytes(data)
            data.extend(byte)
        raise ValueError("long SOCKS4 string")

    def address(self, version):
        credentials = None
        if version == 5:
            methods = self.take(self.take(1)[0])
            method = 2 if self.server.require_auth else 0
            self.wfile.write(bytes([5, method if method in methods else 255]))
            if method not in methods:
                return None
            if method == 2:
                if self.take(1) != b"\1":
                    raise ValueError("invalid SOCKS5 auth version")
                credentials = self.take(self.take(1)[0]), self.take(self.take(1)[0])
                valid = credentials == (b"u:s", b"p+w")
                self.wfile.write(bytes([1, int(not valid)]))
                if not valid:
                    return None
            if self.take(3) != b"\5\1\0":
                raise ValueError("expected SOCKS5 CONNECT")
            kind = self.take(1)[0]
            if kind == 3:
                host = self.take(self.take(1)[0]).decode("ascii")
            else:
                host = str(ipaddress.ip_address(self.take({1: 4, 4: 16}[kind])))
            port = int.from_bytes(self.take(2), "big")
        elif version == 4:
            if self.take(1) != b"\1":
                raise ValueError("expected SOCKS4 CONNECT")
            port = int.from_bytes(self.take(2), "big")
            address = self.take(4)
            credentials = self.cstring()
            host = (
                self.cstring().decode("ascii")
                if address[:3] == bytes(3) and address[3]
                else str(ipaddress.ip_address(address))
            )
            kind = 3 if address[:3] == bytes(3) and address[3] else 1
        else:
            raise ValueError("unexpected SOCKS version")
        return kind, host, port, credentials

    def handle(self):
        try:
            self.request.settimeout(12)
            version = self.take(1)[0]
            address = self.address(version)
            if address is None:
                return
            self.server.observed.append((version, *address))
            # The requested hostname never determines the upstream address.
            with socket.create_connection(self.server.origin, timeout=5) as upstream:
                self.wfile.write(b"\5\0\0\3\3abc\0\1" if version == 5 else b"\0\x5a" + bytes(6))
                while True:
                    ready, _, _ = select.select([self.request, upstream], [], [], 15)
                    if not ready:
                        return
                    for src in ready:
                        block = src.recv(65536)
                        if not block:
                            return
                        (upstream if src is self.request else self.request).sendall(block)
        except (EOFError, BrokenPipeError, ConnectionResetError):
            return


def check_android_tunnels(adb, directory, library, socks, socks_port, clear, secure):
    import shlex

    # Names resolved on the proxy need not exist in the client's DNS.
    # PATH points at the fixture directory containing the fake curl marker so
    # any accidental curl launch returns 218 and fails immediately.
    cases = (
        ("socks4", "127.0.0.1", {(1, "127.0.0.1")}, False, False, "challenge"),
        ("socks4", "localhost", {(1, "127.0.0.1")}, False, True, "challenge"),
        ("socks4a", "origin-only.invalid", {(3, "origin-only.invalid")}, True, False, "challenge"),
        ("socks4a", "localhost", {(3, "localhost")}, True, True, "challenge"),
        ("socks5", "[::1]", {(4, "::1")}, True, False, "challenge"),
        ("socks5", "localhost", {(1, "127.0.0.1"), (4, "::1")}, True, True, "challenge"),
        ("socks5h", "origin-only.invalid", {(3, "origin-only.invalid")}, True, False, "challenge"),
        ("socks5h", "localhost", {(3, "localhost")}, True, True, "challenge"),
        ("socks5h", "origin-only.invalid", {(3, "origin-only.invalid")}, True, False, "explicit-header"),
        ("socks5h", "localhost", {(3, "localhost")}, True, True, "explicit-header"),
        ("system-socks", "localhost", {(3, "localhost")}, False, True, "system-socks"),
    )
    for scheme, host, expected_targets, auth, tls, probe_mode in cases:
        peer = secure if tls else clear
        socks.require_auth = auth
        socks.origin = peer.server_address
        user = "u%3As:p%2Bw@" if auth else ""
        setting = "" if scheme == "system-socks" else f"{scheme}://{user}127.0.0.1:{socks_port}"
        origin = f"{'https' if tls else 'http'}://{host}:43210"
        before = len(socks.observed)
        peer.challenges.clear()
        command = [
            directory + "/trust-root",
            directory + "/platform",
            "/system/bin/env",
            "PATH=" + directory,
            "no_proxy=",
            "NO_PROXY=",
            "http_proxy=" + setting,
            "https_proxy=" + setting,
            "HTTPS_PROXY=",
            "all_proxy=",
            "ALL_PROXY=",
            "SSL_CERT_FILE=",
            "CURL_CA_BUNDLE=",
            "SSL_CERT_DIR=",
            "CLASSPATH=" + directory + "/driver.jar",
            "/system/bin/app_process",
            "-Xcheck:jni",
            "/system/bin",
            "AndroidHTTPS",
            directory + "/" + library.name,
            directory + "/test.pem",
            origin,
            origin,
            probe_mode,
            str(socks_port),
        ]
        result = adb("shell", shlex.join(command), text=True, capture_output=True, timeout=45)
        expected_line = (
            "Android explicit header status 204" if probe_mode == "explicit-header" else "Android challenge status 401"
        )
        assert result.stdout.strip() == expected_line, result
        assert "JNI DETECTED ERROR" not in result.stderr, result
        version = 4 if scheme.startswith("socks4") else 5
        credentials = (b"u:s" if auth else b"") if version == 4 else ((b"u:s", b"p+w") if auth else None)
        observed = socks.observed[before:]
        assert len(observed) == 1, observed
        obs_ver, obs_kind, obs_host, obs_port, obs_creds = observed[0]
        assert (obs_ver, obs_port, obs_creds) == (version, 43210, credentials), observed[0]
        assert (obs_kind, obs_host) in expected_targets, observed[0]
        if probe_mode != "explicit-header":
            assert peer.challenges == [False]
            peer.challenges.clear()
        assert not peer.leaked_proxy_credentials
