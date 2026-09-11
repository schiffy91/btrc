import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import PackageTarget
from tools.native_plan import NativePlanBuilder, NativePlanReader

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "src" / "tests" / "native" / "local_application_channel"
CONFORMANCE = FIXTURE / "LocalApplicationChannelConformance.btrc"
EXPECTED = FIXTURE / "local_application_channel_conformance.expected"
COMPILE_TIMEOUT = 240
RUN_TIMEOUT = 30

PLANNED_CONSUMER = """\
import Library.Bytes;
import Library.LocalApplicationChannel;

int main() {
    LocalApplicationChannelConfiguration configuration = LocalApplicationChannelConfiguration.standard();
    LocalApplicationChannelClientOutcome rejected = LocalApplicationChannelClient.request("", Bytes(), configuration, 100);
    if (rejected.kind != LOCAL_APPLICATION_CHANNEL_REQUEST_INVALID) { return 2; }
    print("PASS: planned local application channel runtime");
    return 0;
}
"""


def _transpile(frontend: str, output: Path, request: pytest.FixtureRequest, source: Path = CONFORMANCE) -> None:
    target = PackageTarget.parse(None)
    target_text = f"{target.operating_system}-{target.architecture}"
    plan = output.with_suffix(".json")
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
            str(source),
            "--strict-imports",
            "--target",
            target_text,
            "--emit-link-plan",
            str(plan),
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
            [str(btrcc), "--strict-imports", "--target", target_text, "--emit-link-plan", str(plan), str(source)],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT,
        )
        if result.returncode == 0:
            output.write_text(result.stdout)
    assert result.returncode == 0 and output.is_file(), result.stderr


def _compile(c_compiler: str, generated: Path, executable: Path, *, sanitized: bool = False) -> None:
    environment = dict(os.environ)
    plan = NativePlanReader().read(generated.with_suffix(".json"))
    assert plan.units == ()
    definitions = [f"-D{name}={value}" if value else f"-D{name}" for name, value in plan.defines]
    sanitizer_flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitized else []
    sdk_flags = []
    if sanitized and sys.platform == "darwin":
        environment.pop("DEVELOPER_DIR", None)
        environment.pop("SDKROOT", None)
        sdk_flags = ["-isysroot", environment["BTRC_NATIVE_SYSROOT"], "-target", environment["BTRC_NATIVE_TARGET"]]
    flags = [
        *definitions,
        *sanitizer_flags,
        *sdk_flags,
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-pedantic-errors",
        *(f"-I{directory}" for directory in plan.include_directories),
    ]
    objects = []
    sources = [("generated", generated)]
    for name, source in sources:
        object_path = executable.with_suffix(f".{name}.o")
        result = subprocess.run(
            [c_compiler, *flags, "-c", str(source), "-o", str(object_path)],
            env=environment,
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT,
        )
        assert result.returncode == 0, result.stderr
        objects.append(object_path)
    result = subprocess.run(
        [c_compiler, *sanitizer_flags, *sdk_flags, *(str(path) for path in objects), "-o", str(executable)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=COMPILE_TIMEOUT,
    )
    assert result.returncode == 0, result.stderr


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


@pytest.mark.parametrize("sanitized", [False, True])
def test_local_channel_client_wire_and_lifetime(
    compiler: str, sanitized: bool, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    generated = tmp_path / "client.c"
    executable = tmp_path / "client"
    _transpile(compiler, generated, request, FIXTURE / "LocalChannelClientConformance.btrc")
    c_compiler = "/usr/bin/clang" if sanitized and sys.platform == "darwin" else "clang"
    _compile(c_compiler, generated, executable, sanitized=sanitized)
    ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "PASS: local channel client wire and lifetime\n"
    assert ran.stderr == ""


@pytest.mark.parametrize("c_compiler,sanitized", [("gcc", False), ("clang", False), ("clang", True)])
def test_local_channel_server_ownership_and_framing(
    compiler: str, c_compiler: str, sanitized: bool, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    generated = tmp_path / "server.c"
    executable = tmp_path / "server"
    _transpile(compiler, generated, request, FIXTURE / "LocalChannelServerConformance.btrc")
    if sanitized and sys.platform == "darwin":
        c_compiler = "/usr/bin/clang"
    _compile(c_compiler, generated, executable, sanitized=sanitized)
    ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "PASS: local channel server ownership and framing\n"
    assert ran.stderr == ""


def test_import_emits_and_links_compiler_owned_local_channel(
    compiler: str, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    target = PackageTarget.parse(None)
    target_text = f"{target.operating_system}-{target.architecture}"
    project = tmp_path / "project"
    project.mkdir()
    source = project / "Main.btrc"
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
    assert payload["units"] == []
    executable = tmp_path / f"planned-{compiler}"
    NativePlanBuilder().build(plan_path=plan, generated_c=generated, output=executable)
    ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "PASS: planned local application channel runtime\n"
    assert ran.stderr == ""
