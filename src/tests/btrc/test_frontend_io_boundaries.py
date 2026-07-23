"""Fail-closed source I/O and dependency-resolution boundaries."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
CC = shlex.split(os.environ.get("BTRC_CC", "cc"))


def _selfhost(compiler: Path, program: Path, *, timeout: int = 120):
    return subprocess.run(
        [str(compiler), "--no-stdlib", str(program)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _reference(program: Path, output: Path, *, timeout: int = 120):
    return subprocess.run(
        [
            "python3",
            "-m",
            "src.compiler.python.main",
            str(program),
            "--no-stdlib",
            "--no-cache",
            "-o",
            str(output),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@pytest.mark.parametrize(
    "payload",
    [b"", b"\xef\xbb\xbfint main() { return 0; }\r\n"],
    ids=["empty", "bom-crlf"],
)
def test_source_text_boundary_preserves_valid_inputs(
    semantic_btrcc: Path,
    tmp_path: Path,
    payload: bytes,
) -> None:
    program = tmp_path / "valid.btrc"
    program.write_bytes(payload)

    selfhost = _selfhost(semantic_btrcc, program)
    reference = _reference(program, tmp_path / "reference.c")

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr


@pytest.mark.parametrize(
    "payload",
    [b"int main() { return 0; }\0int hidden;\n", b"int main() { return 0; }\xff\n"],
    ids=["nul", "invalid-utf8"],
)
def test_source_text_boundary_rejects_lossy_inputs(
    semantic_btrcc: Path,
    tmp_path: Path,
    payload: bytes,
) -> None:
    program = tmp_path / "invalid.btrc"
    program.write_bytes(payload)

    selfhost = _selfhost(semantic_btrcc, program)
    reference = _reference(program, tmp_path / "reference.c")

    assert selfhost.returncode != 0
    assert reference.returncode != 0


def test_source_text_boundary_enforces_the_production_size_limit(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    program = tmp_path / "oversized.btrc"
    with program.open("wb") as stream:
        stream.truncate(64 * 1024 * 1024 + 1)

    selfhost = _selfhost(semantic_btrcc, program)
    reference = _reference(program, tmp_path / "reference.c")

    assert selfhost.returncode != 0
    assert "67108864-byte limit" in selfhost.stderr
    assert reference.returncode != 0
    assert "67108864-byte limit" in reference.stderr


def test_dependency_read_failure_is_not_an_empty_include(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    dependency = tmp_path / "dependency.btrc"
    dependency.mkdir()
    program = tmp_path / "program.btrc"
    program.write_text('#include "dependency.btrc"\nint main() { return 0; }\n')

    selfhost = _selfhost(semantic_btrcc, program)
    reference = _reference(program, tmp_path / "reference.c")

    assert selfhost.returncode != 0
    assert "cannot read source file" in selfhost.stderr
    assert reference.returncode != 0
    assert "cannot read source file" in reference.stderr


@pytest.mark.parametrize(
    "directive",
    ['#include "missing.btrc"', "import ./missing.btrc", "import std.missing"],
)
def test_unresolved_dependency_is_fatal_in_both_frontends(
    semantic_btrcc: Path,
    tmp_path: Path,
    directive: str,
) -> None:
    program = tmp_path / "program.btrc"
    program.write_text(f"{directive}\nint main() {{ return 0; }}\n")

    selfhost = _selfhost(semantic_btrcc, program)
    reference = _reference(program, tmp_path / "reference.c")

    assert selfhost.returncode != 0
    assert reference.returncode != 0


@pytest.mark.parametrize("package", ["dep", "dep.module"])
def test_selfhost_rejects_package_names_instead_of_guessing_local_paths(
    semantic_btrcc: Path,
    tmp_path: Path,
    package: str,
) -> None:
    (tmp_path / package).write_text("int dependency() { return 1; }\n")
    program = tmp_path / "program.btrc"
    program.write_text(f"import {package}\nint main() {{ return 0; }}\n")

    result = _selfhost(semantic_btrcc, program)

    assert result.returncode != 0
    assert "package import" in result.stderr
    assert "unsupported by btrcc" in result.stderr


@pytest.mark.parametrize(
    "directive",
    ["import 'dep.btrc'", 'import "one.btrc" "two.btrc"', "import std.{vector"],
)
def test_malformed_imports_are_not_removed_before_parsing(
    semantic_btrcc: Path,
    tmp_path: Path,
    directive: str,
) -> None:
    program = tmp_path / "program.btrc"
    program.write_text(f"{directive}\nint main() {{ return 0; }}\n")

    selfhost = _selfhost(semantic_btrcc, program)
    reference = _reference(program, tmp_path / "reference.c")

    assert selfhost.returncode != 0
    assert reference.returncode != 0


@pytest.mark.parametrize("directive", ["import std . math", "import std . { math }"])
def test_spaced_std_imports_follow_the_grammar(
    semantic_btrcc: Path,
    tmp_path: Path,
    directive: str,
) -> None:
    program = tmp_path / "program.btrc"
    program.write_text(f"{directive}\nint main() {{ return 0; }}\n")

    selfhost = _selfhost(semantic_btrcc, program)
    reference = _reference(program, tmp_path / "reference.c")

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr


def test_quoted_import_uses_the_lexer_payload(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    (tmp_path / "semi;colon.btrc").write_text("int dependency() { return 1; }\n")
    program = tmp_path / "program.btrc"
    program.write_text('import "semi;colon.btrc" // trailing comment\nint main() { return dependency() - 1; }\n')

    selfhost = _selfhost(semantic_btrcc, program)
    reference = _reference(program, tmp_path / "reference.c")

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr


@pytest.mark.parametrize(
    "directive",
    ["import std.{\n math,\n vector\n}", "import std .\n math"],
)
def test_multiline_imports_follow_the_whitespace_insensitive_grammar(
    semantic_btrcc: Path,
    tmp_path: Path,
    directive: str,
) -> None:
    program = tmp_path / "program.btrc"
    program.write_text(f"{directive}\nint main() {{ return 0; }}\n")

    selfhost = _selfhost(semantic_btrcc, program)
    reference = _reference(program, tmp_path / "reference.c")

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr


def test_import_depth_limit_precedes_stack_exhaustion(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    count = 258
    for index in range(count):
        path = tmp_path / f"level_{index}.btrc"
        if index + 1 < count:
            path.write_text(f'#include "level_{index + 1}.btrc"\n')
        else:
            path.write_text("int terminal() { return 0; }\n")

    root = tmp_path / "level_0.btrc"
    selfhost = _selfhost(semantic_btrcc, root)
    reference = _reference(root, tmp_path / "reference.c")

    assert selfhost.returncode != 0
    assert "maximum depth of 256" in selfhost.stderr
    assert reference.returncode != 0
    assert "maximum depth of 256" in reference.stderr


@pytest.mark.skipif(not Path("/dev/full").exists(), reason="requires /dev/full")
def test_stdout_flush_failure_returns_nonzero(semantic_btrcc: Path) -> None:
    with Path("/dev/full").open("wb", buffering=0) as sink:
        result = subprocess.run(
            [str(semantic_btrcc), "--help"],
            cwd=REPO,
            stdout=sink,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )

    assert result.returncode != 0
    assert "cannot write standard output" in result.stderr


def test_frontend_scan_limits_are_wired_before_materialization() -> None:
    frontend = (REPO / "src/compiler/btrc/frontend.btrc").read_text()
    source_io = (REPO / "src/compiler/btrc/frontend_source_io.btrc").read_text()
    filesystem = (REPO / "src/stdlib/fs.btrc").read_text()

    assert "feReadRequiredDirectory(path, budget.remainingEntries())" in frontend
    assert "directory.entriesBounded(maxEntries)" in source_io
    assert "budget.addEntries(entries.len)" in frontend
    assert "budget.addFile()" in frontend
    assert "Vector<string> pending = []" in frontend
    assert "result.len > maxEntries" in filesystem


@pytest.mark.skipif(
    not CC or shutil.which(CC[0]) is None,
    reason="needs a C compiler",
)
def test_frontend_resolver_reuse_resets_state_and_isolates_results(
    tmp_path: Path,
) -> None:
    stage = REPO / "src/compiler/btrc/frontend/stage.btrc"
    grammar_path = REPO / "src/language/grammar.ebnf"
    stdlib_path = REPO / "src/stdlib"
    virtual_source = tmp_path / "virtual.btrc"
    isolated_source = tmp_path / "isolated.btrc"
    program = tmp_path / "resolver_reuse.btrc"
    generated = tmp_path / "resolver_reuse.c"
    executable = tmp_path / "resolver_reuse"
    first_source = "int firstValue;\n"
    second_source = "int secondValue;\n"
    program.write_text(
        f"import {json.dumps(str(stage))};\n"
        "\n"
        "int main() {\n"
        f"    GrammarInfo grammar = parseGrammar(feReadRequiredSource({json.dumps(str(grammar_path))}));\n"
        f"    FeStdlibRepository stdlib = FeStdlibRepository({json.dumps(str(stdlib_path))}, grammar);\n"
        "    FeFrontendResolver resolver = FeFrontendResolver(grammar, stdlib, false, true);\n"
        f"    string firstSource = {json.dumps(first_source)};\n"
        f"    string secondSource = {json.dumps(second_source)};\n"
        f"    string sourcePath = {json.dumps(str(virtual_source))};\n"
        "    FeResolvedSource first = resolver.resolve(firstSource, sourcePath);\n"
        "    FeResolvedSource second = resolver.resolve(secondSource, sourcePath);\n"
        "    if (!first.userSource.equals(firstSource)) { return 1; }\n"
        "    if (!second.userSource.equals(secondSource)) { return 2; }\n"
        f"    string isolatedPath = {json.dumps(str(isolated_source))};\n"
        "    second.dependencies.ensureSource(isolatedPath);\n"
        "    if (first.dependencies.hasSource(isolatedPath)) { return 3; }\n"
        "    return 0;\n"
        "}\n",
        encoding="utf-8",
    )

    transpile = _reference(program, generated, timeout=300)
    assert transpile.returncode == 0, transpile.stderr
    native = subprocess.run(
        [
            *CC,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(generated),
            "-o",
            str(executable),
            "-lm",
            "-lpthread",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert native.returncode == 0, native.stderr
    executed = subprocess.run(
        [str(executable)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert executed.returncode == 0, executed.stderr


@pytest.mark.skipif(
    not CC or shutil.which(CC[0]) is None,
    reason="needs a C compiler",
)
def test_stdlib_repository_instances_reuse_their_own_isolated_state(
    tmp_path: Path,
) -> None:
    stage = REPO / "src/compiler/btrc/frontend/stage.btrc"
    grammar_path = REPO / "src/language/grammar.ebnf"
    stdlib_a = tmp_path / "stdlib_a"
    stdlib_b = tmp_path / "stdlib_b"
    stdlib_a.mkdir()
    stdlib_b.mkdir()
    (stdlib_a / "vector.btrc").write_text("import std.strings\nclass Alpha { }\n", encoding="utf-8")
    (stdlib_a / "zeta.btrc").write_text("class Zeta { }\n", encoding="utf-8")
    (stdlib_b / "strings.btrc").write_text("class Beta { }\n", encoding="utf-8")

    program = tmp_path / "stdlib_repository_isolation.btrc"
    generated = tmp_path / "stdlib_repository_isolation.c"
    executable = tmp_path / "stdlib_repository_isolation"
    program.write_text(
        f"import {json.dumps(str(stage))};\n"
        "\n"
        "int main() {\n"
        f"    GrammarInfo grammar = parseGrammar(feReadRequiredSource({json.dumps(str(grammar_path))}));\n"
        f"    FeStdlibRepository first = FeStdlibRepository({json.dumps(str(stdlib_a))}, grammar);\n"
        f"    FeStdlibRepository second = FeStdlibRepository({json.dumps(str(stdlib_b))}, grammar);\n"
        "    FeStdlibRootSnapshot firstSnapshot = first.rootSnapshot();\n"
        "    FeStdlibRootSnapshot secondSnapshot = second.rootSnapshot();\n"
        "    if (firstSnapshot.count() != 2\n"
        '            || !PathTools.basename(firstSnapshot.pathAt(0)).equals("vector.btrc")\n'
        '            || !PathTools.basename(firstSnapshot.pathAt(1)).equals("zeta.btrc")) { return 1; }\n'
        "    if (secondSnapshot.count() != 1\n"
        '            || !PathTools.basename(secondSnapshot.pathAt(0)).equals("strings.btrc")) { return 2; }\n'
        '    if (!first.requiredModuleForCompilation("vector", firstSnapshot).found\n'
        '            || first.requiredModuleForCompilation("strings", firstSnapshot).found) { return 3; }\n'
        '    if (!second.requiredModuleForCompilation("strings", secondSnapshot).found\n'
        '            || second.requiredModuleForCompilation("vector", secondSnapshot).found) { return 4; }\n'
        '    string firstSource = first.sourceAtSnapshot("int userValue;\\n", firstSnapshot);\n'
        '    if (!firstSource.contains("class Alpha")\n'
        '            || !firstSource.contains("class Zeta")\n'
        '            || firstSource.contains("import std.strings")) { return 5; }\n'
        '    if (!second.sourceAtSnapshot("int userValue;\\n", secondSnapshot).contains("class Beta")) { return 6; }\n'
        '    if (second.sourceAtSnapshot("class Beta { }\\n", secondSnapshot).contains("class Beta")) { return 7; }\n'
        "    return 0;\n"
        "}\n",
        encoding="utf-8",
    )

    transpile = _reference(program, generated, timeout=300)
    assert transpile.returncode == 0, transpile.stderr
    native = subprocess.run(
        [
            *CC,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(generated),
            "-o",
            str(executable),
            "-lm",
            "-lpthread",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert native.returncode == 0, native.stderr
    executed = subprocess.run(
        [str(executable)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert executed.returncode == 0, executed.stderr


@pytest.mark.skipif(
    not CC or shutil.which(CC[0]) is None,
    reason="needs a C compiler",
)
def test_stdlib_symbol_index_detects_changes_and_recovers_atomically(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    parser_stage = REPO / "src/compiler/btrc/parser/stage.btrc"
    grammar_path = REPO / "src/language/grammar.ebnf"
    stdlib = tmp_path / "stdlib"
    stdlib.mkdir()
    indexed_source = stdlib / "alpha.btrc"
    indexed_source.write_text("class Alpha { }\n", encoding="utf-8")

    program = tmp_path / "stdlib_symbol_index_reuse.btrc"
    generated = tmp_path / "stdlib_symbol_index_reuse.c"
    executable = tmp_path / "stdlib_symbol_index_reuse"
    invalid_stdlib_source = "class Beta { }\nclass {\n"
    fixed_stdlib_source = "class Beta { }\nclass Gamma { }\n"
    program.write_text(
        "import std.fs;\n"
        f"import {json.dumps(str(parser_stage))};\n"
        "\n"
        "int main() {\n"
        f"    GrammarInfo grammar = parseGrammar(feReadRequiredSource({json.dumps(str(grammar_path))}));\n"
        f"    FeStdlibRepository repository = FeStdlibRepository({json.dumps(str(stdlib))}, grammar);\n"
        "    FeStdlibSymbolIndex index = FeStdlibSymbolIndex(grammar);\n"
        "    Map<string, Vector<string>> firstSymbols = {};\n"
        "    FeStdlibRootSnapshot firstSnapshot = repository.rootSnapshot();\n"
        "    FeStdlibSymbolIndexResult first = index.mergeSnapshotInto(\n"
        "        firstSymbols, firstSnapshot);\n"
        '    if (!first.success || !firstSymbols.has("Alpha")\n'
        '            || firstSymbols.get("Alpha").len != 1) { return 1; }\n'
        f"    if (!FileSystem.writeText({json.dumps(str(indexed_source))}, "
        f"{json.dumps(invalid_stdlib_source)})) {{ return 2; }}\n"
        "    FeStdlibRootSnapshot invalidSnapshot = repository.rootSnapshot();\n"
        "    Map<string, Vector<string>> failedSymbols = {};\n"
        "    FeStdlibSymbolIndexResult failed = index.mergeSnapshotInto(\n"
        "        failedSymbols, invalidSnapshot);\n"
        "    if (failed.success || !failed.diagnostic.contains(\n"
        '            "cannot index standard-library source")\n'
        "            || firstSnapshot.sameContents(invalidSnapshot)\n"
        '            || failedSymbols.has("Alpha")\n'
        '            || failedSymbols.has("Beta")) { return 3; }\n'
        f"    if (!FileSystem.writeText({json.dumps(str(indexed_source))}, "
        f"{json.dumps(fixed_stdlib_source)})) {{ return 4; }}\n"
        "    FeStdlibRootSnapshot fixedSnapshot = repository.rootSnapshot();\n"
        "    Map<string, Vector<string>> fixedSymbols = {};\n"
        "    FeStdlibSymbolIndexResult fixed = index.mergeSnapshotInto(\n"
        "        fixedSymbols, fixedSnapshot);\n"
        "    if (!fixed.success || fixedSnapshot.sameContents(invalidSnapshot)\n"
        '            || fixedSymbols.has("Alpha")\n'
        '            || !fixedSymbols.has("Beta")\n'
        '            || !fixedSymbols.has("Gamma")\n'
        '            || fixedSymbols.get("Beta").len != 1\n'
        '            || fixedSymbols.get("Gamma").len != 1) { return 5; }\n'
        "    return 0;\n"
        "}\n",
        encoding="utf-8",
    )

    transpile = _selfhost(semantic_btrcc, program, timeout=300)
    assert transpile.returncode == 0 and transpile.stdout.strip(), transpile.stderr
    generated.write_text(transpile.stdout, encoding="utf-8")
    native = subprocess.run(
        [
            *CC,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(generated),
            "-o",
            str(executable),
            "-lm",
            "-lpthread",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert native.returncode == 0, native.stderr
    executed = subprocess.run(
        [str(executable)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert executed.returncode == 0, executed.stderr
