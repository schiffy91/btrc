"""The focused GUI gate must select a driver for every GUI/tray fixture.

This is static wiring coverage, not evidence that a fixture executed. Literal
filenames/stems, named fixture subdirectories and constrained f-strings count;
a generic GUI root or a wholly variable filename cannot cover future fixtures.
"""

from __future__ import annotations

import ast
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pytest

from src.tests.process_limits import TOOL_TIMEOUT

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


@pytest.fixture
def setup_environment(tmp_path: Path) -> dict[str, str]:
    """Exercise setup policy without downloading a toolchain in every unit run."""
    tools = tmp_path / "tools"
    tools.mkdir()
    fake_nix = tools / "nix"
    fake_nix.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "args = sys.argv[1:]\n"
        "with open(os.environ['SETUP_CALLS'], 'a') as stream:\n"
        " stream.write(json.dumps(args) + '\\n')\n"
        "if 'gh' in args:\n"
        " assert 'GH_TOKEN' not in os.environ and 'GITHUB_TOKEN' not in os.environ\n"
        " if 'status' in args: sys.exit(int(os.environ.get('STORED_AUTH_FAILURE', '0')))\n"
        " if 'login' in args:\n"
        "  assert sys.stdin.read() == 'synthetic-setup-secret'\n"
        "sys.exit(int(os.environ.get('NIX_FAILURE', '0')))\n"
    )
    fake_nix.chmod(0o755)
    # Spaces and shell metacharacters remain path characters, never shell code.
    rc = tmp_path / "profile $(false); space.rc"
    rc.write_text("# existing user settings\n")
    environment = {
        **os.environ,
        "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
        "BTRC_CODEX_GCROOTS": str(tmp_path / "roots with spaces"),
        "BTRC_CODEX_RC_FILE": str(rc),
        "SETUP_CALLS": str(tmp_path / "calls.jsonl"),
    }
    environment.pop("GH_TOKEN", None)
    environment.pop("GITHUB_TOKEN", None)
    return environment


def _setup(environment: dict[str, str], *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(REPO / "tools/ui/codex-setup.sh"), *arguments],
        env=environment,
        capture_output=True,
        text=True,
        timeout=TOOL_TIMEOUT,
    )


def _setup_calls(environment: dict[str, str]) -> list[list[str]]:
    path = Path(environment["SETUP_CALLS"])
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_setup_is_repeatable_and_platforms_are_opt_in(setup_environment: dict[str, str]) -> None:
    rc = Path(setup_environment["BTRC_CODEX_RC_FILE"])
    for _ in range(2):
        result = _setup(setup_environment)
        assert result.returncode == 0, result.stderr
    assert rc.read_text() == "# existing user settings\n\nexport BTRC_TEST_RUNNER=linux-devcontainer\n"
    calls = _setup_calls(setup_environment)
    assert len(calls) == 8
    assert not any(".#platforms" in call or "gh" in call for call in calls)
    assert calls[:4] == calls[4:]
    result = _setup(setup_environment, "--platforms")
    assert result.returncode == 0, result.stderr
    assert sum(".#platforms" in call for call in _setup_calls(setup_environment)) == 1


@pytest.mark.parametrize("stored_failure", ["0", "1"])
def test_setup_persists_supplied_secret_only_when_needed(
    setup_environment: dict[str, str], stored_failure: str
) -> None:
    setup_environment.update(GH_TOKEN="synthetic-setup-secret", STORED_AUTH_FAILURE=stored_failure)
    result = _setup(setup_environment)
    assert result.returncode == 0, result.stderr
    assert "synthetic-setup-secret" not in result.stdout + result.stderr
    calls = _setup_calls(setup_environment)
    assert sum("login" in call for call in calls) == int(stored_failure)
    assert not any("setup-git" in call for call in calls)


def test_setup_failure_does_not_claim_ready_or_edit_rc(setup_environment: dict[str, str]) -> None:
    setup_environment["NIX_FAILURE"] = "23"
    result = _setup(setup_environment)
    assert result.returncode == 23
    assert "ready" not in result.stdout
    assert Path(setup_environment["BTRC_CODEX_RC_FILE"]).read_text() == "# existing user settings\n"


def test_setup_rejects_unknown_options_before_mutation(setup_environment: dict[str, str]) -> None:
    result = _setup(setup_environment, "--platfroms")
    assert result.returncode == 2
    assert _setup_calls(setup_environment) == []
