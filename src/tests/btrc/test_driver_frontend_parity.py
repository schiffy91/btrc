"""Production-driver parity for explicit source dependencies."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
CC = shlex.split(os.environ.get("BTRC_CC", "cc"))

pytestmark = pytest.mark.skipif(
    not CC or shutil.which(CC[0]) is None,
    reason="needs a C compiler",
)


def _run(command: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _reference(program: Path, output: Path, *flags: str):
    return _run(
        [
            "python3",
            "-m",
            "src.compiler.python.main",
            *flags,
            "--no-stdlib",
            "--no-cache",
            str(program),
            "-o",
            str(output),
        ]
    )


def _selfhost(compiler: Path, program: Path, *flags: str):
    return _run([str(compiler), *flags, "--no-stdlib", str(program)])


@pytest.mark.parametrize(
    "directive",
    [
        "import Library.Audio.AudioDevice;",
        "import Library.{Audio.AudioDevice, Audio.RealtimeAudio,};",
    ],
)
def test_nested_library_packages_resolve_and_execute(semantic_btrcc: Path, tmp_path: Path, directive: str) -> None:
    program = tmp_path / "Main.btrc"
    program.write_text(
        directive + "\nint main() { var stream = AudioStreamRequest(48000, 32); return stream.bufferFrames() - 32; }\n"
    )
    reference_c = tmp_path / "Reference.c"
    reference = _reference(program, reference_c)
    selfhost = _selfhost(semantic_btrcc, program)
    assert reference.returncode == 0, reference.stderr
    assert selfhost.returncode == 0, selfhost.stderr
    selfhost_c = tmp_path / "Selfhost.c"
    selfhost_c.write_text(selfhost.stdout)
    for generated in (reference_c, selfhost_c):
        executable = generated.with_suffix("")
        built = _run([*CC, "-std=c11", str(generated), "-lm", "-o", str(executable)])
        assert built.returncode == 0, built.stderr
        ran = _run([str(executable)])
        assert ran.returncode == 0, ran.stderr


def test_nested_library_missing_package_does_not_fall_back(semantic_btrcc: Path, tmp_path: Path) -> None:
    program = tmp_path / "Main.btrc"
    program.write_text("import Library.missing.Strings;\nint main() { return 0; }\n")
    for result in (_reference(program, tmp_path / "Reference.c"), _selfhost(semantic_btrcc, program)):
        assert result.returncode != 0
        assert "Library.missing.Strings" in result.stderr and "not found" in result.stderr


def test_relaxed_core_excludes_explicit_native_providers(semantic_btrcc: Path, tmp_path: Path) -> None:
    program = tmp_path / "Main.btrc"
    program.write_text("int main() { return 0; }\n")
    for command in (
        [str(semantic_btrcc)],
        ["python3", "-m", "src.compiler.python.main", "--no-cache", "-o", str(tmp_path / "Main.c")],
    ):
        result = _run([*command, "--relaxed-imports", str(program)])
        assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("flags", ((), ("--strict-imports",)), ids=("default", "explicit"))
def test_real_corpus_source_compiles_in_both_strict_modes(
    semantic_btrcc: Path,
    tmp_path: Path,
    flags: tuple[str, ...],
) -> None:
    program = REPO / "src/tests/collections/VectorBool.btrc"
    selfhost = _selfhost(semantic_btrcc, program, *flags)
    reference = _reference(program, tmp_path / "reference.c", *flags)

    assert selfhost.returncode == 0 and selfhost.stdout.strip(), selfhost.stderr
    assert reference.returncode == 0, reference.stderr


@pytest.mark.parametrize("flags", ((), ("--strict-imports",)), ids=("default", "explicit"))
@pytest.mark.parametrize(
    ("owner_source", "consumer_source", "symbol"),
    (
        ("class B {}\n", "B makeB() { return new B(); }\n", "B"),
        ("int shared = 42;\n", "int initialized = shared;\n", "shared"),
        ("enum Color { RED, BLUE };\n", "int color() { return RED; }\n", "RED"),
        ("#define ANSWER() 42\n", "int answer() { return ANSWER(); }\n", "ANSWER"),
    ),
    ids=("class", "global", "bare-enumerator", "source-macro"),
)
def test_strict_visibility_diagnostics_are_exactly_equal(
    semantic_btrcc: Path,
    tmp_path: Path,
    flags: tuple[str, ...],
    owner_source: str,
    consumer_source: str,
    symbol: str,
) -> None:
    owner = tmp_path / "owner.btrc"
    consumer = tmp_path / "consumer.btrc"
    program = tmp_path / "program.btrc"
    owner.write_text(owner_source)
    consumer.write_text(consumer_source)
    program.write_text("import ./owner.btrc;\nimport ./consumer.btrc;\nint main() { return 0; }\n")

    selfhost = _selfhost(semantic_btrcc, program, *flags)
    reference = _reference(program, tmp_path / "reference.c", *flags)

    assert selfhost.returncode == 1
    assert reference.returncode == 1
    assert f"'{symbol}' is defined in owner.btrc" in reference.stderr
    assert selfhost.stderr == reference.stderr


def test_import_direction_is_not_reversed_through_an_include_unit(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    (tmp_path / "fragment.btrc").write_text("Root makeRoot() { return new Root(); }\n")
    (tmp_path / "package.btrc").write_text('#include "fragment.btrc"\n')
    program = tmp_path / "program.btrc"
    program.write_text("import ./package.btrc;\nclass Root {}\nint main() { return 0; }\n")

    selfhost = _selfhost(semantic_btrcc, program)
    reference = _reference(program, tmp_path / "reference.c")

    assert selfhost.returncode == 1
    assert reference.returncode == 1
    assert selfhost.stderr == reference.stderr


@pytest.mark.parametrize(
    ("consumer_prefix", "root_directives", "flags"),
    (
        ("import ./owner.btrc;\n", "import ./consumer.btrc;\n", ()),
        ("", '#include "consumer.btrc"\n#include "owner.btrc"\n', ()),
        ("", "import ./consumer.btrc;\nimport ./owner.btrc;\n", ("--relaxed-imports",)),
    ),
    ids=("explicit-import", "include-unit", "relaxed-opt-out"),
)
def test_visibility_success_modes_have_frontend_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    consumer_prefix: str,
    root_directives: str,
    flags: tuple[str, ...],
) -> None:
    (tmp_path / "owner.btrc").write_text("class B {}\n")
    (tmp_path / "consumer.btrc").write_text(consumer_prefix + "B makeB() { return new B(); }\n")
    program = tmp_path / "program.btrc"
    program.write_text(root_directives + "int main() { return 0; }\n")

    selfhost = _selfhost(semantic_btrcc, program, *flags)
    reference = _reference(program, tmp_path / "reference.c", *flags)

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr


def test_method_generic_is_not_mistaken_for_top_level_type(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    (tmp_path / "u.btrc").write_text("class U {}\n")
    (tmp_path / "box.btrc").write_text("class Box { public U identity<U>(U value) { return value; } }\n")
    program = tmp_path / "program.btrc"
    program.write_text("import ./u.btrc;\nimport ./box.btrc;\nint main() { return 0; }\n")

    selfhost = _selfhost(semantic_btrcc, program)
    reference = _reference(program, tmp_path / "reference.c")

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr


@pytest.mark.parametrize(
    ("owner_source", "consumer_source"),
    (
        (
            "int value = 99;\n",
            "class Holder {\n"
            "  private int stored;\n"
            "  public int item {\n"
            "    get { return self.stored; }\n"
            "    set { self.stored = value; }\n"
            "  }\n"
            "}\n",
        ),
        (
            "int left = 99;\n",
            "enum class Packet { Pair(int left, int right = left + 1) }\n",
        ),
        (
            "int member = 99;\n",
            "#define READ_MEMBER(object) ((object).member)\n",
        ),
    ),
    ids=("property-setter-value", "rich-enum-earlier-parameter", "macro-member-selector"),
)
def test_implicit_and_lexical_bindings_have_frontend_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    owner_source: str,
    consumer_source: str,
) -> None:
    (tmp_path / "owner.btrc").write_text(owner_source)
    (tmp_path / "consumer.btrc").write_text(consumer_source)
    program = tmp_path / "program.btrc"
    program.write_text("import ./owner.btrc;\nimport ./consumer.btrc;\nint main() { return 0; }\n")

    selfhost = _selfhost(semantic_btrcc, program)
    reference = _reference(program, tmp_path / "reference.c")

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr


@pytest.mark.parametrize("flags", ((), ("--strict-imports",)), ids=("default", "explicit"))
@pytest.mark.parametrize(
    ("owner_source", "consumer_source", "symbol", "dependent_file"),
    (
        (
            "int later = 41;\n",
            "int choose(int first = later, int later = 0) { return first + later; }\n",
            "later",
            "consumer.btrc",
        ),
        (
            "int selected = 41;\n",
            "int choose(int branch) {\n"
            "  switch (branch) {\n"
            "    case 0:\n"
            "      int selected = 1;\n"
            "      return selected;\n"
            "    default:\n"
            "      return selected;\n"
            "  }\n"
            "}\n",
            "selected",
            "consumer.btrc",
        ),
    ),
    ids=("later-default-parameter", "isolated-switch-case"),
)
def test_lexical_scope_visibility_diagnostics_are_exactly_equal(
    semantic_btrcc: Path,
    tmp_path: Path,
    flags: tuple[str, ...],
    owner_source: str,
    consumer_source: str,
    symbol: str,
    dependent_file: str,
) -> None:
    (tmp_path / "owner.btrc").write_text(owner_source)
    (tmp_path / "consumer.btrc").write_text(consumer_source)
    program = tmp_path / "program.btrc"
    program.write_text("import ./owner.btrc;\nimport ./consumer.btrc;\nint main() { return 0; }\n")

    selfhost = _selfhost(semantic_btrcc, program, *flags)
    reference = _reference(program, tmp_path / "reference.c", *flags)

    assert selfhost.returncode == 1
    assert reference.returncode == 1
    assert f"'{symbol}' is defined in owner.btrc" in reference.stderr
    assert f"{dependent_file} does not import it" in reference.stderr
    assert selfhost.stderr == reference.stderr


@pytest.mark.parametrize("flags", ((), ("--strict-imports",)), ids=("default", "explicit"))
def test_macro_replacement_dependency_diagnostics_are_exactly_equal(
    semantic_btrcc: Path,
    tmp_path: Path,
    flags: tuple[str, ...],
) -> None:
    (tmp_path / "owner.btrc").write_text("int shared = 42;\n")
    (tmp_path / "macros.btrc").write_text("#define READ_SHARED() shared\n")
    (tmp_path / "consumer.btrc").write_text("import ./macros.btrc;\nint readShared() { return READ_SHARED(); }\n")
    program = tmp_path / "program.btrc"
    program.write_text("import ./owner.btrc;\nimport ./consumer.btrc;\nint main() { return 0; }\n")

    selfhost = _selfhost(semantic_btrcc, program, *flags)
    reference = _reference(program, tmp_path / "reference.c", *flags)

    assert selfhost.returncode == 1
    assert reference.returncode == 1
    assert "'shared' is defined in owner.btrc" in reference.stderr
    assert "macros.btrc does not import it" in reference.stderr
    assert selfhost.stderr == reference.stderr


@pytest.mark.parametrize("flags", ((), ("--strict-imports",)), ids=("default", "explicit"))
def test_unimported_stdlib_symbol_diagnostics_are_exactly_equal(
    semantic_btrcc: Path,
    tmp_path: Path,
    flags: tuple[str, ...],
) -> None:
    program = tmp_path / "program.btrc"
    program.write_text("Vector<int> values;\nint main() { return 0; }\n")

    selfhost = _selfhost(semantic_btrcc, program, *flags)
    reference = _reference(program, tmp_path / "reference.c", *flags)

    assert selfhost.returncode == 1
    assert reference.returncode == 1
    assert "'Vector' is defined in Vector.btrc" in reference.stderr
    assert "program.btrc does not import it" in reference.stderr
    assert selfhost.stderr == reference.stderr


def test_hosted_name_in_untrusted_lookalike_file_still_requires_import(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    (tmp_path / "shadow.btrc").write_text("int memcpy(int value) { return value; }\n")
    (tmp_path / "Bytes.btrc").write_text("int copy(int value) { return memcpy(value); }\n")
    program = tmp_path / "program.btrc"
    program.write_text("import ./shadow.btrc;\nimport ./Bytes.btrc;\nint main() { return 0; }\n")

    selfhost = _selfhost(semantic_btrcc, program)
    reference = _reference(program, tmp_path / "reference.c")

    assert selfhost.returncode == 1
    assert reference.returncode == 1
    assert "'memcpy' is defined in shadow.btrc" in reference.stderr
    assert "Bytes.btrc does not import it" in reference.stderr
    assert selfhost.stderr == reference.stderr


def test_no_stdlib_still_resolves_explicit_include_and_import(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    legacy_helper = tmp_path / "legacy_helper.btrc"
    imported_helper = tmp_path / "imported_helper.btrc"
    program = tmp_path / "program.btrc"
    legacy_helper.write_text("int legacyValue() { return 19; }\n")
    imported_helper.write_text("int importedValue() { return 23; }\n")
    program.write_text(
        '#include "legacy_helper.btrc"\n'
        "import ./imported_helper.btrc\n"
        "int main() { return legacyValue() + importedValue() == 42 ? 0 : 1; }\n"
    )

    selfhost = _run([str(semantic_btrcc), "--no-stdlib", str(program)])
    selfhost_c = tmp_path / "selfhost.c"
    if selfhost.returncode == 0:
        selfhost_c.write_text(selfhost.stdout)

    reference_c = tmp_path / "reference.c"
    reference = _run(
        [
            "python3",
            "-m",
            "src.compiler.python.main",
            str(program),
            "--no-stdlib",
            "--no-cache",
            "-o",
            str(reference_c),
        ]
    )

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    for frontend, generated in (("selfhost", selfhost_c), ("reference", reference_c)):
        source = generated.read_text()
        assert "legacyValue" in source
        assert "importedValue" in source
        assert "legacy_helper.btrc" not in source
        assert "imported_helper.btrc" not in source
        executable = tmp_path / frontend
        build = _run(
            [
                *CC,
                "-std=c11",
                "-pedantic-errors",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(generated),
                "-lm",
                "-o",
                str(executable),
            ]
        )
        assert build.returncode == 0, build.stderr
        executed = _run([str(executable)], timeout=30)
        assert executed.returncode == 0, executed.stderr
