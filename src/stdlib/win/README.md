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
  `regex.h`, `fnmatch.h`, `glob.h`, `pwd.h`, `termios.h`, `sys/wait.h`,
  `sys/socket.h`, `sys/select.h`, `netinet/in.h`, `arpa/inet.h`. They are empty
  by design: `btrcc` never calls into these modules, so the include only needs to
  *resolve*.
* **Missing-*symbol* compat** (`btrc_win_compat.h`, force-included): POSIX
  functions MinGW omits but that survive DCE in the emitted C. Currently maps
  `lstat` → `stat` (Windows has no POSIX symlinks).

## Scope / Milestone 2

This layer gets `btrcc` and ordinary btrc programs **building and running** on
Windows. It does **not** yet give the POSIX-only stdlib modules real behaviour on
Windows — a program that actually calls `Process`, `Terminal` (raw mode),
sockets, or `Regex` will reference symbols these shims stub out. Real Win32
backends (`#ifdef _WIN32` paths in the stdlib runtime) are a follow-up. Until
then, the supported Windows surface is: the compiler itself plus programs that
stay within the portable stdlib (strings, collections, math, fs basics, I/O).

## Testing

`make test-windows` cross-builds `btrcc.exe` plus a sample program to `.exe`
(works on any host) and runs the sample under `wine`/`wine64` if present
(Linux/CI), skipping execution gracefully where wine isn't available.
