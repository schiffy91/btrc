"""Library.Process on Windows: the CreateProcessW provider (CX-P2-06) over the runtime seam (CL-P2-02).

The root btrc.toml selects Process's private host seam per row:
Windows/ProcessHostProvider on windows rows and the selection-only
Unix/ProcessHostProvider shell everywhere else, where Process.btrc's POSIX
bodies stay as they were (docs/design/windows-os-services.md, "Process and
shell"). This test proves that selection through both frontends on every
target row, and builds src/tests/native/process_windows/ProcessWindows.btrc
with both compilers for x64 and ARM64 Windows, linking the runtime object the
emitted C retains exactly as the target runner and the native-plan builder
do. With BTRC_WIN32_EVIDENCE_DIR set the executables are copied there;
windows.yml's process-native job runs each beside the launch harness on a
Windows runner of its architecture, where the fixture checks argv quoting
(non-ASCII included), exit codes, a deadline that kills a three-level tree,
the UnixShell, descriptor and foreground refusals, the Windows environment
grammar, stdin, cwd and capture limits.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.abi.generated import TARGET_ROWS
from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.runtime.generated import RUNTIME_HELPER_ROWS
from src.tests.process_limits import TOOL_TIMEOUT, TRANSPILE_TIMEOUT
from src.tests.target_runner import FRONTENDS, TargetBundle, TargetCorpusRunner
from tools.compiler_codegen.runtime import RuntimeManifest
from tools.native_plan import RuntimeObjects, TargetToolchain

REPO = Path(__file__).resolve().parents[3]
FIXTURE = REPO / "src" / "tests" / "native" / "process_windows" / "ProcessWindows.btrc"
HARNESS = REPO / "src" / "tests" / "native" / "windows_launch" / "launch_harness.c"
RUNTIME = REPO / "src" / "runtime" / "c"
ROWS = {row.label: row for row in TARGET_ROWS}
TARGETS = {"windows-x64": "windows-x86_64", "windows-arm64": "windows-aarch64"}
STRICT = ["-pedantic-errors", "-Wall", "-Wextra", "-Werror", "-O2"]
PASS_LINE = "process-windows PASS checks="

RUN = """import Library.Process;

int main() {
	ExecResult result = ChildProcess.run("tool", ["x"]);
	return result.code;
}
"""
RELAXED = """int main() {
	ExecResult result = ChildProcess.run("tool", ["x"]);
	return result.code;
}
"""
RENDER = """import Library.Process;

int main() {
	print(Command("tool").arg("a b").render());
	return 0;
}
"""

SUPERVISOR = """#include <stddef.h>
#include <stdint.h>

int main() {
    __btrc_windows_supervisor_owner* owner = NULL;
    __btrc_windows_launch_error_t error;
    size_t required = 0;
    uint32_t delivered = 0;
    uint32_t running = 0;
    uint32_t code = 0;
    int status = __btrc_windows_supervisor_accept(1000, &owner, &error);
    status += __btrc_windows_supervisor_copy_startup(owner, NULL, 0, &required, &error);
    status += __btrc_windows_supervisor_prepare(owner, &error);
    status += __btrc_windows_supervisor_ready_wait_commit(owner, &error);
    status += __btrc_windows_supervisor_ack(owner, &delivered, &error);
    status += __btrc_windows_supervisor_spawn_managed(owner, &error);
    status += __btrc_windows_supervisor_poll_managed(owner, &running, &code, &error);
    status += __btrc_windows_supervisor_terminate_managed(owner, 1, &error);
    status += __btrc_windows_supervisor_close(&owner, 1000, &error);
    return status;
}
"""


DAEMON_FILES = """#include <stddef.h>
#include <stdint.h>

int main() {
    __btrc_windows_daemon_file_owner* directory = NULL;
    __btrc_windows_daemon_file_owner* file = NULL;
    __btrc_windows_daemon_directory_entry entry;
    __btrc_windows_launch_error_t error;
    unsigned char buffer[32];
    size_t count = 0;
    uint32_t state = 0;
    int status = __btrc_windows_daemon_directory_open(NULL, 0, 0, &directory, &error);
    status += __btrc_windows_daemon_directory_path(directory, buffer, 32, &count, &error);
    status += __btrc_windows_daemon_directory_next(directory, 0, buffer, 32, &count, &entry, &error);
    status += __btrc_windows_daemon_control_open(NULL, 0, 0, &file, &error);
    status += __btrc_windows_daemon_control_open_at(directory, buffer, count, 0, &entry, &file, &error);
    status += __btrc_windows_daemon_file_read(file, 0, buffer, 32, &count, &error);
    status += __btrc_windows_daemon_file_write(file, 0, buffer, count, &count, &error);
    status += __btrc_windows_daemon_file_flush(file, &error);
    status += __btrc_windows_daemon_file_dispose(file, &state, &error);
    status += __btrc_windows_daemon_log_open(NULL, 0, &file, &error);
    status += __btrc_windows_daemon_record_open(NULL, 0, buffer, 0, &file, &error);
    status += __btrc_windows_daemon_file_close(&file, &error);
    status += __btrc_windows_daemon_file_close(&directory, &error);
    return status + (int)entry.present + (int)entry.kind + (int)(entry.volume & 1) + (int)entry.file_id[15];
}
"""


def transpile(frontend: str, source: Path, label: str, request, *, relaxed: bool = False) -> str:
    if frontend == "reference":
        result = Compiler().compile(
            source.read_text(encoding="utf-8"),
            str(source),
            CompilerOptions(use_cache=False, use_ast_cache=False, target=label, strict_imports=not relaxed),
        )
        assert result.c_source is not None, (result.failure, result.diagnostics)
        return result.c_source
    btrcc = request.getfixturevalue("immutable_btrcc")
    completed = subprocess.run(
        [str(btrcc), "--no-cache", *(["--relaxed-imports"] if relaxed else []), "--target", label, str(source)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=TRANSPILE_TIMEOUT,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("label", sorted(ROWS))
@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_every_row_resolves_the_process_provider(frontend, label, request, tmp_path):
    c_source = transpile(frontend, write(tmp_path, "Render.btrc", RENDER), label, request)
    assert "ProcessHostProvider" not in c_source
    assert RuntimeObjects.selected([c_source]) == ()


@pytest.mark.parametrize("label", sorted(ROWS))
@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_only_windows_gnu_rows_launch_through_the_runtime_seam(frontend, label, request, tmp_path):
    """The gnu rows launch through windows_os.c, the unqualified MSVC row
    refuses (its C names neither seam), every other row keeps the POSIX body."""
    c_source = transpile(frontend, write(tmp_path, "Run.btrc", RUN), label, request)
    row = ROWS[label]
    windows = row.operating_system == "windows"
    seam = windows and row.environment == "gnu"
    assert [selected.source for selected in RuntimeObjects.selected([c_source])] == (["windows_os.c"] if seam else [])
    # The provider retains these windows_os.h sections verbatim, and nothing else of the seam.
    sections = {row.name: row.c_source.strip() for row in RUNTIME_HELPER_ROWS}
    retained = (
        "__btrc_windows_launch_types",
        "__btrc_windows_launch",
        "__btrc_windows_launch_wait",
        "__btrc_windows_launch_copy_output",
        "__btrc_windows_launch_close",
    )
    for helper in retained:
        assert (sections[helper] in c_source) is seam, helper
    for helper in ("__btrc_windows_launch_terminate", "__btrc_windows_quote_argv_utf8"):
        assert sections[helper] not in c_source, helper
    assert ("ChildProcess.run is unavailable on windows-msvc" in c_source) is (windows and not seam)
    for posix in ("fork(", "execve(", "waitpid(", "__btrc_posix_spawn_cloexec("):
        assert (posix in c_source) is not windows, posix


@pytest.mark.parametrize("label", sorted(ROWS))
@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_relaxed_composition_loads_the_selected_provider(frontend, label, request, tmp_path):
    """Relaxed imports (and the prebuilt archive) compose the root modules, then the
    providers the root manifest selects for the row, as the strict graph loads them."""
    c_source = transpile(frontend, write(tmp_path, "Relaxed.btrc", RELAXED), label, request, relaxed=True)
    row = ROWS[label]
    seam = row.operating_system == "windows" and row.environment == "gnu"
    assert [selected.source for selected in RuntimeObjects.selected([c_source])] == (["windows_os.c"] if seam else [])
    assert ("fork(" in c_source) is (row.operating_system != "windows")


def build(c_source: str, label: str, executable: Path, work: Path) -> None:
    """The target runner's build: the generated unit with the Windows overlay,
    each retained runtime object as its own unit, one link."""
    toolchain = TargetToolchain(ROWS[label])
    generated = work / f"{executable.stem}.c"
    generated.write_text(c_source, encoding="utf-8")
    objects = [work / f"{executable.stem}.o"]
    commands = [toolchain.compile_command(generated, objects[0], generated=True, flags=STRICT)]
    rows = RuntimeObjects.selected([c_source])
    for index, source in enumerate(RuntimeObjects.sources(rows)):
        objects.append(work / f"{executable.stem}.runtime-{index}.o")
        commands.append(toolchain.compile_command(source, objects[-1], generated=False, flags=STRICT))
    commands.append(
        [
            *toolchain.drivers["cc"],
            *toolchain.arguments,
            *(str(path) for path in objects),
            *RuntimeObjects.library_flags(rows, ROWS[label].operating_system),
            *toolchain.runtime_libraries(),
            "-o",
            str(executable),
        ]
    )
    for command in commands:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=TOOL_TIMEOUT, check=False)
        assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("label", sorted(TARGETS.values()))
@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_supervisor_seam_emits_sdk_free_declarations_and_links(frontend, label, request, tmp_path):
    c_source = transpile(frontend, write(tmp_path, "SupervisorSeam.btrc", SUPERVISOR), label, request)
    assert [row.source for row in RuntimeObjects.selected([c_source])] == ["windows_os.c"]
    for row in RuntimeManifest.load(RUNTIME / "manifest.toml").helpers:
        if row.name.startswith("__btrc_windows_supervisor_") and row.asset == "windows_os.h":
            assert row.source.strip() in c_source, row.name
    assert "#include <windows.h>" not in c_source
    build(c_source, label, tmp_path / "supervisor-seam.exe", tmp_path)


@pytest.mark.parametrize("label", sorted(TARGETS.values()))
@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_daemon_file_seam_emits_sdk_free_declarations_and_links(frontend, label, request, tmp_path):
    c_source = transpile(frontend, write(tmp_path, "DaemonFileSeam.btrc", DAEMON_FILES), label, request)
    assert [row.source for row in RuntimeObjects.selected([c_source])] == ["windows_os.c"]
    for row in RuntimeManifest.load(RUNTIME / "manifest.toml").helpers:
        if row.name.startswith("__btrc_windows_daemon_") and row.asset == "windows_os.h":
            assert row.source.strip() in c_source, row.name
    assert "#include <windows.h>" not in c_source
    build(c_source, label, tmp_path / "daemon-file-seam.exe", tmp_path)


def build_harness(label: str, executable: Path) -> None:
    toolchain = TargetToolchain(ROWS[label])
    completed = subprocess.run(
        [
            *toolchain.drivers["cc"],
            *toolchain.arguments,
            "-std=c11",
            *STRICT,
            "-I",
            str(RUNTIME),
            str(HARNESS),
            str(RUNTIME / "windows_os.c"),
            "-o",
            str(executable),
            "-lshell32",
        ],
        capture_output=True,
        text=True,
        timeout=TOOL_TIMEOUT,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


# The corpus programs that exercise Library.Process (target-applicability.toml
# decides each one's Windows verdict).
CORPUS = (
    "stdlib/ChildProcess*.btrc",
    "stdlib/CommandBuilder.btrc",
    "stdlib/Environment.btrc",
    "stdlib/Process.btrc",
    "stdlib/ProcessStatusPipe.btrc",
    "stdlib/ShellCwdEnv.btrc",
    "stdlib/Shellwords.btrc",
)
WINDOWS_CORPUS = {
    "stdlib/ChildProcess.btrc": "built",
    "stdlib/ChildProcessClosedFds.btrc": "restricted",
    "stdlib/ChildProcessDescriptor.btrc": "restricted",
    "stdlib/ChildProcessDescriptorMapping.btrc": "restricted",
    "stdlib/CommandBuilder.btrc": "built",
    "stdlib/Environment.btrc": "built",
    "stdlib/Process.btrc": "built",
    "stdlib/ProcessStatusPipe.btrc": "built",
    "stdlib/ShellCwdEnv.btrc": "built",
    "stdlib/Shellwords.btrc": "built",
}


@pytest.mark.parametrize("target", sorted(TARGETS))
def test_process_corpus_builds_for_windows_through_both_frontends(target, immutable_btrcc, tmp_path):
    """The target runner's compile-only bundle; windows.yml's process step runs
    it with the windows-native executor against the same goldens."""
    evidence = os.environ.get("BTRC_WIN32_EVIDENCE_DIR")
    bundle = Path(evidence) / f"process-corpus-{target}" if evidence else tmp_path / "bundle"
    runner = TargetCorpusRunner(
        TARGETS[target], FRONTENDS, output=tmp_path / "run", bundle=bundle, btrcc=immutable_btrcc, programs=CORPUS
    )
    report = runner.run(compile_only=True)
    assert not report.failed, [outcome.as_dict() for outcome in report.outcomes if outcome.status == "failed"]
    statuses = {
        (entry["source"], entry["frontend"]): entry["status"] for entry in TargetBundle.load(bundle).programs.values()
    }
    assert statuses == {
        (source, frontend): status for source, status in WINDOWS_CORPUS.items() for frontend in FRONTENDS
    }


@pytest.mark.parametrize("target", sorted(TARGETS))
@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_process_fixture_builds_for_windows(frontend, target, request, tmp_path):
    label = TARGETS[target]
    c_source = transpile(frontend, FIXTURE, label, request)
    assert [row.source for row in RuntimeObjects.selected([c_source])] == ["windows_os.c"]
    executable = tmp_path / f"process-windows-{frontend}-{target}.exe"
    build(c_source, label, executable, tmp_path)
    harness = tmp_path / f"windows-launch-seam-{target}.exe"
    build_harness(label, harness)
    assert executable.read_bytes()[:2] == b"MZ"
    evidence = os.environ.get("BTRC_WIN32_EVIDENCE_DIR")
    if evidence:
        Path(evidence).mkdir(parents=True, exist_ok=True)
        shutil.copy2(executable, Path(evidence) / executable.name)
        shutil.copy2(harness, Path(evidence) / harness.name)
    if sys.platform == "win32":
        ran = subprocess.run(
            [str(executable), "--parent", str(harness)], capture_output=True, text=True, timeout=600, check=False
        )
        last = ran.stdout.strip().splitlines()[-1] if ran.stdout.strip() else ""
        assert ran.returncode == 0 and last.startswith(PASS_LINE), (ran.stdout, ran.stderr)
