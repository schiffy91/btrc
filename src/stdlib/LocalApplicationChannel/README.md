# `Library.LocalApplicationChannel`

A bounded same-user request channel for a native application loop. The server
polls without blocking, delivers one request at a time and queues one response
per peer. The synchronous client uses one monotonic deadline for connection,
request and response.

BTRC owns the listener, endpoint identity, client descriptors, partial frames,
response buffers, byte budgets and idle expiration. A managed identity token
rejects requests from another or reopened server without retaining the server.
Endpoint cleanup checks its recorded user/device/inode; a failed bind cannot
delete a colliding file. Interrupted nonblocking I/O yields to the event loop.

The wire format is a four-byte big-endian length followed by bounded payload
bytes; empty and binary messages are valid. macOS/Linux use private-directory
Unix sockets and verify peer credentials. `Socket.h` contains SDK declarations
and a small Darwin/Linux credential-layout adapter only. Linux's `_GNU_SOURCE`
requirement belongs to the package build plan. No handwritten C implementation,
hosted channel ABI, or channel archive remains.

Both macOS frontends pass process exchange, partial/oversized/empty frames,
timeouts, stale requests, late responses, bind collisions, endpoint replacement
and descriptor cleanup, including ASan/UBSan (16 tests). Linux's reference path
passes nine channel/ABI checks with GCC, Clang and sanitizers. The naming, ABI,
build and package suite passes 117 tests. Reports are
`build/LocalChannelServerMigration.xml`, `build/LocalChannelServerLinux.xml` and
`build/LocalChannelServerFinalHygiene.xml`. Windows explicit-unsupported provider
selection and Linux self-hosted qualification remain open.
