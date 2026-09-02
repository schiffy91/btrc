import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import PackageTarget
from tools.native_plan import NativePlanBuilder

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT / "src" / "stdlib" / "local_application_channel"
FIXTURE = ROOT / "src" / "tests" / "native" / "local_application_channel"
CONFORMANCE = FIXTURE / "local_application_channel_conformance.btrc"
EXPECTED = FIXTURE / "local_application_channel_conformance.expected"
FAULTS = FIXTURE / "local_application_channel_faults.c"
COMPILE_TIMEOUT = 240
RUN_TIMEOUT = 30
PACKAGE_NAME = "btrc_stdlib_local_application_channel_runtime"

PLANNED_CONSUMER = """\
import std.bytes;
import std.local_application_channel;

int main() {
    LocalApplicationChannelConfiguration configuration = LocalApplicationChannelConfiguration.standard();
    LocalApplicationChannelClientOutcome rejected = LocalApplicationChannelClient.request("", Bytes(), configuration, 100);
    if (rejected.kind != LOCAL_APPLICATION_CHANNEL_REQUEST_INVALID) { return 2; }
    print("PASS: planned local application channel runtime");
    return 0;
}
"""


def _transpile(frontend: str, output: Path, request: pytest.FixtureRequest) -> None:
    environment = {
        **os.environ,
        "BTRC_CACHE_DIR": str(output.parent / f"cache-{frontend}"),
        "BTRC_HOME": str(ROOT / "src"),
    }
    if frontend == "python":
        command = [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            str(CONFORMANCE),
            "--strict-imports",
            "--no-cache",
            "-o",
            str(output),
        ]
        result = subprocess.run(
            command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=COMPILE_TIMEOUT
        )
    else:
        btrcc = request.getfixturevalue("immutable_btrcc")
        result = subprocess.run(
            [str(btrcc), "--strict-imports", str(CONFORMANCE)],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT,
        )
        if result.returncode == 0:
            output.write_text(result.stdout)
    assert result.returncode == 0 and output.is_file(), result.stderr


def _compile(c_compiler: str, generated: Path, executable: Path) -> None:
    flags = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic-errors", f"-I{RUNTIME}"]
    objects = []
    for name, source in (("generated", generated), ("runtime", RUNTIME / "btrc_local_application_channel.c")):
        object_path = executable.with_suffix(f".{name}.o")
        result = subprocess.run(
            [c_compiler, *flags, "-c", str(source), "-o", str(object_path)],
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT,
        )
        assert result.returncode == 0, result.stderr
        objects.append(object_path)
    result = subprocess.run(
        [c_compiler, *(str(path) for path in objects), "-o", str(executable)],
        capture_output=True,
        text=True,
        timeout=COMPILE_TIMEOUT,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("c_compiler", ["gcc", "clang"])
def test_local_application_channel_native_faults(c_compiler: str, tmp_path: Path) -> None:
    if not shutil.which(c_compiler):
        pytest.skip(f"{c_compiler} is unavailable")
    executable = tmp_path / f"local-channel-faults-{c_compiler}"
    command = [
        c_compiler,
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-pedantic-errors",
        f"-I{RUNTIME}",
        str(FAULTS),
        str(RUNTIME / "btrc_local_application_channel.c"),
        "-o",
        str(executable),
    ]
    built = subprocess.run(command, capture_output=True, text=True, timeout=COMPILE_TIMEOUT)
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "PASS: local application channel faults\n"
    assert ran.stderr == ""


@pytest.mark.parametrize("c_compiler", ["gcc", "clang"])
def test_local_application_channel_on_both_frontends_and_c_compilers(
    compiler: str, c_compiler: str, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    if not shutil.which(c_compiler):
        pytest.skip(f"{c_compiler} is unavailable")
    generated = tmp_path / f"local-channel-{compiler}-{c_compiler}.c"
    executable = tmp_path / f"local-channel-{compiler}-{c_compiler}"
    _transpile(compiler, generated, request)
    _compile(c_compiler, generated, executable)
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert result.returncode == 0, result.stderr
    assert result.stdout == EXPECTED.read_text()
    assert result.stderr == ""


def test_import_emits_and_links_compiler_owned_local_channel(
    compiler: str, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    target = PackageTarget.parse(None)
    target_text = f"{target.operating_system}-{target.architecture}"
    project = tmp_path / "project"
    project.mkdir()
    source = project / "main.btrc"
    source.write_text(PLANNED_CONSUMER)
    (project / "btrc.toml").write_text('manifest-version = 1\n\n[package]\nname = "planned_local_channel"\n')
    generated = tmp_path / f"planned-{compiler}.c"
    plan = tmp_path / f"planned-{compiler}.json"
    environment = {**os.environ, "BTRC_CACHE_DIR": str(tmp_path / f"cache-{compiler}"), "BTRC_HOME": str(ROOT / "src")}
    if compiler == "python":
        command = [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            "--strict-imports",
            "--no-cache",
            "--target",
            target_text,
            "--emit-link-plan",
            str(plan),
            str(source),
            "-o",
            str(generated),
        ]
        completed = subprocess.run(
            command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=COMPILE_TIMEOUT
        )
    else:
        btrcc = request.getfixturevalue("immutable_btrcc")
        command = [str(btrcc), "--strict-imports", "--target", target_text, "--emit-link-plan", str(plan), str(source)]
        completed = subprocess.run(
            command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=COMPILE_TIMEOUT
        )
        if completed.returncode == 0:
            generated.write_text(completed.stdout)
    assert completed.returncode == 0, completed.stderr
    if compiler == "btrc":
        reference_generated = tmp_path / "planned-reference.c"
        reference_plan = tmp_path / "planned-reference.json"
        reference = subprocess.run(
            [
                sys.executable,
                "-m",
                "src.compiler.python.main",
                "--strict-imports",
                "--no-cache",
                "--target",
                target_text,
                "--emit-link-plan",
                str(reference_plan),
                str(source),
                "-o",
                str(reference_generated),
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT,
        )
        assert reference.returncode == 0, reference.stderr
        assert plan.read_bytes() == reference_plan.read_bytes()
    payload = json.loads(plan.read_text())
    assert [unit for unit in payload["units"] if unit["package"] == PACKAGE_NAME] == [
        {
            "language": "c",
            "package": PACKAGE_NAME,
            "path": str(RUNTIME / "btrc_local_application_channel.c"),
            "standard": "c11",
        }
    ]
    executable = tmp_path / f"planned-{compiler}"
    NativePlanBuilder().build(plan_path=plan, generated_c=generated, output=executable)
    ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "PASS: planned local application channel runtime\n"
    assert ran.stderr == ""
