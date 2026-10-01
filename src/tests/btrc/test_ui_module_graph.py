"""Library.UI is an acyclic import graph behind an import-only facade."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[3]
UI = REPOSITORY / "src" / "stdlib" / "UI"
MODULES = ("Text", "Semantics", "Element", "Typography", "Render", "TextRaster")
IMPORT = re.compile(r"^import Library\.UI\.(\w+);$", re.MULTILINE)


def _ui_imports(module: str) -> set[str]:
    return set(IMPORT.findall((UI / f"{module}.btrc").read_text()))


def test_ui_modules_use_imports_not_textual_includes() -> None:
    for source in UI.glob("*.btrc"):
        assert '#include "' not in source.read_text(), source.name


def test_ui_import_graph_is_acyclic_in_layer_order() -> None:
    layer = {module: index for index, module in enumerate(MODULES)}
    for module in MODULES:
        for dependency in _ui_imports(module):
            assert layer[dependency] < layer[module], f"{module} imports {dependency}"


def test_ui_facade_only_imports_every_module() -> None:
    lines = [line for line in (UI / "UI.btrc").read_text().splitlines() if line.startswith(("import", "class", "enum"))]
    assert lines == [f"import Library.UI.{module};" for module in sorted(MODULES)]


@pytest.mark.parametrize("module", MODULES)
def test_each_ui_module_compiles_alone(semantic_btrcc: Path, tmp_path: Path, module: str) -> None:
    program = tmp_path / "Alone.btrc"
    program.write_text(f"import Library.UI.{module};\n\nint main() {{ return 0; }}\n")
    reference = subprocess.run(
        [sys.executable, "-m", "src.compiler.python.main", "--no-cache", str(program), "-o", str(tmp_path / "py.c")],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert reference.returncode == 0, reference.stderr
    selfhost = subprocess.run(
        [str(semantic_btrcc), str(program)], cwd=REPOSITORY, capture_output=True, text=True, timeout=300
    )
    assert selfhost.returncode == 0, selfhost.stderr
