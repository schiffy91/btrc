"""Every IR-generation module must remain independently importable."""

from __future__ import annotations

import ast
import importlib
import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
IR_GEN_ROOT = REPO_ROOT / "src" / "compiler" / "python" / "ir" / "gen"

CALL_OWNER_CONSTRUCTORS = {
    "call_operands.py": {
        "self",
        "context",
        "ownership",
        "resolver",
        "arguments",
        "hosted_results",
    },
    "call_resolver.py": {"self", "context", "expressions"},
    "calls.py": {
        "self",
        "context",
        "ownership",
        "hosted_results",
        "arguments",
        "dispatch",
    },
}


def _module_names() -> list[str]:
    return [
        ".".join(path.relative_to(REPO_ROOT).with_suffix("").parts)
        for path in sorted(IR_GEN_ROOT.rglob("*.py"))
        if path.name != "__init__.py"
    ]


@pytest.mark.parametrize("module_name", _module_names())
def test_ir_generation_module_imports(module_name: str) -> None:
    importlib.import_module(module_name)


def test_every_relative_import_names_an_existing_module() -> None:
    missing = []
    for path in sorted(IR_GEN_ROOT.rglob("*.py")):
        module_name = ".".join(path.relative_to(REPO_ROOT).with_suffix("").parts)
        package = module_name.rpartition(".")[0]
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if not isinstance(node, ast.ImportFrom) or node.level == 0:
                continue
            relative = "." * node.level + (node.module or "")
            target = importlib.util.resolve_name(relative, package)
            if importlib.util.find_spec(target) is None:
                missing.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno} -> {target}")

    assert missing == []


@pytest.mark.parametrize(
    ("filename", "expected_parameters"),
    CALL_OWNER_CONSTRUCTORS.items(),
)
def test_call_planners_receive_only_narrow_owners(
    filename: str,
    expected_parameters: set[str],
) -> None:
    """Call planning must not regain the composition root by another name."""
    path = IR_GEN_ROOT / filename
    tree = ast.parse(path.read_text(), filename=str(path))
    constructor = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "__init__"
    )
    parameters = {
        argument.arg
        for argument in [
            *constructor.args.posonlyargs,
            *constructor.args.args,
            *constructor.args.kwonlyargs,
        ]
    }
    assert parameters == expected_parameters
    assert "IRLowerer" not in path.read_text()


def test_call_root_reachthrough_is_confined_to_integration_owners() -> None:
    """Only the two migration seams may retain the procedural IR host."""
    owners = []
    for path in sorted(IR_GEN_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                and target.attr == "lowerer"
                for target in targets
            ):
                owners.append(path.name)

    assert owners == ["call_arguments.py", "call_emission.py"]
