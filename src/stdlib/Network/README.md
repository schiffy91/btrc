# `Library.Network`

IPv4 addresses and TCP connections. `import Library.Network;` brings in the
whole group.

| Module | Owns |
|--------|------|
| `Library.Network.IPv4Address` | `IPv4Address` and `IPv4Network`: parsed from and printed as dotted text, compared by number. No socket code, so it builds on every target. |
| `Library.Network.TCPStream` | A connected stream that owns its socket: `connect`, `connectHost`, `resolve`, bounded `read`/`readExactly`/`write`, `finishWriting`, and `detach` to hand the socket on. |
| `Library.Network.TCPListener` | A listening socket: `listen` (port 0 lets the system choose), `port`, and `accept` with a timeout. |

Every wait takes a timeout in milliseconds and is bounded by one monotonic
deadline, however many partial reads or writes it takes. Sockets are
nonblocking and close-on-exec. Writes use `MSG_NOSIGNAL`, so a peer that went
away is a failed write and the process's `SIGPIPE` handling is never touched.
`read` returns a byte count or a `TCPStreamRead` value: closed, timed out or
failed. Failures to connect or listen throw the system's reason.

`Sockets.h` holds only SDK includes. The typed binding imports what the hosted
ABI does not carry: `getaddrinfo`, `freeaddrinfo`, `addrinfo` and
`TCP_NODELAY`. glibc declares the resolver only under a feature macro, so the
manifest defines `_GNU_SOURCE` on Linux.

Linux and macOS have rows. Windows has no provider yet (HTTP's Winsock seam is
the model); iOS and Android have BSD sockets but no row spells them. IPv6 is
not covered.

`src/tests/python/test_network_runtime.py` runs
`src/tests/native/network/NetworkConformance.btrc` through both frontends with
gcc, clang and the sanitizers: a listener the system gives a port, streams in
both directions, deadlines, half-close, a peer that goes away, the resolver,
and a megabyte through a forked echo peer. `src/tests/stdlib/NetworkAddress.btrc`
covers the address values on every target.
