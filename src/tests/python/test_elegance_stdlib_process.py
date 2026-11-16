"""Tests for unified Library.Process execution: pipe-backed stdinBytes with NULs,
large concurrent stdin/stdout streaming without pipe deadlock, check=true failures,
PipeProcess interactive streaming, BackgroundProcess lifecycle, and Python/btrcc parity."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.results import CompilerOptions
from src.tests.c_toolchains import HOST_C_COMPILERS

PROCESS_SUITE_SOURCE = """
import Library.Bytes;
import Library.Process;
import Library.Strings;
import Library.Testing;
import Library.Vector;

int main(Vector<string> args) {
\tExpect.intEq((long long)args.length, 1LL, "expected python executable path");
\tstring py = args[0];

\t/* 1. Binary stdinBytes + stdoutBytes round-trip with embedded NULs. */
\tBytes binaryIn = Bytes();
\tbinaryIn.push((uint8_t)0);
\tbinaryIn.push((uint8_t)65);
\tbinaryIn.push((uint8_t)0);
\tbinaryIn.push((uint8_t)255);
\tbinaryIn.push((uint8_t)10);
\tbinaryIn.push((uint8_t)0);
\tExecResult echoed = Process.run(
\t\tpy,
\t\t["-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"],
\t\tstdinBytes=binaryIn,
\t\tcheck=true
\t);
\tExpect.bytesEq(echoed.stdoutBytes(), binaryIn, "binary stdinBytes roundtrip");

\t/* 2. Concurrent >192 KiB stdin + stdout without pipe deadlock or /tmp files. */
\tBytes largeIn = Bytes();
\tfor (int i = 0; i < 196608; i++) {
\t\tlargeIn.push((uint8_t)(i & 255));
\t}
\tExecResult largeEcho = Process.run(
\t\tpy,
\t\t["-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"],
\t\tstdinBytes=largeIn,
\t\tcheck=true
\t);
\tExpect.intEq((long long)largeEcho.stdoutBytes().length, 196608LL, "large pipe length");
\tExpect.bytesEq(largeEcho.stdoutBytes(), largeIn, "large pipe content");

\t/* 3. check=true throws on non-zero exit status. */
\tExpect check = Expect();
\tcheck.throwsWith(py, (string pythonBin) => {
\t\tProcess.run(
\t\t\tpythonBin,
\t\t\t["-c", "import sys; sys.stderr.write('boom-err'); sys.exit(17)"],
\t\t\tcheck=true
\t\t);
\t}, "boom-err");

\t/* 4. Interactive line-by-line PipeProcess via Process.pipe. */
\tPipeProcess pipe = Process.pipe(
\t\tpy,
\t\t["-u", "-c", "import sys\\nfor line in sys.stdin:\\n    sys.stdout.write('ack:' + line)\\n    sys.stdout.flush()"]
\t);
\tpipe.writeLine("first");
\tstring? r1 = pipe.readLine();
\tExpect.strEq(r1 ?? "", "ack:first");
\tpipe.writeLine("second");
\tstring? r2 = pipe.readLine();
\tExpect.strEq(r2 ?? "", "ack:second");
\tpipe.closeInput();
\tExpect.isTrue(pipe.readLine() == null, "EOF after closeInput");
\tExpect.intEq((long long)pipe.wait(), 0LL);

\t/* 5. Managed BackgroundProcess via Process.start with killOnDrop and stop(). */
\tBackgroundProcess bg = Process.start(
\t\tpy,
\t\t["-c", "import time; time.sleep(30)"],
\t\tstdout=COMMAND_OUTPUT_SUPPRESS,
\t\tstderr=COMMAND_OUTPUT_SUPPRESS,
\t\tkillOnDrop=true
\t);
\tExpect.isTrue(bg.pid() > 0);
\tExpect.isTrue(bg.isRunning());
\tbg.stop(500);
\tExpect.isFalse(bg.isRunning());

\t/* 6. Process.shell with stdinBytes. */
\tExecResult shOut = Process.shell("cat", stdinBytes=Bytes.fromString("shell-ok"), check=true);
\tExpect.strEq(shOut.out, "shell-ok");

\t/* 7. Synchronous exec-failure reporting for PipeProcess and BackgroundProcess. */
\tcheck.throwsWith("/definitely/missing/btrc-cmd", (string missingPath) => {
\t\tPipeProcess p = Process.pipe(missingPath);
\t\tp.close();
\t}, "missing");
\tcheck.throwsWith("/definitely/missing/btrc-cmd", (string missingPath) => {
\t\tBackgroundProcess b = Process.start(missingPath);
\t\tb.stop();
\t}, "missing");
\treturn 0;
}
"""


@pytest.mark.skipif(sys.platform == "win32", reason="exercises POSIX pipe/shell process APIs")
@pytest.mark.skipif(not HOST_C_COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", HOST_C_COMPILERS, ids=lambda path: Path(path).name)
def test_unified_process_api_executes_and_matches_across_compilers(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    src_file = tmp_path / "ProcessElegance.btrc"
    src_file.write_text(PROCESS_SUITE_SOURCE, encoding="utf-8")

    py_result = Compiler().compile(
        PROCESS_SUITE_SOURCE,
        str(src_file),
        CompilerOptions(use_cache=False),
    )
    assert py_result.successful, py_result.failure or py_result.diagnostics
    assert py_result.c_source is not None

    c_file = tmp_path / "ProcessElegance.c"
    exe = tmp_path / "ProcessElegance"
    c_file.write_text(py_result.c_source, encoding="utf-8")
    build = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(c_file),
            "-o",
            str(exe),
            "-lm",
            "-lpthread",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert build.returncode == 0, build.stderr

    ran = subprocess.run(
        [str(exe), sys.executable],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert ran.returncode == 0, (ran.stdout, ran.stderr)
