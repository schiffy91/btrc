"""Contracts for selecting runnable shared-language corpus files."""

from pathlib import Path

from src.tests.corpus_files import include_fixtures, language_test_files

TESTS = Path("src/tests")


def test_helper_named_programs_are_not_mistaken_for_include_fixtures():
    selected = set(language_test_files(TESTS))

    assert "gpu/GpuWithHelperFunc.btrc" in selected
    assert "stdlib/MathFloatHelpers.btrc" in selected


def test_upper_camel_contract_programs_are_runnable_corpus_entries():
    selected = set(language_test_files(TESTS))

    assert "stdlib/FileSystemHandlesContract.btrc" in selected
    assert "stdlib/FileSystemHandlesReal.btrc" in selected
    assert "stdlib/FileSystemHandleInventoryReal.btrc" in selected
    assert "stdlib/FileTreeSnapshotReal.btrc" in selected
    assert "stdlib/PrivateDirectoryReal.btrc" in selected
    assert "stdlib/RegularFileSnapshotReal.btrc" in selected


def test_native_programs_are_owned_by_their_dedicated_harnesses():
    selected = set(language_test_files(TESTS))

    assert "native/app/MacOsDirectoryPickerConformance.btrc" not in selected
    assert "native/gui/NativeContainers.btrc" not in selected


def test_formatter_fixtures_are_owned_by_syntax_preservation_tests():
    selected = set(language_test_files(TESTS))

    assert "formatter/fixtures/ImportGroups.btrc" not in selected


def test_textual_include_fixtures_are_not_standalone_corpus_programs():
    selected = set(language_test_files(TESTS))

    fixtures = include_fixtures(TESTS)

    assert selected.isdisjoint(fixtures)
    assert "control_flow/includehelpers/AngleIncludeHelper.btrc" in fixtures
    assert "imports/treehelpers/deep/Inner.btrc" in fixtures


def test_fixtures_are_derived_from_every_reference_form(tmp_path):
    (tmp_path / "topic" / "parts" / "deep").mkdir(parents=True)
    (tmp_path / "sibling").mkdir()
    for name in ("Quoted", "Angle", "Dotted", "Bare", "Parent", "Glob", "Deep"):
        (tmp_path / "topic" / "parts" / f"{name}.btrc").write_text("")
    (tmp_path / "topic" / "parts" / "deep" / "Leaf.btrc").write_text("")
    (tmp_path / "sibling" / "Up.btrc").write_text("")
    (tmp_path / "topic" / "Helpers.btrc").write_text("int main() { return 0; }\n")
    (tmp_path / "topic" / "Program.btrc").write_text(
        '#include "parts/Quoted.btrc"\n'
        "#include <parts/Angle.btrc>\n"
        "import ./parts/Dotted.btrc\n"
        'import "parts/Bare.btrc"\n'
        "import ../sibling/Up.btrc\n"
        "import Library.Vector;\n"
        '#include "native.c"\n'
    )
    (tmp_path / "topic" / "Globbing.btrc").write_text("import ./parts/deep/**\n")

    assert include_fixtures(tmp_path) == {
        "topic/parts/Quoted.btrc",
        "topic/parts/Angle.btrc",
        "topic/parts/Dotted.btrc",
        "topic/parts/Bare.btrc",
        "sibling/Up.btrc",
        "topic/parts/deep/Leaf.btrc",
    }
    assert "topic/Helpers.btrc" in language_test_files(tmp_path)


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
