"""Durable ownership and package contracts for the self-hosted compiler."""

from __future__ import annotations

import re
from collections import deque
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
    expressions = _path("ir/lowering/expressions.btrc").read_text()
    ownership_calls = _path("ir/lowering/ownership/calls.btrc").read_text()

    declarations = _program("ir/lowering/calls.btrc").declarations
    classes = {
        declaration.name
        for declaration in declarations
        if type(declaration).__name__ == "ClassDecl"
    }
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
    assert all(
        "self.hostedAbi." in _path(relative).read_text()
        for relative in actual_owners
    )

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

    optimize = optimizer[optimizer.index("public void optimize(") : optimizer.index("private void eliminateUnreachable(")]
    assert optimize.index("self.setjmpSafety.apply(module)") < optimize.index("CleanupSlotValidator(")
    assert optimize.index("CleanupSlotValidator(") < optimize.index("self.eliminateUnreachable(module)")
    assert optimize.index("CycleReturnBoundaryLowerer(") < optimize.index("self.normalizeUnusedParameters(module)")
    assert optimize.index("self.normalizeUnusedParameters(module)") < optimize.index("materializeInto(")
    assert "GpuPipeline.eliminateUnreachable(module);" in optimizer
    assert "private GpuPipeline" not in optimizer

    assert "public void materializeInto(" in runtime_catalog
    assert "class CycleReturnBoundaryLowerer {" in cycle_boundaries
    assert "private IRTemporaryNames temporaryNames;" in cycle_boundaries
    assert "LoweringContext" not in cycle_boundaries[
        cycle_boundaries.index("class CycleReturnBoundaryLowerer {") : cycle_boundaries.index("class CycleBoundaryLowerer {")
    ]
    assert "class IRTemporaryNames {" in model
    assert "public IRTemporaryNames temporary_names;" in model
    assert "private IRTemporaryNames temporaryNameState;" in context
    assert "module.temporary_names = self.temporaryNameState;" in context

    assert "GeneratedHostedAbiData" not in setjmp_analysis
    assert "HostedAbiRepository hostedAbi" in setjmp_analysis
    assert "HostedAbiRepository" not in setjmp_safety
    assert "private SetjmpEffectAnalysis effectAnalysis;" in setjmp_safety
    assert "self.effectAnalysis.analyze(module)" in setjmp_safety
