"""The focused GUI gate must select a driver for every GUI/tray fixture.

This is static wiring coverage, not evidence that a fixture executed. Literal
filenames/stems, named fixture subdirectories and constrained f-strings count;
a generic GUI root or a wholly variable filename cannot cover future fixtures.
"""

from __future__ import annotations

import ast
import fnmatch
import re
from pathlib import Path, PurePosixPath

import pytest

REPO = Path(__file__).resolve().parents[3]
FIXTURE_ROOTS = ("src/tests/native/gui", "src/tests/native/tray")


def _selected_modules(makefile: str, available: set[str]) -> set[str]:
    """Expand the deliberately small Make expression used by NATIVE_GUI_TESTS."""
    logical = makefile.replace("\\\n", " ")
    match = re.search(r"^NATIVE_GUI_TESTS\s*:?=\s*(.+)$", logical, re.MULTILINE)
    assert match, "NATIVE_GUI_TESTS assignment is missing"
    expression = match[1]
    expression = re.sub(
        r"\$\(addprefix\s+([^,()]+),([^()]+)\)",
        lambda item: " ".join(item[1].strip() + word for word in item[2].split()),
        expression,
    )
    expression = re.sub(
        r"\$\(wildcard\s+([^()]+)\)",
        lambda item: " ".join(
            sorted(path for path in available if any(fnmatch.fnmatchcase(path, glob) for glob in item[1].split()))
        ),
        expression,
    )
    expression = re.sub(r"\$\(sort\s+([^()]*)\)", lambda item: " ".join(sorted(set(item[1].split()))), expression)
    assert "$" not in expression, f"Unrecognized NATIVE_GUI_TESTS expression: {expression}"
    selected = set(expression.split())
    assert selected <= available, f"Selected GUI drivers do not exist: {sorted(selected - available)}"
    return selected


def _driver_patterns(source: str) -> set[str]:
    tree = ast.parse(source)
    patterns: set[str] = set()
    # Do not interpret an f-string's individual constant pieces as literal paths.
    fragments = {id(part) for node in ast.walk(tree) if isinstance(node, ast.JoinedStr) for part in node.values}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in fragments:
            patterns.add(node.value)
        elif isinstance(node, ast.JoinedStr):
            pattern = "".join(part.value if isinstance(part, ast.Constant) else "*" for part in node.values)
            name = PurePosixPath(pattern).name
            # Require a literal basename prefix/suffix beyond the extension.
            if name.endswith(".btrc") and name.removesuffix(".btrc").replace("*", ""):
                patterns.add(pattern)
    return patterns


def _covered(fixture: str, patterns: set[str]) -> bool:
    path = PurePosixPath(fixture)
    for pattern in patterns:
        value = pattern.rstrip("/")
        if value in {str(path), path.name, path.stem}:
            return True
        for root in FIXTURE_ROOTS:
            if path.is_relative_to(root):
                relative = path.relative_to(root)
                if value in {str(relative), str(relative.with_suffix(""))}:
                    return True
        # A full named subtree drives its descendants. Bare platform labels
        # such as "linux" are not directory references.
        if any(value.startswith(root + "/") for root in FIXTURE_ROOTS) and fixture.startswith(value + "/"):
            return True
        if "*" in value and value.endswith(".btrc") and PurePosixPath(value).stem.replace("*", ""):
            candidate = str(path) if "/" in value else path.name
            if fnmatch.fnmatchcase(candidate, value):
                return True
    return False


def _uncovered(fixtures: set[str], drivers: dict[str, str], selected: set[str]) -> set[str]:
    patterns = set().union(*(_driver_patterns(drivers[module]) for module in selected))
    return {fixture for fixture in fixtures if not _covered(fixture, patterns)}


def test_native_gui_target_drives_every_fixture() -> None:
    available = {path.relative_to(REPO).as_posix() for path in (REPO / "src/tests/python").glob("test_*.py")}
    selected = _selected_modules((REPO / "Makefile").read_text(), available)
    fixtures = {path.relative_to(REPO).as_posix() for root in FIXTURE_ROOTS for path in (REPO / root).rglob("*.btrc")}
    drivers = {module: (REPO / module).read_text() for module in selected}
    assert fixtures, "GUI/tray fixture roots are empty"
    assert not (missing := _uncovered(fixtures, drivers, selected)), (
        f"Fixtures missing from focused GUI gate: {sorted(missing)}"
    )


def test_target_expands_literals_and_the_future_ui_glob() -> None:
    available = {
        "src/tests/python/test_native_gui.py",
        "src/tests/python/test_native_ui_new.py",
        "src/tests/python/test_other.py",
    }
    makefile = (
        "NATIVE_GUI_TESTS := $(addprefix src/tests/python/,test_native_gui.py) \\\n"
        " $(sort $(wildcard src/tests/python/test_native_ui_*.py))\n"
    )
    assert _selected_modules(makefile, available) == available - {"src/tests/python/test_other.py"}


def test_unselected_driver_does_not_hide_a_missing_fixture() -> None:
    fixture = "src/tests/native/gui/NewControl.btrc"
    drivers = {"selected.py": 'name = "KnownControl"', "other.py": 'name = "NewControl"'}
    assert _uncovered({fixture}, drivers, {"selected.py"}) == {fixture}


@pytest.mark.parametrize(
    "reference", ['"NativeKeyboard"', '"NativeKeyboard.btrc"', '"src/tests/native/gui/NativeKeyboard.btrc"']
)
def test_literal_names_count(reference: str) -> None:
    assert _covered("src/tests/native/gui/NativeKeyboard.btrc", _driver_patterns(f"source = {reference}"))


@pytest.mark.parametrize("reference", ['"controls/macos/ButtonAlignment"', '"controls/macos/ButtonAlignment.btrc"'])
def test_root_relative_names_cover_only_the_exact_fixture(reference: str) -> None:
    fixture = "src/tests/native/gui/controls/macos/ButtonAlignment.btrc"
    others = {
        "src/tests/native/gui/controls/macos/OtherControl.btrc",
        "src/tests/native/gui/other/ButtonAlignment.btrc",
    }
    drivers = {"selected.py": f"name = {reference}"}
    assert _uncovered({fixture, *others}, drivers, {"selected.py"}) == others
    assert _uncovered({fixture}, drivers, set()) == {fixture}


def test_named_subtree_and_constrained_filename_template_count() -> None:
    patterns = _driver_patterns(
        'directory = "src/tests/native/gui/webgpu_child"\nname = f"MacOS{control}Conformance.btrc"'
    )
    assert _covered("src/tests/native/gui/webgpu_child/Consumer.btrc", patterns)
    assert _covered("src/tests/native/gui/MacOSScrollConformance.btrc", patterns)
    assert not _covered("src/tests/native/gui/Unrelated.btrc", patterns)


@pytest.mark.parametrize(
    "source",
    [
        'root = "src/tests/native/gui"',
        'root = "src/tests/native/tray"',
        'name = f"src/tests/native/gui/{fixture}.btrc"',
        'name = f"{fixture}.btrc"',
        'platform = "linux"',
        'name = "*.btrc"',
        'name = "src/tests/native/gui/*.btrc"',
    ],
)
def test_generic_anchors_do_not_claim_fixture_coverage(source: str) -> None:
    patterns = _driver_patterns(source)
    assert not _covered("src/tests/native/gui/linux/NewControl.btrc", patterns)
    assert not _covered("src/tests/native/tray/NewTray.btrc", patterns)


def test_unknown_make_syntax_fails_loudly() -> None:
    with pytest.raises(AssertionError, match="Unrecognized"):
        _selected_modules("NATIVE_GUI_TESTS := $(shell discover-tests)\n", set())
