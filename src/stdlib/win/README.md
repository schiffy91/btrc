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
  by design: where a program doesn't call into the module, the include only needs
  to *resolve*.
* **Missing-*symbol* compat** (`btrc_win_compat.h`, force-included): POSIX
  functions/macros MinGW omits but that the emitted C references. Each is a
  *correct* Windows equivalent, not a link-only stub:
  - `lstat` → `stat`, `S_ISLNK` → 0 (Windows has no POSIX symlinks)
  - `geteuid`/`getuid` → 0 (no POSIX uid model)
  - `gmtime_r`/`localtime_r` (thread-safe time, via copy-out)
  - `setenv`/`unsetenv` (via `_putenv_s`)
  - `mkdir(path, mode)` → `_mkdir(path)` (Windows drops the mode bits)
  - `realpath` → `_fullpath`
  - `mkdtemp` (real Win32 implementation)

## Coverage

Across the full language corpus, **848 / 863 programs cross-compile to Windows**
(98.3%). The 15 that don't are all out of this layer's scope:

* **Milestone 2 — POSIX subsystems needing real Win32 backends**: `Process`
  spawn/wait (`WIFEXITED`, and the `stdout`/`stderr` parameter-name vs
  `<stdio.h>`-macro collision in `UnixShell`), raw-mode `Terminal`
  (`struct termios`), `Regex` (`regex_t`), and glob (`fnmatch`). Stubbing these
  to merely link would misbehave, so they're left out deliberately.
* **Not standalone programs**: `*_helper.btrc` fixtures that are `#include`d by
  other tests and have no `main()` (link error `undefined symbol: WinMain`).
* **GUI**: the native system-tray example (`btrc_tray.h`).

## Scope / Milestone 2

This layer gets `btrcc` and ordinary btrc programs **building and running** on
Windows. Real Win32 backends for the POSIX-only modules above (`#ifdef _WIN32`
paths in the stdlib runtime) are a follow-up. The supported Windows surface today
is: the compiler itself plus programs within the portable stdlib (strings,
collections, math, fs basics, env, time, I/O).

## Testing

`make test-windows` cross-builds `btrcc.exe` plus a sample program to `.exe`
(works on any host) and runs the sample under `wine`/`wine64` if present
(Linux/CI), skipping execution gracefully where wine isn't available. A native
`windows-latest` CI job ([`.github/workflows/windows.yml`](../../../.github/workflows/windows.yml))
builds and runs the binaries on real Windows on every push.
