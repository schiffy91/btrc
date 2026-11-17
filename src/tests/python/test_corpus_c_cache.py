"""Generated C of the corpus, shared by the gates that only change the C compiler (src/tests/corpus_c_cache.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tests import runner
from src.tests.corpus_c_cache import CorpusCCache


def _checkout(root: Path) -> Path:
    for relative in (
        "src/compiler/python/main.py",
        "src/stdlib/Vector.btrc",
        "src/language/grammar.ebnf",
        "src/runtime/c/core.c",
        "src/tests/basics/Hello.btrc",
        "src/tests/basics/expected/Hello.stdout",
        "src/tests/python/test_hello.py",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{relative}\n")
    return root


def test_a_generation_is_everything_a_transpile_can_read(tmp_path: Path) -> None:
    repo = _checkout(tmp_path / "checkout")
    compiler = tmp_path / "btrcc"
    compiler.write_text("one compiler\n")

    def generation(frontend: str = "python", selfhost_compiler: Path | None = None) -> str:
        return CorpusCCache(tmp_path / "c", repo=repo).generation(
            frontend, str(selfhost_compiler) if selfhost_compiler else None
        )

    reference, selfhost = generation(), generation("btrc", compiler)
    assert reference.startswith("python-") and selfhost.startswith("btrc-") and reference != selfhost
    # A golden or a Python suite is read by no transpile.
    (repo / "src/tests/basics/expected/Hello.stdout").write_text("another golden\n")
    (repo / "src/tests/python/test_hello.py").write_text("another suite\n")
    assert (generation(), generation("btrc", compiler)) == (reference, selfhost)
    # The self-hosted frontend is its binary; the reference frontend is its sources.
    (repo / "src/compiler/python/main.py").write_text("edited\n")
    assert generation() != reference and generation("btrc", compiler) == selfhost
    compiler.write_text("another compiler\n")
    assert generation("btrc", compiler) != selfhost
    # A program, the stdlib, the runtime and the checkout's own path each start a new generation.
    reference, selfhost = generation(), generation("btrc", compiler)
    for relative in ("src/tests/basics/Hello.btrc", "src/stdlib/Vector.btrc", "src/runtime/c/core.c"):
        (repo / relative).write_text("edited\n")
        assert generation() != reference and generation("btrc", compiler) != selfhost, relative
        reference, selfhost = generation(), generation("btrc", compiler)
    moved = _checkout(tmp_path / "elsewhere")
    for path in repo.rglob("*"):
        if path.is_file():
            (moved / path.relative_to(repo)).write_text(path.read_text())
    assert CorpusCCache(tmp_path / "c", repo=moved).generation("python") != reference


def test_a_program_is_kept_per_frontend_and_one_generation_stays(tmp_path: Path) -> None:
    repo = _checkout(tmp_path / "checkout")
    cache = CorpusCCache(tmp_path / "c", repo=repo)
    assert cache.load("python", "basics/Hello.btrc") is None
    cache.store("python", "basics/Hello.btrc", "int main(void) { return 0; }\n", ["a warning"])
    assert cache.load("python", "basics/Hello.btrc") == ("int main(void) { return 0; }\n", ["a warning"])
    assert cache.load("python", "basics/Other.btrc") is None
    compiler = tmp_path / "btrcc"
    compiler.write_text("compiler\n")
    assert cache.load("btrc", "basics/Hello.btrc", str(compiler)) is None

    # After an edit the old generation answers nothing, and the first new entry removes it.
    old = cache.root / cache.generation("python")
    (repo / "src/stdlib/Vector.btrc").write_text("edited\n")
    edited = CorpusCCache(tmp_path / "c", repo=repo)
    assert edited.load("python", "basics/Hello.btrc") is None and old.is_dir()
    edited.store("python", "basics/Hello.btrc", "int main(void) { return 1; }\n", [])
    assert not old.exists() and [path.name for path in cache.root.iterdir()] == [edited.generation("python")]


def test_sharing_is_opt_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CorpusCCache.VARIABLE, raising=False)
    assert CorpusCCache.configured() is None
    monkeypatch.setenv(CorpusCCache.VARIABLE, str(tmp_path / "c"))
    assert CorpusCCache.configured().root == tmp_path / "c"
    for invalid in ("", "build/corpus-c"):
        monkeypatch.setenv(CorpusCCache.VARIABLE, invalid)
        with pytest.raises(ValueError, match="absolute directory"):
            CorpusCCache.configured()


def test_the_runner_transpiles_a_program_once_for_every_cell_that_shares(tmp_path: Path, monkeypatch) -> None:
    program = "basics/BasicTypes.btrc"
    transpiled = []
    transpile = runner._transpile_python_with_warnings

    def counting(btrc_path, btrc_file, native_directory=None):
        transpiled.append(btrc_file)
        return transpile(btrc_path, btrc_file, native_directory)

    monkeypatch.setattr(runner, "_transpile_python_with_warnings", counting)
    monkeypatch.setattr(runner, "MODULE_UNITS", False)

    # Without a shared directory every cell transpiles for itself.
    monkeypatch.setattr(runner, "CORPUS_C", None)
    alone, _ = runner._corpus_c("python", program, None, tmp_path)
    runner._corpus_c("python", program, None, tmp_path)
    assert transpiled == [program, program]

    # With one, the second cell compiles the C the first one generated: the C compiler is not part of it.
    monkeypatch.setattr(runner, "CORPUS_C", CorpusCCache(tmp_path / "c"))
    first = runner._corpus_c("python", program, None, tmp_path)
    monkeypatch.setenv("BTRC_CC", "clang")
    monkeypatch.setenv("BTRC_CFLAGS", "-std=c11 -pedantic-errors -O2")
    second = runner._corpus_c("python", program, None, tmp_path)
    assert transpiled == [program, program, program]
    assert first == second and first[0] == alone and isinstance(first[0], str) and "main" in first[0]
    # Module units are never shared.
    monkeypatch.setattr(runner, "MODULE_UNITS", True)
    monkeypatch.setattr(runner, "_transpile_python_module_units", lambda path, directory: (("unit",), []))
    assert runner._corpus_c("python", program, None, tmp_path) == (("unit",), [])
