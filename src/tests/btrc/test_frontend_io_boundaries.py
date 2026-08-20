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
    frontend = (REPO / "src/compiler/btrc/frontend/resolver.btrc").read_text()
    source_io = (REPO / "src/compiler/btrc/frontend/source_io.btrc").read_text()
    filesystem = (REPO / "src/stdlib/fs.btrc").read_text()
    read_required = source_io[
        source_io.index("private Vector<string> readRequired(") : source_io.index(
            "public Vector<string> sortedEntries("
        )
    ]
    budgeted_scan = source_io[source_io.index("public Vector<string> sortedEntriesWithinBudget(") :]
    tree_scan = frontend[frontend.index("private void collectTree(") : frontend.index("private void sortPaths(")]
    directory_scan = frontend[
        frontend.index("private void collectDirectory(") : frontend.index("private Vector<string> resolveRelative(")
    ]

    assert "source.readBytesBounded(self.policy.sourceByteLimit())" in source_io
    assert "directory.entriesBounded(maximumEntries)" in read_required
    assert budgeted_scan.index("path, budget.remainingEntries())") < budgeted_scan.index(
        "budget.addEntries(entries.len)"
    )
    assert tree_scan.index(".sortedEntriesWithinBudget(current, budget)") < tree_scan.index(
        "while (index < entries.len)"
    )
    assert directory_scan.index(".sortedEntriesWithinBudget(root, budget)") < directory_scan.index(
        "while (index < entries.len)"
    )
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
    stdlib_path = tmp_path / "stdlib"
    stdlib_path.mkdir()
    mutable_module = stdlib_path / "mutable.btrc"
    mutable_module.write_text("class BeforeRefresh { }\n", encoding="utf-8")
    virtual_source = tmp_path / "virtual.btrc"
    isolated_source = tmp_path / "isolated.btrc"
    isolated_source.write_text("int isolatedValue;\n", encoding="utf-8")
    program = tmp_path / "resolver_reuse.btrc"
    generated = tmp_path / "resolver_reuse.c"
    executable = tmp_path / "resolver_reuse"
    first_source = "import std.mutable;\nint firstValue;\n"
    second_source = 'import std.mutable;\n#include "isolated.btrc"\nint secondValue;\n'
    refreshed_module = "class AfterRefresh { }\n"
    program.write_text(
        f"import {json.dumps(str(stage))};\n"
        "\n"
        "int main() {\n"
        "    FeSourceResolutionPolicy resolutionPolicy = FeSourceResolutionPolicy();\n"
        "    FeSourceFileReader sourceFiles = FeSourceFileReader(resolutionPolicy);\n"
        "    FeResolutionBudget firstGraphBudget = resolutionPolicy.newResolutionBudget();\n"
        "    FeResolutionBudget secondGraphBudget = resolutionPolicy.newResolutionBudget();\n"
        '    firstGraphBudget.enter("abc", "first.btrc", 0);\n'
        '    resolutionPolicy.validateCombinedSource("left", "\\n", "right");\n'
        "    if (resolutionPolicy.sourceByteLimit() != 67108864\n"
        "            || resolutionPolicy.sourceFileLimit() != 10000\n"
        "            || resolutionPolicy.directoryEntryLimit() != 100000\n"
        "            || resolutionPolicy.importDepthLimit() != 256\n"
        "            || firstGraphBudget.sourceBytes() != 3\n"
        "            || firstGraphBudget.fileCount() != 1\n"
        "            || secondGraphBudget.sourceBytes() != 0\n"
        "            || secondGraphBudget.fileCount() != 0) { return 9; }\n"
        f"    string grammarSource = sourceFiles.readRequired({json.dumps(str(grammar_path))});\n"
        "    EbnfGrammarParser grammarParser = EbnfGrammarParser(grammarSource);\n"
        "    GrammarInfo grammar = grammarParser.parse();\n"
        f"    FeStdlibRepository stdlib = FeStdlibRepository({json.dumps(str(stdlib_path))}, sourceFiles, resolutionPolicy);\n"
        "    FeFrontendResolver resolver = FeFrontendResolver(\n"
        "        grammar, stdlib, false, true, resolutionPolicy);\n"
        f"    string firstSource = {json.dumps(first_source)};\n"
        f"    string secondSource = {json.dumps(second_source)};\n"
        f"    string sourcePath = {json.dumps(str(virtual_source))};\n"
        "    FeResolvedSource first = resolver.resolve(firstSource, sourcePath);\n"
        f"    if (!FileSystem.writeText({json.dumps(str(mutable_module))}, "
        f"{json.dumps(refreshed_module)})) {{ return 1; }}\n"
        "    FeResolvedSource second = resolver.resolve(secondSource, sourcePath);\n"
        '    if (!first.userSource.contains("class BeforeRefresh")\n'
        '            || first.userSource.contains("class AfterRefresh")\n'
        '            || !first.userSource.contains("int firstValue")) { return 2; }\n'
        '    if (!second.userSource.contains("class AfterRefresh")\n'
        '            || second.userSource.contains("class BeforeRefresh")\n'
        '            || !second.userSource.contains("int secondValue")) { return 3; }\n'
        "    if (first.stdlibSnapshot.sameContents(second.stdlibSnapshot)) { return 4; }\n"
        f"    string isolatedPath = {json.dumps(str(isolated_source))};\n"
        "    if (!second.dependencies.hasSource(isolatedPath)\n"
        "            || first.dependencies.hasSource(isolatedPath)) { return 5; }\n"
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
    os.name == "nt" or not CC or shutil.which(CC[0]) is None,
    reason="needs symlinks and a C compiler",
)
def test_import_resolver_owns_deterministic_bulk_paths_and_c11_rendering(
    tmp_path: Path,
) -> None:
    stage = REPO / "src/compiler/btrc/frontend/stage.btrc"
    grammar_path = REPO / "src/language/grammar.ebnf"
    stdlib_path = tmp_path / "stdlib"
    imports = tmp_path / "imports"
    nested = imports / "nested"
    external = tmp_path / "external"
    stdlib_path.mkdir()
    nested.mkdir(parents=True)
    external.mkdir()
    (imports / "a.btrc").write_text("int a;\n", encoding="utf-8")
    (imports / "z.c").write_text("int z;\n", encoding="utf-8")
    (imports / "ignored.txt").write_text("ignored\n", encoding="utf-8")
    (nested / "b.btrc").write_text("int b;\n", encoding="utf-8")
    (external / "leak.btrc").write_text("int leak;\n", encoding="utf-8")
    (imports / "linked").symlink_to(external, target_is_directory=True)

    program = tmp_path / "import_resolver_contract.btrc"
    generated = tmp_path / "import_resolver_contract.c"
    executable = tmp_path / "import_resolver_contract"
    program.write_text(
        f"import {json.dumps(str(stage))};\n"
        "\n"
        "int main() {\n"
        "    FeSourceResolutionPolicy resolutionPolicy = FeSourceResolutionPolicy();\n"
        "    FeSourceFileReader sourceFiles = FeSourceFileReader(resolutionPolicy);\n"
        f"    string grammarSource = sourceFiles.readRequired({json.dumps(str(grammar_path))});\n"
        "    EbnfGrammarParser grammarParser = EbnfGrammarParser(grammarSource);\n"
        "    GrammarInfo grammar = grammarParser.parse();\n"
        f"    FeStdlibRepository stdlib = FeStdlibRepository({json.dumps(str(stdlib_path))}, sourceFiles, resolutionPolicy);\n"
        "    FeStdlibRootSnapshot snapshot = stdlib.rootSnapshot();\n"
        "    FeSourceDirectoryScanner directories = FeSourceDirectoryScanner(resolutionPolicy);\n"
        "    FeImportResolver resolver = FeImportResolver(\n"
        "        stdlib, snapshot, directories, resolutionPolicy);\n"
        f"    string sourceDirectory = {json.dumps(str(tmp_path))};\n"
        f"    string importsDirectory = {json.dumps(str(imports))};\n"
        "    FeDirectoryScanBudget firstBudget = resolutionPolicy.newDirectoryBudget(importsDirectory);\n"
        "    FeDirectoryScanBudget secondBudget = resolutionPolicy.newDirectoryBudget(importsDirectory);\n"
        "    Vector<string> firstEntries = directories.sortedEntriesWithinBudget(\n"
        "        importsDirectory, firstBudget);\n"
        "    Vector<string> secondEntries = directories.sortedEntriesWithinBudget(\n"
        "        importsDirectory, secondBudget);\n"
        "    if (firstEntries.len != secondEntries.len\n"
        "            || firstBudget.entryCount() != firstEntries.len\n"
        "            || secondBudget.entryCount() != secondEntries.len\n"
        "            || firstEntries.len != 5) { return 1; }\n"
        "    int entryIndex = 0;\n"
        "    while (entryIndex < firstEntries.len) {\n"
        "        if (!firstEntries.get(entryIndex).equals(secondEntries.get(entryIndex))) { return 2; }\n"
        "        entryIndex++;\n"
        "    }\n"
        '    FeSourceText firstText = FeSourceText("alpha\\nbeta\\n");\n'
        '    FeSourceText secondText = FeSourceText("std.vector");\n'
        "    Vector<string> firstLines = firstText.lines();\n"
        "    if (firstLines.len != 3 || firstText.lineCount() != 3\n"
        '            || !firstText.startsWithAt(6, "beta")\n'
        '            || firstText.startsWithAt(-1, "alpha")\n'
        '            || !secondText.startsWithAt(0, "std.")\n'
        '            || !FeSourceText.joinLines(firstLines).equals("alpha\\nbeta\\n")) { return 3; }\n'
        '    Vector<string> direct = resolver.resolveSpec("./imports/*", sourceDirectory);\n'
        "    if (direct.len != 2\n"
        '            || !PathTools.basename(direct.get(0)).equals("a.btrc")\n'
        '            || !PathTools.basename(direct.get(1)).equals("z.c")) { return 4; }\n'
        '    Vector<string> recursive = resolver.resolveSpec("./imports/**", sourceDirectory);\n'
        "    if (recursive.len != 3\n"
        '            || !PathTools.basename(recursive.get(0)).equals("a.btrc")\n'
        '            || !recursive.get(1).endsWith("/nested/b.btrc")\n'
        '            || !PathTools.basename(recursive.get(2)).equals("z.c")) { return 5; }\n'
        '    if (!resolver.renderCInclude("safe path.c").equals(\n'
        '            "#include \\"safe path.c\\"")) { return 6; }\n'
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
    first_input = tmp_path / "first_input.btrc"
    second_input = tmp_path / "second_input.btrc"
    first_input.write_bytes(b"\xef\xbb\xbfalpha\r\n")
    second_input.write_bytes(b"beta\r")

    program = tmp_path / "stdlib_repository_isolation.btrc"
    generated = tmp_path / "stdlib_repository_isolation.c"
    executable = tmp_path / "stdlib_repository_isolation"
    program.write_text(
        f"import {json.dumps(str(stage))};\n"
        "\n"
        "int main() {\n"
        "    FeSourceResolutionPolicy resolutionPolicy = FeSourceResolutionPolicy();\n"
        "    FeSourceResolutionPolicy isolatedPolicy = FeSourceResolutionPolicy();\n"
        "    FeSourceFileReader sourceFiles = FeSourceFileReader(resolutionPolicy);\n"
        "    FeSourceFileReader isolatedSourceFiles = FeSourceFileReader(isolatedPolicy);\n"
        f"    string firstRead = sourceFiles.readRequired({json.dumps(str(first_input))});\n"
        f"    string secondRead = isolatedSourceFiles.readRequired({json.dumps(str(second_input))});\n"
        f"    string firstReadAgain = sourceFiles.readRequired({json.dumps(str(first_input))});\n"
        '    if (!firstRead.equals("alpha\\n") || !secondRead.equals("beta\\n")\n'
        "            || !firstReadAgain.equals(firstRead)) { return 1; }\n"
        f"    string grammarSource = sourceFiles.readRequired({json.dumps(str(grammar_path))});\n"
        "    EbnfGrammarParser grammarParser = EbnfGrammarParser(grammarSource);\n"
        "    GrammarInfo grammar = grammarParser.parse();\n"
        f"    FeStdlibRepository first = FeStdlibRepository({json.dumps(str(stdlib_a))}, sourceFiles, resolutionPolicy);\n"
        f"    FeStdlibRepository second = FeStdlibRepository({json.dumps(str(stdlib_b))}, sourceFiles, resolutionPolicy);\n"
        "    FeStdlibRootSnapshot firstSnapshot = first.rootSnapshot();\n"
        "    FeStdlibRootSnapshot secondSnapshot = second.rootSnapshot();\n"
        "    FeFrontendResolver firstResolver = FeFrontendResolver(\n"
        "        grammar, first, false, true, resolutionPolicy);\n"
        "    FeFrontendResolver secondResolver = FeFrontendResolver(\n"
        "        grammar, second, false, true, resolutionPolicy);\n"
        "    if (firstSnapshot.count() != 2\n"
        '            || !PathTools.basename(firstSnapshot.pathAt(0)).equals("vector.btrc")\n'
        '            || !PathTools.basename(firstSnapshot.pathAt(1)).equals("zeta.btrc")) { return 2; }\n'
        "    if (secondSnapshot.count() != 1\n"
        '            || !PathTools.basename(secondSnapshot.pathAt(0)).equals("strings.btrc")) { return 3; }\n'
        '    if (!first.requiredModuleForCompilation("vector", firstSnapshot).found\n'
        '            || first.requiredModuleForCompilation("strings", firstSnapshot).found) { return 4; }\n'
        '    if (!second.requiredModuleForCompilation("strings", secondSnapshot).found\n'
        '            || second.requiredModuleForCompilation("vector", secondSnapshot).found) { return 5; }\n'
        '    string firstSource = firstResolver.sourceAtSnapshot("int userValue;\\n", firstSnapshot);\n'
        '    if (!firstSource.contains("class Alpha")\n'
        '            || !firstSource.contains("class Zeta")\n'
        '            || firstSource.contains("import std.strings")) { return 6; }\n'
        '    if (!secondResolver.sourceAtSnapshot("int userValue;\\n", secondSnapshot).contains("class Beta")) { return 7; }\n'
        '    if (secondResolver.sourceAtSnapshot("class Beta { }\\n", secondSnapshot).contains("class Beta")) { return 8; }\n'
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
    frontend_stage = REPO / "src/compiler/btrc/frontend/stage.btrc"
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
        f"import {json.dumps(str(frontend_stage))};\n"
        "\n"
        "FeVisibilityCheckResult checkStdlibSnapshot(\n"
        "        FeStdlibRepository repository, FeStdlibSymbolIndex index,\n"
        "        GrammarInfo grammar, FeSourceResolutionPolicy resolutionPolicy,\n"
        "        string sourcePath) {\n"
        "    FeFrontendResolver resolver = FeFrontendResolver(\n"
        "        grammar, repository, false, true, resolutionPolicy);\n"
        '    FeResolvedSource resolved = resolver.resolve("int localValue;\\n", sourcePath);\n'
        "    Lexer lexer = Lexer(resolved.source, grammar);\n"
        "    Vector<Token> tokens = lexer.tokenize();\n"
        "    Parser parser = Parser(tokens, grammar);\n"
        "    Node parsed = parser.parseProgram();\n"
        "    Map<string, bool> implicitFunctions = {};\n"
        "    FeImportVisibilityChecker checker = FeImportVisibilityChecker(\n"
        "        parsed, resolved, repository, index, grammar, implicitFunctions);\n"
        "    return checker.check();\n"
        "}\n"
        "\n"
        "int main() {\n"
        "    FeSourceResolutionPolicy resolutionPolicy = FeSourceResolutionPolicy();\n"
        "    FeSourceFileReader sourceFiles = FeSourceFileReader(resolutionPolicy);\n"
        f"    string grammarSource = sourceFiles.readRequired({json.dumps(str(grammar_path))});\n"
        "    EbnfGrammarParser grammarParser = EbnfGrammarParser(grammarSource);\n"
        "    GrammarInfo grammar = grammarParser.parse();\n"
        f"    FeStdlibRepository repository = FeStdlibRepository({json.dumps(str(stdlib))}, sourceFiles, resolutionPolicy);\n"
        "    FeStdlibSymbolIndex index = FeStdlibSymbolIndex();\n"
        f"    string sourcePath = {json.dumps(str(program))};\n"
        "    FeStdlibRootSnapshot firstSnapshot = repository.rootSnapshot();\n"
        "    FeVisibilityCheckResult first = checkStdlibSnapshot(\n"
        "        repository, index, grammar, resolutionPolicy, sourcePath);\n"
        "    Map<string, Vector<string>> firstSymbols = {};\n"
        "    index.mergeInto(firstSymbols);\n"
        "    if (!first.success || !index.currentFor(firstSnapshot)\n"
        '            || !firstSymbols.has("Alpha")\n'
        '            || firstSymbols.get("Alpha").len != 1) { return 1; }\n'
        f"    if (!FileSystem.writeText({json.dumps(str(indexed_source))}, "
        f"{json.dumps(invalid_stdlib_source)})) {{ return 2; }}\n"
        "    FeStdlibRootSnapshot invalidSnapshot = repository.rootSnapshot();\n"
        "    FeVisibilityCheckResult failed = checkStdlibSnapshot(\n"
        "        repository, index, grammar, resolutionPolicy, sourcePath);\n"
        "    Map<string, Vector<string>> failedSymbols = {};\n"
        "    index.mergeInto(failedSymbols);\n"
        "    if (failed.success || !failed.diagnostic.contains(\n"
        '            "cannot index standard-library source")\n'
        "            || firstSnapshot.sameContents(invalidSnapshot)\n"
        "            || !index.currentFor(firstSnapshot)\n"
        "            || index.currentFor(invalidSnapshot)\n"
        '            || !failedSymbols.has("Alpha")\n'
        '            || failedSymbols.get("Alpha").len != 1\n'
        '            || failedSymbols.has("Beta")) { return 3; }\n'
        f"    if (!FileSystem.writeText({json.dumps(str(indexed_source))}, "
        f"{json.dumps(fixed_stdlib_source)})) {{ return 4; }}\n"
        "    FeStdlibRootSnapshot fixedSnapshot = repository.rootSnapshot();\n"
        "    FeVisibilityCheckResult fixed = checkStdlibSnapshot(\n"
        "        repository, index, grammar, resolutionPolicy, sourcePath);\n"
        "    Map<string, Vector<string>> fixedSymbols = {};\n"
        "    index.mergeInto(fixedSymbols);\n"
        "    if (!fixed.success || fixedSnapshot.sameContents(invalidSnapshot)\n"
        "            || !index.currentFor(fixedSnapshot)\n"
        "            || index.currentFor(firstSnapshot)\n"
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
