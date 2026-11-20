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

`setKeepAlive` turns probing of an idle connection on; `setKeepAliveTiming`
sets its pace (first probe, interval, how many may go unanswered), where a
system's own takes hours to notice a dead peer. `setUnacknowledgedTimeout`
drops a connection whose sent data stays unacknowledged, so a write to a peer
that is gone fails.

`Sockets.h` holds the SDK includes and two small functions for those options,
whose names differ between Linux and Apple's systems. The typed binding imports
them and what the hosted ABI does not carry: `getaddrinfo`, `freeaddrinfo`,
`addrinfo` and `TCP_NODELAY`. glibc declares the resolver only under a feature macro, so the
manifest defines `_GNU_SOURCE` on Linux.

Linux, macOS, iOS and iPadOS have rows. Windows has no provider yet (HTTP's
Winsock seam is the model); Android has BSD sockets but no row spells them.
IPv6 is not covered.

`src/tests/python/test_network_runtime.py` runs
`src/tests/native/network/NetworkConformance.btrc` through both frontends with
gcc, clang and the sanitizers: a listener the system gives a port, streams in
both directions, deadlines, half-close, a peer that goes away, the resolver,
and a megabyte through a forked echo peer. `src/tests/python/test_stdlib_ios_programs.py`
runs the same program as a process of an iPhone and an iPad simulator.
`src/tests/stdlib/NetworkAddress.btrc` covers the address values on every target.
