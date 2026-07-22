"""Bootstrap fixed-point test for the self-hosted compiler (btrcc).

The self-hosted compiler is only truly "self-hosting" if it can compile its OWN
source and the result is stable: compiling the compiler with itself, then again
with that output, must yield byte-identical C (a fixed point). This walks the
three-stage bootstrap and asserts the fixed point:

    btrcc1 = cc(  btrcpy(compiler source) )      # reference-built (stage 1)
    btrcc2 = cc( btrcc1(compiler source) )       # self-built     (stage 2)
    btrcc3.c =   btrcc2(compiler source)         # self-built again (stage 3)
    assert btrcc2.c == btrcc3.c                  # FIXED POINT

It also confirms the self-built compiler is functional (compiles a sample
program to its golden output). Uses whatever C compiler `BTRC_CC` selects
(default `cc`), so it runs under gcc and clang alike.
"""

from __future__ import annotations

import contextlib
import filecmp
import os
import shlex
import shutil
import signal
import subprocess
import tempfile
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CC = shlex.split(os.environ.get("BTRC_CC", "cc"))
CFLAGS = shlex.split(os.environ.get("BTRC_CFLAGS", "-std=c11 -Wall -Wextra -Werror -pedantic -O2"))
LDLIBS = shlex.split(os.environ.get("BTRC_LDLIBS", "-lm" if os.name == "nt" else "-lm -lpthread"))
PYTHON = shlex.split(os.environ.get("BTRC_PYTHON", "python" if os.name == "nt" else "python3"))
BOOTSTRAP_TIMEOUT = int(os.environ.get("BTRC_BOOTSTRAP_TIMEOUT_SECONDS", "1200"))
EXE_SUFFIX = ".exe" if os.name == "nt" else ""


def _terminate_process_tree(process: subprocess.Popen) -> None:
    """Kill the bounded command and every descendant it may have spawned."""
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
            return
        except ProcessLookupError:
            return
        except OSError:
            pass
    elif os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    with contextlib.suppress(ProcessLookupError):
        process.kill()


def _run_process(cmd, *, cwd=REPO, timeout, **kwargs):
    """Run one bootstrap stage with a hard, descendant-aware deadline."""
    group_options = (
        {"start_new_session": True}
        if os.name == "posix"
        else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt"
        else {}
    )
    process = subprocess.Popen(cmd, cwd=cwd, **group_options, **kwargs)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _terminate_process_tree(process)
        stdout, stderr = process.communicate()
        raise subprocess.TimeoutExpired(
            process.args,
            timeout,
            output=stdout,
            stderr=stderr,
        ) from None
    except BaseException:
        _terminate_process_tree(process)
        process.communicate()
        raise
    return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)


def _run(cmd, *, cwd=REPO, timeout, **kwargs):
    return _run_process(
        cmd,
        cwd=cwd,
        timeout=timeout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **kwargs,
    )


def _transpile_with_python(project_root: str, data_root: str, in_btrc: str, out_c: str) -> None:
    """Stage 1 source: reference compiler transpiles the btrcc source to C."""
    # Use the platform command (overridable with BTRC_PYTHON), not
    # sys.executable: under xdist the worker can be a Nix env-wrapper path that
    # is not directly executable from a subprocess.
    r = _run(
        [
            *PYTHON,
            "-m",
            "src.compiler.python.main",
            in_btrc,
            "--strict-imports",
            "--no-cache",
            "-o",
            out_c,
        ],
        cwd=project_root,
        env={**os.environ, "BTRC_HOME": data_root, "PYTHONPATH": project_root},
        timeout=BOOTSTRAP_TIMEOUT,
    )
    assert r.returncode == 0 and os.path.exists(out_c), f"btrcpy failed to transpile btrcc:\n{r.stderr[:2000]}"


def _cc(src_c: str, out_bin: str, *, workdir: str) -> None:
    r = _run(
        [*CC, *CFLAGS, src_c, "-o", out_bin, *LDLIBS],
        cwd=workdir,
        timeout=BOOTSTRAP_TIMEOUT,
    )
    assert r.returncode == 0 and os.path.exists(out_bin), (
        f"{' '.join(CC)} failed to build {os.path.basename(src_c)}:\n{r.stderr[:3000]}"
    )


def _btrcc(binary: str, in_btrc: str, out_c: str, *, data_root: str, workdir: str) -> None:
    """Run a btrcc binary on a .btrc file, streaming emitted C to out_c."""
    output = os.path.join(REPO, out_c)
    with open(output, "w") as generated:
        r = _run_process(
            [binary, "--strict-imports", in_btrc],
            cwd=workdir,
            env={**os.environ, "BTRC_HOME": data_root},
            stdout=generated,
            stderr=subprocess.PIPE,
            text=True,
            timeout=BOOTSTRAP_TIMEOUT,
        )
    assert r.returncode == 0 and os.path.getsize(output) > 0, (
        f"{os.path.basename(binary)} failed on {in_btrc}:\n{r.stderr[:2000]}"
    )


def _snapshot_compiler_inputs(tmp_dir: str) -> tuple[str, str, str]:
    """Copy one immutable, local source snapshot for every bootstrap stage."""
    project_root = os.path.join(tmp_dir, "snapshot")
    source_root = os.path.join(project_root, "src")
    ignored = shutil.ignore_patterns("__pycache__", "*.pyc", "build")
    for relative in (
        os.path.join("compiler", "btrc"),
        os.path.join("compiler", "python"),
        "language",
        "stdlib",
    ):
        source = os.path.join(REPO, "src", relative)
        destination = os.path.join(source_root, relative)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copytree(source, destination, ignore=ignored)
    compiler = os.path.join(source_root, "compiler", "btrc", "btrcc_main.btrc")
    return project_root, source_root, compiler


@unittest.skipUnless(CC and shutil.which(CC[0]), "needs a C compiler")
class TestBootstrap(unittest.TestCase):
    def test_bootstrap_fixed_point_and_self_built_compiler_is_functional(self):
        """Prove the fixed point, then exercise that same self-built compiler."""
        with tempfile.TemporaryDirectory(prefix="btrc-bootstrap-") as d:
            project_root, data_root, compiler_source = _snapshot_compiler_inputs(d)
            c1 = os.path.join(d, "btrcc1.c")
            b1 = os.path.join(d, f"btrcc1{EXE_SUFFIX}")
            c2 = os.path.join(d, "btrcc2.c")
            b2 = os.path.join(d, f"btrcc2{EXE_SUFFIX}")
            c3 = os.path.join(d, "btrcc3.c")

            # Stage 1: reference compiler builds btrcc1.
            _transpile_with_python(project_root, data_root, compiler_source, c1)
            _cc(c1, b1, workdir=project_root)

            # Stage 2: btrcc1 compiles its OWN source -> btrcc2.
            _btrcc(b1, compiler_source, c2, data_root=data_root, workdir=project_root)
            _cc(c2, b2, workdir=project_root)

            # Stage 3: btrcc2 compiles its OWN source again.
            _btrcc(b2, compiler_source, c3, data_root=data_root, workdir=project_root)

            self.assertTrue(
                filecmp.cmp(c2, c3, shallow=False),
                "bootstrap not at a fixed point: btrcc2.c != btrcc3.c "
                "(the self-built compiler does not reproduce itself)",
            )

            sample = os.path.join(REPO, "src", "tests", "classes", "test_inherited_operator_overload.btrc")
            prog_c = os.path.join(d, "sample.c")
            prog_bin = os.path.join(d, f"sample{EXE_SUFFIX}")
            _btrcc(b2, sample, prog_c, data_root=data_root, workdir=project_root)
            _cc(prog_c, prog_bin, workdir=project_root)
            run = _run([prog_bin], cwd=project_root, timeout=30)
            self.assertEqual(run.returncode, 0, f"sample crashed: {run.stderr[:1000]}")
            golden = os.path.join(
                REPO,
                "src",
                "tests",
                "classes",
                "expected",
                "test_inherited_operator_overload.stdout",
            )
            with open(golden) as expected:
                self.assertEqual(run.stdout, expected.read(), "self-built compiler output != golden")


if __name__ == "__main__":
    unittest.main()
