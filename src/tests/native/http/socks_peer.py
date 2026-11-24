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
    cases = (
        ("socks4", "127.0.0.1", 1, False, False),
        ("socks4a", "origin-only.invalid", 3, True, False),
        ("socks5", "[::1]", 4, True, False),
        ("socks5h", "origin-only.invalid", 3, True, False),
        ("socks5h", "localhost", 3, True, True),
        ("system-socks", "localhost", 3, False, True),
    )
    for scheme, host, address_type, auth, tls in cases:
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
            "PATH=/no-curl",
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
            "system-socks" if scheme == "system-socks" else "challenge",
            str(socks_port),
        ]
        result = adb("shell", shlex.join(command), text=True, capture_output=True, timeout=45)
        assert result.stdout.strip() == "Android challenge status 401", result
        assert "JNI DETECTED ERROR" not in result.stderr, result
        version = 4 if scheme.startswith("socks4") else 5
        credentials = (b"u:s" if auth else b"") if version == 4 else ((b"u:s", b"p+w") if auth else None)
        assert socks.observed[before:] == [(version, address_type, host.strip("[]"), 43210, credentials)]
        assert peer.challenges == [False] and not peer.leaked_proxy_credentials
