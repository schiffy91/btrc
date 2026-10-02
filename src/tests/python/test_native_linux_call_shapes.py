"""Linux SDK call shapes the native importer lowers: GNU transparent unions and fixed variadic tails.

glibc declares `connect`, `bind` and `accept` with a transparent-union address
(`__CONST_SOCKADDR_ARG`) under `_GNU_SOURCE`, and `fcntl` as a variadic
function. A transparent-union parameter projects as its first member, the
type the C ABI passes, so btrc code names `const struct sockaddr*` as on every
other platform. An imported tagged record answers to its C spelling too:
`struct sockaddr` and `struct pollfd` are the imported `sockaddr` and `pollfd`. A variadic function is callable only through a selected tail:
a `function.selector` shape binds an opcode constant, while a whole-function
shape (`[native.bindings.variadic-calls.fcntl]`) fixes one tail for every call
and keeps the selector visible. Both lower through a checked adapter, so a
function value has the projected signature. Every case runs through the
reference compiler and btrcc, and a refusal reads the same in both.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.process_limits import RUN_TIMEOUT, TRANSPILE_TIMEOUT
from tools.native_plan import NativePlanBuilder

REPO = Path(__file__).resolve().parents[3]

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="the call shapes are proven against glibc")

# Transparent unions are an SDK feature: C11 forbids converting an argument to
# a union, and compilers waive that only for a type a system header declares.
HEADER = """#pragma GCC system_header
#include <sys/socket.h>
#include <sys/un.h>
#include <fcntl.h>
#include <poll.h>
#include <unistd.h>
#include <stdarg.h>

typedef union { const int* exact; const long* wide; } Probe __attribute__((__transparent_union__));
static inline int probeRead(Probe value) { return *value.exact; }
static inline int probePair(Probe value, const int* other) { return *value.exact + *other; }
typedef struct Pair { int first; } Pair;
static inline void probeOut(Probe value, Pair* out) { out->first = *value.exact; }

typedef union { int number; long wide; } Plain;
static inline int plainRead(Plain value) { return value.number; }

static inline int sumTail(int count, ...) {
\tva_list arguments; va_start(arguments, count);
\tint total = 0;
\tfor (int index = 0; index < count; index++) { total += va_arg(arguments, int); }
\tva_end(arguments); return total;
}
"""

MANIFEST = """manifest-version = 1
[package]
name = "callShapes"

[[native.bindings]]
module = "Main"
header = "Shapes.h"
language = "c"
standard = "c11"
symbols = [{symbols}]
{extra}
[[native.defines]]
name = "_GNU_SOURCE"
value = "1"
modules = ["Main"]

[[native.include-directories]]
path = "."
"""

SYMBOLS = [
    "probeRead",
    "socket",
    "connect",
    "bind",
    "accept",
    "close",
    "poll",
    "pollfd",
    "POLLOUT",
    "fcntl",
    "sumTail",
    "AF_UNIX",
    "SOCK_STREAM",
    "F_GETFL",
    "F_SETFL",
    "O_NONBLOCK",
]
SHAPES = """
[native.bindings.variadic-calls.fcntl]
arguments = ["int"]

[native.bindings.variadic-calls."sumTail.count"]
value = "F_GETFL"
arguments = ["int", "int", "int"]
"""

PROGRAM = """#include <errno.h>
#include <assert.h>
#include <string.h>

typedef struct sockaddr_un Address;

int main() {
\tint value = 41;
\tassert(probeRead(&value) == 41);
\tvar read = probeRead;
\tvalue = 42;
\tassert(read(&value) == 42);

\tint descriptor = socket(AF_UNIX, SOCK_STREAM, 0);
\tassert(descriptor >= 0);
\tint flags = fcntl(descriptor, F_GETFL, 0);
\tassert(flags >= 0);
\tvar control = fcntl;
\tassert(control(descriptor, F_SETFL, flags | O_NONBLOCK) == 0);
\tassert((fcntl(descriptor, F_GETFL, 0) & O_NONBLOCK) != 0);

\tAddress address;
\tmemset(&address, 0, sizeof(address));
\taddress.sun_family = AF_UNIX;
\terrno = 0;
\tassert(connect(descriptor, (sockaddr*)&address, sizeof(address)) != 0);
\tassert(errno != 0);
\tvar attach = bind;
\tassert(attach(-1, (struct sockaddr*)&address, sizeof(address)) != 0 && errno == EBADF);
\tstruct pollfd pending;
\tpending.fd = descriptor;
\tpending.events = (short)POLLOUT;
\tpending.revents = 0;
\tpollfd* first = &pending;
\tassert(poll(first, (nfds_t)1, 0) >= 0);
\tassert(accept(-1, null, null) < 0 && errno == EBADF);
\tclose(descriptor);

\tassert(F_GETFL == 3 && sumTail(1, 2, 3) == 6);
\tprintf("PASS: native Linux call shapes\\n");
\treturn 0;
}
"""


def _compile(tmp_path: Path, request, frontend: str, program: str, symbols: list[str], extra: str):
    (tmp_path / "Shapes.h").write_text(HEADER, encoding="utf-8")
    (tmp_path / "btrc.toml").write_text(
        MANIFEST.format(symbols=", ".join(f'"{symbol}"' for symbol in symbols), extra=extra), encoding="utf-8"
    )
    source = tmp_path / "Main.btrc"
    source.write_text(program, encoding="utf-8")
    generated = tmp_path / "main.c"
    plan = tmp_path / "plan.json"
    flags = ["--no-cache", "--target", "linux-x64", "--emit-link-plan", str(plan), str(source)]
    command = (
        [sys.executable, "-m", "src.compiler.python.main", *flags, "-o", str(generated)]
        if frontend == "python"
        else [request.getfixturevalue("btrcc_bin"), *flags]
    )
    compiled = subprocess.run(command, cwd=REPO, capture_output=True, text=True, timeout=TRANSPILE_TIMEOUT)
    if frontend == "selfhost" and compiled.returncode == 0:
        generated.write_text(compiled.stdout, encoding="utf-8")
    return compiled, generated, plan


@pytest.fixture(scope="module")
def reader() -> str:
    executable = os.environ.get("BTRC_NATIVE_HEADER_READER")
    if not executable:
        pytest.skip("requires the explicitly built native header reader")
    return executable


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_transparent_unions_and_variadic_tails_build_and_run(reader, tmp_path, request, frontend) -> None:
    del reader  # The compilers locate it through BTRC_NATIVE_HEADER_READER.
    compiled, generated, plan = _compile(tmp_path, request, frontend, PROGRAM, SYMBOLS, SHAPES)
    assert compiled.returncode == 0, compiled.stderr
    text = generated.read_text(encoding="utf-8")
    # Each shape calls the SDK prototype through its adapter, never a redeclaration.
    for adapter in ("probeRead", "connect", "bind", "accept", "fcntl", "sumTail"):
        assert f"__btrc_native_{adapter}(" in text
    assert "__CONST_SOCKADDR_ARG" not in text
    assert "int fcntl(" not in text
    executable = tmp_path / "program"
    NativePlanBuilder().build(plan_path=plan, generated_c=generated, output=executable, cc="cc", cxx="c++")
    ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "PASS: native Linux call shapes\n"


@pytest.mark.parametrize(
    ("statement", "symbols", "extra", "diagnostic"),
    [
        ("int number = 0;", ["plainRead"], "", "native union values require native-type lowering"),
        (
            "int number = 0;",
            ["probeRead"],
            'realtime-safe = ["probeRead"]\n',
            "transparent-union parameters do not support callbacks, borrows, resources, owned or copied results, "
            "or realtime calls",
        ),
        (
            "int number = 0;",
            ["probePair"],
            'read-only-borrows = ["probePair.other"]\n',
            "transparent-union parameters do not support callbacks, borrows, resources, owned or copied results, "
            "or realtime calls",
        ),
        (
            "int number = 0;",
            ["probeOut", "Pair"],
            'owned-records = ["Pair"]\nrecord-outputs = ["probeOut.out"]\n',
            "record-outputs cannot combine transparent-union parameters",
        ),
        ("int number = 0;", ["fcntl"], "", "variadic native calls require a selected variadic-calls shape"),
        (
            "int number = 0;",
            ["F_GETFL"],
            '[native.bindings.variadic-calls.fcntl]\narguments = ["int"]\n',
            "variadic-calls must name selected functions",
        ),
        (
            "int number = 0;",
            ["fcntl"],
            "[native.bindings.variadic-calls.fcntl]\n",
            "variadic-calls requires only arguments for a whole function",
        ),
        (
            "int number = 0;",
            ["fcntl", "F_GETFL"],
            '[native.bindings.variadic-calls.fcntl]\nvalue = "F_GETFL"\narguments = ["int"]\n',
            "variadic-calls requires only arguments for a whole function",
        ),
        (
            "int number = 0;",
            ["fcntl", "F_GETFL"],
            '[native.bindings.variadic-calls.fcntl]\narguments = ["int"]\n'
            '[native.bindings.variadic-calls."fcntl.__cmd"]\nvalue = "F_GETFL"\narguments = ["int"]\n',
            "variadic-calls selects exactly one shape per function",
        ),
        (
            "int number = 0;",
            ["probeRead"],
            '[native.bindings.variadic-calls.probeRead]\narguments = ["int"]\n',
            "variadic-calls requires an SDK variadic function",
        ),
        (
            "int number = 0;",
            ["fcntl"],
            '[native.bindings.variadic-calls.fcntl]\narguments = ["float"]\n',
            "variadic-calls requires promoted scalars or scalar pointers",
        ),
        (
            'int number = fcntl(0, 1, "flags");',
            ["fcntl"],
            '[native.bindings.variadic-calls.fcntl]\narguments = ["int"]\n',
            "error: Argument 'variadicArgument0' to 'fcntl()' expects 'int' but got 'string'",
        ),
        (
            "union sockaddr* address = null; int number = connect(0, address, 0);",
            ["connect"],
            "",
            "error: Argument '__addr' to 'connect()' expects 'const sockaddr*' but got 'union sockaddr*'",
        ),
        (
            "long wide = 1; int number = probeRead(&wide);",
            ["probeRead"],
            "",
            "error: Argument 'value' to 'probeRead()' expects 'const int*' but got 'long*'",
        ),
    ],
)
def test_call_shape_diagnostics_match_across_compilers(
    reader, tmp_path, request, statement, symbols, extra, diagnostic
):
    del reader  # The compilers locate it through BTRC_NATIVE_HEADER_READER.
    program = f"int main() {{\n\t{statement}\n\treturn 0;\n}}\n"
    reports = []
    for frontend in ("python", "selfhost"):
        directory = tmp_path / frontend
        directory.mkdir()
        compiled, _, _ = _compile(directory, request, frontend, program, symbols, extra)
        assert compiled.returncode != 0, frontend
        lines = [line for line in compiled.stderr.splitlines() if diagnostic in line]
        assert lines, (frontend, compiled.stderr)
        # Each compiler frames a diagnostic its own way (a trailing `at line:col`,
        # a manifest context prefix); the message itself must match.
        reports.append(re.sub(r" at \d+:\d+$", "", lines[0][lines[0].index(diagnostic) :]))
    assert reports[0] == reports[1]


@pytest.mark.parametrize("arguments", ["0, 1", "0, 1, 2, 3"])
def test_whole_function_variadic_shape_fixes_the_arity(reader, tmp_path, request, arguments):
    """The tail is fixed, not open: too few or too many arguments are refused.

    The two analyzers word an arity error differently for every function (a
    missing named parameter, or an expected count), so this pins the refusal
    and the callee rather than the text.
    """

    del reader  # The compilers locate it through BTRC_NATIVE_HEADER_READER.
    program = f"int main() {{\n\treturn fcntl({arguments});\n}}\n"
    shape = '[native.bindings.variadic-calls.fcntl]\narguments = ["int"]\n'
    for frontend in ("python", "selfhost"):
        directory = tmp_path / frontend
        directory.mkdir()
        compiled, _, _ = _compile(directory, request, frontend, program, ["fcntl"], shape)
        assert compiled.returncode != 0, frontend
        assert "error: 'fcntl()'" in compiled.stderr, (frontend, compiled.stderr)


HTTP_PROGRAM = """import Library.Bytes;
import Library.HTTP.HTTPSocket;
import Library.LocalApplicationChannel;

int main() {
\tint listener = HTTPSocket.openListener(0, false);
\tif (listener < 0) { return 1; }
\tint client = HTTPSocket.acceptConnection(listener, 0);
\tHTTPSocket.closeConnection(listener);
\tLocalApplicationChannelConfiguration configuration = LocalApplicationChannelConfiguration.standard();
\tvar outcome = LocalApplicationChannelClient.request("", Bytes(), configuration, 100);
\tprintf("%d %d\\n", client < 0 ? 1 : 0, outcome.kind == LOCAL_APPLICATION_CHANNEL_REQUEST_INVALID ? 1 : 0);
\treturn 0;
}
"""


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_hosted_tags_and_imported_records_are_one_type(reader, tmp_path, request, frontend) -> None:
    """A module that writes `struct sockaddr*` and `struct pollfd` against its own
    hosted includes shares a program with the channel's imported `sockaddr`
    and `pollfd`; the tag aliases make each the same type, as it is in C."""

    del reader  # The compilers locate it through BTRC_NATIVE_HEADER_READER.
    source = tmp_path / "Main.btrc"
    source.write_text(HTTP_PROGRAM, encoding="utf-8")
    generated = tmp_path / "main.c"
    plan = tmp_path / "plan.json"
    flags = ["--strict-imports", "--no-cache", "--target", "linux-x64", "--emit-link-plan", str(plan), str(source)]
    command = (
        [sys.executable, "-m", "src.compiler.python.main", *flags, "-o", str(generated)]
        if frontend == "python"
        else [request.getfixturevalue("btrcc_bin"), *flags]
    )
    environment = {**os.environ, "BTRC_HOME": str(REPO / "src"), "BTRC_CACHE_DIR": str(tmp_path / "cache")}
    compiled = subprocess.run(
        command, cwd=REPO, env=environment, capture_output=True, text=True, timeout=TRANSPILE_TIMEOUT
    )
    assert compiled.returncode == 0, compiled.stderr
    if frontend == "selfhost":
        generated.write_text(compiled.stdout, encoding="utf-8")
    executable = tmp_path / "program"
    NativePlanBuilder().build(plan_path=plan, generated_c=generated, output=executable, cc="cc", cxx="c++")
    ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "1 1\n"
