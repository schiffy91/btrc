# Windows compatibility layer

This directory makes the self-hosted compiler (`btrcc`) — and any btrc program —
cross-compile to Windows with `zig cc -target x86_64-windows-gnu`. It is applied
**only** to Windows builds, via the Makefile variable:

```make
WIN_COMPAT := -I src/stdlib/win -include src/stdlib/win/btrc_win_compat.h
```

POSIX (macOS/Linux) builds never add these flags, so their output is unchanged.

## Why it's needed

The btrc stdlib (`terminal`, `process`, `fs`, `http`, `regex`) is written against
POSIX. When a program is transpiled to C, those modules pull in POSIX headers.
Dead-code elimination removes the *bodies* of modules a given program doesn't
use, but an orphaned `#include <…>` line can survive even after its functions are
gone. MinGW-w64 (what `zig cc` targets) provides most of libc plus `dirent.h` and
winpthreads, but omits a handful of POSIX headers and a few symbols. This layer
fills exactly those gaps — nothing more.

## What's here

* **Missing-*file* shims** (resolved via `-I`): minimal guarded headers for the
  POSIX headers MinGW-w64 lacks but that survive as orphan `#include`s —
  `regex.h`, `fnmatch.h`, `glob.h`, `grp.h`, `poll.h`, `pwd.h`, `termios.h`,
  `sys/resource.h`, `sys/wait.h`, `sys/socket.h`, `sys/select.h`,
  `netinet/in.h`, `arpa/inet.h`. They are empty
  by design: where a program doesn't call into the module, the include only needs
  to *resolve*. If dead-code elimination retains an operation that needs one of
  those APIs, the program remains unsupported rather than linking to a fake
  implementation.
* **Missing-*symbol* compat** (`btrc_win_compat.h`, force-included): POSIX
  functions/macros MinGW omits but that the emitted C references. The supported
  adapters have explicit Windows semantics; unsupported descriptor operations
  fail with `ENOTSUP`:
  - `lstat`/`unlink` classify and remove a final directory reparse point without
    enumerating its target; Win32 failures retain precise `errno` categories
  - `open(..., O_CLOEXEC)` maps to UCRT's non-inheritable descriptor flag;
    unsupported `O_NOFOLLOW`/`O_DIRECTORY` requests fail with `ENOTSUP` instead
    of silently following a reparse point or weakening a directory-only open
  - `geteuid`/`getuid` → the compatibility sentinel `0`, not a Windows identity
  - `gmtime_r`/`localtime_r` (thread-safe time, via copy-out)
  - `setenv`/`unsetenv` (via `_putenv_s`)
  - `mkdir(path, mode)` → `_mkdir(path)` (Windows drops the mode bits)
  - `realpath(path, NULL)` → allocation-only, dynamic UTF-16 Win32 handle
    resolution (follows the final reparse target and is not limited to
    `_MAX_PATH`). Caller-provided output buffers are rejected because their
    capacity is unknowable and Windows paths can exceed POSIX `PATH_MAX`.
  - `mkdtemp` (real Win32 implementation)

## Coverage

CI cross-builds the relocatable compiler bundle and representative portable
programs, then native Windows CI executes the compiler, generated programs,
drive/UNC path semantics, junction-based bundle discovery, and the compatibility
seams. This is a verified subset, not a claim that every corpus fixture is a
supported standalone Windows program.

The following boundaries remain intentional:

* `Process` spawn/wait, raw-mode `Terminal`, sockets, `Regex`, and glob/fnmatch
  need real Win32 backends. Retained calls to these APIs fail compilation or at
  runtime instead of silently using link-only stubs.
* Filesystem and compiler I/O generally uses narrow C-runtime functions or
  Win32 `A` APIs. Non-ASCII paths outside the active Windows code page are not
  supported consistently. `realpath` alone has an explicit UTF-8/UTF-16 bridge.
* `FileSystem.removeRecursive` removes files and final reparse points, but
  returns `-1` for an ordinary directory. Path-based directory traversal has an
  ancestor-junction race, so recursive directory deletion remains disabled
  until a handle-relative NT implementation is available.
* Native GUI/tray dependencies have their own platform requirements and are not
  supplied by this compatibility header.

## Scope / Milestone 2

This layer gets `btrcc` and programs within the verified portable subset
**building and running** on Windows. Real Win32 backends for the POSIX-only
modules above are follow-up work. The supported surface today is the compiler
itself plus portable strings, collections, math, environment, time, basic I/O,
and the filesystem operations described above.

## Testing

`make test-windows` cross-builds `btrcc.exe` plus a sample program to `.exe`
(works on any host) and runs the sample under `wine`/`wine64` if present
(Linux/CI), skipping execution gracefully where wine isn't available. A native
`windows-latest` CI job ([`.github/workflows/windows.yml`](../../../.github/workflows/windows.yml))
builds and runs the binaries for pushes and pull requests targeting `main`.
