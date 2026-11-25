# DBus

A first-party D-Bus client. It speaks the wire protocol of the
[D-Bus specification](https://dbus.freedesktop.org/doc/dbus-specification.html)
to the bus daemon's socket and links no D-Bus library: on Linux what the
system supplies is the kernel and the C library, and a system service is
reached over its socket by code in this tree.

It exists for the stdlib's own Linux providers. `Tray/Linux/LinuxTray.btrc`
serves a StatusNotifierItem and its menu on the session bus with it, and
`Bluetooth/Linux/BluetoothAdapterProvider.btrc` drives BlueZ on the system
bus. It is exported so those groups can import it, and it is a general
client, but it carries only what they need: a client connection to a message
bus, with no server side, no peer-to-peer listener and no object tree.

## Modules

| Module | What it holds |
| --- | --- |
| `DBusAddress` | Server addresses: parsing, escaping, where the session and system buses are. |
| `DBusMessage` | `DBusMessage`, `DBusWriter` and `DBusReader`: a message's header fields and the marshalling of its body. |
| `DBusConnection` | A registered connection to a bus: authentication, Hello, sending, calling, receiving. |
| `DBus` | The facade: imports the three. |

`DBusWire` is private: the type alignments, the signature and name syntax,
the limits and the one walker that validates a marshalled value against its
signature. `Linux/DBusTransportProvider` is the transport,
selected by `[[package.providers]]`. Linux provides close-on-exec sockets
with nonblocking reads and writes. `DBusAddress` and `DBusMessage` also
compile on the other targets.

## Finding and joining a bus

`DBusConnection.session()` first honors `DBUS_SESSION_BUS_ADDRESS`, then
tries the user's socket at `$XDG_RUNTIME_DIR/bus`. A legacy X11 session can
also advertise an address in `~/.dbus/session-bus/<machine-id>-<display>`,
which `autolaunch:` reads directly when `DISPLAY` is set. `Library.DBus`
never spawns `dbus-launch`. `DBusConnection.system()` honors
`DBUS_SYSTEM_BUS_ADDRESS` and defaults to `/var/run/dbus/system_bus_socket`.

An address list is tried in order. The client supports Unix filesystem and
abstract sockets, `unix:runtime=yes`, `tcp`, `nonce-tcp`, the caller's
`unixexec` transport command and X11 `autolaunch:`. An explicit bus GUID
must match the authenticated peer. Remote sockets use the system resolver
and can specify IPv4 or IPv6. A helper's arguments are passed directly.

On a local socket the client offers `EXTERNAL` with its effective user ID,
then negotiates Unix descriptor passing. Buses that advertise
`DBUS_COOKIE_SHA1` can authenticate using the user's private keyring.
Anonymous authentication requires the bus to advertise that mechanism.
A connection joins the bus by calling `org.freedesktop.DBus.Hello`.

## Using a connection

The connection is pulled; nothing calls back.

```
DBusConnection? opened = DBusConnection.session();
if (opened == null) { throw "No D-Bus session bus"; }
DBusConnection bus = opened;

DBusMessage request = DBusMessage.methodCall("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "GetNameOwner");
request.writer().appendString("org.example.Service");
DBusMessage? reply = bus.call(request, 2000);   // null: bus.lastError() names why
```

- `send` gives a message its serial and writes it whole.
- `call` sends a method call and waits for its reply; it returns null on a
  timeout, a closed connection or an error reply, and `lastError` is then the
  error's name (`org.freedesktop.DBus.Error.NoReply`, `...Disconnected`, or
  what the peer answered). `exchange` returns the error reply itself. Messages
  that arrive while a call waits stay queued in order.
- `readWrite(timeout)` waits for the bus to send something and reads it into
  the queue; it does not wait when messages are already queued, and returns
  false once the connection is closed. `popMessage` hands over the oldest
  queued message. `descriptor` is the socket, for a caller that polls several
  things.
- `requestName`, `ownName` (do-not-queue) and `addMatch` are the bus calls
  the providers need.

A message is built by `DBusMessage.methodCall`, `methodReturn`, `error` or
`signal` and filled through `writer()`. Containers open from the writer they
go into and close on the writer that came back:

```
DBusMessage reply = DBusMessage.methodReturn(call);
DBusWriter dictionary = reply.writer().openArray("{sv}");
dictionary.dictString("Title", title);
DBusWriter entry = dictionary.openEntry("Size");
DBusWriter variant = entry.openVariant("(ii)");
DBusWriter size = variant.openStruct();
size.appendInt32(width);
size.appendInt32(height);
size.close();
variant.close();
entry.close();
dictionary.close();
bus.send(reply);
```

A received message is walked with `reader()`: `type` says what the reader
stands on, a `read` method returns it (the zero of the type asked for when it
stands on something else), `recurse` opens a container and `next` moves on.

The writer throws on what would make a message a bus refuses, since a bus
answers such a message by dropping the connection: text that is not UTF-8, a
malformed object path or signature, a value that does not match the type its
array or variant was opened for, an empty struct, a name the protocol does
not allow. Messages are marshalled little-endian.

## What a peer can and cannot do

Nothing received is trusted. A message is read into an allocation of exactly
its declared size and parsed whole before any of it is queued. The parser
accepts both byte orders and checks, before reading each: every length and
offset against the end of what encloses it, alignment padding (which must be
zero), each string's terminator and UTF-8, object-path and signature syntax,
boolean values, the header's required fields and name syntax, and that the
body is exactly what its signature describes.

| Limit | Value |
| --- | --- |
| One message, sent or received | 128 MiB (the specification limit) |
| One array's elements | 64 MiB (the specification limit) |
| Unix descriptors attached to a message | 16 |
| A signature | 255 bytes |
| Array, struct and dict-entry nesting in a signature | 32 each |
| Container nesting in a body, variants included | 64 |
| Unpopped messages | 63 MiB of wire bytes or 4,096 descriptors; reading pauses until some are popped |

A malformed or oversized message closes the
connection; so does a failed or timed-out write, because a half-written
message cannot be taken back. A closed connection stays closed. A message of
a type the client does not know is dropped, as the specification asks.

A received value of type `h` names a descriptor installed by the kernel.
`DBusReader.readUnixFD()` borrows it for the lifetime of the message. The
reader validates the attached descriptor count and every referenced index.

## Tests

`src/tests/python/test_dbus_runtime.py` builds the programs in
`src/tests/native/dbus` through both compilers. `DBusConformance` runs
against a private `dbus-daemon`: addresses, the codec, Hello, RequestName,
ListNames, GetNameOwner, AddMatch and NameOwnerChanged, error replies,
timeouts, and every type between two connections of this client.
`DBusMalformed` feeds the parser truncated, corrupted and hand-broken frames
under AddressSanitizer and UndefinedBehaviorSanitizer. `DBusEcho` is driven
by other implementations: GDBus in both byte orders, and libdbus's
`dbus-send` and `dbus-monitor`.
