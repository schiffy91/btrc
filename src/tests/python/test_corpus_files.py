"""Contracts for selecting runnable shared-language corpus files."""

from pathlib import Path

from src.tests.corpus_files import INCLUDE_FIXTURES, language_test_files

TESTS = Path("src/tests")


def test_helper_named_programs_are_not_mistaken_for_include_fixtures():
    selected = set(language_test_files(TESTS))

    assert "gpu/test_gpu_with_helper_func.btrc" in selected
    assert "stdlib/test_stdlib_math_float_helpers.btrc" in selected


def test_textual_include_fixtures_are_not_standalone_corpus_programs():
    selected = set(language_test_files(TESTS))

    assert selected.isdisjoint(INCLUDE_FIXTURES)


def test_every_runnable_program_has_a_stdout_golden():
    required = set()
    for relative in language_test_files(TESTS):
        source = TESTS / relative
        expected = source.parent / "expected" / f"{source.stem}.stdout"
        required.add(expected.relative_to(TESTS).as_posix())

    actual = {path.relative_to(TESTS).as_posix() for path in TESTS.rglob("expected/*.stdout")}

    assert required - actual == set()
    assert actual - required == set()


def test_stderr_goldens_are_adjacent_to_runnable_programs():
    allowed = set()
    for relative in language_test_files(TESTS):
        source = TESTS / relative
        expected = source.parent / "expected" / f"{source.stem}.stderr"
        allowed.add(expected.relative_to(TESTS).as_posix())

    actual = {path.relative_to(TESTS).as_posix() for path in TESTS.rglob("expected/*.stderr")}

    assert actual - allowed == set()
