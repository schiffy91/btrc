"""Durable ownership and package contracts for the self-hosted compiler."""

from __future__ import annotations

import re
from collections import Counter, deque
from collections.abc import Iterator
from dataclasses import fields, is_dataclass
from functools import cache
from pathlib import Path

from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser

REPO = Path(__file__).resolve().parents[3]
SELFHOST = REPO / "src/compiler/btrc"

EXPECTED_BTRC_FILES = frozenset(
    """
    analyzer/analyzer.btrc
    analyzer/declarations.btrc
    analyzer/expressions.btrc
    analyzer/generics.btrc
    analyzer/gpu.btrc
    analyzer/hosted_abi.btrc
    analyzer/models.btrc
    analyzer/operators.btrc
    analyzer/ownership/cycles.btrc
    analyzer/ownership/values.btrc
    analyzer/source_macros.btrc
    analyzer/stage.btrc
    analyzer/types.btrc
    analyzer/validation/borrows.btrc
    analyzer/validation/calls.btrc
    analyzer/validation/constants.btrc
    analyzer/validation/control_flow.btrc
    analyzer/validation/declarations.btrc
    analyzer/validation/expressions.btrc
    analyzer/validation/names.btrc
    analyzer/validation/ownership.btrc
    analyzer/validation/storage.btrc
    analyzer/validation/types.btrc
    analyzer/validation/validator.btrc
    btrcc_main.btrc
    cli/driver.btrc
    compiler.btrc
    frontend/models.btrc
    frontend/resolver.btrc
    frontend/source_io.btrc
    frontend/stage.btrc
    frontend/stdlib.btrc
    frontend/visibility.btrc
    generated/ast/node.btrc
    generated/hosted_abi/tables.btrc
    generated/runtime/catalog.btrc
    ir/emitter.btrc
    ir/gpu/pipeline.btrc
    ir/gpu/wgsl.btrc
    ir/lowering/aggregates.btrc
    ir/lowering/assignments.btrc
    ir/lowering/callable_flow.btrc
    ir/lowering/callables.btrc
    ir/lowering/calls.btrc
    ir/lowering/concurrency.btrc
    ir/lowering/context.btrc
    ir/lowering/control_flow.btrc
    ir/lowering/declarations.btrc
    ir/lowering/expressions.btrc
    ir/lowering/functions.btrc
    ir/lowering/generics.btrc
    ir/lowering/lowerer.btrc
    ir/lowering/ownership/calls.btrc
    ir/lowering/ownership/cycle_boundaries.btrc
    ir/lowering/ownership/lifetime.btrc
    ir/lowering/ownership/managed_types.btrc
    ir/lowering/ownership/operands.btrc
    ir/lowering/ownership/semantics.btrc
    ir/lowering/statements.btrc
    ir/lowering/strings.btrc
    ir/lowering/types.btrc
    ir/model.btrc
    ir/optimization/cleanup.btrc
    ir/optimization/optimizer.btrc
    ir/optimization/setjmp/analysis.btrc
    ir/optimization/setjmp/safety.btrc
    ir/runtime/catalog.btrc
    ir/runtime/references.btrc
    ir/stage.btrc
    lexer/lexer.btrc
    lexer/stage.btrc
    parser/parser.btrc
    parser/source_macros.btrc
    parser/stage.btrc
    pipeline/models.btrc
    pipeline/pipeline.btrc
    pipeline/stage.btrc
    syntax/grammar.btrc
    syntax/identity.btrc
    syntax/literals.btrc
    syntax/tokens.btrc
    syntax/types.btrc
    tools/ast/dump_main.btrc
    tools/ast/generate_main.btrc
    tools/ast/schema.btrc
    tools/frontend_main.btrc
    tools/lex_main.btrc
    tools/parse_main.btrc
    """.split()  # noqa: SIM905 - the normative tree is clearest as an indented block
)

STAGE_MANIFESTS = frozenset(
    {
        "lexer/stage.btrc",
        "frontend/stage.btrc",
        "parser/stage.btrc",
        "analyzer/stage.btrc",
        "ir/stage.btrc",
        "pipeline/stage.btrc",
    }
)

PUBLIC_ENTRY_POINTS = frozenset(
    {
        "btrcc_main.btrc",
        "tools/frontend_main.btrc",
        "tools/lex_main.btrc",
        "tools/parse_main.btrc",
        "tools/ast/dump_main.btrc",
        "tools/ast/generate_main.btrc",
    }
)

# Public surfaces that only external probes exercise: the dependency graph's
# membership query and the two identity spellings the shared type-identity
# contract pins in both compilers (see fixtures/type_identity_driver.btrc).
INTENTIONAL_DEFINITION_ONLY_METHODS = frozenset(
    {
        ("FeDependencyGraph", "hasSource"),
        ("TypeComposition", "substitutionPointerDepth"),
        ("TypeIdentity", "symbolComponent"),
    }
)

REQUIRED_OWNER_BY_PATH = {
    "compiler.btrc": "Compiler",
    "cli/driver.btrc": "BtrccDriver",
    "pipeline/pipeline.btrc": "CompilerPipeline",
    "lexer/lexer.btrc": "Lexer",
    "parser/parser.btrc": "Parser",
    "parser/source_macros.btrc": "SourceMacroDefinition",
    "frontend/source_io.btrc": "FeSourceFileReader",
    "frontend/stdlib.btrc": "FeStdlibRepository",
    "frontend/resolver.btrc": "FeFrontendResolver",
    "frontend/visibility.btrc": "FeImportVisibilityChecker",
    "analyzer/analyzer.btrc": "SemanticAnalyzer",
    "analyzer/declarations.btrc": "DeclarationRegistry",
    "analyzer/types.btrc": "SemanticTypeSystem",
    "analyzer/expressions.btrc": "ExpressionTypeResolver",
    "analyzer/generics.btrc": "GenericSpecializer",
    "analyzer/operators.btrc": "OperatorSemantics",
    "analyzer/hosted_abi.btrc": "HostedAbiRepository",
    "analyzer/source_macros.btrc": "SourceMacroNamespace",
    "analyzer/gpu.btrc": "GpuSemantics",
    "analyzer/ownership/values.btrc": "ManagedValueSemantics",
    "analyzer/ownership/cycles.btrc": "CycleSemantics",
    "analyzer/validation/validator.btrc": "SemanticValidator",
    "analyzer/validation/types.btrc": "TypeValidator",
    "analyzer/validation/constants.btrc": "ConstantValidator",
    "analyzer/validation/names.btrc": "NameValidator",
    "analyzer/validation/storage.btrc": "StorageValidator",
    "analyzer/validation/ownership.btrc": "OwnershipValidator",
    "analyzer/validation/borrows.btrc": "BorrowValidator",
    "analyzer/validation/calls.btrc": "CallValidator",
    "analyzer/validation/expressions.btrc": "ExpressionValidator",
    "analyzer/validation/control_flow.btrc": "ControlFlowValidator",
    "analyzer/validation/declarations.btrc": "DeclarationValidator",
    "ir/runtime/catalog.btrc": "RuntimeHelperCatalog",
    "ir/runtime/references.btrc": "RuntimeReferenceCollector",
    "ir/lowering/context.btrc": "LoweringContext",
    "ir/lowering/lowerer.btrc": "IRLowerer",
    "ir/lowering/types.btrc": "CTypeLowerer",
    "ir/lowering/declarations.btrc": "DeclarationLowerer",
    "ir/lowering/generics.btrc": "GenericLowerer",
    "ir/lowering/functions.btrc": "FunctionLowerer",
    "ir/lowering/statements.btrc": "StatementLowerer",
    "ir/lowering/control_flow.btrc": "ControlFlowLowerer",
    "ir/lowering/expressions.btrc": "ExpressionLowerer",
    "ir/lowering/calls.btrc": "CallLowerer",
    "ir/lowering/callables.btrc": "CallableValueSemantics",
    "ir/lowering/callable_flow.btrc": "CallableFlowState",
    "ir/lowering/assignments.btrc": "AssignmentLowerer",
    "ir/lowering/aggregates.btrc": "AggregateValueLowerer",
    "ir/lowering/strings.btrc": "StringLowerer",
    "ir/lowering/concurrency.btrc": "ConcurrencyLowerer",
    "ir/lowering/ownership/semantics.btrc": "OwnershipSemantics",
    "ir/lowering/ownership/operands.btrc": "OwnershipOperandPlanner",
    "ir/lowering/ownership/calls.btrc": "CallOwnershipLowerer",
    "ir/lowering/ownership/lifetime.btrc": "ManagedLifetimeLowerer",
    "ir/lowering/ownership/managed_types.btrc": "ManagedTypeLowerer",
    "ir/lowering/ownership/cycle_boundaries.btrc": "CycleBoundaryLowerer",
    "ir/gpu/wgsl.btrc": "GpuWgslEmitter",
    "ir/gpu/pipeline.btrc": "GpuPipeline",
    "ir/optimization/optimizer.btrc": "IROptimizer",
    "ir/optimization/cleanup.btrc": "CleanupSlotValidator",
    "ir/optimization/setjmp/analysis.btrc": "SetjmpEffectAnalysis",
    "ir/optimization/setjmp/safety.btrc": "SetjmpSafetyPlanner",
    "ir/emitter.btrc": "CEmitter",
}

_IMPORT = re.compile(r"^\s*import\s+([^;]+);", re.MULTILINE)
_BTRC_INCLUDE = re.compile(r"#include\s+\"[^\"]+\.btrc\"")


def _path(relative: str) -> Path:
    return SELFHOST / relative


@cache
def _program(relative: str):
    path = _path(relative)
    return Parser(Lexer(path.read_text(), str(path)).tokenize()).parse()


def _local_imports(relative: str) -> tuple[str, ...]:
    imports: list[str] = []
    path = _path(relative)
    for spec in _IMPORT.findall(path.read_text()):
        spec = spec.strip()
        if not spec.endswith(".btrc"):
            continue
        target = (path.parent / spec).resolve()
        assert target.is_relative_to(SELFHOST.resolve()), f"{relative} imports outside the package: {spec}"
        assert target.is_file(), f"{relative} imports missing unit: {spec}"
        imports.append(target.relative_to(SELFHOST.resolve()).as_posix())
    return tuple(imports)


def _import_graph() -> dict[str, set[str]]:
    return {relative: set(_local_imports(relative)) for relative in EXPECTED_BTRC_FILES}


def _cycle_residue(graph: dict[str, set[str]]) -> set[str]:
    indegree = {node: 0 for node in graph}
    reverse = {node: set() for node in graph}
    for node, dependencies in graph.items():
        for dependency in dependencies:
            indegree[node] += 1
            reverse[dependency].add(node)
    ready = deque(node for node, degree in indegree.items() if degree == 0)
    while ready:
        dependency = ready.popleft()
        for node in reverse[dependency]:
            indegree[node] -= 1
            if indegree[node] == 0:
                ready.append(node)
    return {node for node, degree in indegree.items() if degree != 0}


def _class_declarations() -> dict[str, tuple[str, object]]:
    declarations: dict[str, tuple[str, object]] = {}
    for relative in EXPECTED_BTRC_FILES:
        for declaration in _program(relative).declarations:
            if type(declaration).__name__ != "ClassDecl":
                continue
            assert declaration.name not in declarations, f"duplicate class owner: {declaration.name}"
            declarations[declaration.name] = (relative, declaration)
    return declarations


def _type_bases(type_expr) -> set[str]:
    bases = {type_expr.base}
    for argument in type_expr.generic_args:
        bases.update(_type_bases(argument))
    return bases


def _retained_owner_graph() -> dict[str, set[str]]:
    declarations = _class_declarations()
    graph = {name: set() for name in declarations}
    for name, (_, declaration) in declarations.items():
        for member in declaration.members:
            if type(member).__name__ != "FieldDecl":
                continue
            graph[name].update(_type_bases(member.type) & declarations.keys())
        graph[name].discard(name)
    return graph


def _without_comments(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"//.*", "", source)


def _ast_nodes(root: object) -> Iterator[object]:
    pending = [root]
    while pending:
        node = pending.pop()
        if is_dataclass(node) and not isinstance(node, type):
            yield node
            pending.extend(getattr(node, field.name) for field in fields(node))
        elif isinstance(node, (list, tuple)):
            pending.extend(node)
        elif isinstance(node, dict):
            pending.extend(node.values())


def _declaring_method(
    classes: dict[str, tuple[str, object]], owner: str | None, name: str
) -> tuple[str, object] | None:
    visited: set[str] = set()
    while owner is not None and owner in classes and owner not in visited:
        visited.add(owner)
        declaration = classes[owner][1]
        for member in declaration.members:
            if type(member).__name__ == "MethodDecl" and member.name == name:
                return owner, member
        owner = declaration.parent
    return None


def _member_result_owner(classes: dict[str, tuple[str, object]], owner: str | None, name: str) -> str | None:
    visited: set[str] = set()
    while owner is not None and owner in classes and owner not in visited:
        visited.add(owner)
        declaration = classes[owner][1]
        for member in declaration.members:
            if member.name != name:
                continue
            if type(member).__name__ in {"FieldDecl", "PropertyDecl"}:
                return member.type.base
            if type(member).__name__ == "MethodDecl":
                return member.return_type.base
        owner = declaration.parent
    return None


def _receiver_owner(
    expression: object,
    current: str | None,
    bindings: dict[str, object],
    classes: dict[str, tuple[str, object]],
) -> str | None:
    kind = type(expression).__name__
    if kind == "SelfExpr":
        return current
    if kind == "SuperExpr":
        return classes[current][1].parent if current is not None else None
    if kind == "Identifier":
        binding = bindings.get(
            expression.name,
            expression.name if expression.name in classes else None,
        )
        return binding if isinstance(binding, str) else getattr(binding, "base", None)
    if kind == "NewExpr":
        return expression.type.base
    if kind == "CastExpr":
        return expression.target_type.base
    if kind == "CallExpr":
        callee = expression.callee
        if type(callee).__name__ == "Identifier" and callee.name in classes:
            return callee.name
        if type(callee).__name__ == "FieldAccessExpr":
            if type(callee.obj).__name__ == "Identifier":
                receiver_type = bindings.get(callee.obj.name)
                generic_arguments = getattr(receiver_type, "generic_args", [])
                if callee.field in {"get", "first", "last", "iterGet"} and generic_arguments:
                    return generic_arguments[0].base
                if callee.field in {"getOrDefault", "iterValueAt"} and len(generic_arguments) > 1:
                    return generic_arguments[1].base
            owner = _receiver_owner(callee.obj, current, bindings, classes)
            return _member_result_owner(classes, owner, callee.field)
    if kind == "FieldAccessExpr":
        owner = _receiver_owner(expression.obj, current, bindings, classes)
        return _member_result_owner(classes, owner, expression.field)
    return None


def _callable_bindings(
    body: object,
    parameters: list[object],
    current: str | None,
    classes: dict[str, tuple[str, object]],
) -> dict[str, object]:
    bindings = {parameter.name: parameter.type for parameter in parameters}
    if current is not None:
        bindings["self"] = current
        owner: str | None = current
        visited: set[str] = set()
        while owner is not None and owner in classes and owner not in visited:
            visited.add(owner)
            for member in classes[owner][1].members:
                if type(member).__name__ in {"FieldDecl", "PropertyDecl"}:
                    bindings.setdefault(member.name, member.type)
            owner = classes[owner][1].parent

    variables = [node for node in _ast_nodes(body) if type(node).__name__ == "VarDeclStmt"]
    for variable in variables:
        if variable.type is not None and variable.type.base != "var":
            bindings[variable.name] = variable.type
    while True:
        changed = False
        for variable in variables:
            if variable.name in bindings:
                continue
            owner = _receiver_owner(variable.initializer, current, bindings, classes)
            if owner is not None:
                bindings[variable.name] = owner
                changed = True
        if not changed:
            return bindings


def test_selfhost_tree_is_the_exact_ownership_namespace() -> None:
    actual = {path.relative_to(SELFHOST).as_posix() for path in SELFHOST.rglob("*.btrc")}

    assert actual == EXPECTED_BTRC_FILES
    assert len(actual) == 88
    assert {path.name for path in SELFHOST.glob("*.btrc")} == {"btrcc_main.btrc", "compiler.btrc"}


def test_every_unit_parses_and_behavior_files_have_complete_owners() -> None:
    missing_classes: list[str] = []
    for relative in EXPECTED_BTRC_FILES:
        declarations = _program(relative).declarations
        if relative in STAGE_MANIFESTS or relative in PUBLIC_ENTRY_POINTS:
            continue
        if not any(type(declaration).__name__ == "ClassDecl" for declaration in declarations):
            missing_classes.append(relative)

    assert missing_classes == []

    classes = _class_declarations()
    missing_owners = {relative: owner for relative, owner in REQUIRED_OWNER_BY_PATH.items() if owner not in classes}
    misplaced_owners = {
        relative: (owner, classes[owner][0])
        for relative, owner in REQUIRED_OWNER_BY_PATH.items()
        if owner in classes and classes[owner][0] != relative
    }
    assert missing_owners == {}
    assert misplaced_owners == {}


def test_call_lowering_has_one_typed_target_resolution_owner() -> None:
    calls = _path("ir/lowering/calls.btrc").read_text()
    expressions = _path("ir/lowering/expressions.btrc").read_text()
    operators = _path("analyzer/operators.btrc").read_text()
    ownership_calls = _path("ir/lowering/ownership/calls.btrc").read_text()
    statements = _path("ir/lowering/statements.btrc").read_text()

    declarations = _program("ir/lowering/calls.btrc").declarations
    classes = {declaration.name for declaration in declarations if type(declaration).__name__ == "ClassDecl"}
    assert {
        "CallSignature",
        "CallTarget",
        "CallTargetResolver",
        "CallArgumentPlan",
        "CallLowerer",
    } <= classes
    assert "CallTargetResolver callTargets" in expressions
    assert "CallTargetResolver targets" in ownership_calls
    assert "callTargetResolvedParameters" not in expressions
    assert "paramsForCall" not in expressions
    assert "parametersFor" not in ownership_calls
    assert "self.expressions.lowerAssignedValueRaw(" not in statements
    assert 'mangled + "_new"' not in statements
    assert "replaceOptionalFallback" not in calls
    assert expressions.count("private bool replaceOptionalFallback(") == 1
    assert expressions.count("private string optionalResultVariable(") == 1
    assert expressions.count("private IRNode? optionalResultAssignment(") == 1
    assert expressions.count("private bool replaceOptionalResultDefinition(") == 1
    assert expressions.count("private bool replaceOptionalSequenceFallback(") == 1
    assert "resultName = alias;" in expressions
    assert "node.expr, resultName" in expressions
    assert "node.args.get(node.args.len - 1), resultName" in expressions
    assert "absentAssignment.right = fallback;" in expressions
    assert "definition.condition" not in expressions
    assert operators.count("private bool isOptionalValueExpression(") == 1
    assert "expression.kind == NK_CALL_EXPR" in operators
    assert "expression.callee.kind == NK_FIELD_ACCESS_EXPR" in operators


def test_default_helpers_share_call_claim_and_function_body_owners() -> None:
    definitions: dict[str, list[str]] = {
        "ensureDefaultHelper": [],
        "materializeDefaultHelper": [],
        "materializeDeferredClosure": [],
    }
    for relative in EXPECTED_BTRC_FILES:
        for declaration in _program(relative).declarations:
            if type(declaration).__name__ != "ClassDecl":
                continue
            for member in declaration.members:
                if type(member).__name__ == "MethodDecl" and member.name in definitions:
                    definitions[member.name].append(f"{relative}:{declaration.name}")

    assert definitions == {
        "ensureDefaultHelper": ["ir/lowering/calls.btrc:CallLowerer"],
        "materializeDefaultHelper": ["ir/lowering/functions.btrc:FunctionLowerer"],
        "materializeDeferredClosure": ["ir/lowering/functions.btrc:FunctionLowerer"],
    }
    calls = _path("ir/lowering/calls.btrc").read_text()
    expressions = _path("ir/lowering/expressions.btrc").read_text()
    functions = _path("ir/lowering/functions.btrc").read_text()
    lowerer = _path("ir/lowering/lowerer.btrc").read_text()
    assert "activeModule().function_decls.push(declaration)" in calls
    assert "selfType.generic_args.push(" in calls
    assert expressions.count("self.calls.ensureDefaultHelper(") == 1
    assert "self.calls.defaultHelperSymbol(" not in expressions
    assert "self.calls.takePendingDefaultHelpers()" in functions
    assert "activeModule().functions.push(definition)" in functions
    assert lowerer.count("self.functions.materializeDeferredClosure()") == 1


def test_gpu_call_classification_has_one_semantic_owner() -> None:
    definitions: dict[str, list[str]] = {
        "callResolvesToIntrinsic": [],
        "callResolvesToSourceSymbol": [],
    }
    for relative in EXPECTED_BTRC_FILES:
        for declaration in _program(relative).declarations:
            if type(declaration).__name__ != "ClassDecl":
                continue
            for member in declaration.members:
                if type(member).__name__ == "MethodDecl" and member.name in definitions:
                    definitions[member.name].append(f"{relative}:{declaration.name}")

    assert definitions == {
        "callResolvesToIntrinsic": ["analyzer/gpu.btrc:GpuSemantics"],
        "callResolvesToSourceSymbol": ["analyzer/gpu.btrc:GpuSemantics"],
    }
    semantics = _path("analyzer/gpu.btrc").read_text()
    calls = _path("analyzer/validation/calls.btrc").read_text()
    wgsl = _path("ir/gpu/wgsl.btrc").read_text()
    contextual = semantics[semantics.index("public string contextualExprBase(") :]
    assert contextual.count("callResolvesToIntrinsic(") == 2
    assert "callResolvesToBuiltin(" not in contextual
    assert calls.count("self.gpu.callResolvesToIntrinsic(") == 2
    assert calls.count("self.gpu.callResolvesToSourceSymbol(") == 1
    assert "self.state.gpuCallable\n            && !self.state.inParameterDefault" in calls
    assert wgsl.count("self.semantics.callResolvesToSourceSymbol(") == 1
    assert "callResolvesToBuiltin(" not in calls
    assert "callResolvesToBuiltin(" not in wgsl


def test_member_indexes_share_analyzed_canonical_identity() -> None:
    definitions: list[str] = []
    for relative in EXPECTED_BTRC_FILES:
        for declaration in _program(relative).declarations:
            if type(declaration).__name__ != "ClassDecl":
                continue
            definitions.extend(
                f"{relative}:{declaration.name}"
                for member in declaration.members
                if type(member).__name__ == "MethodDecl" and member.name == "memberKey"
            )

    assert definitions == ["analyzer/models.btrc:Analyzed"]
    models = _path("analyzer/models.btrc").read_text()
    declarations = _path("analyzer/declarations.btrc").read_text()
    assert "class string memberKey(string owner, string member)" in models
    assert models.count("Analyzed.memberKey(") == 3
    assert declarations.count("Analyzed.memberKey(") == 2
    assert "DeclarationRegistry.memberKey(" not in declarations


def test_managed_instance_field_stores_have_one_typed_owner() -> None:
    owned_methods = {
        "planStaticFieldStore",
        "materializeStaticFieldStore",
        "planInstanceFieldStore",
        "materializeInstanceFieldStore",
    }
    definitions: list[str] = []
    for relative in EXPECTED_BTRC_FILES:
        for declaration in _program(relative).declarations:
            if type(declaration).__name__ != "ClassDecl":
                continue
            definitions.extend(
                f"{relative}:{declaration.name}.{member.name}"
                for member in declaration.members
                if type(member).__name__ == "MethodDecl" and member.name in owned_methods
            )

    assert definitions == [
        "ir/lowering/ownership/managed_types.btrc:ManagedTypeLowerer.planStaticFieldStore",
        "ir/lowering/ownership/managed_types.btrc:ManagedTypeLowerer.materializeStaticFieldStore",
        "ir/lowering/ownership/managed_types.btrc:ManagedTypeLowerer.planInstanceFieldStore",
        "ir/lowering/ownership/managed_types.btrc:ManagedTypeLowerer.materializeInstanceFieldStore",
    ]
    managed_types = _path("ir/lowering/ownership/managed_types.btrc").read_text()
    expressions = _path("ir/lowering/expressions.btrc").read_text()
    assert "member.kind != NK_FIELD_DECL" in managed_types
    assert 'member.access == "class"' in managed_types
    assert "self.managedValues.isClass(concreteReceiver)" in managed_types
    assert managed_types.count("DeclarationRegistry.propertyNeedsBacking(member)") == 1
    assert managed_types.count("DeclarationRegistry.propertyTargetUsesBacking(") == 1
    assert managed_types.count("self.context.currentPropertyBacking") == 1
    assert expressions.count("self.managedTypes.planStaticFieldStore(") == 1
    assert expressions.count("self.managedTypes.materializeStaticFieldStore(") == 1
    assert expressions.count("self.managedTypes.planInstanceFieldStore(") == 1
    assert expressions.count("self.managedTypes.materializeInstanceFieldStore(") == 1
    assert "self.managedLifetime.replaceEdge(" not in expressions


def test_static_initializer_classification_is_typed_and_storage_owned() -> None:
    relative = "analyzer/validation/storage.btrc"
    declarations = _program(relative).declarations
    category = next(
        declaration
        for declaration in declarations
        if type(declaration).__name__ == "EnumDecl" and declaration.name == "StaticInitializerCategory"
    )
    assert [value.name for value in category.values] == [
        "STATIC_INITIALIZER_INVALID",
        "STATIC_INITIALIZER_INTEGER",
        "STATIC_INITIALIZER_ARITHMETIC",
        "STATIC_INITIALIZER_ADDRESS",
    ]

    validator = next(
        declaration
        for declaration in declarations
        if type(declaration).__name__ == "ClassDecl" and declaration.name == "StorageValidator"
    )
    classifier = next(member for member in validator.members if member.name == "staticInitializerCategory")
    assert classifier.return_type.base == "StaticInitializerCategory"
    assert re.search(r"\bSC_(?:INVALID|INTEGER|ARITHMETIC|ADDRESS)\b", _path(relative).read_text()) is None

    storage = _path(relative).read_text()
    declaration_source = _path("analyzer/validation/declarations.btrc").read_text()
    assert "bool hasStaticStorage = isGlobal" in storage
    assert "!self.staticInitializer(" in storage
    assert "self.storage.staticInitializer(" in declaration_source
    assert "StaticInitializerCategory" not in declaration_source
    assert "staticInitializerCategory(" not in declaration_source


def test_static_initializer_lowering_uses_structured_constant_operators() -> None:
    expressions = _path("ir/lowering/expressions.btrc").read_text()
    statements = _path("ir/lowering/statements.btrc").read_text()
    static_lowering = expressions[
        expressions.index("private IRNode lowerStaticBinaryInitializer(") : expressions.index(
            "/* Bounded-depth lowering for long left-associated string concatenations. */"
        )
    ]

    for constructor in (
        "IRNode.binary(",
        "IRNode.unary(",
        "IRNode.cast(",
        "IRNode.ternary(",
        "IRNode.addressOf(",
        "IRNode.indexAccess(",
    ):
        assert constructor in static_lowering
    assert "__btrc_div" not in static_lowering
    assert "__btrc_mod" not in static_lowering
    assert statements.count("self.expressions.lowerStaticInitializer(") >= 3

    runtime_numeric = expressions[
        expressions.index("public IRNode lowerNumericValues(") : expressions.index(
            "public IRNode lowerNumericComparisonValues("
        )
    ]
    assert 'if (op == "/" || op == "%")' in runtime_numeric
    assert 'string helper = "__btrc_div";' in runtime_numeric
    assert 'if (op == "%") { helper = "__btrc_mod"; }' in runtime_numeric


def test_expression_lowering_has_no_uninitialized_managed_ir_locals() -> None:
    offenders = {
        relative: match.group(0).strip()
        for relative in EXPECTED_BTRC_FILES
        for match in re.finditer(
            r"(?m)^\s*IRNode\s+[A-Za-z_][A-Za-z0-9_]*\s*;",
            _without_comments(_path(relative).read_text()),
        )
    }
    assert offenders == {}


def test_ir_binary_nodes_use_the_canonical_typed_kind() -> None:
    model = _program("ir/model.btrc")
    ir_kind = next(
        declaration
        for declaration in model.declarations
        if type(declaration).__name__ == "EnumDecl" and declaration.name == "IRKind"
    )
    variants = {value.name for value in ir_kind.values}
    assert "IRK_BINOP" in variants
    assert "IRK_BINARY" not in variants
    assert all(re.search(r"\bIRK_BINARY\b", _path(relative).read_text()) is None for relative in EXPECTED_BTRC_FILES)


def test_concurrency_requires_the_contexts_bound_module() -> None:
    context = _path("ir/lowering/context.btrc").read_text()
    concurrency = _path("ir/lowering/concurrency.btrc").read_text()
    assert "public IRModule activeModule()" in context
    assert "if (self.module == null)" in context
    assert "IRModule module = self.context.activeModule();" in concurrency
    assert "self.context.module.functions" not in concurrency


def test_same_owner_method_calls_are_explicitly_qualified() -> None:
    unqualified: list[str] = []
    for relative in EXPECTED_BTRC_FILES:
        for declaration in _program(relative).declarations:
            if type(declaration).__name__ != "ClassDecl":
                continue
            methods = [member for member in declaration.members if type(member).__name__ == "MethodDecl"]
            method_names = {method.name for method in methods if not method.is_constructor}
            for method in methods:
                for node in _ast_nodes(method.body):
                    if type(node).__name__ != "CallExpr":
                        continue
                    callee = node.callee
                    if type(callee).__name__ == "Identifier" and callee.name in method_names:
                        unqualified.append(f"{relative}:{node.line} {declaration.name}.{method.name} -> {callee.name}")

    assert unqualified == []


def test_only_explicit_external_probes_are_definition_only() -> None:
    classes = _class_declarations()
    methods = {
        (owner, member.name): member
        for owner, (_, declaration) in classes.items()
        for member in declaration.members
        if type(member).__name__ == "MethodDecl"
    }
    references: Counter[tuple[str, str]] = Counter()
    unresolved_names: set[str] = set()

    def count_callable(body: object, parameters: list[object], current: str | None) -> None:
        bindings = _callable_bindings(body, parameters, current, classes)
        for node in _ast_nodes(body):
            if type(node).__name__ == "FieldAccessExpr":
                owner = _receiver_owner(node.obj, current, bindings, classes)
                target = _declaring_method(classes, owner, node.field)
                if target is None:
                    unresolved_names.add(node.field)
                else:
                    references[(target[0], target[1].name)] += 1
            elif (
                current is not None and type(node).__name__ == "CallExpr" and type(node.callee).__name__ == "Identifier"
            ):
                target = _declaring_method(classes, current, node.callee.name)
                if target is not None:
                    references[(target[0], target[1].name)] += 1

    for _, declaration in classes.values():
        for member in declaration.members:
            if type(member).__name__ == "MethodDecl" and member.body is not None:
                count_callable(member.body, member.params, declaration.name)
    for relative in EXPECTED_BTRC_FILES:
        for declaration in _program(relative).declarations:
            if type(declaration).__name__ == "FunctionDecl" and declaration.body is not None:
                count_callable(declaration.body, declaration.params, None)

    identities_by_name: dict[str, set[tuple[str, str]]] = {}
    for identity in methods:
        identities_by_name.setdefault(identity[1], set()).add(identity)
    for name in unresolved_names:
        identities = identities_by_name.get(name, set())
        if len(identities) == 1:
            references[next(iter(identities))] += 1

    definition_only = {
        identity
        for identity, method in methods.items()
        if method.body is not None
        and not method.is_abstract
        and not method.is_constructor
        and references[identity] == 0
    }
    assert definition_only == INTENTIONAL_DEFINITION_ONLY_METHODS


def test_lexer_owns_its_cursor_and_literal_scanning() -> None:
    declarations = _program("lexer/lexer.btrc").declarations
    classes = [declaration for declaration in declarations if type(declaration).__name__ == "ClassDecl"]

    assert [declaration.name for declaration in classes] == ["Lexer"]
    lexer = classes[0]
    fields = [member for member in lexer.members if type(member).__name__ == "FieldDecl"]
    methods = [member for member in lexer.members if type(member).__name__ == "MethodDecl"]

    assert {field.name for field in fields if field.access == "public"} == {"failed", "diagnostic"}
    assert {field.name for field in fields if field.access == "private"} == {
        "source",
        "sourceLen",
        "grammar",
        "pos",
        "line",
        "col",
        "tokens",
        "complete",
    }
    assert {method.name for method in methods if method.access == "public"} == {"Lexer", "tokenize"}
    assert {"readNumber", "readString", "readChar", "readFstring", "appendEscape"} <= {
        method.name for method in methods if method.access == "private"
    }
    assert not any(parameter.type.base == "Lexer" for method in methods for parameter in method.params)


def test_stage_manifests_are_import_only_and_no_source_is_textually_included() -> None:
    included_sources = {
        relative: _BTRC_INCLUDE.findall(_without_comments(_path(relative).read_text()))
        for relative in EXPECTED_BTRC_FILES
        if _BTRC_INCLUDE.search(_without_comments(_path(relative).read_text()))
    }
    assert included_sources == {}

    for relative in STAGE_MANIFESTS:
        body = _without_comments(_path(relative).read_text())
        statements = [line.strip() for line in body.splitlines() if line.strip()]
        assert statements
        assert all(re.fullmatch(r"import\s+[^;]+;", statement) for statement in statements), relative


def test_imports_resolve_form_a_dag_and_reach_every_unit() -> None:
    graph = _import_graph()

    assert _cycle_residue(graph) == set()

    reachable: set[str] = set()
    pending = list(PUBLIC_ENTRY_POINTS)
    while pending:
        relative = pending.pop()
        if relative in reachable:
            continue
        reachable.add(relative)
        pending.extend(graph[relative])

    assert reachable == EXPECTED_BTRC_FILES


def test_retained_collaborators_form_a_dag_without_composition_root_leaks() -> None:
    graph = _retained_owner_graph()

    assert _cycle_residue(graph) == set()

    forbidden_roots = {"IRLowerer", "SemanticAnalyzer", "Compiler"}
    leaked_roots = {
        owner: sorted(dependencies & forbidden_roots)
        for owner, dependencies in graph.items()
        if dependencies & forbidden_roots
    }
    assert leaked_roots == {}
    assert graph["Compiler"] & {"CompilerPipeline"} == {"CompilerPipeline"}

    for state_name in ("LoweringContext", "SemanticValidationState"):
        retained_services = {
            dependency
            for dependency in graph[state_name]
            if dependency.endswith(
                (
                    "Analyzer",
                    "Catalog",
                    "Lowerer",
                    "Pipeline",
                    "Registry",
                    "Repository",
                    "Resolver",
                    "Semantics",
                    "Validator",
                )
            )
        }
        assert retained_services == set(), state_name


def test_hosted_abi_is_pipeline_owned_and_injected_only_into_query_owners() -> None:
    expected_owners = {
        "analyzer/declarations.btrc",
        "analyzer/expressions.btrc",
        "analyzer/gpu.btrc",
        "analyzer/validation/borrows.btrc",
        "analyzer/validation/calls.btrc",
        "analyzer/validation/declarations.btrc",
        "analyzer/validation/names.btrc",
        "analyzer/validation/ownership.btrc",
        "ir/gpu/pipeline.btrc",
        "ir/lowering/callables.btrc",
        "ir/lowering/calls.btrc",
        "ir/lowering/concurrency.btrc",
        "ir/lowering/declarations.btrc",
        "ir/lowering/expressions.btrc",
        "ir/lowering/functions.btrc",
        "ir/lowering/ownership/semantics.btrc",
        "ir/lowering/statements.btrc",
        "ir/lowering/strings.btrc",
        "ir/lowering/types.btrc",
        "ir/optimization/setjmp/analysis.btrc",
        "pipeline/pipeline.btrc",
    }
    actual_owners = {
        relative
        for relative in EXPECTED_BTRC_FILES
        if "private HostedAbiRepository hostedAbi;" in _path(relative).read_text()
    }
    assert actual_owners == expected_owners
    assert all("self.hostedAbi." in _path(relative).read_text() for relative in actual_owners)

    pipeline = _path("pipeline/pipeline.btrc").read_text()
    analyzer = _path("analyzer/analyzer.btrc").read_text()
    lowerer = _path("ir/lowering/lowerer.btrc").read_text()
    models = _path("analyzer/models.btrc").read_text()
    validation_state = _path("analyzer/validation/types.btrc").read_text()
    hosted_abi = _path("analyzer/hosted_abi.btrc").read_text()
    declarations = _path("analyzer/declarations.btrc").read_text()

    assert pipeline.count("HostedAbiRepository(") == 1
    assert "self.hostedAbi = HostedAbiRepository(" in pipeline
    assert "HostedAbiRepository" not in models
    assert "hostedAbi" not in validation_state
    assert "HostedAbiRepository" not in analyzer.split("public SemanticAnalyzer(", 1)[0]
    assert "HostedAbiRepository" not in lowerer.split("public IRLowerer(", 1)[0]
    assert "HostedAbiRepository" not in _path("ir/optimization/optimizer.btrc").read_text()
    assert "HostedAbiRepository" not in _path("ir/optimization/setjmp/safety.btrc").read_text()
    assert "lexicalBindingCName" not in models
    assert "string name, bool typeConflict" in hosted_abi
    assert "public string sourceFunctionSymbol(string name)" in declarations
    assert "class string sourceFunctionSymbol" not in declarations

    service_location = {
        relative: marker
        for relative in EXPECTED_BTRC_FILES
        for marker in (".analyzed.hostedAbi", ".state.analyzed.hostedAbi")
        if marker in _path(relative).read_text()
    }
    assert service_location == {}


def test_only_explicit_process_entry_points_have_top_level_behavior() -> None:
    actual: dict[str, list[str]] = {}
    for relative in EXPECTED_BTRC_FILES:
        functions = [
            declaration.name
            for declaration in _program(relative).declarations
            if type(declaration).__name__ == "FunctionDecl"
        ]
        if functions:
            actual[relative] = functions

    assert actual == {relative: ["main"] for relative in PUBLIC_ENTRY_POINTS}


def test_retired_facades_and_parallel_compilers_cannot_return() -> None:
    combined = "\n".join(_path(relative).read_text() for relative in EXPECTED_BTRC_FILES)

    for retired in (
        "IRGen",
        "SemanticAnalyzerMixin",
        "CycleRuntimeSourceCatalog",
        "CycleRuntimeDependencyCatalog",
        "_UserGenericEmitter",
        "bindCollaborators",
        "bindGenerics",
    ):
        assert retired not in combined

    assert not any(
        "utils" in Path(relative).stem or "helpers" in Path(relative).stem for relative in EXPECTED_BTRC_FILES
    )


def test_pipeline_exposes_the_six_stage_ir_boundary_explicitly() -> None:
    pipeline = _path("pipeline/pipeline.btrc").read_text()
    lowerer = _path("ir/lowering/lowerer.btrc").read_text()
    optimizer = _path("ir/optimization/optimizer.btrc").read_text()
    runtime_catalog = _path("ir/runtime/catalog.btrc").read_text()
    setjmp_analysis = _path("ir/optimization/setjmp/analysis.btrc").read_text()
    setjmp_safety = _path("ir/optimization/setjmp/safety.btrc").read_text()
    cycle_boundaries = _path("ir/lowering/ownership/cycle_boundaries.btrc").read_text()
    context = _path("ir/lowering/context.btrc").read_text()
    model = _path("ir/model.btrc").read_text()

    lower_call = pipeline.index("IRModule module = lowerer.lower(program);")
    optimize_call = pipeline.index("optimizer.optimize(module, options.runDce);")
    emit_call = pipeline.index("emitter.emit(module)")
    assert lower_call < optimize_call < emit_call

    for forbidden in (
        "../optimization/",
        "../runtime/references.btrc",
        "setDceEnabled",
        "dceEnabled",
        "collectHelpers",
        "IROptimizer",
        "SetjmpSafetyPlanner",
        "CleanupSlotValidator",
        "installProgramBoundary",
    ):
        assert forbidden not in lowerer

    optimize = optimizer[
        optimizer.index("public void optimize(") : optimizer.index("private void eliminateUnreachable(")
    ]
    assert optimize.index("self.setjmpSafety.apply(module)") < optimize.index("CleanupSlotValidator(")
    assert optimize.index("CleanupSlotValidator(") < optimize.index("self.eliminateUnreachable(module)")
    assert optimize.index("CycleReturnBoundaryLowerer(") < optimize.index("self.normalizeUnusedParameters(module)")
    assert optimize.index("self.normalizeUnusedParameters(module)") < optimize.index("materializeInto(")
    assert "GpuPipeline.eliminateUnreachable(module);" in optimizer
    assert "private GpuPipeline" not in optimizer

    assert "public void materializeInto(" in runtime_catalog
    assert "class CycleReturnBoundaryLowerer {" in cycle_boundaries
    assert "private IRTemporaryNames temporaryNames;" in cycle_boundaries
    assert (
        "LoweringContext"
        not in cycle_boundaries[
            cycle_boundaries.index("class CycleReturnBoundaryLowerer {") : cycle_boundaries.index(
                "class CycleBoundaryLowerer {"
            )
        ]
    )
    assert "class IRTemporaryNames {" in model
    assert "public IRTemporaryNames temporary_names;" in model
    assert "private IRTemporaryNames temporaryNameState;" in context
    assert "module.temporary_names = self.temporaryNameState;" in context

    assert "GeneratedHostedAbiData" not in setjmp_analysis
    assert "HostedAbiRepository hostedAbi" in setjmp_analysis
    assert "HostedAbiRepository" not in setjmp_safety
    assert "private SetjmpEffectAnalysis effectAnalysis;" in setjmp_safety
    assert "self.effectAnalysis.analyze(module)" in setjmp_safety
