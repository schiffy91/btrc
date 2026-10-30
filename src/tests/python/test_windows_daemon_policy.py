"""BTRC daemon file policy against deterministic seam failures, without Windows claims."""

import subprocess
from pathlib import Path

import pytest

from src.compiler.python.abi.hosted import TargetRepository
from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.results import CompilerOptions
from src.tests.c_toolchains import configured_c_compiler
from src.tests.process_limits import C_COMPILE_TIMEOUT, RUN_TIMEOUT
from src.tests.python.test_windows_process import TARGETS, build, transpile
from tools.native_plan import RuntimeObjects

REPO = Path(__file__).resolve().parents[3]
NATIVE = REPO / "src/tests/native/daemon_windows"
RUNTIME = REPO / "src/runtime/c"


@pytest.fixture(scope="module", params=["reference", "selfhost"])
def control_store(request, tmp_path_factory):
    work = tmp_path_factory.mktemp(f"control-store-{request.param}")
    # Keep the production module private. Exercise its exact bytes in an
    # isolated package alongside the policy client.
    (work / "DaemonControlStore.btrc").write_bytes(
        (REPO / "src/stdlib/Daemon/Windows/DaemonControlStore.btrc").read_bytes()
    )
    client = work / "ControlStore.btrc"
    client.write_bytes((NATIVE / "ControlStore.btrc").read_bytes())
    target = TargetRepository.host()
    assert target is not None
    source = transpile(request.param, client, target.label, request)
    generated = work / "policy.c"
    generated.write_text(source, encoding="utf-8")
    executable = work / "policy"
    result = subprocess.run(
        [
            *configured_c_compiler(),
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            "-I",
            str(RUNTIME),
            str(generated),
            str(NATIVE / "control_store_fake.c"),
            "-o",
            str(executable),
            "-lm",
            "-lpthread",
        ],
        capture_output=True,
        text=True,
        timeout=C_COMPILE_TIMEOUT,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return executable


@pytest.mark.parametrize("scenario", range(1, 16))
def test_control_file_policy_preserves_identity_errors_and_ownership(control_store, scenario):
    result = subprocess.run(
        [str(control_store), str(scenario)], capture_output=True, text=True, timeout=RUN_TIMEOUT, check=False
    )
    assert result.returncode == 0, (scenario, result.stdout, result.stderr)


@pytest.fixture(scope="module", params=["reference", "selfhost"])
def supervisor_policy(request, tmp_path_factory):
    work = tmp_path_factory.mktemp(f"supervisor-policy-{request.param}")
    target = TargetRepository.host()
    assert target is not None
    entry = REPO / "src/stdlib/Daemon/Windows/DaemonSupervisorMain.btrc"
    source = transpile(request.param, entry, target.label, request)
    generated = work / "supervisor.c"
    generated.write_text(source, encoding="utf-8")
    object_file = work / "supervisor.o"
    executable = work / "supervisor-policy"
    flags = [
        *configured_c_compiler(),
        "-std=c11",
        "-pedantic-errors",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-O2",
        "-I",
        str(RUNTIME),
    ]
    commands = [
        [*flags, "-Dmain=daemon_policy_main", "-c", str(generated), "-o", str(object_file)],
        [
            *flags,
            str(object_file),
            str(NATIVE / "supervisor_policy_fake.c"),
            "-o",
            str(executable),
            "-lm",
            "-lpthread",
        ],
    ]
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True, timeout=C_COMPILE_TIMEOUT, check=False)
        assert result.returncode == 0, result.stderr
    return executable


@pytest.mark.parametrize("scenario", range(1, 20))
def test_supervisor_commit_liveness_restart_and_cleanup(supervisor_policy, scenario):
    result = subprocess.run(
        [str(supervisor_policy), str(scenario)], capture_output=True, text=True, timeout=RUN_TIMEOUT, check=False
    )
    assert result.returncode == 0, (scenario, result.stdout, result.stderr)


@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
@pytest.mark.parametrize("label", sorted(TARGETS.values()))
def test_production_supervisor_links_without_consumer_metadata(frontend, label, request, tmp_path):
    entry = REPO / "src/stdlib/Daemon/Windows/DaemonSupervisorMain.btrc"
    source = transpile(frontend, entry, label, request)
    assert [row.source for row in RuntimeObjects.selected([source])] == ["windows_os.c"]
    assert "__btrc_windows_daemon_metadata" not in source
    build(source, label, tmp_path / "daemon-supervisor.exe", tmp_path)


def test_production_supervisor_has_no_recursive_auxiliary_plan():
    entry = REPO / "src/stdlib/Daemon/Windows/DaemonSupervisorMain.btrc"
    result = Compiler().compile(
        entry.read_text(),
        str(entry),
        CompilerOptions(use_cache=False, use_ast_cache=False, target="windows-x86_64", strict_imports=True),
    )
    assert result.successful, (result.failure, result.diagnostics)
    assert "auxiliary-executables" not in result.native_plan.as_dict()
