"""White-box contracts for the self-hosted compiler's structured IR."""

import re
from pathlib import Path

from src.compiler.python.runtime.catalog import RuntimeHelperCatalog

REPO = Path(__file__).resolve().parents[3]
SELFHOST = REPO / "src" / "compiler" / "btrc"


def _source(name: str) -> str:
    return (SELFHOST / name).read_text()


def test_selfhost_has_no_raw_expression_escape_hatch() -> None:
    source = "\n".join(path.read_text() for path in SELFHOST.rglob("*.btrc"))

    assert "IRK_RAW_EXPR" not in source
    assert "irRawExpr" not in source
    assert "/* unknown expr */" not in source


def test_selfhost_has_no_raw_statement_escape_hatch() -> None:
    source = "\n".join(path.read_text() for path in SELFHOST.rglob("*.btrc"))

    assert "IRK_RAW_C" not in source
    assert "irRawC" not in source


def test_top_level_declarations_are_typed_end_to_end() -> None:
    schema = _source("ir/model.btrc")
    declarations = _source("ir/lowering/declarations.btrc")
    functions = _source("ir/lowering/functions.btrc")
    types = _source("ir/lowering/types.btrc")
    emitter = _source("ir/emitter.btrc")
    all_selfhost = "\n".join(path.read_text() for path in SELFHOST.rglob("*.btrc"))

    for legacy in (
        "public Vector<string> raw_sections;",
        "public Vector<string> forward_decls;",
        "public Vector<string> includes;",
        "public Vector<string> enum_defs;",
        ".raw_sections",
        ".forward_decls",
        ".includes",
    ):
        assert legacy not in all_selfhost
    for declaration_type in (
        "IRPreprocessorDecl",
        "IREnumDef",
        "IRStructForward",
        "IRFunctionPointerTypedef",
        "IRFunctionDecl",
    ):
        assert declaration_type in schema
    for declaration in (
        "public Vector<IRPreprocessorDecl> preprocessor_decls;",
        "public Vector<IREnumDef> enum_defs;",
        "public Vector<IRStructForward> struct_forwards;",
        "public Vector<IRFunctionPointerTypedef> function_pointer_typedefs;",
        "public Vector<IRFunctionDecl> function_decls;",
    ):
        assert declaration in schema

    assert "m.struct_forwards.push(IRStructForward(" in declarations
    assert "m.function_decls.push(" in declarations + functions
    assert "module.function_pointer_typedefs.push(declaration);" in types
    assert "m.enum_defs.push(" in declarations
    assert "m.preprocessor_decls" in emitter
    assert 'substring(0, 15) == "typedef struct "' not in emitter
    assert 'substring(0, 8) == "typedef "' not in emitter
    assert "private Map<string, Node> functionPointerTypes;" in types
    assert "private Vector<string> functionPointerOrder;" in types
    registration = types[
        types.index("private string functionPointerName(") : types.index("private bool aliasBaseIsReference(")
    ]
    # Preserve named typedef boundaries while still registering directly
    # nested callback spellings before the outer function-pointer declaration.
    register_nested = registration.index("self.lower(typeExpr.generic_args.get(component))")
    register_outer = registration.index("self.functionPointerOrder.push(mangled)")
    assert register_nested < register_outer
    assert "SemanticTypeSystem.resolveTypedefType(" not in registration
    assert "self.analyzed.fnPtr" not in registration


def test_preprocessor_ir_is_validated_and_emitted_structurally() -> None:
    declarations = _source("ir/lowering/declarations.btrc")
    emitter = _source("ir/emitter.btrc")

    assert "public bool is_system;" in _source("ir/model.btrc")
    assert "public bool function_like;" in _source("ir/model.btrc")
    assert "public Vector<string> params;" in _source("ir/model.btrc")
    assert "lowerPreprocessorDirective(d.text, m);" in declarations
    assert "unsupported preprocessor directive" in declarations
    assert "malformed #include directive" in declarations
    assert "duplicate function-like macro parameter" in declarations
    assert "multi-line preprocessor directives are unsupported" in declarations
    assert "IR_PREPROCESSOR_INCLUDE" in emitter
    assert "IR_PREPROCESSOR_MACRO" in emitter
    assert "#include <" in emitter
    assert '#include \\"' not in declarations


def test_string_literals_do_not_root_dead_functions() -> None:
    optimizer = _source("ir/optimization/optimizer.btrc")
    start = optimizer.index("private void collectFuncRefs(")
    end = optimizer.index("private void eliminateDeadFunctions(", start)
    collector = optimizer[start:end]

    assert "node.kind == IRK_CALL" in collector
    assert "node.kind == IRK_FUNCTION_REF" in collector
    assert "node.kind == IRK_VAR && names.has(node.name)" not in collector
    assert "node.kind == IRK_LITERAL" not in collector
    assert "self.scanTextForNames(declaration.replacement" in optimizer


def test_selfhost_models_structured_c_expression_forms() -> None:
    nodes = _source("ir/model.btrc")
    control_flow = _source("ir/lowering/control_flow.btrc")
    emitter = _source("ir/emitter.btrc")

    for contract in (
        "IRK_INITIALIZER_LIST",
        "IRK_COMPOUND_LITERAL",
        "IRK_SWITCH",
        "IRK_CASE",
        "class IRNode sizeofType(",
        "class IRNode sizeofExpression(",
        "class IRNode switchStatement(",
        "class IRNode caseClause(",
    ):
        assert contract in nodes
    switch_plan = control_flow[
        control_flow.index("class SwitchPlan {") : control_flow.index("class ControlFlowLowerer {")
    ]
    assert "public Vector<IRNode> cases;" in switch_plan
    assert "self.cases = cases;" in switch_plan
    assert "IRNode statement = IRNode.switchStatement(" in control_flow
    assert "plan.value, plan.cases);" in control_flow
    assert "return statement;" in control_flow
    assert "if (s.kind == IRK_SWITCH)" in emitter
    assert "irExprText" not in control_flow


def test_gpu_translation_unit_records_belong_to_the_ir_model() -> None:
    schema = _source("ir/model.btrc")
    pipeline = _source("ir/gpu/pipeline.btrc")

    for record in ("IRGpuBuffer", "IRGpuUniform", "IRGpuKernel"):
        assert f"class {record} {{" in schema
        assert f"class {record} {{" not in pipeline
    assert "public Vector<IRGpuKernel> gpu_kernels;" in schema


def test_selfhost_emits_struct_array_bounds_and_indirect_calls_only_from_ir() -> None:
    nodes = _source("ir/model.btrc")
    declarations = _source("ir/lowering/declarations.btrc")
    expressions = _source("ir/lowering/expressions.btrc")
    callables = _source("ir/lowering/callables.btrc")
    emitter = _source("ir/emitter.btrc")
    helper_reachability = _source("ir/runtime/references.btrc")
    optimizer = _source("ir/optimization/optimizer.btrc")
    field_schema = nodes[nodes.index("class IRStructField {") : nodes.index("class IRStructDef {")]
    emit_struct = declarations[
        declarations.index("public void emitStructDecl(") : declarations.index("public void emitGlobalVar(")
    ]

    assert "public IRNode array_size;" in field_schema
    assert "self.array_size = null;" in field_schema
    assert "CallableFlowState callableFlow = CallableFlowState();" in emit_struct
    assert "f.type.array_size, empty, callableFlow);" in emit_struct
    assert (
        "public IRNode lowerExpr(Node node, Map<string, Node> varTypes, CallableFlowState callableFlow)"
    ) in expressions
    assert "self.callableLowering.materializeInvocation(" in expressions
    assert "public IRNode materializeInvocation(" in callables
    assert "return IRNode.call(lambda.functionName, arguments);" in callables
    assert 'suffix = "[" + self.expr(field.array_size) + "]";' in emitter
    assert emitter.count("self.structFieldDeclaration(") == 2
    assert "self.collectStructRefsNode(field.array_size, knownNames, fr);" in optimizer
    assert "self.collectStructRefsNode(field.array_size, knownNames, refs);" in optimizer
    assert "self.collectNode(field.array_size, used);" in helper_reachability
    assert 'f.name + "["' not in declarations
    assert "irExprText" not in declarations + expressions


def test_selfhost_enum_symbols_are_structured_variable_references() -> None:
    declarations = _source("ir/lowering/declarations.btrc")
    expressions = _source("ir/lowering/expressions.btrc")

    rich_enum = declarations[
        declarations.index("public void emitRichEnumDecl(") : declarations.index("public IRFunction enumToStringFn(")
    ]
    enum_to_string = declarations[
        declarations.index("public IRFunction enumToStringFn(") : declarations.index("public void emitStructDecl(")
    ]

    assert 'IRNode.variable(name + "_" + v.name + "_TAG")' in rich_enum
    assert "IRNode.variable(caseLabel)" in enum_to_string
    assert "IRNode.variable(prefix + node.name)" in expressions
    assert "IRNode.variable(owner + node.name)" in expressions
    assert 'IRNode.variable(node.obj.name + "_" + node.field)' in expressions

    for raw_symbol in (
        'IRNode.literal(name + "_" + v.name + "_TAG")',
        "IRNode.literal(caseLabel)",
        "IRNode.literal(prefix + node.name)",
        "IRNode.literal(owner + node.name)",
        'IRNode.literal(node.obj.name + "_" + node.field)',
    ):
        assert raw_symbol not in declarations + expressions


def test_selfhost_portability_lowering_is_structured() -> None:
    parser = _source("parser/parser.btrc")
    analyzer_expressions = _source("analyzer/expressions.btrc")
    expressions = _source("ir/lowering/expressions.btrc")
    literals = _source("syntax/literals.btrc")
    identity = _source("syntax/identity.btrc")
    numeric = _source("analyzer/operators.btrc")
    operators = numeric
    model = _source("ir/model.btrc")
    runtime_catalog = _source("ir/runtime/catalog.btrc")
    runtime_rows = RuntimeHelperCatalog().definitions
    runtime = "\n".join(row.c_source for row in runtime_rows)
    runtime_names = {row.name for row in runtime_rows}

    assert "import ../syntax/literals.btrc;" in parser
    assert "import ../syntax/literals.btrc;" in numeric
    assert "import ../../syntax/literals.btrc;" in expressions
    assert "class IntegerLiteral {" in literals
    assert "public string cSource(int storedValue)" in literals
    assert "IntegerLiteral(node.raw).cSource(node.value_int)" in expressions
    assert "NumericSemantics.integerLiteralType(node.raw)" in analyzer_expressions
    assert "class NumericSemantics {" in numeric
    assert "class Node? resultType(" in numeric
    assert "class bool operandsNeedCast(" in numeric
    assert "class OperatorSemantics {" in operators
    assert "public bool referenceTypesCompatible(" in operators
    assert "public bool specializationIsSubtype(" in operators
    assert "NumericSemantics.resultType(" in expressions
    assert "self.operators.comparisonDomain(" in expressions
    assert "lowerStringComparisonValues" in expressions
    assert 'freshTemporary("__btrc_cmp_left")' in expressions
    assert 'freshTemporary("__btrc_cmp_right")' in expressions
    assert 'string helper = "__btrc_div";' in expressions
    assert 'self.context.referenceHelper("__btrc_hash_real")' in expressions
    assert "lowerIndirectAssignment" in expressions
    assert "lowerIndirectIncDec" in expressions
    assert "lowerGenericIntrinsic" in expressions
    assert 'IRNode.cast("uintptr_t", args.get(0))' in expressions
    assert "IRK_INVALID_EXPR" in model
    assert "invalidExpression" in model
    pointer = identity.index('component = component + "_p"')
    nullable = identity.index('component = component + "_n"')
    array = identity.index('component = component + "_a"')
    assert pointer < nullable < array
    assert "__builtin_choose_expr" not in model
    assert "__typeof__" not in model
    assert "#define __btrc_div" in runtime
    assert "#define __btrc_mod" in runtime
    assert "__btrc_hash_real" in runtime
    for obsolete in ("__btrc_eq", "__btrc_lt", "__btrc_gt", "__btrc_hash"):
        assert obsolete not in runtime_names
    assert "class RuntimeHelperCatalog" in runtime_catalog
    assert "private Vector<GeneratedRuntimeHelperRow> rows;" in runtime_catalog


def test_numeric_and_operator_behavior_has_domain_owners() -> None:
    numeric = _source("analyzer/operators.btrc")
    operators = numeric
    analyzer = _source("analyzer/analyzer.btrc")
    validation_types = _source("analyzer/validation/types.btrc")
    validator = _source("analyzer/validation/validator.btrc")
    expressions = _source("ir/lowering/expressions.btrc")
    lowerer = _source("ir/lowering/lowerer.btrc")
    pipeline = _source("pipeline/pipeline.btrc")
    all_selfhost = "\n".join(path.read_text() for path in SELFHOST.rglob("*.btrc"))
    loose_behavior = re.compile(
        r"^(?:bool|int|string|Node\??) [A-Za-z_][A-Za-z0-9_]*\(",
        re.MULTILINE,
    )

    assert loose_behavior.search(numeric) is None
    assert loose_behavior.search(operators) is None
    assert numeric.count("class NumericSemantics {") == 1
    assert operators.count("class OperatorSemantics {") == 1
    assert "private Analyzed analyzed;" in operators
    assert "public OperatorSemantics(Analyzed analyzed)" in operators
    assert "OperatorSemantics." not in all_selfhost
    assert all_selfhost.count("OperatorSemantics(self.analysis)") == 1
    assert "self.operators = OperatorSemantics(self.analysis);" in analyzer
    assert analyzer.count("self.operators") == 5
    state = validation_types[
        validation_types.index("class SemanticValidationState {") : validation_types.index("class TypeValidator {")
    ]
    assert "OperatorSemantics" not in state
    assert "self.state = SemanticValidationState(analyzed);" in validator
    assert "OperatorSemantics operators" in validator
    assert "self.operators = operators;" in validation_types
    assert "private OperatorSemantics operators;" in expressions
    assert "OperatorSemantics operators," in lowerer
    assert "analyzer.operatorSemantics()," in pipeline


def test_destroyed_query_has_its_own_helper_node() -> None:
    catalog = RuntimeHelperCatalog()
    state = catalog.definition("__btrc_destroyed_tracking")
    query = catalog.definition("__btrc_is_destroyed")

    assert "__btrc_is_destroyed(void* ptr)" not in state.c_source
    assert "__btrc_is_destroyed(void* ptr)" in query.c_source
    assert "__btrc_destroyed_tracking" in query.depends_on


def test_cycle_suspect_callable_is_split_from_thread_state() -> None:
    catalog = RuntimeHelperCatalog()
    state = catalog.definition("__btrc_suspect_state")
    suspect = catalog.definition("__btrc_suspect")

    assert "static inline void __btrc_suspect(" in suspect.c_source
    assert "static void __btrc_suspect(" not in suspect.c_source
    assert "__btrc_suspect_locked" in suspect.depends_on
    assert "__btrc_suspect_buf" not in state.c_source + suspect.c_source


def test_optional_launder_callable_is_split_from_cleanup_state() -> None:
    catalog = RuntimeHelperCatalog()
    launder_state = catalog.definition("__btrc_launder_state")
    launder = catalog.definition("__btrc_launder")
    cleanup = catalog.definition("__btrc_try_state_cleanup")

    assert launder_state.c_source
    assert launder.c_source
    assert "__btrc_launder_state" in cleanup.depends_on
    assert "__btrc_launder" not in cleanup.depends_on


def test_selfhost_runtime_helpers_mirror_portable_python_contracts() -> None:
    catalog = RuntimeHelperCatalog()
    strings = _source("ir/lowering/strings.btrc")

    modulo = catalog.definition("__btrc_mod").c_source
    assert "a != a || b != b" in modulo
    assert "a <= lower || a >= upper" in modulo
    assert "truncl" not in modulo
    assert "isfinite" not in modulo

    parse = "\n".join(
        catalog.definition(name).c_source for name in ("__btrc_parseLong", "__btrc_parseInt", "__btrc_parseBool")
    )
    assert "unsigned long limit = negative" in parse
    assert "__btrc_parseLong(s)" in parse
    assert "__btrc_parseBool" in parse
    assert "strtol" not in parse
    assert "__btrc_parseLong" in catalog.definition("__btrc_parseInt").depends_on
    assert 'self.context.referenceHelper("__btrc_parseBool")' in strings

    real_hash = catalog.definition("__btrc_hash_real").c_source
    assert "double canonical = (double)value;" in real_hash
    assert "memcpy(bytes, &canonical, sizeof canonical);" in real_hash
    for obsolete in ("isnan", "isinf", "signbit", "frexpl", "fabsl"):
        assert obsolete not in real_hash


def test_pragma_pack_is_struct_metadata_not_a_raw_section() -> None:
    nodes = _source("ir/model.btrc")
    lowerer = _source("ir/lowering/lowerer.btrc")
    declarations = _source("ir/lowering/declarations.btrc")
    emitter = _source("ir/emitter.btrc")

    assert "public int pack_alignment;" in nodes
    assert "self.declarations.packAlignments(program)" in lowerer
    assert "sd.pack_alignment = self.context.packAlignments.get" in declarations
    assert "if (self.isPackPragma(text)) { return; }" in declarations
    assert 'self.line("#pragma pack(push, "' in emitter
    assert 'self.line("#pragma pack(pop)")' in emitter
