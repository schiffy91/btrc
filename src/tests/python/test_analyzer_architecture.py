"""Structural contracts for the Python semantic-analysis package."""

from __future__ import annotations

import ast
import importlib
import importlib.util
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
ANALYZER_ROOT = REPO_ROOT / "src/compiler/python/analyzer"
ANALYZER_PACKAGE = "src.compiler.python.analyzer"

OWNER_MODULES = {
    "aggregates.py": "AggregateAnalyzer",
    "analyzer.py": "SemanticAnalyzer",
    "calls.py": "CallAnalyzer",
    "declarations.py": "DeclarationRegistry",
    "expressions.py": "ExpressionAnalyzer",
    "flow.py": "ControlFlowAnalyzer",
    "generated_symbols.py": "GeneratedSymbolRegistry",
    "generics.py": "GenericAnalyzer",
    "gpu.py": "GpuAnalyzer",
    "macros.py": "SourceMacroAnalyzer",
    "ownership.py": "OwnershipAnalyzer",
    "program.py": "AnalysisSession",
    "statements.py": "StatementAnalyzer",
    "storage.py": "StorageModel",
    "types.py": "TypeSystem",
}
EXPECTED_FILES = {"__init__.py", *OWNER_MODULES}

COLLABORATOR_PARAMETERS = {
    "aggregates",
    "analyzer",
    "callable_values",
    "calls",
    "context",
    "declarations",
    "expressions",
    "flow",
    "generated_symbols",
    "generics",
    "gpu",
    "hierarchy",
    "identity",
    "index",
    "intrinsics",
    "layout",
    "macros",
    "names",
    "numeric_literals",
    "ownership",
    "policy",
    "registry",
    "resolver",
    "runtime_catalog",
    "runtime_helpers",
    "semantic_analyzer",
    "session",
    "signature_types",
    "statements",
    "storage",
    "type_identity",
    "types",
    "validator",
}
COMPOSITION_ROOT_FIELDS = {
    "analyzer",
    "composition",
    "owners",
    "semantic_analyzer",
    "services",
}
FORBIDDEN_REACHTHROUGH = {
    "self.declarations.policy",
    "self.declarations.services",
    "self.registry.context",
    "self.registry.policy",
    "self.registry.services",
    "self.session.context",
    "self.types.index_protocols",
}
FORBIDDEN_ANNOTATION_NAMES = {"Any", "Callable", "object"}
SEMANTIC_OWNER_SUFFIXES = (
    "Analyzer",
    "Layout",
    "Model",
    "Policy",
    "Registry",
    "Resolver",
    "Semantics",
    "System",
    "Validator",
)
SEMANTIC_OWNER_NAMES = {
    "SourceMacroNamespace",
    "SourceRuntimeSymbols",
    "TypeIdentity",
}


def _module_name(path: Path) -> str:
    relative = path.relative_to(REPO_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def _owner_class(path: Path, name: str) -> ast.ClassDef:
    return next(node for node in _tree(path).body if isinstance(node, ast.ClassDef) and node.name == name)


def _constructor(owner: ast.ClassDef) -> ast.FunctionDef | None:
    return next(
        (node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name == "__init__"),
        None,
    )


def _module_paths() -> dict[str, Path]:
    return {_module_name(path): path for path in ANALYZER_ROOT.glob("*.py")}


def _import_targets(
    module_name: str,
    path: Path,
    known_modules: set[str],
) -> set[str]:
    """Resolve every import, including guarded and method-local imports."""
    package = module_name if path.name == "__init__.py" else module_name.rpartition(".")[0]
    targets: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for candidate in known_modules:
                    if alias.name == candidate or alias.name.startswith(candidate + "."):
                        targets.add(candidate)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = importlib.util.resolve_name(
                    "." * node.level + (node.module or ""),
                    package,
                )
            else:
                base = node.module or ""
            if base in known_modules:
                targets.add(base)
            for alias in node.names:
                candidate = f"{base}.{alias.name}"
                if candidate in known_modules:
                    targets.add(candidate)
    return targets


def _internal_import_graph() -> dict[str, set[str]]:
    modules = _module_paths()
    names = set(modules)
    return {module_name: _import_targets(module_name, path, names) for module_name, path in modules.items()}


def _cyclic_components(graph: dict[str, set[str]]) -> list[set[str]]:
    """Return non-trivial strongly connected components."""
    next_index = 0
    indexes: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    active: set[str] = set()
    cycles: list[set[str]] = []

    def visit(node: str) -> None:
        nonlocal next_index
        indexes[node] = next_index
        lowlinks[node] = next_index
        next_index += 1
        stack.append(node)
        active.add(node)
        for target in graph[node]:
            if target not in indexes:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in active:
                lowlinks[node] = min(lowlinks[node], indexes[target])
        if lowlinks[node] != indexes[node]:
            return
        component: set[str] = set()
        while stack:
            member = stack.pop()
            active.remove(member)
            component.add(member)
            if member == node:
                break
        if len(component) > 1 or node in graph[node]:
            cycles.append(component)

    for node in graph:
        if node not in indexes:
            visit(node)
    return cycles


def _parameters(function: ast.FunctionDef) -> list[ast.arg]:
    return [
        *function.args.posonlyargs,
        *function.args.args,
        *function.args.kwonlyargs,
    ]


def _assignment_targets(node: ast.Assign | ast.AnnAssign) -> list[ast.expr]:
    return [node.target] if isinstance(node, ast.AnnAssign) else node.targets


def _annotation_names(annotation: ast.expr) -> set[str]:
    names = {node.id for node in ast.walk(annotation) if isinstance(node, ast.Name)}
    for node in ast.walk(annotation):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        names.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", node.value))
    return names


def _is_bind_name(name: str) -> bool:
    public = name.lstrip("_")
    return bool(public == "bind" or public.startswith("bind_") or re.match(r"bind[A-Z]", public))


def _semantic_owner_types() -> set[str]:
    owners = set(SEMANTIC_OWNER_NAMES)
    for path in ANALYZER_ROOT.glob("*.py"):
        if path.name == "program.py":
            continue
        owners.update(
            node.name
            for node in _tree(path).body
            if isinstance(node, ast.ClassDef) and node.name.endswith(SEMANTIC_OWNER_SUFFIXES)
        )
    return owners


def test_analyzer_package_has_the_exact_owner_tree() -> None:
    assert {path.relative_to(ANALYZER_ROOT).as_posix() for path in ANALYZER_ROOT.rglob("*.py")} == EXPECTED_FILES
    for filename, owner in OWNER_MODULES.items():
        _owner_class(ANALYZER_ROOT / filename, owner)


def test_analyzer_package_manifest_is_declarative() -> None:
    failures: list[str] = []
    for node in _tree(ANALYZER_ROOT / "__init__.py").body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        if isinstance(node, ast.Assign) and all(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            continue
        failures.append(f"__init__.py:{node.lineno}:{type(node).__name__}")
    assert failures == []


@pytest.mark.parametrize("filename", sorted(EXPECTED_FILES))
def test_analyzer_module_imports(filename: str) -> None:
    importlib.import_module(_module_name(ANALYZER_ROOT / filename))


def test_analyzer_modules_import_concrete_owners_without_facades() -> None:
    failures: list[str] = []
    for path in sorted(ANALYZER_ROOT.glob("*.py")):
        for node in ast.walk(_tree(path)):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                aliases = node.names
                if any(alias.name == "*" for alias in aliases):
                    failures.append(f"{path.name}:{node.lineno}: wildcard import")
            if path.name == "__init__.py" or not isinstance(node, ast.ImportFrom):
                continue
            if node.level == 1 and node.module is None:
                failures.append(f"{path.name}:{node.lineno}: package-facade import")
            if node.level == 0 and node.module == ANALYZER_PACKAGE:
                failures.append(f"{path.name}:{node.lineno}: package-facade import")
    assert failures == []


def test_analyzer_import_graph_is_conceptually_acyclic() -> None:
    assert _cyclic_components(_internal_import_graph()) == []


def test_retained_semantic_owner_graph_is_acyclic() -> None:
    from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
    from src.compiler.python.analyzer.program import DeclarationIndex

    root = SemanticAnalyzer()
    owner_types = _semantic_owner_types()
    owner_types.add("SemanticAnalyzer")
    retained: dict[int, object] = {}
    pending = [root]
    while pending:
        owner = pending.pop()
        if id(owner) in retained or type(owner).__name__ not in owner_types:
            continue
        retained[id(owner)] = owner
        pending.extend(getattr(owner, "__dict__", {}).values())

    labels = {identifier: f"{type(owner).__name__}:{identifier}" for identifier, owner in retained.items()}
    graph = {
        labels[identifier]: {
            labels[id(collaborator)]
            for collaborator in getattr(owner, "__dict__", {}).values()
            if id(collaborator) in retained
        }
        for identifier, owner in retained.items()
    }
    assert _cyclic_components(graph) == []
    assert isinstance(root.index, DeclarationIndex)
    assert root.types.index is root.index
    assert root.declarations.index is root.index
    assert not hasattr(root.types, "declarations")


def test_declaration_index_is_not_reexported_as_registry_tables() -> None:
    from dataclasses import fields

    from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
    from src.compiler.python.analyzer.program import DeclarationIndex

    analyzer = SemanticAnalyzer()
    table_names = {field.name for field in fields(DeclarationIndex)}
    assert not (table_names & vars(analyzer.declarations).keys())


def test_declaration_registry_owns_array_return_policy() -> None:
    registry = _owner_class(ANALYZER_ROOT / "declarations.py", "DeclarationRegistry")
    methods = {node.name: node for node in registry.body if isinstance(node, ast.FunctionDef)}
    interface_registration = methods["_register_interface"]

    assert "validate_array_return" in methods
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "policy"
        and node.func.attr == "validate_array_return"
        for node in ast.walk(interface_registration)
    )
    assert not any(
        isinstance(node, ast.Attribute) and node.attr == "callables" for node in ast.walk(interface_registration)
    )


def test_production_analyzer_behavior_is_class_owned() -> None:
    loose: list[str] = []
    for path in sorted(ANALYZER_ROOT.glob("*.py")):
        for node in _tree(path).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                loose.append(f"{path.name}:{node.lineno}:{node.name}")
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                value = node.value
                if value is not None and any(isinstance(part, ast.Lambda) for part in ast.walk(value)):
                    loose.append(f"{path.name}:{node.lineno}:<lambda>")
    assert loose == []


def test_owner_constructor_dependencies_are_explicit_and_concrete() -> None:
    missing: list[str] = []
    forbidden: list[str] = []
    for filename, owner_name in OWNER_MODULES.items():
        owner = _owner_class(ANALYZER_ROOT / filename, owner_name)
        constructor = _constructor(owner)
        assert constructor is not None
        for parameter in _parameters(constructor):
            if parameter.arg == "self":
                continue
            if parameter.annotation is None:
                missing.append(f"{filename}:{owner_name}.{parameter.arg}")
                continue
            bad_names = _annotation_names(parameter.annotation) & FORBIDDEN_ANNOTATION_NAMES
            if bad_names:
                forbidden.append(f"{filename}:{owner_name}.{parameter.arg}: {ast.unparse(parameter.annotation)}")

    for path in sorted(ANALYZER_ROOT.glob("*.py")):
        for owner in (node for node in _tree(path).body if isinstance(node, ast.ClassDef)):
            constructor = _constructor(owner)
            if constructor is None:
                continue
            for parameter in _parameters(constructor):
                if parameter.arg == "self" or parameter.arg not in COLLABORATOR_PARAMETERS:
                    continue
                if parameter.annotation is None:
                    missing.append(f"{path.name}:{owner.name}.{parameter.arg}")
                    continue
                bad_names = _annotation_names(parameter.annotation) & FORBIDDEN_ANNOTATION_NAMES
                if bad_names:
                    forbidden.append(f"{path.name}:{owner.name}.{parameter.arg}: {ast.unparse(parameter.annotation)}")
    assert sorted(set(missing)) == []
    assert sorted(set(forbidden)) == []


def test_no_compatibility_binding_or_service_locator_seams_remain() -> None:
    failures: list[str] = []
    for path in sorted(ANALYZER_ROOT.glob("*.py")):
        tree = _tree(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name.endswith("Mixin"):
                failures.append(f"{path.name}:{node.lineno}:{node.name}")
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                node.name == "__getattr__" or _is_bind_name(node.name)
            ):
                failures.append(f"{path.name}:{node.lineno}:{node.name}")
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute) and _is_bind_name(node.func.attr):
                    failures.append(f"{path.name}:{node.lineno}:{ast.unparse(node.func)}")
                if (
                    isinstance(node.func, ast.Name)
                    and node.func.id in {"getattr", "hasattr"}
                    and node.args
                    and isinstance(node.args[0], ast.Name)
                    and node.args[0].id == "self"
                ):
                    failures.append(f"{path.name}:{node.lineno}:{node.func.id}(self, ...)")
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "self"
                and node.attr in COMPOSITION_ROOT_FIELDS
            ):
                failures.append(f"{path.name}:{node.lineno}:self.{node.attr}")
            if isinstance(node, ast.Attribute):
                expression = ast.unparse(node)
                if expression in FORBIDDEN_REACHTHROUGH:
                    failures.append(f"{path.name}:{node.lineno}:{expression}")
                if (
                    node.attr == "context"
                    and isinstance(node.value, ast.Name)
                    and node.value.id in {"declarations", "registry"}
                ):
                    failures.append(f"{path.name}:{node.lineno}:{expression}")
    assert failures == []


def test_behavior_parameters_do_not_hide_cross_owner_callbacks() -> None:
    callbacks: list[str] = []
    for path in sorted(ANALYZER_ROOT.glob("*.py")):
        for owner in (node for node in _tree(path).body if isinstance(node, ast.ClassDef)):
            for method in (node for node in owner.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
                parameters = {
                    parameter.arg for parameter in _parameters(method) if parameter.arg not in {"self", "cls"}
                }
                for call in (node for node in ast.walk(method) if isinstance(node, ast.Call)):
                    if isinstance(call.func, ast.Name) and call.func.id in parameters:
                        callbacks.append(f"{path.name}:{owner.name}.{method.name}:{call.func.id}")
    assert callbacks == ["types.py:TypeIdentity.substitute:reference_resolver"]


def test_collaborators_are_used_only_through_public_apis() -> None:
    reachthrough: list[str] = []
    for path in sorted(ANALYZER_ROOT.glob("*.py")):
        for node in ast.walk(_tree(path)):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr.startswith("_")
                and isinstance(node.func.value, ast.Attribute)
                and isinstance(node.func.value.value, ast.Name)
                and node.func.value.value.id == "self"
            ):
                continue
            reachthrough.append(f"{path.name}:{node.lineno}:self.{node.func.value.attr}.{node.func.attr}")
    assert reachthrough == []


def test_analysis_session_carries_state_but_no_semantic_owners() -> None:
    session = _owner_class(ANALYZER_ROOT / "program.py", "AnalysisSession")
    constructor = _constructor(session)
    assert constructor is not None
    assert [parameter.arg for parameter in _parameters(constructor)] == ["self"]

    owner_types = _semantic_owner_types()
    owner_references: list[str] = []
    retained_services: list[str] = []
    for node in ast.walk(session):
        if isinstance(node, ast.Name) and node.id in owner_types:
            owner_references.append(f"program.py:{node.lineno}:{node.id}")
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            for target in _assignment_targets(node):
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                    and target.attr in COLLABORATOR_PARAMETERS
                ):
                    retained_services.append(f"program.py:{target.lineno}:self.{target.attr}")
    assert owner_references == []
    assert retained_services == []
