"""Extract which hosted ``[platform]`` names each compilation target declares.

PLAN.md Stage 24 (``platforms-p1-hosted-abi-targets``), designed in
docs/design/platform-target-contract.md §2.3. ``HostedPlatformExtractor``
writes, for one ``targets.toml`` row, the ``[[platform_targets]]`` fragment
that ``hosted_abi.toml`` schema 3 carries: the ``[platform]`` names of each of
the five kinds that the row's C compile does **not** declare. The generator
never runs this tool; its output is reviewed and copied into the spec.

For one row the extractor builds a probe translation unit. The probe opens
with the C emitter's prologue defines and includes the hosted prologue
headers (the emitter's fixed list and ``btrc_rt.h``'s hosted list) and the
platform header families that hosted btrc sources reach (``PROBE_HEADERS``),
each behind ``__has_include`` so a header a row lacks is simply absent. The
row's real C toolchain preprocesses it with exactly the row's build flags:

- ``linux-*``: ``zig cc -target <zig_target>``, as the release build does
  (``Makefile``), so the glibc floor is zig's default for that target (2.31
  in zig 0.16.0), recorded in the fragment;
- ``windows-*`` (``zig-mingw``): ``zig cc -target <zig_target>`` with zig's
  ``any-windows-any`` (MinGW-w64) headers plus ``-I src/runtime/windows
  -include src/runtime/windows/btrc_win_compat.h`` (``Makefile`` WIN_COMPAT);
- ``android-*`` (``ndk``): the unwrapped clang with the row's
  ``target_arguments`` and ``--sysroot`` at the NDK r29 sysroot. The triple
  carries the API level; ``-D__ANDROID_API__`` is never passed;
- ``macos-*``/``ios-*`` (``xcrun``, ``--xcrun``): ``xcrun clang`` with the
  row's ``target_arguments`` and ``-isysroot`` at the SDK path.

Macros come from the preprocessor's ``-E -dD`` output. Declarations come from
``clang <target_arguments> -x cpp-output -Xclang -ast-dump=json`` over the
preprocessed unit, so zig rows are read by the same parser as clang rows.
(The native header reader has no names-only mode yet; the design names this
AST route as its fallback.) An identifier counts as declared for a kind when
the unit declares it as anything (a function, object, tag, typedef,
enumerator or struct member) or defines it as a macro, since either makes the
name usable in C. A name every declaration of which is marked ``unavailable``
is not declared; on the xcrun rows the text AST dump also supplies
``API_UNAVAILABLE(<os>)``, whose platform the JSON dump omits.

Two kinds of name are never listed. btrc's own namespace
(``RUNTIME_PREFIXES``) is ported, not filtered; names the btrc GPU runtime
headers declare are read on the host, best effort. A ``[platform]`` name that a
btrc stdlib source declares itself at file scope (``extern char** environ;``)
counts as declared on every extracted row, because the C library exports it,
except on the conservative MSVC row; each fragment names them.

``windows-aarch64-msvc`` (``windows-sdk``) is runner-bound. Its table is the
conservative copy §2.3 prescribes: ``windows-aarch64``'s list plus every
``[platform]`` name the MSVC toolchain cannot be shown to declare (see
``conservative_msvc``), with ``source = "conservative copy pending runner
extraction"``. It can only refuse too much, never too little.

    python3 -m tools.hosted_platform [--target LABEL ...] [--xcrun] [--output DIR]

Run it inside ``nix develop`` (``nix develop .#platforms`` for the NDK rows).
"""

from __future__ import annotations

import argparse
import bisect
import datetime
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.compiler.python.abi.generated import (
    HOSTED_PLATFORM_FUNCTION_NAMES,
    HOSTED_PLATFORM_MACRO_NAMES,
    HOSTED_PLATFORM_OBJECT_NAMES,
    HOSTED_PLATFORM_TYPE_NAMES,
    HOSTED_PLATFORM_TYPEDEF_NAMES,
    TARGET_ROWS,
    GeneratedTargetRow,
)

REPO = Path(__file__).resolve().parents[1]

KINDS = ("functions", "macros", "objects", "types", "typedefs")

PLATFORM_NAMES = {
    "functions": frozenset(HOSTED_PLATFORM_FUNCTION_NAMES),
    "macros": frozenset(HOSTED_PLATFORM_MACRO_NAMES),
    "objects": frozenset(HOSTED_PLATFORM_OBJECT_NAMES),
    "types": frozenset(HOSTED_PLATFORM_TYPE_NAMES),
    "typedefs": frozenset(HOSTED_PLATFORM_TYPEDEF_NAMES),
}

# The defines every hosted translation unit opens with (the C emitter's prologue).
PROLOGUE_DEFINES = ("_DEFAULT_SOURCE", "_DARWIN_C_SOURCE")

# The C emitter's fixed hosted includes, then btrc_rt.h's hosted includes.
PROLOGUE_HEADERS = (
    "stdio.h",
    "stdlib.h",
    "string.h",
    "stdbool.h",
    "stdint.h",
    "ctype.h",
    "math.h",
    "assert.h",
    "limits.h",
    "stddef.h",
    "stdatomic.h",
    "float.h",
    "setjmp.h",
    "stdarg.h",
    "pthread.h",
)

# The platform header families hosted btrc sources reach: the stdlib's and the
# runtime's system includes, POSIX, and the glibc, bionic, Darwin and
# MinGW/UCRT extension headers that declare [platform] names. Each is guarded
# by __has_include. §2.3 calls this "the row's automatic headers": a hosted
# [platform] name reaches C through one of these includes, not through the
# emitter's fixed prologue (which declares only ISO C). Probing a header the
# row's C compile might not include errs permissive, the safe direction (the
# check is never stricter than C); leaving one out would err strict.
PROBE_HEADERS = (
    "errno.h",
    "fcntl.h",
    "time.h",
    "locale.h",
    "signal.h",
    "inttypes.h",
    "wchar.h",
    "wctype.h",
    "fenv.h",
    "uchar.h",
    "threads.h",
    "unistd.h",
    "sys/types.h",
    "sys/stat.h",
    "sys/time.h",
    "sys/times.h",
    "sys/wait.h",
    "sys/socket.h",
    "sys/un.h",
    "sys/uio.h",
    "sys/select.h",
    "sys/mman.h",
    "sys/resource.h",
    "sys/utsname.h",
    "sys/ioctl.h",
    "sys/file.h",
    "sys/param.h",
    "sys/statvfs.h",
    "sys/syscall.h",
    "sys/sysctl.h",
    "sys/random.h",
    "sys/ipc.h",
    "sys/shm.h",
    "sys/sem.h",
    "sys/msg.h",
    "sys/xattr.h",
    "sys/mount.h",
    "sys/event.h",
    "sys/proc_info.h",
    "sys/epoll.h",
    "sys/inotify.h",
    "sys/eventfd.h",
    "sys/prctl.h",
    "sys/sendfile.h",
    "sys/statfs.h",
    "sys/vfs.h",
    "sys/sysmacros.h",
    "netinet/icmp6.h",
    "values.h",
    "sys/reboot.h",
    "sys/swap.h",
    "uuid/uuid.h",
    "poll.h",
    "dirent.h",
    "dlfcn.h",
    "netdb.h",
    "arpa/inet.h",
    "netinet/in.h",
    "netinet/tcp.h",
    "net/if.h",
    "ifaddrs.h",
    "pwd.h",
    "grp.h",
    "regex.h",
    "fnmatch.h",
    "glob.h",
    "termios.h",
    "spawn.h",
    "sched.h",
    "semaphore.h",
    "strings.h",
    "libgen.h",
    "getopt.h",
    "err.h",
    "syslog.h",
    "pty.h",
    "util.h",
    "libutil.h",
    "utmpx.h",
    "utime.h",
    "wordexp.h",
    "search.h",
    "langinfo.h",
    "iconv.h",
    "nl_types.h",
    "ftw.h",
    "fts.h",
    "aio.h",
    "monetary.h",
    "execinfo.h",
    "malloc.h",
    "alloca.h",
    "endian.h",
    "libproc.h",
    "copyfile.h",
    "crt_externs.h",
    "mach/mach_time.h",
    "io.h",
    "direct.h",
    "process.h",
)

# The btrc GPU runtime headers (btrc_rt.h's BTRC_RT_GPU_HEADER and its
# siblings). The runtime is ported, never filtered (§2.2): the names declared
# under src/runtime/gpu are read once on the host, best effort, and count as
# declared on every row.
GPU_RUNTIME_HEADERS = ("btrc_gpu_compute_internal.h", "btrc_gpu_compute_singleton.h", "btrc_gpu_async.h")

# The ISO C11 library headers, minus <threads.h>, which UCRT gained late. Every name a
# strict C11 compile declares through them is in the MSVC row's C library.
ISO_C_HEADERS = (
    "assert.h",
    "complex.h",
    "ctype.h",
    "errno.h",
    "fenv.h",
    "float.h",
    "inttypes.h",
    "iso646.h",
    "limits.h",
    "locale.h",
    "math.h",
    "setjmp.h",
    "signal.h",
    "stdalign.h",
    "stdarg.h",
    "stdbool.h",
    "stddef.h",
    "stdint.h",
    "stdio.h",
    "stdlib.h",
    "stdnoreturn.h",
    "string.h",
    "time.h",
    "uchar.h",
    "wchar.h",
    "wctype.h",
)

# Headers in zig's any-windows-any that only MinGW-w64 or winpthreads ship;
# the Windows SDK and UCRT have no counterpart (platform-target-contract.md §2.3).
MINGW_ONLY_HEADERS = frozenset(
    {
        "dirent.h",
        "getopt.h",
        "libgen.h",
        "sched.h",
        "semaphore.h",
        "strings.h",
        "sys/file.h",
        "sys/param.h",
        "sys/time.h",
        "sys/unistd.h",
        "unistd.h",
        "utime.h",
    }
)
MINGW_ONLY_PREFIXES = ("pthread", "_mingw", "mingw")

# zig release -> the MinGW-w64 revision its any-windows-any headers carry.
MINGW_REVISIONS = {"0.16.0": "38c8142f"}

# btrc's own namespace (runtime helpers, GPU runtime, native header guards).
# The runtime is ported, never filtered (§2.2), so no row lists these names.
RUNTIME_PREFIXES = ("btrc_", "Btrc", "BTRC_")

CONSERVATIVE_SOURCE = "conservative copy pending runner extraction"

# Names and the rows on which they must (or must not) be declared. They are
# checked against what each extracted row declares, not against [platform].
SPOT_CHECKS = (
    ("GetFileAttributesA", frozenset({"linux", "android", "macos", "ios"}), False),
    # glibc added the arc4random family in 2.36, above the rows' 2.31 floor.
    ("arc4random_uniform", frozenset({"linux"}), False),
    ("arc4random_uniform", frozenset({"android", "macos", "ios"}), True),
    ("explicit_bzero", frozenset({"linux"}), True),
    # bionic (NDK r29) declares no explicit_bzero at any API level.
    ("explicit_bzero", frozenset({"android"}), False),
    ("getrandom", frozenset({"android"}), True),
    ("posix_spawn", frozenset({"android"}), True),
    ("aligned_alloc", frozenset({"android"}), True),
    ("timespec_get", frozenset({"android"}), True),
    ("reallocarray", frozenset({"android"}), True),
    # Introduced at API 30, so hidden at the API 29 floor (__INTRODUCED_IN).
    ("memfd_create", frozenset({"android"}), False),
    # Below API 30, NDK r29's <threads.h> declares the C11 threads API as
    # static inlines (android/legacy_threads_inlines.h), so it is declared at 29.
    ("thrd_create", frozenset({"android"}), True),
    ("mtx_init", frozenset({"android"}), True),
    ("cnd_wait", frozenset({"android"}), True),
)

DEFAULT_LABELS = (
    "linux-x86_64",
    "linux-aarch64",
    "windows-x86_64",
    "windows-aarch64",
    "windows-aarch64-msvc",
    "android-aarch64",
    "android-x86_64",
)
XCRUN_LABELS = ("macos-x86_64", "macos-aarch64", "ios-aarch64", "ios-aarch64-simulator")

_LINEMARKER = re.compile(r'^#\s*(?:line\s+)?\d+\s+"((?:[^"\\]|\\.)*)"')
_DEFINE = re.compile(r"^#\s*define\s+([A-Za-z_]\w*)")
_UNDEF = re.compile(r"^#\s*undef\s+([A-Za-z_]\w*)")
_GLIBC = re.compile(r"^#\s*define\s+__GLIBC_MINOR__\s+(\d+)", re.MULTILINE)
_STDLIB_EXTERN = re.compile(r"^extern\b[^;{]*?\b([A-Za-z_]\w*)\s*(?:\(|\[|;)", re.MULTILINE)
_CATEGORIES = {
    "FunctionDecl": "function",
    "VarDecl": "object",
    "RecordDecl": "tag",
    "EnumDecl": "tag",
    "TypedefDecl": "typedef",
    "EnumConstantDecl": "enumerator",
    "FieldDecl": "field",
    "IndirectFieldDecl": "field",
}
_TEXT_DECLARATION = re.compile(
    r"^[|`]-(?:FunctionDecl|VarDecl|RecordDecl|EnumDecl|TypedefDecl) 0x[0-9a-f]+ "
    r"(?:parent 0x[0-9a-f]+ )?(?:prev 0x[0-9a-f]+ )?<(?:[^<>]|<[^<>]*>)*> (?P<rest>.*)$"
)
_TEXT_UNAVAILABLE = re.compile(
    r"^[| ] [|`]-AvailabilityAttr 0x[0-9a-f]+ <(?:[^<>]|<[^<>]*>)*> (?P<platform>\w+) \S+ \S+ \S+ Unavailable\b"
)
_TEXT_LOCATION = re.compile(r"^(?:<invalid sloc>|\S+) ")
_TEXT_FLAGS = frozenset(
    {"implicit", "used", "referenced", "invalid", "struct", "union", "enum", "definition", "extern", "static", "inline"}
)


class HostedPlatformError(RuntimeError):
    """A row cannot be extracted on this host, or its probe failed."""


@dataclass(frozen=True)
class ProbePlan:
    """How one row's probe is preprocessed and parsed."""

    preprocessor: tuple[str, ...]
    parser: tuple[str, ...]
    description: str
    # clang availability platforms whose "Unavailable" marking hides a declaration.
    availability_platforms: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProbeNames:
    """What one probe declares."""

    files: dict[str, frozenset[str]]
    """Every declared identifier (declarations and macros) -> its declaring headers."""
    categories: dict[str, frozenset[str]]
    """Declared identifiers -> how C declares them: function, object, tag, typedef, enumerator, field."""
    imported: frozenset[str]
    """Declarations marked dllimport: exports of a CRT or system DLL."""
    glibc: str = ""
    """The glibc release the headers select (``2.31``), or ``""``."""


@dataclass(frozen=True)
class PlatformExtraction:
    """One row's declared names, their declaring files and its unavailable lists."""

    label: str
    declared: frozenset[str]
    files: dict[str, frozenset[str]]
    unavailable: dict[str, tuple[str, ...]]
    source: str
    imported: frozenset[str] = frozenset()
    notes: tuple[str, ...] = field(default=())


class HostedPlatformExtractor:
    """Extract one target row's hosted availability through its real C toolchain."""

    def __init__(
        self,
        repo: Path = REPO,
        *,
        platform_names: dict[str, frozenset[str]] | None = None,
        rows: tuple[GeneratedTargetRow, ...] = TARGET_ROWS,
        clang: str | None = None,
        zig: str | None = None,
        ndk_home: Path | None = None,
        date: str | None = None,
        runtime_declared: frozenset[str] | None = None,
        iso_c_declared: frozenset[str] | None = None,
        stdlib_declared: frozenset[str] | None = None,
        timeout: int = 900,
    ) -> None:
        self._runtime = runtime_declared
        self._iso_c = iso_c_declared
        self._stdlib = stdlib_declared
        self.repo = repo
        self.platform_names = platform_names if platform_names is not None else PLATFORM_NAMES
        self.rows = {row.label: row for row in rows}
        self._clang = clang
        self._zig = zig
        configured = ndk_home or os.environ.get("ANDROID_NDK_HOME") or os.environ.get("ANDROID_NDK_ROOT")
        self.ndk_home = Path(configured) if configured else None
        self.date = date or datetime.date.today().isoformat()
        self.timeout = timeout

    # --- rows and probe ---

    def row(self, label: str) -> GeneratedTargetRow:
        try:
            return self.rows[label]
        except KeyError:
            raise HostedPlatformError(
                f"unknown target {label!r}; expected one of {', '.join(sorted(self.rows))}"
            ) from None

    def probe_source(self) -> str:
        """The probe translation unit, identical for every row."""
        lines = ["/* hosted platform probe (tools/hosted_platform.py) */"]
        lines += [f"#define {name}" for name in PROLOGUE_DEFINES]
        for header in (*PROLOGUE_HEADERS, *PROBE_HEADERS):
            lines += [f"#if __has_include(<{header}>)", f"#include <{header}>", "#endif"]
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _common_flags() -> list[str]:
        return ["-std=c11", "-w"]

    # --- toolchain discovery ---

    def clang(self) -> str:
        """The clang driver that parses every row: unwrapped from a nix wrapper when present."""
        if self._clang is not None:
            return self._clang
        wrapper = shutil.which("clang")
        if wrapper is None:
            raise HostedPlatformError("clang is not on PATH; run inside nix develop")
        original = Path(wrapper).resolve().parents[1] / "nix-support" / "orig-cc"
        if original.is_file():
            candidate = Path(original.read_text().strip()) / "bin" / "clang"
            if candidate.is_file():
                return str(candidate)
        return wrapper

    def zig(self) -> str:
        if self._zig is not None:
            return self._zig
        found = shutil.which("zig")
        if found is None:
            raise HostedPlatformError("zig is not on PATH; run inside nix develop")
        return found

    def _run(self, command: list[str], what: str) -> str:
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=self.timeout)
        except FileNotFoundError as error:
            raise HostedPlatformError(f"{what}: {error}") from error
        except subprocess.TimeoutExpired as error:
            raise HostedPlatformError(f"{what}: timed out after {self.timeout} s") from error
        if result.returncode != 0:
            raise HostedPlatformError(f"{what} failed ({result.returncode}):\n{result.stderr.strip()[-4000:]}")
        return result.stdout

    def zig_version(self) -> str:
        return self._run([self.zig(), "version"], "zig version").strip()

    def ndk_sysroot(self) -> Path:
        if self.ndk_home is None:
            raise HostedPlatformError("ANDROID_NDK_HOME is unset; run inside nix develop .#platforms or pass --ndk")
        prebuilt = self.ndk_home / "toolchains" / "llvm" / "prebuilt"
        for tag in ("linux-x86_64", "darwin-x86_64", "windows-x86_64"):
            sysroot = prebuilt / tag / "sysroot"
            if (sysroot / "usr" / "include").is_dir():
                return sysroot
        raise HostedPlatformError(f"no NDK sysroot under {prebuilt}")

    def ndk_revision(self) -> str:
        if self.ndk_home is None:
            return "unknown revision"
        properties = self.ndk_home / "source.properties"
        if properties.is_file():
            match = re.search(r"Pkg\.Revision\s*=\s*(\S+)", properties.read_text())
            if match:
                return match.group(1)
        return "unknown revision"

    # --- probe plans ---

    def plan(self, row: GeneratedTargetRow) -> ProbePlan:
        """The preprocessor and parser commands for *row* on this host."""
        flags = self._common_flags()
        kind = row.sysroot_kind
        if kind == "none" and row.operating_system == "linux":
            # The unversioned target, as the release build passes it: zig's default glibc floor.
            command = (self.zig(), "cc", "-target", row.zig_target, *flags)
            return ProbePlan(command, self._parser(row), f"zig {self.zig_version()} bundled {row.zig_target} headers")
        if kind == "zig-mingw":
            overlay = self.repo / "src" / "runtime" / "windows"
            compat = ["-I", str(overlay), "-include", str(overlay / "btrc_win_compat.h")]
            command = (self.zig(), "cc", "-target", row.zig_target, *flags, *compat)
            version = self.zig_version()
            revision = MINGW_REVISIONS.get(version, "revision unknown")
            return ProbePlan(
                command,
                self._parser(row),
                f"zig {version} lib/libc/include/any-windows-any (MinGW-w64 {revision}) plus src/runtime/windows",
            )
        if kind == "ndk":
            sysroot = self.ndk_sysroot()
            command = (self.clang(), *row.target_arguments, f"--sysroot={sysroot}", *flags)
            return ProbePlan(
                command,
                self._parser(row),
                f"ndk {self.ndk_revision()} sysroot, API {row.minimum_version}",
            )
        if kind == "xcrun":
            sdk = self._run(["xcrun", "--sdk", row.sysroot_name, "--show-sdk-path"], "xcrun").strip()
            command = ("xcrun", "--sdk", row.sysroot_name, "clang", *row.target_arguments, "-isysroot", sdk, *flags)
            parser = ("xcrun", "--sdk", row.sysroot_name, "clang", *row.target_arguments)
            return ProbePlan(
                command,
                parser,
                f"{row.sysroot_name} SDK {Path(sdk).name} (xcrun clang)",
                (row.operating_system,),
            )
        raise HostedPlatformError(f"target {row.label} ({kind} sysroot) cannot be extracted on this host")

    def _parser(self, row: GeneratedTargetRow) -> tuple[str, ...]:
        return (self.clang(), *row.target_arguments)

    # --- reading the probe ---

    @staticmethod
    def parse_macros(text: str) -> dict[str, str]:
        """Macro name -> defining file, from ``-E -dD`` output (``#undef`` removes)."""
        macros: dict[str, str] = {}
        current = ""
        for line in text.splitlines():
            if not line.startswith("#"):
                continue
            marker = _LINEMARKER.match(line)
            if marker:
                current = marker.group(1)
                continue
            define = _DEFINE.match(line)
            if define:
                macros[define.group(1)] = current
                continue
            undef = _UNDEF.match(line)
            if undef:
                macros.pop(undef.group(1), None)
        return macros

    @staticmethod
    def glibc_release(text: str) -> str:
        """The glibc release (``2.31``) an ``-E -dD`` dump selects, or ``""``."""
        minors = _GLIBC.findall(text)
        return f"2.{minors[-1]}" if minors else ""

    @staticmethod
    def presumed_files(preprocessed: bytes) -> tuple[list[int], list[str]]:
        """Byte offsets at which a linemarker changes the presumed file, and each file."""
        offsets: list[int] = []
        files: list[str] = []
        position = 0
        for line in preprocessed.splitlines(keepends=True):
            if line.startswith(b"#"):
                marker = _LINEMARKER.match(line.decode("utf-8", "replace"))
                if marker:
                    offsets.append(position + len(line))
                    files.append(marker.group(1))
            position += len(line)
        return offsets, files

    @staticmethod
    def _offset(location: Any) -> int | None:
        if not isinstance(location, dict):
            return None
        if "expansionLoc" in location:
            location = location["expansionLoc"]
        offset = location.get("offset")
        return offset if isinstance(offset, int) else None

    @classmethod
    def parse_ast(
        cls, document: dict[str, Any], preprocessed: bytes
    ) -> tuple[dict[str, set[str]], dict[str, set[str]], set[str]]:
        """File-scope names declared in a preprocessed unit.

        *document* is clang's ``-ast-dump=json`` of *preprocessed*. Every
        location is inside that one file, so a declaration's header is the
        linemarker in force at its byte offset. Functions, objects, struct,
        union and enum tags, typedefs, enumerators and struct members are read;
        function bodies are not entered, but struct and enum bodies are (C
        gives nested tags file scope). A declaration marked ``unavailable``
        is skipped, so a name is declared while any declaration of it is not.
        Returns name -> declaring files, name -> categories, and the names
        with a ``dllimport`` declaration."""
        offsets, files = cls.presumed_files(preprocessed)
        found: dict[str, set[str]] = {}
        categories: dict[str, set[str]] = {}
        imported: set[str] = set()
        stack: list[Any] = list(reversed(document.get("inner", [])))
        while stack:
            node = stack.pop()
            if not isinstance(node, dict):
                continue
            kind = node.get("kind", "")
            name = node.get("name")
            category = _CATEGORIES.get(kind)
            if category is not None and name and not node.get("isImplicit"):
                attributes = {child.get("kind") for child in node.get("inner", []) if isinstance(child, dict)}
                if "UnavailableAttr" in attributes:
                    continue
                if "DLLImportAttr" in attributes:
                    imported.add(name)
                offset = cls._offset(node.get("loc"))
                index = bisect.bisect_right(offsets, offset) - 1 if offset is not None else -1
                found.setdefault(name, set()).add(files[index] if index >= 0 else "")
                categories.setdefault(name, set()).add(category)
            if kind in {"RecordDecl", "EnumDecl"}:
                stack.extend(reversed(node.get("inner", [])))
        return found, categories, imported

    @staticmethod
    def unavailable_on(text_dump: str, platforms: tuple[str, ...]) -> set[str]:
        """Top-level names that clang's text AST dump marks ``Unavailable`` on *platforms*.

        The JSON dump omits an ``AvailabilityAttr``'s platform, so Apple's
        ``API_UNAVAILABLE(ios)`` is read from the text dump instead. A name is
        returned only when every top-level declaration of it is so marked."""
        available: set[str] = set()
        unavailable: set[str] = set()
        current = ""
        marked = False
        for line in [*text_dump.splitlines(), "`-"]:
            declaration = _TEXT_DECLARATION.match(line)
            if declaration or line[:2] in {"|-", "`-"}:
                if current:
                    (unavailable if marked else available).add(current)
                current = HostedPlatformExtractor._text_name(declaration.group("rest")) if declaration else ""
                marked = False
                continue
            attribute = _TEXT_UNAVAILABLE.match(line)
            if attribute and current and attribute.group("platform") in platforms:
                marked = True
        return unavailable - available

    @staticmethod
    def _text_name(rest: str) -> str:
        """The declared name in the tail of a text-dump declaration line, or ``""``."""
        tokens = _TEXT_LOCATION.sub("", rest, count=1).split(" ")
        for token in tokens:
            if token.startswith("'"):
                return ""
            if token in _TEXT_FLAGS:
                continue
            return token if token.isidentifier() else ""
        return ""

    def unavailable(self, declared: frozenset[str]) -> dict[str, tuple[str, ...]]:
        """``[platform] - declared`` for each of the five kinds, outside btrc's own namespace.

        One identifier set serves all five kinds: a name the unit declares as
        anything is usable in C, and a kind mismatch (``realpath`` is a
        function on glibc and a macro under the Windows overlay) must not make
        the table stricter than the C compile."""
        return {
            kind: tuple(
                sorted(name for name in self.platform_names[kind] - declared if not name.startswith(RUNTIME_PREFIXES))
            )
            for kind in KINDS
        }

    # --- extraction ---

    def read_probe(self, plan: ProbePlan, scratch: Path, source: str | None = None) -> ProbeNames:
        """Preprocess *source* (default: the probe) with *plan*; return what it declares."""
        probe = scratch / "probe.c"
        probe.write_text(self.probe_source() if source is None else source)
        defines = self._run([*plan.preprocessor, "-E", "-dD", str(probe)], "probe macros")
        macros = self.parse_macros(defines)
        preprocessed = scratch / "probe.i"
        preprocessed.write_text(self._run([*plan.preprocessor, "-E", str(probe)], "probe preprocess"))
        parse = [*plan.parser, "-std=c11", "-w", "-x", "cpp-output", "-fsyntax-only", "-fno-color-diagnostics"]
        dump = self._run([*parse, "-Xclang", "-ast-dump=json", str(preprocessed)], "probe AST")
        found, categories, imported = self.parse_ast(json.loads(dump), preprocessed.read_bytes())
        if plan.availability_platforms:
            text = self._run([*parse, "-Xclang", "-ast-dump", str(preprocessed)], "probe availability")
            for name in self.unavailable_on(text, plan.availability_platforms):
                found.pop(name, None)
                categories.pop(name, None)
                imported.discard(name)
        files = {name: set(paths) for name, paths in found.items()}
        for name, path in macros.items():
            files.setdefault(name, set()).add(path)
        return ProbeNames(
            {name: frozenset(paths) for name, paths in files.items()},
            {name: frozenset(kinds) for name, kinds in categories.items()},
            frozenset(imported),
            self.glibc_release(defines),
        )

    def runtime_declared(self) -> frozenset[str]:
        """Names declared under ``src/runtime/gpu`` by the GPU runtime headers, best effort.

        They are read once with the host clang (``webgpu.h`` from the dev shell
        or ``GPU_CFLAGS``); when that fails the set is empty, which loses
        nothing that ``RUNTIME_PREFIXES`` does not already exclude."""
        if self._runtime is None:
            gpu = self.repo / "src" / "runtime" / "gpu"
            include = ["-I", str(gpu), *shlex.split(os.environ.get("GPU_CFLAGS", ""))]
            plan = ProbePlan(("clang", *self._common_flags(), *include), ("clang",), "host")
            source = "".join(f'#include "{header}"\n' for header in GPU_RUNTIME_HEADERS)
            try:
                with tempfile.TemporaryDirectory(prefix="hosted-platform-runtime-") as directory:
                    files = self.read_probe(plan, Path(directory), source).files
            except HostedPlatformError as error:
                print(f"warning: GPU runtime names not read: {error}", file=sys.stderr)
                files = {}
            prefix = gpu.resolve().as_posix() + "/"
            self._runtime = frozenset(
                name
                for name, paths in files.items()
                if any(Path(path).resolve().as_posix().startswith(prefix) for path in paths)
            )
        return self._runtime

    def iso_c_declared(self) -> frozenset[str]:
        """Names a strict ISO C11 compile declares (host clang, no feature macros)."""
        if self._iso_c is None:
            plan = ProbePlan(("clang", *self._common_flags()), ("clang",), "host")
            source = "".join(f"#include <{header}>\n" for header in ISO_C_HEADERS)
            with tempfile.TemporaryDirectory(prefix="hosted-platform-iso-") as directory:
                self._iso_c = frozenset(self.read_probe(plan, Path(directory), source).files)
        return self._iso_c

    def stdlib_declared(self) -> frozenset[str]:
        """``[platform]`` names a btrc stdlib source declares itself at file scope."""
        if self._stdlib is None:
            platform_names = set().union(*self.platform_names.values())
            names: set[str] = set()
            for path in sorted((self.repo / "src" / "stdlib").rglob("*.btrc")):
                names.update(_STDLIB_EXTERN.findall(path.read_text(errors="replace")))
            self._stdlib = frozenset(names & platform_names)
        return self._stdlib

    def extract(self, label: str) -> PlatformExtraction:
        row = self.row(label)
        plan = self.plan(row)
        with tempfile.TemporaryDirectory(prefix="hosted-platform-") as directory:
            names = self.read_probe(plan, Path(directory))
        probed = frozenset(names.files) | self.runtime_declared()
        self_declared = self.stdlib_declared() - probed
        declared = probed | self_declared
        arguments = " ".join(row.target_arguments)
        description = plan.description
        notes: list[str] = []
        if row.operating_system == "linux":
            description += f", glibc {names.glibc or 'unknown'} floor"
            notes.append(f"glibc floor: {names.glibc or 'unknown'} (zig's default for {row.zig_target}).")
        if self_declared:
            notes.append(
                "Declared by a btrc stdlib source at file scope, so counted as declared: "
                + ", ".join(sorted(self_declared))
                + "."
            )
        else:
            notes.append("No [platform] name needed a btrc stdlib self-declaration to count as declared.")
        source = f"{description}, {arguments}, extracted {self.date} by tools/hosted_platform.py"
        return PlatformExtraction(
            label, declared, names.files, self.unavailable(declared), source, names.imported, tuple(notes)
        )

    @staticmethod
    def mingw_only(path: str, overlay: Path) -> bool:
        """Whether *path* is a header that only MinGW-w64, winpthreads or the compat overlay ships."""
        normalized = path.replace("\\", "/")
        if normalized.startswith(overlay.as_posix() + "/"):
            return True
        marker = "/any-windows-any/"
        if marker not in normalized:
            return False
        relative = normalized.split(marker, 1)[1]
        return relative in MINGW_ONLY_HEADERS or relative.rsplit("/", 1)[-1].startswith(MINGW_ONLY_PREFIXES)

    def windows_sdk_declared(self, row: GeneratedTargetRow) -> dict[str, frozenset[str]]:
        """Names MinGW-w64's ``<windows.h>`` declares for *row*, with their declaring headers."""
        flags = self._common_flags()
        plan = ProbePlan((self.zig(), "cc", "-target", row.zig_target, *flags), self._parser(row), "windows.h")
        with tempfile.TemporaryDirectory(prefix="hosted-platform-sdk-") as directory:
            return self.read_probe(plan, Path(directory), "#include <windows.h>\n").files

    def conservative_msvc(
        self, label: str, windows: PlatformExtraction, sdk_files: dict[str, frozenset[str]]
    ) -> PlatformExtraction:
        """The runner-bound MSVC row, which may only refuse too much (§2.3).

        It is *windows*' (the gnu sibling's) list plus every name the MSVC
        toolchain cannot be shown to declare, kind by kind. A name stays
        available for a kind only when
        - the Windows API declares it: ``<windows.h>`` (*sdk_files*) declares
          it only in headers that are neither the sibling's CRT headers nor
          MinGW-w64-only;
        - or the sibling declares it in a header UCRT shares (not MinGW-w64,
          winpthreads or the overlay only) and either ISO C11 declares it
          (``iso_c_declared``), or the kind is a function or object whose
          declaration is ``dllimport``, a CRT DLL export.
        Everything else is refused: MinGW-w64's own POSIX additions to shared
        CRT headers (``mkstemp``, ``strtok_r``, ``PATH_MAX``, ``S_ISDIR``),
        winpthreads, the compat overlay, a stdlib self-declaration, and the
        old POSIX spellings UCRT keeps (``access``, ``O_RDONLY``), until the
        runner extraction replaces this table."""
        overlay = (self.repo / "src" / "runtime" / "windows").resolve()
        crt_files = {path for paths in windows.files.values() for path in paths if not self.mingw_only(path, overlay)}
        sdk_api = {
            name
            for name, paths in sdk_files.items()
            if paths and paths.isdisjoint(crt_files) and not any(self.mingw_only(path, overlay) for path in paths)
        }
        iso_c = self.iso_c_declared()

        def kept(name: str, kind: str) -> bool:
            if name in sdk_api:
                return True
            if not any(not self.mingw_only(path, overlay) for path in windows.files.get(name, ())):
                return False
            return name in iso_c or (kind in {"functions", "objects"} and name in windows.imported)

        unavailable = {
            kind: tuple(
                sorted(
                    name
                    for name in self.platform_names[kind]
                    if not name.startswith(RUNTIME_PREFIXES)
                    and (name in windows.unavailable[kind] or not kept(name, kind))
                )
            )
            for kind in KINDS
        }
        declared = frozenset(
            name
            for name in windows.declared
            if name.startswith(RUNTIME_PREFIXES) or any(kept(name, kind) for kind in KINDS)
        )
        notes = ("btrc stdlib self-declarations are not counted on this conservative row.",)
        return PlatformExtraction(label, declared, {}, unavailable, CONSERVATIVE_SOURCE, notes=notes)

    def extract_all(self, labels: list[str]) -> dict[str, PlatformExtraction]:
        """Extract *labels*; a ``windows-sdk`` row is derived from its gnu sibling."""
        extractions: dict[str, PlatformExtraction] = {}
        for label in labels:
            row = self.row(label)
            if row.sysroot_kind != "windows-sdk":
                extractions[label] = self.extract(label)
        for label in labels:
            row = self.row(label)
            if row.sysroot_kind != "windows-sdk":
                continue
            sibling = f"{row.operating_system}-{row.architecture}"
            if sibling not in extractions:
                extractions[sibling] = self.extract(sibling)
            sdk = self.windows_sdk_declared(self.row(sibling))
            extractions[label] = self.conservative_msvc(label, extractions[sibling], sdk)
        return {label: extractions[label] for label in labels}

    # --- output ---

    @staticmethod
    def fragment(extraction: PlatformExtraction, failures: tuple[str, ...] = ()) -> str:
        """The ``[[platform_targets]]`` TOML table for one row, its notes as leading comments."""
        lines = [f"# {note}" for note in extraction.notes]
        lines += [f"# spot check failed: {failure}" for failure in failures]
        lines += ["[[platform_targets]]", f'target = "{extraction.label}"']
        for kind in KINDS:
            names = extraction.unavailable[kind]
            if not names:
                lines.append(f"unavailable_{kind} = []")
                continue
            lines.append(f"unavailable_{kind} = [")
            lines += [f'  "{name}",' for name in names]
            lines.append("]")
        lines.append(f"source = {json.dumps(extraction.source)}")
        return "\n".join(lines) + "\n"

    def spot_check(self, extractions: dict[str, PlatformExtraction]) -> dict[str, list[str]]:
        """Failures of ``SPOT_CHECKS`` per extracted row (no entry passes)."""
        failures: dict[str, list[str]] = {}
        for name, systems, expected in SPOT_CHECKS:
            for label, extraction in sorted(extractions.items()):
                if self.row(label).operating_system not in systems:
                    continue
                if (name in extraction.declared) != expected:
                    state = "available" if expected else "unavailable"
                    failures.setdefault(label, []).append(f"{name} should be {state} on {label}")
        return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", action="append", dest="targets", help="row label (repeatable)")
    parser.add_argument("--xcrun", action="store_true", help="extract the macOS and iOS rows through xcrun")
    parser.add_argument("--output", type=Path, default=REPO / "build" / "hosted-platform")
    parser.add_argument("--ndk", type=Path, help="NDK root (default: ANDROID_NDK_HOME)")
    parser.add_argument("--date", help="extraction date recorded in each source (default: today)")
    arguments = parser.parse_args(argv)
    labels = arguments.targets or list(XCRUN_LABELS if arguments.xcrun else DEFAULT_LABELS)
    extractor = HostedPlatformExtractor(ndk_home=arguments.ndk, date=arguments.date)
    try:
        extractions = extractor.extract_all(labels)
    except HostedPlatformError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    failures = extractor.spot_check(extractions)
    arguments.output.mkdir(parents=True, exist_ok=True)
    for label, extraction in extractions.items():
        path = arguments.output / f"{label}.toml"
        path.write_text(extractor.fragment(extraction, tuple(failures.get(label, ()))))
        sizes = ", ".join(f"{kind}={len(extraction.unavailable[kind])}" for kind in KINDS)
        print(f"{label}: {sizes} -> {path}")
    for label_failures in failures.values():
        for failure in label_failures:
            print(f"spot check failed: {failure}", file=sys.stderr)
    print(f"spot checks: {'failed' if failures else 'passed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
