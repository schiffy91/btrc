"""Debug builds keep the files a real Darwin debugger reads after linking."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import NativeGeneratedUnit, NativeLinkPlan, PackageTarget
from tools.native_plan import NativePlanBuilder, NativePlanError

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="Darwin executable debug maps reference object files")


def debug_build(tmp_path, *, cached=True):
    source = tmp_path / "program.c"
    source.write_text("int answer(void); int main(void) { return answer() == 42 ? 0 : 1; }\n")
    payload = NativeLinkPlan(
        PackageTarget.parse(None),
        generated_units=(
            NativeGeneratedUnit("Answer", "c", "c11", "manual", "int answer(void) {\n    return 42;\n}\n"),
        ),
    ).as_dict()
    plan = tmp_path / "program.link.json"
    plan.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    return dict(
        plan_path=plan,
        generated_c=source,
        output=tmp_path / "program",
        debug_info=True,
        optimization=0,
        object_cache=tmp_path / "cache" if cached else None,
        cc="/usr/bin/clang",
        cxx="/usr/bin/clang++",
    )


def check_debugger(output, adapter, *, function="answer", line=2):
    # Symbol lookup uses the executable's actual debug map, without launching
    # an inferior or relying on host ptrace permissions.
    result = subprocess.run(
        [
            "/usr/bin/lldb",
            "--no-lldbinit",
            "--batch",
            str(output),
            "-o",
            f"image lookup -v -n {function}",
            "-o",
            f'breakpoint set --file "{adapter}" --line {line}',
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    line_entries = [entry for entry in result.stdout.splitlines() if "LineEntry:" in entry]
    assert any(f"{adapter}:" in entry for entry in line_entries), result.stdout + result.stderr
    assert "no locations" not in result.stdout and "locations = 0" not in result.stdout, result.stdout
    assert "LineEntry:" in result.stdout, result.stdout
    debug_map = subprocess.run(
        ["/usr/bin/dsymutil", "--dump-debug-map", str(output)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert debug_map.returncode == 0 and not debug_map.stderr, debug_map.stderr
    assert "objects:" in debug_map.stdout, debug_map.stdout


@pytest.mark.parametrize("cached", [False, True])
def test_debugger_reads_objects_and_adapter_sources_after_build(tmp_path, cached):
    options = debug_build(tmp_path, cached=cached)
    cold = NativePlanBuilder().build(**options)
    output = options["output"]
    adapter = Path(cold.units[-1].source)
    check_debugger(output, adapter)
    assert adapter.read_text() == "int answer(void) {\n    return 42;\n}\n"
    objects = [Path(argument) for argument in cold.link_command if argument.endswith(".o")]
    before = {path: (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns) for path in objects}
    warm = NativePlanBuilder().build(**options)
    assert warm.as_dict()["compiled_units"] == (0 if cached else 2)
    assert [Path(argument) for argument in warm.link_command if argument.endswith(".o")] == objects
    assert before == {path: (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns) for path in objects}
    if cached:
        shutil.rmtree(options["object_cache"])
    check_debugger(output, adapter)
    subprocess.run([output], check=True, timeout=15)
    assert not list(tmp_path.glob(".btrc-native-*"))


@pytest.mark.parametrize(
    "damage", ["bytes", "timestamp", "missing", "manifest", "extra", "symlink", "directory-symlink", "empty"]
)
def test_damaged_debug_objects_use_new_generation_without_repairing_shared_files(tmp_path, damage):
    options = debug_build(tmp_path)
    first = NativePlanBuilder().build(**options)
    obj = Path(next(argument for argument in first.link_command if argument.endswith(".o")))
    directory = obj.parent
    if damage == "bytes":
        data = bytearray(obj.read_bytes())
        data[-1] ^= 1
        obj.write_bytes(data)
        os.utime(obj, (1, 1))
    elif damage == "timestamp":
        obj.touch()
    elif damage == "missing":
        obj.unlink()
    elif damage == "manifest":
        (directory / "manifest.json").write_text("{}\n")
    elif damage == "extra":
        (directory / "foreign").write_text("preserve me")
    elif damage == "symlink":
        foreign = tmp_path / "foreign.o"
        obj.rename(foreign)
        obj.symlink_to(foreign)
    elif damage == "directory-symlink":
        foreign = tmp_path / "foreign-directory"
        directory.rename(foreign)
        directory.symlink_to(foreign, target_is_directory=True)
    else:
        for path in directory.iterdir():
            path.unlink()
    identity = directory.lstat().st_ino
    before = {path.name: (path.read_bytes(), path.lstat().st_ino) for path in directory.iterdir()}
    second = NativePlanBuilder().build(**options)
    assert second.debug_object_status == "retained-private"
    assert second.as_dict()["compiled_units"] == 0
    assert directory.lstat().st_ino == identity
    assert before == {path.name: (path.read_bytes(), path.lstat().st_ino) for path in directory.iterdir()}
    check_debugger(options["output"], Path(second.units[-1].source))


def test_debug_adapter_fallback_survives_even_without_cache(tmp_path):
    options = debug_build(tmp_path, cached=False)
    first = NativePlanBuilder().build(**options)
    old_source = Path(first.units[-1].source)
    old_source.write_text("int answer(void) { return 99; }\n")
    second = NativePlanBuilder().build(**options)
    assert second.adapter_source_status == "retained-private"
    assert old_source.read_text() == "int answer(void) { return 99; }\n"
    adapter = Path(second.units[-1].source)
    assert adapter.read_text() == "int answer(void) {\n    return 42;\n}\n"
    check_debugger(options["output"], adapter)
    subprocess.run([options["output"]], check=True, timeout=15)


@pytest.mark.parametrize("kind", ["debug", "adapters"])
def test_debug_publication_failure_preserves_previous_executable(tmp_path, monkeypatch, kind):
    options = debug_build(tmp_path)
    options["output"].write_bytes(b"previous output")
    rename = Path.rename

    def fail_publication(self, destination):
        if Path(destination).name.startswith(f".btrc-{kind}-"):
            raise PermissionError("injected debug publication failure")
        return rename(self, destination)

    monkeypatch.setattr(Path, "rename", fail_publication)
    with pytest.raises(NativePlanError, match="injected debug publication failure"):
        NativePlanBuilder().build(**options)
    assert options["output"].read_bytes() == b"previous output"
    assert not list(tmp_path.glob(".btrc-native-*"))


@pytest.mark.parametrize("destination", ["output", "report_path"])
def test_build_cannot_overwrite_retained_debug_inputs(tmp_path, destination):
    options = debug_build(tmp_path)
    first = NativePlanBuilder().build(**options)
    obj = Path(next(argument for argument in first.link_command if argument.endswith(".o")))
    before = obj.read_bytes()
    options[destination] = obj
    with pytest.raises(NativePlanError, match="outside retained debug object directories"):
        NativePlanBuilder().build(**options)
    assert obj.read_bytes() == before
    check_debugger(tmp_path / "program", Path(first.units[-1].source))


def test_debug_generations_remain_usable_across_concurrent_links_and_changed_builds(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    options = debug_build(tmp_path)

    def build(index):
        return NativePlanBuilder().build(**{**options, "output": tmp_path / f"program-{index}"})

    with ThreadPoolExecutor(max_workers=4) as pool:
        reports = list(pool.map(build, range(4)))
    objects = [[argument for argument in report.link_command if argument.endswith(".o")] for report in reports]
    assert all(paths == objects[0] for paths in objects)
    assert len(list(tmp_path.glob(".btrc-debug-*"))) == 1
    for index, report in enumerate(reports):
        check_debugger(tmp_path / f"program-{index}", Path(report.units[-1].source))
    plan = options["plan_path"]
    payload = json.loads(plan.read_text())
    payload["generated-units"][0]["source"] = "int answer(void) {\n    return 43;\n}\n"
    plan.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    changed = build(4)
    assert [argument for argument in changed.link_command if argument.endswith(".o")] != objects[0]
    for index, report in enumerate(reports):
        check_debugger(tmp_path / f"program-{index}", Path(report.units[-1].source))
        subprocess.run([tmp_path / f"program-{index}"], check=True, timeout=15)
    check_debugger(tmp_path / "program-4", Path(changed.units[-1].source))
    assert subprocess.run([tmp_path / "program-4"], timeout=15).returncode == 1


@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_split_compiler_outputs_remain_source_debuggable_after_link(tmp_path, request, frontend):
    root = Path(__file__).resolve().parents[3]
    values = tmp_path / "Values.btrc"
    values.write_text("\n".join(f"int value{index}() {{ return {index}; }}" for index in range(40)) + "\n")
    source = tmp_path / "Main.btrc"
    source.write_text(
        'import ./Values.btrc;\nint main() { printf("%d\\n", '
        + " + ".join(f"value{index}()" for index in range(40))
        + "); return 0; }\n"
    )
    compiler = (
        [sys.executable, "-m", "src.compiler.python.main"]
        if frontend == "reference"
        else [str(request.getfixturevalue("immutable_btrcc"))]
    )
    generated, plan, output = tmp_path / "program.c", tmp_path / "plan.json", tmp_path / "program"
    result = subprocess.run(
        [
            *compiler,
            "--target",
            f"macos-{os.uname().machine}",
            "--no-stdlib",
            "--debug",
            "--no-cache",
            "--strict-imports",
            "--emit-units",
            str(generated),
            "--emit-link-plan",
            str(plan),
            "-o",
            str(generated),
            str(source),
        ],
        cwd=root,
        env={**os.environ, "BTRC_HOME": str(root / "src"), "BTRC_UNIT_LINES": "120"},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(plan.read_text())["emitted-units"]
    options = dict(
        plan_path=plan,
        generated_c=generated,
        output=output,
        debug_info=True,
        optimization=0,
        object_cache=tmp_path / "objects",
        cc="/usr/bin/clang",
        cxx="/usr/bin/clang++",
    )
    NativePlanBuilder().build(**options)
    warm = NativePlanBuilder().build(**options)
    assert warm.as_dict()["compiled_units"] == 0
    shutil.rmtree(options["object_cache"])
    check_debugger(output, values, function="value17", line=18)
    assert subprocess.run([output], capture_output=True, text=True, check=True, timeout=15).stdout == "780\n"
    symbols = tmp_path / "program.dSYM"
    result = subprocess.run(
        ["/usr/bin/dsymutil", str(output), "-o", str(symbols)], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0 and not result.stderr, result.stderr
    assert (symbols / "Contents/Resources/DWARF/program").is_file()
