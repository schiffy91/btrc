# `std.local_application_channel`

`LocalApplicationChannelServer` is a bounded, poll-driven request boundary for
one native application process. Its owner calls `poll()` from the application
loop, dispatches the returned bytes through product policy, and queues exactly
one response with `respond()`. `LocalApplicationChannelClient.request()` is the
synchronous, deadline-bounded CLI/MCP adapter.

On macOS and Linux the runtime uses a length-framed Unix-domain socket inside
an existing owner-only directory. It rejects symlink or regular-file endpoint
collisions, verifies endpoint and peer ownership, cleans only a proven stale
same-user socket, bounds peers/messages/work per poll, expires partial clients,
and removes only the endpoint inode it created. The Windows API currently
returns the explicit unsupported outcome; a named-pipe provider can implement
the same public contract without changing applications.

Importing `std.local_application_channel` adds the compiler-shipped C runtime
to the emitted native link plan. Product repositories do not include socket
headers, descriptors, framing, permissions, or platform branches.
