"""Exact structural contracts for the Python AST-to-IR lowering package."""

from __future__ import annotations

import ast
import importlib
import importlib.util
from collections import Counter, defaultdict
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
LOWERING_ROOT = REPO_ROOT / "src/compiler/python/ir/lowering"
PACKAGE = "src.compiler.python.ir.lowering"

OWNER_MODULES = {
    "calls.py": "CallLowerer",
    "classes.py": "ClassLowerer",
    "collections.py": "CollectionLowerer",
    "concurrency.py": "ConcurrencyLowerer",
    "control_flow.py": "ControlFlowLowerer",
    "declarations.py": "DeclarationLowerer",
    "exceptions.py": "ExceptionLowerer",
    "expressions.py": "ExpressionLowerer",
    "functions.py": "FunctionLowerer",
    "generics.py": "GenericSpecializer",
    "gpu.py": "GpuLowerer",
    "iteration.py": "IterationLowerer",
    "lowerer.py": "IRLowerer",
    "ownership.py": "OwnershipLowerer",
    "session.py": "LoweringSession",
    "statements.py": "StatementLowerer",
    "storage.py": "StorageLowerer",
    "translation_unit.py": "TranslationUnitLowerer",
    "types.py": "CTypeLowerer",
}
EXPECTED_FILES = frozenset({"__init__.py", *OWNER_MODULES})

# Every import is counted, including imports nested below TYPE_CHECKING blocks
# and imports local to methods. The values are concrete modules, never facade
# exports.
EXPECTED_INTERNAL_IMPORTS = {
    "__init__.py": set(),
    "calls.py": {"ownership.py", "session.py", "types.py"},
    "classes.py": {
        "calls.py",
        "collections.py",
        "expressions.py",
        "generics.py",
        "ownership.py",
        "session.py",
        "statements.py",
        "types.py",
    },
    "collections.py": {"calls.py", "ownership.py", "session.py", "types.py"},
    "concurrency.py": {
        "calls.py",
        "ownership.py",
        "session.py",
        "storage.py",
        "types.py",
    },
    "control_flow.py": {
        "calls.py",
        "expressions.py",
        "ownership.py",
        "session.py",
        "types.py",
    },
    "declarations.py": {"calls.py", "expressions.py", "session.py", "types.py"},
    "exceptions.py": {
        "calls.py",
        "expressions.py",
        "ownership.py",
        "session.py",
        "types.py",
    },
    "expressions.py": {
        "calls.py",
        "collections.py",
        "concurrency.py",
        "gpu.py",
        "ownership.py",
        "session.py",
        "storage.py",
        "types.py",
    },
    "functions.py": {
        "calls.py",
        "concurrency.py",
        "exceptions.py",
        "expressions.py",
        "generics.py",
        "gpu.py",
        "ownership.py",
        "session.py",
        "statements.py",
        "types.py",
    },
    "generics.py": set(),
    "gpu.py": {"calls.py", "ownership.py", "session.py", "storage.py", "types.py"},
    "iteration.py": {"calls.py", "expressions.py", "ownership.py", "session.py", "storage.py", "types.py"},
    "lowerer.py": {
        "calls.py",
        "classes.py",
        "collections.py",
        "concurrency.py",
        "control_flow.py",
        "declarations.py",
        "exceptions.py",
        "expressions.py",
        "functions.py",
        "generics.py",
        "gpu.py",
        "iteration.py",
        "ownership.py",
        "session.py",
        "statements.py",
        "storage.py",
        "translation_unit.py",
        "types.py",
    },
    "ownership.py": {"session.py", "types.py"},
    "session.py": {"generics.py"},
    "statements.py": {
        "calls.py",
        "control_flow.py",
        "exceptions.py",
        "expressions.py",
        "gpu.py",
        "iteration.py",
        "ownership.py",
        "session.py",
        "storage.py",
        "types.py",
    },
    "storage.py": {"calls.py", "ownership.py", "session.py", "types.py"},
    "translation_unit.py": {
        "calls.py",
        "classes.py",
        "collections.py",
        "declarations.py",
        "exceptions.py",
        "expressions.py",
        "functions.py",
        "generics.py",
        "gpu.py",
        "ownership.py",
        "session.py",
        "types.py",
    },
    "types.py": {"session.py"},
}

# The primary owner graph is intentionally a DAG. These are retained lowering
# collaborators only; immutable plans and state value objects are not services.
EXPECTED_PRIMARY_RETAINED = {
    "CallLowerer": {
        "LoweringSession",
        "CTypeLowerer",
        "DefaultArgumentLoweringContext",
        "MutexConstructorLowerer",
        "OwnershipLowerer",
        "ManagedValueSemantics",
        "OwnershipOperandOrder",
    },
    "ClassLowerer": {
        "LoweringSession",
        "CTypeLowerer",
        "ExpressionLowerer",
        "StatementLowerer",
        "CollectionLowerer",
        "OwnershipLowerer",
        "ManagedValueSemantics",
        "ManagedLifetimeLowerer",
        "CycleMetadata",
        "CallLowerer",
        "CallableStorageBoundary",
        "CallableSignatureLowerer",
    },
    "CollectionLowerer": {
        "LoweringSession",
        "CTypeLowerer",
        "OwnershipLowerer",
        "ManagedValueSemantics",
        "ManagedLifetimeLowerer",
        "CycleMetadata",
        "CleanupSlotRegistry",
        "CleanupScopeState",
    },
    "ConcurrencyLowerer": {
        "LoweringSession",
        "CTypeLowerer",
        "OwnershipLowerer",
        "ManagedValueSemantics",
        "ManagedLifetimeLowerer",
        "CleanupSlotRegistry",
        "StorageLowerer",
    },
    "ControlFlowLowerer": {
        "LoweringSession",
        "CTypeLowerer",
        "ExpressionLowerer",
        "OwnershipLowerer",
        "ManagedLifetimeLowerer",
        "CleanupScopeState",
    },
    "DeclarationLowerer": {
        "LoweringSession",
        "CTypeLowerer",
        "ExpressionLowerer",
        "CallableSignatureLowerer",
    },
    "ExceptionLowerer": {
        "LoweringSession",
        "CTypeLowerer",
        "ExpressionLowerer",
        "OwnershipLowerer",
    },
    "ExpressionLowerer": {
        "LoweringSession",
        "CTypeLowerer",
        "DefaultArgumentLoweringContext",
        "OwnershipLowerer",
        "ManagedValueSemantics",
        "ManagedLifetimeLowerer",
        "CleanupSlotRegistry",
        "CleanupScopeState",
        "OwnershipOperandOrder",
        "CallBoundaryLowerer",
        "CallableStorageBoundary",
        "StorageLowerer",
        "CallLowerer",
        "CollectionLowerer",
        "ConcurrencyLowerer",
        "GpuLowerer",
    },
    "FunctionLowerer": {
        "LoweringSession",
        "CTypeLowerer",
        "DefaultArgumentLoweringContext",
        "ExpressionLowerer",
        "StatementLowerer",
        "OwnershipLowerer",
        "ExceptionLowerer",
        "ConcurrencyLowerer",
        "GpuLowerer",
        "CallLowerer",
        "CallableSignatureLowerer",
    },
    "GenericSpecializer": set(),
    "GpuLowerer": {
        "LoweringSession",
        "CTypeLowerer",
        "OwnershipLowerer",
        "ManagedValueSemantics",
        "ManagedLifetimeLowerer",
        "CleanupScopeState",
        "OwnershipOperandOrder",
        "CallLowerer",
        "StorageLowerer",
    },
    "IterationLowerer": {
        "LoweringSession",
        "CTypeLowerer",
        "StorageLowerer",
        "OwnershipLowerer",
        "ManagedValueSemantics",
        "ManagedLifetimeLowerer",
        "CleanupScopeState",
    },
    "IRLowerer": set(),
    "OwnershipLowerer": {
        "LoweringSession",
        "CTypeLowerer",
        "ManagedValueSemantics",
        "CycleMetadata",
        "ManagedLifetimeLowerer",
        "CleanupScopeState",
    },
    "LoweringSession": set(),
    "StatementLowerer": {
        "LoweringSession",
        "CTypeLowerer",
        "ExpressionLowerer",
        "StorageLowerer",
        "OwnershipLowerer",
        "CallableStorageBoundary",
        "ManagedValueSemantics",
        "ManagedLifetimeLowerer",
        "CleanupScopeState",
        "ControlFlowLowerer",
        "ExceptionLowerer",
        "IterationLowerer",
        "GpuLowerer",
    },
    "StorageLowerer": {
        "LoweringSession",
        "CTypeLowerer",
        "OwnershipLowerer",
        "ManagedValueSemantics",
        "ManagedLifetimeLowerer",
    },
    "TranslationUnitLowerer": {
        "LoweringSession",
        "CTypeLowerer",
        "ExpressionLowerer",
        "CollectionLowerer",
        "DeclarationLowerer",
        "ClassLowerer",
        "FunctionLowerer",
        "GenericSpecializer",
        "GpuLowerer",
        "ExceptionLowerer",
        "CallableSignatureLowerer",
        "CallableStorageBoundary",
        "CleanupSlotRegistry",
    },
    "CTypeLowerer": {"LoweringSession"},
}

BEHAVIOR_ARGUMENTS = frozenset(
    {
        "activate_cleanup",
        "emit_expression",
        "emit_statement",
        "fresh_temp",
        "isolated_function_context",
        "local_is_declared",
        "lower_block",
        "lower_declaration",
        "lower_expr",
        "lower_expression",
        "lower_loop_body",
        "lower_statement",
        "lower_stmt",
        "record_declaration",
        "render_type",
        "resolve_type",
        "type_of",
    }
)
COMPOSITION_BINDERS = frozenset(
    {
        "attach_collaborators",
        "attach_lowerer",
        "bind_collaborators",
        "bind_generator",
        "bind_lowerer",
        "bind_owners",
        "bind_services",
        "from_lowerer",
        "locate_owner",
        "set_generator",
        "set_lowerer",
    }
)
SERVICE_FIELDS = frozenset(
    {
        "binder",
        "callback",
        "callbacks",
        "collaborators",
        "emitter",
        "gen",
        "generator",
        "locator",
        "lowerer",
        "owners",
        "services",
    }
)


def _paths() -> tuple[Path, ...]:
    return tuple(sorted(LOWERING_ROOT.rglob("*.py")))


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(LOWERING_ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join((PACKAGE, *parts))


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def _owner_class(path: Path, name: str) -> ast.ClassDef:
    return next(node for node in _tree(path).body if isinstance(node, ast.ClassDef) and node.name == name)


def _constructor(owner: ast.ClassDef) -> ast.FunctionDef | None:
    return next(
        (node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name == "__init__"),
        None,
    )


def _parameters(function: ast.FunctionDef) -> list[ast.arg]:
    return [
        *function.args.posonlyargs,
        *function.args.args,
        *function.args.kwonlyargs,
    ]


def _is_dataclass(owner: ast.ClassDef) -> bool:
    return any(
        (isinstance(decorator, ast.Name) and decorator.id == "dataclass")
        or (
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Name)
            and decorator.func.id == "dataclass"
        )
        for decorator in owner.decorator_list
    )


def _class_definitions() -> dict[str, list[tuple[Path, ast.ClassDef]]]:
    definitions: dict[str, list[tuple[Path, ast.ClassDef]]] = defaultdict(list)
    for path in _paths():
        for node in _tree(path).body:
            if isinstance(node, ast.ClassDef):
                definitions[node.name].append((path, node))
    return definitions


def _class_registry() -> dict[str, tuple[Path, ast.ClassDef]]:
    definitions = _class_definitions()
    return {name: values[0] for name, values in definitions.items()}


def _annotation_names(annotation: ast.expr | None) -> set[str]:
    if annotation is None:
        return set()
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        try:
            annotation = ast.parse(annotation.value, mode="eval").body
        except SyntaxError:
            return {annotation.value}
    return {node.id for node in ast.walk(annotation) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(annotation) if isinstance(node, ast.Attribute)
    }


def _collaborator_names() -> set[str]:
    registry = _class_registry()
    names = set(OWNER_MODULES.values())
    names.update(
        name
        for name, (_path, owner) in registry.items()
        if not _is_dataclass(owner) and name not in {"CodegenError", "TypedOperatorError"}
    )
    return names


def _assignment_targets(node: ast.Assign | ast.AnnAssign) -> list[ast.expr]:
    return node.targets if isinstance(node, ast.Assign) else [node.target]


def _retained_fields(owner: ast.ClassDef) -> dict[str, set[str]]:
    collaborators = _collaborator_names()
    retained: dict[str, set[str]] = defaultdict(set)
    constructor = _constructor(owner)
    if constructor is not None:
        parameters = {
            parameter.arg: _annotation_names(parameter.annotation) & collaborators
            for parameter in _parameters(constructor)
            if parameter.arg != "self"
        }
        for node in ast.walk(constructor):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            if not isinstance(node.value, ast.Name) or node.value.id not in parameters:
                continue
            for target in _assignment_targets(node):
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                ):
                    retained[target.attr].update(parameters[node.value.id])
    for node in owner.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            retained[node.target.id].update(_annotation_names(node.annotation) & collaborators)
    return {name: targets for name, targets in retained.items() if targets}


def _retained_graph() -> dict[str, set[str]]:
    registry = _class_registry()
    collaborators = _collaborator_names()
    graph: dict[str, set[str]] = {}
    for name, (_path, owner) in registry.items():
        if name not in collaborators:
            continue
        fields = _retained_fields(owner)
        graph[name] = set().union(*fields.values()) if fields else set()
    return graph


def _resolve_import_base(
    module_name: str,
    path: Path,
    node: ast.ImportFrom,
) -> str:
    if not node.level:
        return node.module or ""
    package = module_name if path.name == "__init__.py" else module_name.rpartition(".")[0]
    return importlib.util.resolve_name(
        "." * node.level + (node.module or ""),
        package,
    )


def _internal_import_graph() -> dict[str, set[str]]:
    modules = {_module_name(path): path for path in _paths()}
    graph = {path.name: set() for path in modules.values()}
    for module_name, path in modules.items():
        for node in ast.walk(_tree(path)):
            targets: set[str] = set()
            if isinstance(node, ast.Import):
                targets.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = _resolve_import_base(module_name, path, node)
                targets.add(base)
                targets.update(f"{base}.{alias.name}" for alias in node.names)
            else:
                continue
            graph[path.name].update(modules[target].name for target in targets if target in modules)
    return graph


def _cyclic_components(graph: dict[str, set[str]]) -> list[set[str]]:
    """Return every non-trivial strongly connected component."""

    index = 0
    indexes: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    active: set[str] = set()
    cycles: list[set[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indexes[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        active.add(node)
        for target in graph[node]:
            if target not in graph:
                continue
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


def _self_chain(node: ast.expr) -> tuple[str, ...] | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name) or node.id != "self":
        return None
    return tuple(reversed(parts))


def _callable_aliases(tree: ast.Module) -> set[str]:
    aliases = {"Callable"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in {"typing", "collections.abc"}:
            aliases.update(alias.asname or alias.name for alias in node.names if alias.name == "Callable")
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        if "Callable" not in _annotation_names(node.value):
            continue
        for target in _assignment_targets(node):
            if isinstance(target, ast.Name):
                aliases.add(target.id)
    return aliases


def _is_callable_annotation(annotation: ast.expr, aliases: set[str]) -> bool:
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        return any(name in annotation.value.replace(".", " ").split() for name in aliases)
    return bool(_annotation_names(annotation) & aliases)


def test_lowering_package_has_the_exact_twenty_file_tree() -> None:
    relative_files = {path.relative_to(LOWERING_ROOT).as_posix() for path in LOWERING_ROOT.rglob("*.py")}
    assert relative_files == EXPECTED_FILES
    assert len(relative_files) == 20
    assert not (LOWERING_ROOT.parent / "gen").exists()
    for filename, owner in OWNER_MODULES.items():
        _owner_class(LOWERING_ROOT / filename, owner)


def test_package_init_has_an_intentional_empty_internal_api() -> None:
    path = LOWERING_ROOT / "__init__.py"
    tree = _tree(path)
    assert ast.get_docstring(tree) == "Structured AST-to-IR lowering owners."
    assert len(tree.body) == 1
    assert isinstance(tree.body[0], ast.Expr)
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(tree))
    assert "__all__" not in path.read_text()


@pytest.mark.parametrize("filename", sorted(EXPECTED_FILES))
def test_every_concrete_lowering_module_imports(filename: str) -> None:
    importlib.import_module(_module_name(LOWERING_ROOT / filename))


def test_every_relative_import_resolves() -> None:
    missing: list[str] = []
    for path in _paths():
        module_name = _module_name(path)
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.ImportFrom) or node.level == 0:
                continue
            target = _resolve_import_base(module_name, path, node)
            if importlib.util.find_spec(target) is None:
                missing.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno} -> {target}")
    assert missing == []


def test_full_internal_import_graph_is_exact_and_acyclic() -> None:
    graph = _internal_import_graph()
    assert graph == EXPECTED_INTERNAL_IMPORTS
    assert _cyclic_components(graph) == []


def test_mutex_constructor_port_is_narrow_and_preserves_import_direction() -> None:
    owner = _owner_class(LOWERING_ROOT / "calls.py", "MutexConstructorLowerer")
    assert _annotation_names(owner.bases[0]) == {"Protocol"}
    assert [node.name for node in owner.body if isinstance(node, ast.FunctionDef)] == ["create_mutex_value"]
    assert "concurrency.py" not in _internal_import_graph()["calls.py"]


def test_internal_code_imports_concrete_owners_not_the_package_facade() -> None:
    facade_imports: list[str] = []
    wildcards: list[str] = []
    for path in _paths():
        if path.name == "__init__.py":
            continue
        module_name = _module_name(path)
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.ImportFrom):
                base = _resolve_import_base(module_name, path, node)
                if base == PACKAGE:
                    facade_imports.append(f"{path.name}:{node.lineno}")
                if any(alias.name == "*" for alias in node.names):
                    wildcards.append(f"{path.name}:{node.lineno}")
            elif isinstance(node, ast.Import) and any(alias.name == PACKAGE for alias in node.names):
                facade_imports.append(f"{path.name}:{node.lineno}")
    assert facade_imports == []
    assert wildcards == []


def test_production_lowering_behavior_is_class_owned() -> None:
    loose: list[str] = []
    module_lambdas: list[str] = []
    for path in _paths():
        tree = _tree(path)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                loose.append(f"{path.name}:{node.lineno}:{node.name}")
            if isinstance(node, ast.ClassDef):
                continue
            module_lambdas.extend(
                f"{path.name}:{part.lineno}" for part in ast.walk(node) if isinstance(part, ast.Lambda)
            )
    assert loose == []
    assert module_lambdas == []


def test_owner_constructors_are_explicit_and_concrete() -> None:
    missing: list[str] = []
    vague: list[str] = []
    variadic: list[str] = []
    for filename, owner_name in OWNER_MODULES.items():
        owner = _owner_class(LOWERING_ROOT / filename, owner_name)
        constructor = _constructor(owner)
        if constructor is None:
            assert _is_dataclass(owner), f"{filename}:{owner_name} has no constructor"
    for path in _paths():
        tree = _tree(path)
        aliases = _callable_aliases(tree)
        for owner in (node for node in tree.body if isinstance(node, ast.ClassDef)):
            constructor = _constructor(owner)
            if constructor is None:
                continue
            if constructor.args.vararg is not None or constructor.args.kwarg is not None:
                variadic.append(f"{path.name}:{owner.name}")
            for parameter in _parameters(constructor):
                if parameter.arg == "self":
                    continue
                if parameter.annotation is None:
                    missing.append(f"{path.name}:{owner.name}.{parameter.arg}")
                    continue
                annotation_names = _annotation_names(parameter.annotation)
                if annotation_names & {"Any", "object"} or _is_callable_annotation(parameter.annotation, aliases):
                    vague.append(f"{path.name}:{owner.name}.{parameter.arg}:{ast.unparse(parameter.annotation)}")
    assert missing == []
    assert vague == []
    assert variadic == []


def test_retained_primary_owner_graph_is_exact_and_every_owner_scc_is_trivial() -> None:
    duplicate_classes = {
        name: [path.name for path, _owner in definitions]
        for name, definitions in _class_definitions().items()
        if len(definitions) > 1
    }
    assert duplicate_classes == {}
    registry = _class_registry()
    actual: dict[str, set[str]] = {}
    for owner_name in OWNER_MODULES.values():
        fields = _retained_fields(registry[owner_name][1])
        actual[owner_name] = set().union(*fields.values()) if fields else set()
    assert actual == EXPECTED_PRIMARY_RETAINED
    assert _cyclic_components(_retained_graph()) == []


def test_callable_provenance_is_fresh_per_body_and_never_a_retained_service() -> None:
    retained = _retained_graph()
    assert {owner for owner, dependencies in retained.items() if "CallableProvenance" in dependencies} == set()
    assert {owner for owner, dependencies in retained.items() if "CallableSignatureLowerer" in dependencies} == {
        "CallableProvenance",
        "ClassLowerer",
        "DeclarationLowerer",
        "FunctionLowerer",
        "TranslationUnitLowerer",
    }

    construction_sites: Counter[tuple[str, str]] = Counter()
    for path in _paths():
        tree = _tree(path)
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        for call in (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "CallableProvenance"
        ):
            assert len(call.args) == 4
            assert isinstance(call.args[3], ast.Attribute)
            assert isinstance(call.args[3].value, ast.Name)
            assert call.args[3].value.id == "self"
            assert call.args[3].attr == "_signatures"
            parent = parents[call]
            assert isinstance(parent, ast.Assign)
            function = parents[parent]
            while not isinstance(function, ast.FunctionDef):
                function = parents[function]
            construction_sites[(path.name, function.name)] += 1

    assert construction_sites == Counter(
        {
            ("classes.py", "emit_constructor"): 2,
            ("classes.py", "emit_destructor"): 1,
            ("classes.py", "emit_method"): 1,
            ("classes.py", "emit_inherited_methods"): 1,
            ("classes.py", "emit_property"): 2,
            ("classes.py", "emit_inherited_properties"): 1,
            ("classes.py", "emit_static_fields"): 1,
            ("classes.py", "emit_struct_decl"): 1,
            ("classes.py", "_emit_class_struct"): 1,
            ("declarations.py", "_emit_enum"): 1,
            ("declarations.py", "_emit_rich_enum"): 1,
            ("functions.py", "materialize_default_helpers"): 1,
            ("functions.py", "materialize_deferred_functions"): 1,
            ("functions.py", "emit_function_decl"): 1,
            ("functions.py", "lower_specialization"): 1,
            ("functions.py", "lower_lambda"): 1,
            ("translation_unit.py", "emit_global_var"): 1,
        }
    )
    assert "function_scope" not in "\n".join(path.read_text() for path in _paths())


def test_collaborators_are_retained_once_without_late_binders_or_locators() -> None:
    duplicates: list[str] = []
    unretained: list[str] = []
    forbidden: list[str] = []
    collaborators = _collaborator_names()
    for path in _paths():
        for owner in (node for node in _tree(path).body if isinstance(node, ast.ClassDef)):
            if owner.name.endswith(("Binder", "Locator", "Mixin")):
                forbidden.append(f"{path.name}:{owner.name}")
            forbidden.extend(
                f"{path.name}:{owner.name}.{node.name}"
                for node in owner.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and (node.name in COMPOSITION_BINDERS or node.name == "__getattr__")
            )
            constructor = _constructor(owner)
            if constructor is None:
                continue
            parameters = {
                parameter.arg: _annotation_names(parameter.annotation) & collaborators
                for parameter in _parameters(constructor)
                if parameter.arg != "self"
            }
            collaborator_parameters = {name: targets for name, targets in parameters.items() if targets}
            target_counts = Counter(target for targets in collaborator_parameters.values() for target in targets)
            duplicates.extend(
                f"{path.name}:{owner.name}:{target}" for target, count in target_counts.items() if count > 1
            )
            retained_parameters: dict[str, set[str]] = defaultdict(set)
            retained_fields: dict[str, set[str]] = defaultdict(set)
            for node in ast.walk(constructor):
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                for target in _assignment_targets(node):
                    if (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                    ):
                        if target.attr.lstrip("_") in SERVICE_FIELDS:
                            forbidden.append(f"{path.name}:{owner.name}.{target.attr}:{target.lineno}")
                        if isinstance(node.value, ast.Name) and node.value.id in collaborator_parameters:
                            retained_parameters[node.value.id].add(target.attr)
                            retained_fields[target.attr].add(node.value.id)
            duplicates.extend(
                f"{path.name}:{owner.name}.{parameter}->{sorted(fields)}"
                for parameter, fields in retained_parameters.items()
                if len(fields) > 1
            )
            duplicates.extend(
                f"{path.name}:{owner.name}.{field}<-{sorted(parameters)}"
                for field, parameters in retained_fields.items()
                if len(parameters) > 1
            )
            if owner.name != "IRLowerer":
                unretained.extend(
                    f"{path.name}:{owner.name}.{parameter}"
                    for parameter in collaborator_parameters
                    if parameter not in retained_parameters
                )
            forbidden.extend(
                f"{path.name}:{owner.name}.{parameter}"
                for parameter in parameters
                if parameter.lstrip("_") in SERVICE_FIELDS
            )
    assert duplicates == []
    assert unretained == []
    assert forbidden == []


def test_lowering_session_is_state_only() -> None:
    owner = _owner_class(LOWERING_ROOT / "session.py", "LoweringSession")
    assert _is_dataclass(owner)
    collaborators = _collaborator_names() - {"LoweringSession"}
    fields = {
        node.target.id: node
        for node in owner.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    retained_services = {
        name: _annotation_names(node.annotation) & collaborators
        for name, node in fields.items()
        if _annotation_names(node.annotation) & collaborators
    }
    dynamic_state: list[str] = []
    for node in ast.walk(owner):
        if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                and target.attr not in fields
            ):
                dynamic_state.append(f"{target.attr}:{target.lineno}")
    assert retained_services == {}
    assert not (set(fields) & SERVICE_FIELDS)
    assert dynamic_state == []


def test_raw_ir_lowering_has_no_optimizer_or_verifier_dependency() -> None:
    forbidden: list[str] = []
    for filename in ("lowerer.py", "translation_unit.py"):
        tree = _tree(LOWERING_ROOT / filename)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in {"optimizer", "verifier"}:
                forbidden.append(f"{filename}:{node.lineno}:{node.module}")
            if isinstance(node, ast.Name) and node.id in {"IROptimizer", "IRVerifier"}:
                forbidden.append(f"{filename}:{node.lineno}:{node.id}")
    assert forbidden == []


def test_runtime_helper_selection_is_owned_per_lowering_session() -> None:
    session = _owner_class(LOWERING_ROOT / "session.py", "LoweringSession")
    fields = {
        node.target.id: ast.unparse(node.annotation)
        for node in session.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    assert fields["runtime_helpers"] == "RuntimeHelperSelection"
    assert "used_helpers" not in fields

    lowerer_source = (LOWERING_ROOT / "lowerer.py").read_text()
    translation_unit_source = (LOWERING_ROOT / "translation_unit.py").read_text()
    assert "runtime_helpers=catalog.selection()" in lowerer_source
    assert "self._session.runtime_helpers.definitions()" in translation_unit_source


def test_assignment_materialization_consumes_the_ownership_plan() -> None:
    owner = _owner_class(LOWERING_ROOT / "expressions.py", "ExpressionLowerer")
    method = next(node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name == "_lower_assignment")
    ownership_calls = {
        node.func.attr
        for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and _self_chain(node.func.value) == ("_ownership",)
    }
    assert {
        "assignment_target_operands",
        "kept_target_operands",
        "assignment_rhs_supplies_owned_result",
    } <= ownership_calls


def test_no_behavior_callbacks_or_callback_bags_remain() -> None:
    callable_annotations: list[str] = []
    behavior_arguments: list[str] = []
    callback_lambdas: list[str] = []
    for path in _paths():
        tree = _tree(path)
        aliases = _callable_aliases(tree)
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for parameter in _parameters(node):
                    if parameter.arg in BEHAVIOR_ARGUMENTS:
                        behavior_arguments.append(f"{path.name}:{node.name}.{parameter.arg}:{parameter.lineno}")
                    if parameter.annotation is not None and _is_callable_annotation(parameter.annotation, aliases):
                        callable_annotations.append(f"{path.name}:{node.name}.{parameter.arg}:{parameter.lineno}")
            if isinstance(node, ast.AnnAssign) and _is_callable_annotation(node.annotation, aliases):
                callable_annotations.append(f"{path.name}:{node.lineno}")
            if isinstance(node, ast.keyword) and node.arg in BEHAVIOR_ARGUMENTS:
                behavior_arguments.append(f"{path.name}:keyword:{node.arg}:{node.lineno}")
            if isinstance(node, ast.Lambda):
                parent = parents.get(node)
                grandparent = parents.get(parent) if parent is not None else None
                is_state_factory = (
                    isinstance(parent, ast.keyword)
                    and parent.arg == "default_factory"
                    and isinstance(grandparent, ast.Call)
                    and isinstance(grandparent.func, ast.Name)
                    and grandparent.func.id == "field"
                )
                if not is_state_factory:
                    callback_lambdas.append(f"{path.name}:{node.lineno}")
    assert callable_annotations == []
    assert behavior_arguments == []
    assert callback_lambdas == []


def test_no_dynamic_self_or_private_collaborator_reach_through() -> None:
    dynamic: list[str] = []
    private: list[str] = []
    for path in _paths():
        for node in ast.walk(_tree(path)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"delattr", "getattr", "hasattr", "setattr", "vars"}
                and node.args
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == "self"
            ):
                dynamic.append(f"{path.name}:{node.lineno}:{node.func.id}")
            if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
                chain = _self_chain(node.value)
                if chain:
                    private.append(f"{path.name}:{node.lineno}:self.{'.'.join((*chain, node.attr))}")
    assert dynamic == []
    assert private == []


def test_no_legacy_composition_or_backend_dependencies_remain() -> None:
    source = "\n".join(path.read_text() for path in _paths())
    for forbidden in (
        "IRGen",
        "_UserGenericEmitter",
        "from_lowerer",
        "src.compiler.python.backend",
        "src.compiler.python.ir.gen",
    ):
        assert forbidden not in source
