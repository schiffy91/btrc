"""Source and CLI file-I/O contracts."""

import ast
import json
import multiprocessing
import os
import stat
from pathlib import Path

import pytest

import src.compiler.python.cli.compiler as file_io
from src.compiler.python.application.pipeline import CompilationPipeline
from src.compiler.python.cli.compiler import CompilerFileIO
from src.compiler.python.frontend.sources import SourceFileReader, SourceReadError
from src.compiler.python.main import main as compiler_main


def test_source_and_cli_io_behavior_is_instance_owned():
    compiler_root = Path(__file__).resolve().parents[2] / "compiler/python"
    for relative_path in ("frontend/sources.py", "cli/compiler.py"):
        module = ast.parse((compiler_root / relative_path).read_text())
        loose_behavior = [
            node.name for node in module.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        assert loose_behavior == []


def test_source_read_accepts_utf8_bom_and_normalizes_newlines(tmp_path):
    path = tmp_path / "bom.btrc"
    path.write_bytes(b"\xef\xbb\xbfint x;\r\nint y;\rint z;\n")
    assert SourceFileReader().read(str(path)) == "int x;\nint y;\nint z;\n"


def test_source_read_rejects_invalid_utf8(tmp_path):
    path = tmp_path / "invalid.btrc"
    path.write_bytes(b"int x;\xff")
    with pytest.raises(SourceReadError, match="not valid UTF-8"):
        SourceFileReader().read(str(path))


def test_source_read_rejects_embedded_nul(tmp_path):
    path = tmp_path / "nul.btrc"
    path.write_bytes(b"int main() { return 0; }\0int hidden;\n")
    with pytest.raises(SourceReadError, match="contains a NUL byte"):
        SourceFileReader().read(str(path))


def test_source_read_has_no_compiler_defined_size_ceiling(tmp_path):
    """Source size is bounded by the host, never by a compiler quota."""

    path = tmp_path / "large.btrc"
    payload = "".join(f"int filler_{index} = {index};\n" for index in range(50000))
    path.write_text(payload, encoding="utf-8")

    assert SourceFileReader().read(str(path)) == payload


def test_write_if_missing_never_clobbers_existing_content(tmp_path):
    path = tmp_path / "btrc_rt.h"
    path.write_text("custom", encoding="utf-8")
    assert not CompilerFileIO().write_output_if_missing(str(path), "generated")
    assert path.read_text(encoding="utf-8") == "custom"


def test_write_if_missing_publishes_complete_content_without_temp_files(tmp_path):
    path = tmp_path / "btrc_rt.h"
    assert CompilerFileIO().write_output_if_missing(str(path), "generated\nheader\n")
    assert path.read_text(encoding="utf-8") == "generated\nheader\n"
    assert not list(tmp_path.glob(".btrc-output-*"))


def test_write_if_missing_fsyncs_parent_after_temp_cleanup(tmp_path, monkeypatch):
    path = tmp_path / "btrc_rt.h"
    observed = []
    compiler_io = CompilerFileIO()
    monkeypatch.setattr(compiler_io, "_sync_parent", lambda target: observed.append(target))

    assert compiler_io.write_output_if_missing(
        str(path),
        "generated",
    )

    assert observed == [str(path)]
    assert not list(tmp_path.glob(".btrc-output-*"))


def test_write_if_missing_publish_failure_leaves_no_partial_file(tmp_path, monkeypatch, capsys):
    path = tmp_path / "btrc_rt.h"

    def interrupted(_source, _target):
        raise OSError("simulated publish failure")

    operation = "rename" if os.name == "nt" else "link"
    monkeypatch.setattr(file_io.os, operation, interrupted)
    with pytest.raises(SystemExit) as error:
        CompilerFileIO().write_output_if_missing(str(path), "partial header")

    assert error.value.code == 1
    assert not path.exists()
    assert not list(tmp_path.glob(".btrc-output-*"))
    assert "simulated publish failure" in capsys.readouterr().err


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission contract")
def test_atomic_output_uses_normal_umask_permissions(tmp_path):
    reference = tmp_path / "reference.c"
    output = tmp_path / "program.c"
    reference.write_text("reference", encoding="utf-8")

    CompilerFileIO().write_output(str(output), "generated")

    assert stat.S_IMODE(output.stat().st_mode) == stat.S_IMODE(reference.stat().st_mode)


def test_atomic_output_fsyncs_parent_after_replacement(tmp_path, monkeypatch):
    output = tmp_path / "program.c"
    observed = []
    compiler_io = CompilerFileIO()
    monkeypatch.setattr(compiler_io, "_sync_parent", lambda target: observed.append(target))

    compiler_io.write_output(str(output), "generated")

    assert observed == [str(output)]


def test_atomic_output_does_not_require_posix_fchmod(tmp_path, monkeypatch):
    output = tmp_path / "program.c"
    monkeypatch.delattr(file_io.os, "fchmod", raising=False)

    CompilerFileIO().write_output(str(output), "generated")

    assert output.read_text(encoding="utf-8") == "generated"


@pytest.mark.skipif(os.name == "nt", reason="POSIX device contract")
def test_output_writes_device_without_atomic_sibling(monkeypatch):
    def unexpected_stage(_target, _content):
        raise AssertionError("device output must not be staged beside the device")

    compiler_io = CompilerFileIO()
    monkeypatch.setattr(compiler_io, "_stage_output", unexpected_stage)
    compiler_io.write_output(os.devnull, "discarded")


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink contract")
def test_atomic_output_preserves_output_symlink(tmp_path):
    target = tmp_path / "target.c"
    link = tmp_path / "program.c"
    target.write_text("old", encoding="utf-8")
    link.symlink_to(target)

    CompilerFileIO().write_output(str(link), "new")

    assert link.is_symlink()
    assert target.read_text(encoding="utf-8") == "new"


def test_output_failure_preserves_previous_file(tmp_path, monkeypatch, capsys):
    path = tmp_path / "program.c"
    path.write_text("last good output", encoding="utf-8")

    def interrupted(_source, _target):
        raise OSError("simulated interruption")

    monkeypatch.setattr(file_io.os, "replace", interrupted)
    with pytest.raises(SystemExit) as error:
        CompilerFileIO().write_output(str(path), "partial replacement")

    assert error.value.code == 1
    assert path.read_text(encoding="utf-8") == "last good output"
    assert not list(tmp_path.glob(".btrc-output-*"))
    assert "simulated interruption" in capsys.readouterr().err


@pytest.mark.parametrize("failure", ["encoding", "directory", "missing-parent"])
def test_output_staging_failure_preserves_other_directories(tmp_path, capsys, failure):
    first = tmp_path / "first/primary.c"
    last = tmp_path / "last/plan.json"
    first.parent.mkdir()
    last.parent.mkdir()
    first.write_text("prior primary")
    last.write_text("prior plan")
    target = last.parent if failure == "directory" else last
    if failure == "missing-parent":
        target = tmp_path / "absent/plan.json"
    content = "\ud800" if failure == "encoding" else "new plan"

    with pytest.raises(SystemExit) as error:
        CompilerFileIO().write_outputs(((str(first), "new primary"), (str(target), content)))

    assert error.value.code == 1
    assert "cannot write output" in capsys.readouterr().err
    assert first.read_text() == "prior primary" and last.read_text() == "prior plan"
    assert not list(tmp_path.rglob(".btrc-output-*"))


def test_output_generation_is_fully_staged_before_first_publication(tmp_path, monkeypatch):
    first, last = tmp_path / "primary.c", tmp_path / "plan.json"
    first.write_text("prior primary")
    last.write_text("prior plan")
    replace = os.replace
    published = []

    def observe_publication(source, target):
        if not published:
            assert first.read_text() == "prior primary" and last.read_text() == "prior plan"
            assert {path.read_text() for path in tmp_path.glob(".btrc-output-*")} == {"new primary", "new plan"}
        replace(source, target)
        published.append(Path(target))

    monkeypatch.setattr(file_io.os, "replace", observe_publication)
    CompilerFileIO().write_outputs(((str(first), "new primary"), (str(last), "new plan")))
    assert published == [first, last]
    assert first.read_text() == "new primary" and last.read_text() == "new plan"
    assert not list(tmp_path.glob(".btrc-output-*"))


@pytest.mark.parametrize("failed_name", ["program.c", "parts.unit-1.c", "program.json"])
def test_cli_staging_failure_preserves_all_previous_outputs(tmp_path, monkeypatch, capsys, failed_name):
    source = tmp_path / "Main.btrc"
    (tmp_path / "Values.btrc").write_text("\n".join(f"int value{index}() {{ return {index}; }}" for index in range(40)))
    source.write_text(
        "import ./Values.btrc;\nint main() { return " + " + ".join(f"value{i}()" for i in range(40)) + "; }\n"
    )
    names = ["program.c", "parts.unit-1.c", "program.json"]
    for name in names:
        (tmp_path / name).write_text(f"last good {name}\n")
    before = {path: path.read_bytes() for path in tmp_path.iterdir()}
    stage = CompilerFileIO._stage_output

    def fail_staging(self, target, content):
        if Path(target).name == failed_name:
            raise OSError("injected output staging failure")
        return stage(self, target, content)

    monkeypatch.setattr(CompilerFileIO, "_stage_output", fail_staging)
    monkeypatch.setenv("BTRC_UNIT_LINES", "20")
    monkeypatch.setattr(
        file_io.sys,
        "argv",
        [
            "btrcpy",
            "--no-cache",
            "--no-stdlib",
            "--emit-units",
            str(tmp_path / "parts"),
            "--emit-link-plan",
            str(tmp_path / "program.json"),
            str(source),
            "-o",
            str(tmp_path / "program.c"),
        ],
    )
    with pytest.raises(SystemExit) as error:
        compiler_main()
    assert error.value.code == 1
    assert "injected output staging failure" in capsys.readouterr().err
    assert {path: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_output_path_rejects_input_aliases(tmp_path, capsys):
    source = tmp_path / "program.btrc"
    alias = tmp_path / "alias.c"
    source.write_text("int main() { return 0; }", encoding="utf-8")
    alias.hardlink_to(source)

    with pytest.raises(SystemExit) as error:
        CompilerFileIO().output_path(str(source), str(alias))

    assert error.value.code == 1
    assert "same file" in capsys.readouterr().err


@pytest.mark.parametrize(
    "collision",
    [
        "plan-secondary",
        "primary-secondary",
        "source-secondary",
        "source-plan-hardlink",
        "import-primary",
        "import-plan",
    ],
)
def test_cli_rejects_generation_aliases_before_writing_any_output(tmp_path, monkeypatch, capsys, collision):
    source = tmp_path / "Main.btrc"
    dependency = tmp_path / "Values.btrc"
    dependency.write_text("\n".join(f"int value{index}() {{ return {index}; }}" for index in range(40)))
    source.write_text(
        "import ./Values.btrc;\nint main() { return " + " + ".join(f"value{i}()" for i in range(40)) + "; }\n"
    )
    primary = tmp_path / "program.c"
    prefix = tmp_path / "parts"
    secondary = tmp_path / "parts.unit-1.c"
    plan = tmp_path / "program.json"
    primary.write_text("last good primary")
    secondary.write_text("last good secondary")
    plan.write_text("last good plan")
    if collision == "plan-secondary":
        plan = secondary
    elif collision == "primary-secondary":
        primary = secondary
    elif collision == "source-secondary":
        secondary.unlink()
        secondary.symlink_to(source)
    elif collision == "source-plan-hardlink":
        plan.unlink()
        plan.hardlink_to(source)
    elif collision == "import-primary":
        primary = dependency
    else:
        plan = dependency
    before = {path: path.read_bytes() for path in tmp_path.iterdir()}
    monkeypatch.setenv("BTRC_UNIT_LINES", "20")
    monkeypatch.setattr(
        file_io.sys,
        "argv",
        [
            "btrcpy",
            "--no-cache",
            "--emit-units",
            str(prefix),
            "--emit-link-plan",
            str(plan),
            str(source),
            "-o",
            str(primary),
        ],
    )

    with pytest.raises(SystemExit) as error:
        compiler_main()

    assert error.value.code == 1
    assert "output" in capsys.readouterr().err
    assert {path: path.read_bytes() for path in before} == before
    assert set(tmp_path.iterdir()) == set(before)
    if collision == "source-secondary":
        assert secondary.is_symlink()


@pytest.mark.parametrize("destination", ["Native.c", "Api.h", "btrc.toml", "btrc.lock"])
def test_cli_protects_native_and_package_inputs_from_output(tmp_path, monkeypatch, capsys, destination):
    (tmp_path / "src").mkdir()
    source = tmp_path / "src/Main.btrc"
    source.write_text("int main() { return 0; }\n")
    (tmp_path / "Native.c").write_text("int nativeValue(void) { return 1; }\n")
    (tmp_path / "Api.h").write_text("int nativeValue(void);\n")
    (tmp_path / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "output_protection"\n'
        '[[native.sources]]\npath = "Native.c"\nlanguage = "c"\nstandard = "c11"\n'
        '[[native.headers]]\npath = "Api.h"\n'
    )
    target = tmp_path / destination
    # First resolve normally so btrc.lock contains the real package graph.
    monkeypatch.setattr(file_io.sys, "argv", ["btrcpy", "--no-cache", str(source), "-o", str(tmp_path / "good.c")])
    compiler_main()
    before = target.read_bytes() if target.exists() else None
    monkeypatch.setattr(file_io.sys, "argv", ["btrcpy", "--no-cache", str(source), "-o", str(target)])

    with pytest.raises(SystemExit) as error:
        compiler_main()

    assert error.value.code == 1
    assert "output" in capsys.readouterr().err
    assert (target.read_bytes() if target.exists() else None) == before


@pytest.mark.parametrize("role", ["primary", "plan"])
def test_cli_rejects_outputs_aliasing_the_freestanding_seam(tmp_path, monkeypatch, capsys, role):
    source = tmp_path / "Main.btrc"
    source.write_text("int main() { return 0; }\n")
    seam = tmp_path / "btrc_rt.h"
    primary = seam if role == "primary" else tmp_path / "program.c"
    plan = seam if role == "plan" else tmp_path / "program.json"
    monkeypatch.setattr(
        file_io.sys,
        "argv",
        ["btrcpy", "--no-cache", "--freestanding", "--emit-link-plan", str(plan), str(source), "-o", str(primary)],
    )
    with pytest.raises(SystemExit) as error:
        compiler_main()
    assert error.value.code == 1
    assert "output" in capsys.readouterr().err
    assert not primary.exists() and not plan.exists() and not seam.exists()


def test_cached_cli_result_still_protects_imported_source(tmp_path, monkeypatch, capsys):
    source = tmp_path / "Main.btrc"
    imported = tmp_path / "Value.btrc"
    imported.write_text("int value() { return 7; }\n")
    source.write_text("import ./Value.btrc;\nint main() { return value(); }\n")
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(file_io.sys, "argv", ["btrcpy", str(source), "-o", str(tmp_path / "program.c")])
    compiler_main()
    before = imported.read_bytes()

    def unexpected_recompile(*_args, **_kwargs):
        raise AssertionError("this request must use the actual stored generation")

    monkeypatch.setattr(CompilationPipeline, "compile_resolved", unexpected_recompile)
    monkeypatch.setattr(file_io.sys, "argv", ["btrcpy", str(source), "-o", str(imported)])
    with pytest.raises(SystemExit) as error:
        compiler_main()
    assert error.value.code == 1
    assert "same file" in capsys.readouterr().err
    assert imported.read_bytes() == before


def _split_cli_arguments(root: Path, prefix: str) -> list[str]:
    units = root / prefix
    units.mkdir(exist_ok=True)
    return [
        "--no-cache",
        "--no-stdlib",
        "--emit-units",
        str(units / "parts"),
        "--emit-link-plan",
        str(root / "program.json"),
        str(root / "Main.btrc"),
        "-o",
        str(root / "program.c"),
    ]


def _write_split_cli_source(root: Path, value: int) -> None:
    (root / "Values.btrc").write_text(
        "\n".join(f"int value{index}() {{ return {index + value}; }}" for index in range(40))
    )
    (root / "Main.btrc").write_text(
        "import ./Values.btrc;\nint main() { return " + " + ".join(f"value{i}()" for i in range(40)) + "; }\n"
    )


def _crash_cli_generation(arguments: list[str], boundary: str) -> None:
    replace = file_io.os.replace

    def replace_and_crash(source, destination):
        replace(source, destination)
        source, destination = Path(source), Path(destination)
        if (
            (boundary == "primary" and destination.name == "program.c" and ".publish.new-" in source.name)
            or (boundary == "plan" and destination.name == "program.json" and ".publish.new-" in source.name)
            or (
                boundary == "commit"
                and destination.name.endswith(".publish.journal")
                and json.loads(destination.read_text())["state"] == "committed"
            )
        ):
            os._exit(94)

    file_io.os.replace = replace_and_crash
    file_io.sys.argv = ["btrcpy", *arguments]
    compiler_main()


@pytest.mark.parametrize("boundary", ["primary", "plan", "commit"])
def test_real_cli_recovers_interrupted_generation_with_a_new_unit_prefix(tmp_path, monkeypatch, boundary):
    monkeypatch.setenv("BTRC_UNIT_LINES", "20")
    _write_split_cli_source(tmp_path, 0)
    arguments = _split_cli_arguments(tmp_path, "original")
    monkeypatch.setattr(file_io.sys, "argv", ["btrcpy", *arguments])
    assert compiler_main() == 0
    original_units = tuple(Path(path) for path in json.loads((tmp_path / "program.json").read_text())["emitted-units"])
    assert original_units
    _write_split_cli_source(tmp_path, 100)
    attempted = _split_cli_arguments(tmp_path, "attempted")
    child = multiprocessing.get_context("spawn").Process(target=_crash_cli_generation, args=(attempted, boundary))
    child.start()
    child.join(30)
    assert not child.is_alive()
    assert child.exitcode == 94
    assert tuple(tmp_path.rglob("*.publish.journal"))

    _write_split_cli_source(tmp_path, 200)
    final_args = _split_cli_arguments(tmp_path, "final")
    monkeypatch.setattr(file_io.sys, "argv", ["btrcpy", *final_args])
    assert compiler_main() == 0
    final_units = tuple(Path(path) for path in json.loads((tmp_path / "program.json").read_text())["emitted-units"])
    assert final_units and all(path.parent == tmp_path / "final" and path.is_file() for path in final_units)
    assert not any(path.exists() for path in original_units)
    assert not tuple((tmp_path / "attempted").glob("parts.unit-*.c"))
    assert not tuple(tmp_path.rglob("*.publish.journal"))

    # Removing both split output and link-plan output retires only owned files.
    monkeypatch.setattr(
        file_io.sys, "argv", ["btrcpy", "--no-cache", str(tmp_path / "Main.btrc"), "-o", str(tmp_path / "program.c")]
    )
    assert compiler_main() == 0
    assert not any(path.exists() for path in final_units)
    assert not (tmp_path / "program.json").exists()


def test_real_cli_replacement_failure_restores_primary_units_and_plan(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BTRC_UNIT_LINES", "20")
    _write_split_cli_source(tmp_path, 0)
    monkeypatch.setattr(file_io.sys, "argv", ["btrcpy", *_split_cli_arguments(tmp_path, "units")])
    assert compiler_main() == 0
    primary, plan = tmp_path / "program.c", tmp_path / "program.json"
    files = (primary, plan, *(Path(path) for path in json.loads(plan.read_text())["emitted-units"]))
    before = {path: path.read_bytes() for path in files}
    replace = file_io.os.replace
    failed = False

    def fail_after_primary(source, destination):
        nonlocal failed
        replace(source, destination)
        if not failed and Path(destination) == primary and ".publish.new-" in Path(source).name:
            failed = True
            raise OSError("injected generation replacement failure")

    _write_split_cli_source(tmp_path, 500)
    monkeypatch.setattr(file_io.os, "replace", fail_after_primary)
    with pytest.raises(SystemExit):
        compiler_main()
    assert failed
    assert {path: path.read_bytes() for path in files} == before
    assert "injected generation replacement failure" in capsys.readouterr().err
    assert compiler_main() == 0
    assert primary.read_bytes() != before[primary]


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink retargeting")
def test_cli_rejects_symlink_retarget_after_staging(tmp_path, monkeypatch, capsys):
    source = tmp_path / "Main.btrc"
    source.write_text("int main() { return 7; }\n")
    target = tmp_path / "target.c"
    target.write_text("prior output")
    alias = tmp_path / "alias.c"
    alias.symlink_to(target)
    before = source.read_bytes()
    stage = CompilerFileIO._stage_output

    def retarget(self, output, content):
        candidate = stage(self, output, content)
        alias.unlink()
        alias.symlink_to(source)
        return candidate

    monkeypatch.setattr(CompilerFileIO, "_stage_output", retarget)
    monkeypatch.setattr(file_io.sys, "argv", ["btrcpy", "--no-cache", str(source), "-o", str(alias)])
    with pytest.raises(SystemExit):
        compiler_main()
    assert "changed after validation" in capsys.readouterr().err
    assert source.read_bytes() == before
    assert target.read_text() == "prior output"


def test_retired_output_cannot_delete_a_current_input(tmp_path, capsys):
    from src.compiler.python.artifacts.cache import CompilerOutputPublication

    primary, old_unit = tmp_path / "program.c", tmp_path / "prior-unit.c"
    io = CompilerFileIO(publication=CompilerOutputPublication())
    io.write_outputs(((str(primary), "old primary"), (str(old_unit), "native source")), roles=("primary", "secondary"))
    prepared = io.prepare_output_paths((str(primary),), (str(old_unit),))
    with pytest.raises(SystemExit):
        io.write_outputs(((str(primary), "new primary"),), roles=("primary",), prepared=prepared)
    assert "same file as a source" in capsys.readouterr().err
    assert primary.read_text() == "old primary"
    assert old_unit.read_text() == "native source"


def test_generation_publication_does_not_use_compilation_cache_directory(tmp_path, monkeypatch):
    from src.compiler.python.artifacts.cache import CompilerOutputPublication

    state = tmp_path / "state"
    cache = tmp_path / "cache"
    monkeypatch.setenv("BTRC_STATE_DIR", str(state))
    monkeypatch.setenv("BTRC_CACHE_DIR", str(cache))
    io = CompilerFileIO(publication=CompilerOutputPublication())
    io.write_outputs(((str(tmp_path / "program.c"), "primary"),), roles=("primary",))
    assert len(tuple(state.glob("*/committed.json"))) == 1
    assert not cache.exists()
    if os.name != "nt":
        assert stat.S_IMODE(state.stat().st_mode) == 0o700


def test_inspection_does_not_create_output_generation_state(tmp_path, monkeypatch):
    state = tmp_path / "state"
    source = tmp_path / "Main.btrc"
    source.write_text("int main() { return 0; }\n")
    monkeypatch.setenv("BTRC_STATE_DIR", str(state))
    monkeypatch.setattr(file_io.sys, "argv", ["btrcpy", "--no-cache", "--emit-ast", str(source)])
    assert compiler_main() == 0
    assert not state.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink and permissions")
def test_real_cli_preserves_symlink_target_permissions_and_custom_seam(tmp_path, monkeypatch):
    source = tmp_path / "Main.btrc"
    source.write_text("int main() { return 0; }\n")
    target = tmp_path / "target.c"
    target.write_text("prior")
    target.chmod(0o640)
    alias = tmp_path / "program.c"
    alias.symlink_to(target)
    seam = tmp_path / "btrc_rt.h"
    seam.write_text("user-provided seam")
    monkeypatch.setattr(file_io.sys, "argv", ["btrcpy", "--no-cache", "--freestanding", str(source), "-o", str(alias)])
    assert compiler_main() == 0
    assert alias.is_symlink() and "int main" in target.read_text()
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert seam.read_text() == "user-provided seam"


def test_recovery_cannot_remove_an_interrupted_output_now_used_as_input(tmp_path, monkeypatch, capsys):
    from src.compiler.python.artifacts.cache import CompilerOutputPublication

    monkeypatch.setenv("BTRC_UNIT_LINES", "20")
    _write_split_cli_source(tmp_path, 0)
    monkeypatch.setattr(file_io.sys, "argv", ["btrcpy", *_split_cli_arguments(tmp_path, "original")])
    assert compiler_main() == 0
    attempted = _split_cli_arguments(tmp_path, "attempted")
    child = multiprocessing.get_context("spawn").Process(target=_crash_cli_generation, args=(attempted, "plan"))
    child.start()
    child.join(30)
    assert not child.is_alive() and child.exitcode == 94
    primary = tmp_path / "program.c"
    plan = tmp_path / "program.json"
    protected = Path(json.loads(plan.read_text())["emitted-units"][0])
    before = {path: path.read_bytes() for path in (primary, plan, protected)}
    io = CompilerFileIO(publication=CompilerOutputPublication())
    prepared = io.prepare_output_paths((str(primary),), (str(protected),))
    with pytest.raises(SystemExit):
        io.write_outputs(((str(primary), "replacement"),), roles=("primary",), prepared=prepared)
    assert "same file as a source" in capsys.readouterr().err
    assert {path: path.read_bytes() for path in before} == before
    assert tuple(tmp_path.rglob("*.publish.journal"))


def test_cli_new_freestanding_seam_stays_create_if_absent(tmp_path, monkeypatch):
    source = tmp_path / "Main.btrc"
    source.write_text("int main() { return 0; }\n")
    output = tmp_path / "program.c"
    seam = tmp_path / "btrc_rt.h"
    monkeypatch.setattr(file_io.sys, "argv", ["btrcpy", "--no-cache", "--freestanding", str(source), "-o", str(output)])
    assert compiler_main() == 0
    assert "int main" in output.read_text() and seam.is_file()
    seam.write_text("custom seam after first build")
    assert compiler_main() == 0
    assert seam.read_text() == "custom seam after first build"


@pytest.mark.skipif(os.name == "nt", reason="POSIX device output")
def test_cli_device_output_does_not_allocate_generation_state(tmp_path, monkeypatch):
    source = tmp_path / "Main.btrc"
    source.write_text("int main() { return 0; }\n")
    state = tmp_path / "state"
    monkeypatch.setenv("BTRC_STATE_DIR", str(state))
    monkeypatch.setattr(file_io.sys, "argv", ["btrcpy", "--no-cache", str(source), "-o", os.devnull])
    assert compiler_main() == 0
    assert not state.exists()


def test_cli_retirement_cannot_replace_a_preserved_freestanding_seam(tmp_path, monkeypatch, capsys):
    source = tmp_path / "Main.btrc"
    source.write_text("int main() { return 0; }\n")
    primary = tmp_path / "program.c"
    seam = tmp_path / "btrc_rt.h"
    monkeypatch.setattr(
        file_io.sys, "argv", ["btrcpy", "--no-cache", "--emit-link-plan", str(seam), str(source), "-o", str(primary)]
    )
    assert compiler_main() == 0
    before = {path: path.read_bytes() for path in (primary, seam)}
    monkeypatch.setattr(
        file_io.sys, "argv", ["btrcpy", "--no-cache", "--freestanding", str(source), "-o", str(primary)]
    )
    with pytest.raises(SystemExit):
        compiler_main()
    assert "another output" in capsys.readouterr().err
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize("boundary", ["compiled", "prepared"])
@pytest.mark.parametrize("dependency", [False, True], ids=["root", "import"])
@pytest.mark.parametrize("mutation", ["rename", "symlink", "edit", "remove"])
def test_cli_preserves_read_time_source_identity(tmp_path, monkeypatch, capsys, dependency, mutation, boundary):
    from src.compiler.python.application.compiler import Compiler

    root = tmp_path / "Main.btrc"
    imported = tmp_path / "Value.btrc"
    imported.write_text("int value() { return 7; }\n")
    root.write_text("import ./Value.btrc;\nint main() { return value(); }\n")
    victim = imported if dependency else root
    original = victim.read_bytes()
    output = tmp_path / "program.c"
    output.write_text("last good output")
    compile_source = Compiler.compile
    expected = {}

    def mutate_source():
        if mutation == "rename":
            victim.replace(output)
            victim.write_text("int replacement;\n")
        elif mutation == "symlink":
            victim.replace(output)
            replacement = tmp_path / "Replacement.btrc"
            replacement.write_text("int replacement;\n")
            victim.symlink_to(replacement)
        elif mutation == "edit":
            victim.write_text("int changedDuringCompile;\n")
        else:
            victim.unlink()
        expected.update({path: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()})

    def changed_after_compile(self, *arguments, **keywords):
        result = compile_source(self, *arguments, **keywords)
        assert result.successful
        if boundary == "compiled":
            mutate_source()
        return result

    prepare = CompilerFileIO.prepare_output_paths

    def changed_after_prepare(self, *arguments, **keywords):
        result = prepare(self, *arguments, **keywords)
        if boundary == "prepared":
            mutate_source()
        return result

    monkeypatch.setattr(CompilerFileIO, "prepare_output_paths", changed_after_prepare)
    monkeypatch.setattr(Compiler, "compile", changed_after_compile)
    monkeypatch.setattr(file_io.sys, "argv", ["btrcpy", str(root), "--no-stdlib", "--no-cache", "-o", str(output)])
    with pytest.raises(SystemExit) as error:
        compiler_main()
    assert error.value.code == 1
    assert "source input changed" in capsys.readouterr().err
    assert {path: path.read_bytes() for path in expected} == expected
    if mutation in {"rename", "symlink"}:
        assert output.read_bytes() == original


@pytest.mark.parametrize("mutation", ["replace", "edit"])
def test_reader_rejects_mutation_of_open_source(tmp_path, monkeypatch, mutation):
    import builtins

    import src.compiler.python.frontend.sources as sources

    path = tmp_path / "Source.btrc"
    path.write_text("int original;\n")
    with builtins.open(path, "rb") as opened:

        class ChangedReader:
            def __enter__(self):
                return self

            def __exit__(self, *arguments):
                opened.close()

            def fileno(self):
                return opened.fileno()

            def read(self):
                value = opened.read()
                if mutation == "replace":
                    path.rename(tmp_path / "original")
                path.write_text("int changed;\n")
                return value

        monkeypatch.setattr(sources, "open", lambda *args, **kwargs: ChangedReader(), raising=False)
        with pytest.raises(SourceReadError, match="source input changed"):
            SourceFileReader().read(str(path))
    assert opened.closed


def test_compiler_input_identity_is_independent_between_invocations(tmp_path):
    from src.compiler.python.application.compiler import Compiler
    from src.compiler.python.application.results import CompilerOptions

    source = tmp_path / "Main.btrc"
    dependency = tmp_path / "Value.btrc"
    dependency.write_text("int value() { return 1; }")
    compiler = Compiler(CompilationPipeline())
    options = CompilerOptions(include_stdlib=False, use_cache=False)
    result = compiler.compile("import ./Value.btrc;\nint main() { return value(); }", str(source), options)
    assert result.successful and not source.exists()
    first = result.input_identities
    dependency.write_text("int value() { return 2; }")
    next_result = compiler.compile("import ./Value.btrc;\nint main() { return value(); }", str(source), options)
    assert next_result.successful
    for identity in next_result.input_identities:
        identity.validate()
    with pytest.raises(SourceReadError, match="source input changed"):
        first[0].validate()


def test_owned_unchanged_generation_avoids_staging_and_preserves_file_identity(tmp_path, monkeypatch):
    from src.compiler.python.artifacts.cache import CompilerOutputPublication

    monkeypatch.setenv("BTRC_STATE_DIR", str(tmp_path / "state"))
    io = CompilerFileIO(publication=CompilerOutputPublication())
    outputs = ((str(tmp_path / "program.c"), "alpha\n" + "λ" * 70000), (str(tmp_path / "program.json"), "{}\n"))
    roles = ("primary", "link-plan")
    io.write_outputs(outputs, roles=roles)
    paths = [*(Path(path) for path, _ in outputs), *tmp_path.glob("state/*/committed.json")]
    before = {path: (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes()) for path in paths}

    def never_stage(*args):
        pytest.fail("unchanged owned generation wrote a candidate")

    monkeypatch.setattr(io, "_stage_output", never_stage)
    io.write_outputs(outputs, roles=roles)
    assert {path: (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes()) for path in paths} == before


@pytest.mark.parametrize("damage", ["content", "missing", "mode", "unowned"])
def test_generation_retention_revalidates_actual_files_and_ownership(tmp_path, monkeypatch, damage):
    from src.compiler.python.artifacts.cache import CompilerOutputPublication

    monkeypatch.setenv("BTRC_STATE_DIR", str(tmp_path / "state"))
    io = CompilerFileIO(publication=CompilerOutputPublication())
    primary, secondary = tmp_path / "main.c", tmp_path / "part.c"
    outputs = ((str(primary), "primary"), (str(secondary), "secondary"))
    roles = ("primary", "secondary")
    io.write_outputs(outputs, roles=roles)
    if damage == "content":
        old = secondary.stat()
        secondary.write_text("CORRUPTED")
        os.utime(secondary, ns=(old.st_atime_ns, old.st_mtime_ns))
    elif damage == "missing":
        secondary.unlink()
    elif damage == "mode":
        secondary.chmod(0o640 if stat.S_IMODE(secondary.stat().st_mode) != 0o640 else 0o600)
    else:
        next(tmp_path.glob("state/*/committed.json")).unlink()
    staged = []
    stage = io._stage_output

    def record(target, content):
        staged.append(target)
        return stage(target, content)

    monkeypatch.setattr(io, "_stage_output", record)
    io.write_outputs(outputs, roles=roles)
    assert staged == [str(primary), str(secondary)]
    assert primary.read_text() == "primary" and secondary.read_text() == "secondary"
    manifest = json.loads(next(tmp_path.glob("state/*/committed.json")).read_text())
    assert manifest["files"][1]["mode"] == stat.S_IMODE(secondary.stat().st_mode)


def test_retention_rechecks_source_identity_after_directory_lock(tmp_path, monkeypatch, capsys):
    from src.compiler.python.artifacts.cache import CompilerOutputPublication
    from src.compiler.python.artifacts.publication import PublicationLock

    monkeypatch.setenv("BTRC_STATE_DIR", str(tmp_path / "state"))
    io = CompilerFileIO(publication=CompilerOutputPublication())
    source, output = tmp_path / "Main.btrc", tmp_path / "main.c"
    source.write_text("source")
    outputs = ((str(output), "compiled"),)
    io.write_outputs(outputs, roles=("primary",))
    io.read_input(str(source))
    prepared = io.prepare_output_paths((str(output),), (str(source),))
    old = (output.stat().st_ino, output.stat().st_mtime_ns)
    lock = PublicationLock._lock_descriptor

    def acquire(owner):
        lock(owner)
        if owner._name is None and owner._directory == tmp_path:
            source.write_text("changed while waiting")

    monkeypatch.setattr(PublicationLock, "_lock_descriptor", acquire)
    with pytest.raises(SystemExit):
        io.write_outputs(outputs, roles=("primary",), prepared=prepared)
    assert "changed" in capsys.readouterr().err
    assert (output.stat().st_ino, output.stat().st_mtime_ns) == old


def test_retention_rechecks_earlier_output_after_reading_whole_generation(tmp_path, monkeypatch, capsys):
    from src.compiler.python.artifacts.cache import CompilerGenerationPublisher, CompilerOutputPublication

    monkeypatch.setenv("BTRC_STATE_DIR", str(tmp_path / "state"))
    io = CompilerFileIO(publication=CompilerOutputPublication())
    primary, secondary = tmp_path / "main.c", tmp_path / "part.c"
    outputs = ((str(primary), "primary"), (str(secondary), "secondary"))
    io.write_outputs(outputs, roles=("primary", "secondary"))
    verify = CompilerGenerationPublisher._retained_output

    def changed(owner, output, owned):
        result = verify(owner, output, owned)
        if output.destination == secondary:
            metadata = primary.stat()
            primary.write_text("changed")
            os.utime(primary, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
        return result

    monkeypatch.setattr(CompilerGenerationPublisher, "_retained_output", changed)
    with pytest.raises(SystemExit):
        io.write_outputs(outputs, roles=("primary", "secondary"))
    assert "changed during retention" in capsys.readouterr().err
    assert primary.read_text() == "changed" and secondary.read_text() == "secondary"


def test_real_split_cli_retains_generation_after_unchanged_source_touch(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("BTRC_UNIT_LINES", "120")
    _write_split_cli_source(tmp_path, 0)
    arguments = _split_cli_arguments(tmp_path, "parts")
    monkeypatch.setattr(file_io.sys, "argv", ["btrcpy", *arguments])
    assert compiler_main() == 0
    plan = tmp_path / "program.json"
    files = [tmp_path / "program.c", plan, *(Path(p) for p in json.loads(plan.read_text())["emitted-units"])]
    assert len(files) > 2
    files.extend(tmp_path.glob("state/*/committed.json"))
    before = {path: (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes()) for path in files}
    (tmp_path / "Values.btrc").touch()
    assert compiler_main() == 0
    assert {path: (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes()) for path in files} == before
