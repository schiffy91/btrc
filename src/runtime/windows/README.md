# Windows compatibility layer

This directory makes the self-hosted compiler (`btrcc`) — and any btrc program —
cross-compile to Windows with `zig cc -target x86_64-windows-gnu`. It is applied
**only** to Windows builds, via the Makefile variable:

```make
WIN_COMPAT := -I src/runtime/windows -include src/runtime/windows/btrc_win_compat.h
```

POSIX (macOS/Linux) builds never add these flags, so their output is unchanged.

## Why it's needed

The btrc stdlib (`process`, `fs`, `http`, `regex`, `pattern`) is written against
POSIX. When a program is transpiled to C, those modules pull in POSIX headers.
Dead-code elimination removes the *bodies* of modules a given program doesn't
use, but an orphaned `#include <…>` line can survive even after its functions are
gone. MinGW-w64 (what `zig cc` targets) provides most of libc plus `dirent.h` and
winpthreads, but omits a handful of POSIX headers and a few symbols. This layer
fills exactly those gaps — nothing more.

## What's here

* **POSIX matching** (resolved via `-I`): `regex.h`, `fnmatch.h` and `glob.h`
  are real. Each declares its POSIX interface and compiles the vendored musl
  engine below into the including translation unit, so the hosted-ABI names
  (`regcomp`, `regexec`, `regerror`, `regfree`, `fnmatch`, `glob`, `globfree`
  and their `REG_`/`FNM_`/`GLOB_` constants) are available on the
  `windows-x86_64` and `windows-aarch64` rows and `Library.Regex`,
  `Library.Pattern` and glob(3) programs build unchanged. The MSVC row has no
  overlay and keeps refusing them.
* **Missing-*file* shims** (resolved via `-I`): minimal guarded headers for the
  POSIX headers MinGW-w64 lacks but that survive as orphan `#include`s —
  `grp.h`, `poll.h`, `pwd.h`, `termios.h`,
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
  - `fchmod`, `fcntl`, and `pread` fail with `ENOTSUP`; private-file capabilities
    require a native handle backend and do not emulate them with weaker calls
  - `geteuid`/`getuid` → the compatibility sentinel `0`, not a Windows identity
  - `gmtime_r`/`localtime_r` (thread-safe time, via copy-out)
  - `setenv`/`unsetenv` (via `_putenv_s`)
  - `mkdir(path, mode)` → `_mkdir(path)` (Windows drops the mode bits)
  - `realpath(path, NULL)` → allocation-only, dynamic UTF-16 Win32 handle
    resolution (follows the final reparse target and is not limited to
    `_MAX_PATH`). Caller-provided output buffers are rejected because their
    capacity is unknowable and Windows paths can exceed POSIX `PATH_MAX`.
  - `mkdtemp` (real Win32 implementation)

## Vendored musl: regex, fnmatch and glob

PLAN.md D22 names a vendored POSIX regex for Windows. `musl/` holds
musl 1.2.5's TRE-derived regex engine, its fnmatch and its glob
(<https://musl.libc.org/releases/musl-1.2.5.tar.gz>, SHA-256
`a9a118bbe84d8764da0ea0d28b3ab3fae8477fc7e4085d90102b8596fc7c75e4`; the
release zig 0.16.0 bundles in `lib/libc/musl`, and 1.2.6 changed none of these
files). musl is MIT-licensed and TRE, its regex engine, BSD-2-Clause; both
notices are in `musl/COPYRIGHT` and the files' headers, and both are
compatible with btrc's MIT licence.

| File | Upstream (SHA-256 of the 1.2.5 file) | Here |
| --- | --- | --- |
| `musl/regcomp.c` | `src/regex/regcomp.c` (`56b0a765…`) | unmodified |
| `musl/regerror.c` | `src/regex/regerror.c` (`72b3ab9c…`) | unmodified |
| `musl/fnmatch.c` | `src/regex/fnmatch.c` (`b6b0d4f9…`) | unmodified |
| `musl/regexec.c` | `src/regex/regexec.c` (`072e8a10…`) | aligns to `void *`, not `long` (LLP64) |
| `musl/tre-mem.c` | `src/regex/tre-mem.c` (`4721979c…`) | aligns to `void *`, not `long` (LLP64) |
| `musl/tre.h` | `src/regex/tre.h` (`e734e68d…`) | include guard; `tre_cint_t` is `int` (Windows' 16-bit `wint_t` cannot hold `TRE_CHAR_MAX+1`); `ALIGN` through `uintptr_t`; no `__tre_mem_*` link aliases |
| `musl/glob.c` | `src/regex/glob.c` (`ceb34d24…`) | UTF-16 directory reader (`_wfindfirst64`) returning UTF-8; `GetFileAttributesW` for existence and `GLOB_MARK`; heap path buffer (MinGW's `PATH_MAX` is 260); `.` and `..` always listed, as `readdir` lists them; no GNU `GLOB_PERIOD` or `GLOB_TILDE` |
| `musl/locale_impl.h` | stands in for musl's internal `src/internal/locale_impl.h` | `LCTRANS_CUR` is the identity, `MB_CUR_MAX` is 1 |

Every change is marked `btrc:` in the source.

`btrc_win_musl.h` compiles the sources into the unit that includes `regex.h`,
`fnmatch.h` or `glob.h`, once per part, with internal linkage, so the build
paths that already force-include this overlay link it without a separate
object and two units of one program keep separate copies. Because generated
code, MinGW headers and `windows.h` share that unit, it saves and restores
every macro it touches (`push_macro`/`pop_macro`: a caller's `MIN`, `END` or
`assert` survives), renames every file-scope name the sources declare into
`btrc_win_musl_`, and maps the POSIX entry points to `btrc_win_` names. It
also redirects the locale-dependent calls (`mbtowc`, the wide-character
classes and case mappings, `isdigit`) to C-locale versions: a byte is a
character and only ASCII is classified or case-folded, which is how glibc and
macOS match in the C locale every btrc program runs in.

`src/tests/python/test_regex_parity.py` runs a table of regex and fnmatch cases
against the host C library and the vendored engine and requires identical
results; windows.yml runs the same table, the regex, fnmatch and glob corpus
programs and a non-ASCII glob natively on x64 and ARM64.
`src/tests/python/test_windows_posix_overlay.py` checks the hygiene. Known
differences that remain: a malformed pattern can get a different `REG_*` code
than on glibc or macOS (`Library.Regex` reports every one as an invalid
pattern); `RE_DUP_MAX` is 255, as on macOS, where glibc allows 32767; an empty
pattern compiles, as on glibc, where macOS refuses it; an unmatched `)` in an
extended pattern is an error, as on macOS, where glibc reads it as a literal;
and matching stays byte-wise in the C locale even after `setlocale`. The
parity table holds only cases on which glibc and macOS agree.

## Coverage

CI cross-builds the relocatable compiler bundle and representative portable
programs, then native Windows CI executes the compiler, generated programs,
drive/UNC path semantics, junction-based bundle discovery, and the compatibility
seams. This is a verified subset, not a claim that every corpus fixture is a
supported standalone Windows program.

The following boundaries remain intentional:

* `Process` launches through its own Win32 backend, not this overlay:
  `Windows/ProcessHostProvider.btrc` calls the runtime's separately compiled
  `src/runtime/c/windows_os.c` (CreateProcessW with an explicit stdio handle
  list, a kill-on-close job, overlapped pipes), which every builder links when
  emitted C retains it. `Library.Terminal` reaches the console through its own
  Win32 provider (`src/stdlib/Terminal/Windows`), not through `termios.h`.
  Sockets still need a real Win32 backend; retained calls to those APIs fail
  compilation or at runtime instead of silently using link-only stubs.
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

The Windows compiler is composed through
`src/compiler/btrc/cli/WindowsMain.btrc`. It shares the normal driver and
compiler pipeline, but does not supply the Unix SDK-reader process provider.
Ordinary compilation remains available; experimental SDK scanning reports an
explicit unsupported-host error. Windows builds and bootstrap stages must use
this entry point instead of pulling Unix process code into the executable.

This layer gets `btrcc` and programs within the verified portable subset
**building and running** on Windows. Real Win32 backends for the POSIX-only
modules above are follow-up work. The supported surface today is the compiler
itself plus portable strings, collections, math, environment, time, basic I/O,
regular expressions, fnmatch and glob, the console terminal, and the
filesystem operations described above.

## Testing

`make test-windows` cross-builds `btrcc.exe` plus a sample program to `.exe`
(works on any host) and runs the sample under `wine`/`wine64` if present
(Linux/CI), skipping execution gracefully where wine isn't available. A native
`windows-latest` CI job ([`.github/workflows/windows.yml`](../../../.github/workflows/windows.yml))
builds and runs the binaries for pushes and pull requests targeting `main`.
