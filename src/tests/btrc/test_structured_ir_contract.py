"""White-box contracts for the self-hosted compiler's structured IR."""

from pathlib import Path

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
    schema = _source("ir_top_nodes.btrc")
    generator = _source("irgen.btrc")
    emitter = _source("emitter.btrc")
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

    assert "m.struct_forwards.push(IRStructForward(" in generator
    assert "m.function_decls.push(" in generator
    assert "m.function_pointer_typedefs.push(" in generator
    assert "m.enum_defs.push(" in generator
    assert "m.preprocessor_decls" in emitter
    assert 'substring(0, 15) == "typedef struct "' not in emitter
    assert 'substring(0, 8) == "typedef "' not in emitter
    registration = generator[generator.index("string fnPtrTypedefName(") : generator.index("string typeToC(")]
    canonicalize = registration.index("Node? canonical = resolveTypedefType(")
    register_nested = registration.index("typeToC(canonical, a)")
    register_outer = registration.index("a.fnPtrOrder.push(mangled)")
    assert canonicalize < register_nested < register_outer


def test_preprocessor_ir_is_validated_and_emitted_structurally() -> None:
    preprocessor = _source("preprocessor_ir.btrc")
    generator = _source("irgen.btrc")
    emitter = _source("emitter.btrc")

    assert "public bool is_system;" in _source("ir_top_nodes.btrc")
    assert "public bool function_like;" in _source("ir_top_nodes.btrc")
    assert "public Vector<string> params;" in _source("ir_top_nodes.btrc")
    assert "lowerPreprocessorDirective(d.text, m);" in generator
    assert "unsupported preprocessor directive" in preprocessor
    assert "malformed #include directive" in preprocessor
    assert "duplicate function-like macro parameter" in preprocessor
    assert "multi-line preprocessor directives are unsupported" in preprocessor
    assert "IR_PREPROCESSOR_INCLUDE" in emitter
    assert "IR_PREPROCESSOR_MACRO" in emitter
    assert "#include <" in emitter
    assert '#include \\"' not in generator


def test_string_literals_do_not_root_dead_functions() -> None:
    generator = _source("irgen.btrc")
    start = generator.index("void collectFuncRefs(")
    end = generator.index("void eliminateDeadFunctions(", start)
    collector = generator[start:end]

    assert "node.kind == IRK_CALL" in collector
    assert "node.kind == IRK_FUNCTION_REF" in collector
    assert "node.kind == IRK_VAR && names.has(node.name)" not in collector
    assert "node.kind == IRK_LITERAL" not in collector
    assert "scanTextForNames(declaration.replacement" in generator


def test_selfhost_models_structured_c_expression_forms() -> None:
    nodes = _source("ir_nodes.btrc")
    generator = _source("irgen.btrc")
    emitter = _source("emitter.btrc")

    for contract in (
        "IRK_INITIALIZER_LIST",
        "IRK_COMPOUND_LITERAL",
        "IRK_SWITCH",
        "IRK_CASE",
        "irSizeofType",
        "irSizeofExpr",
        "irSwitch",
        "irCase",
    ):
        assert contract in nodes
    assert "cases.push(irCase(" in generator
    assert "return irSwitch(" in generator
    assert "if (s.kind == IRK_SWITCH)" in emitter
    assert "irExprText" not in generator


def test_selfhost_emits_struct_array_bounds_and_indirect_calls_only_from_ir() -> None:
    nodes = _source("ir_nodes.btrc")
    generator = _source("irgen.btrc")
    emitter = _source("emitter.btrc")
    helper_reachability = _source("helper_reachability.btrc")
    field_schema = nodes[nodes.index("class IRStructField {") : nodes.index("class IRStructDef {")]

    assert "public IRNode array_size;" in field_schema
    assert "self.array_size = null;" in field_schema
    assert "field.array_size = self.lowerExpr(f.type.array_size, empty);" in generator
    assert "return irCallExpr(lambdaExpr, lambdaArgs);" in generator
    assert 'suffix = "[" + self.expr(field.array_size) + "]";' in emitter
    assert emitter.count("self.structFieldDeclaration(") == 2
    assert "collectStructRefsNode(field.array_size, knownNames, fr);" in generator
    assert "collectStructRefsNode(field.array_size, knownNames, refs);" in generator
    assert "scanHelpersInNode(field.array_size, used);" in helper_reachability
    assert 'f.name + "["' not in generator
    assert "irExprText" not in generator


def test_selfhost_enum_symbols_are_structured_variable_references() -> None:
    generator = _source("irgen.btrc")

    rich_enum = generator[
        generator.index("public void emitRichEnumDecl(") : generator.index("public IRFunction enumToStringFn(")
    ]
    enum_to_string = generator[
        generator.index("public IRFunction enumToStringFn(") : generator.index("public void emitStructDecl(")
    ]
    expressions = generator[
        generator.index("public IRNode lowerExpr(") : generator.index("public IRNode lowerFieldAccessCore(")
    ]
    field_access = generator[
        generator.index("public IRNode lowerFieldAccessCore(") : generator.index("public IRNode lowerIndexCore(")
    ]

    assert 'irVar(name + "_" + v.name + "_TAG")' in rich_enum
    assert "irVar(caseLabel)" in enum_to_string
    assert "irVar(prefix + node.name)" in expressions
    assert "irVar(owner + node.name)" in expressions
    assert 'irVar(node.obj.name + "_" + node.field)' in field_access

    for raw_symbol in (
        'irLiteral(name + "_" + v.name + "_TAG")',
        "irLiteral(caseLabel)",
        "irLiteral(prefix + node.name)",
        "irLiteral(owner + node.name)",
        'irLiteral(node.obj.name + "_" + node.field)',
    ):
        assert raw_symbol not in generator


def test_selfhost_portability_lowering_is_structured() -> None:
    main = _source("btrcc_main.btrc")
    generator = _source("irgen.btrc")
    identity = _source("type_identity.btrc")
    numeric = _source("numeric_semantics.btrc")
    operators = _source("operator_semantics.btrc")
    helpers = _source("ir_nodes.btrc")

    assert main.index('#include "numeric_semantics.btrc"') < main.index('#include "irgen.btrc"')
    assert main.index('#include "operator_semantics.btrc"') < main.index('#include "irgen.btrc"')
    assert main.index('#include "literal_text.btrc"') < main.index('#include "irgen.btrc"')
    assert "formatCIntegerLiteral(node.raw, node.value_int)" in generator
    assert "integerLiteralType(node.raw)" in _source("analyzer.btrc")
    assert "numericResultType" in numeric
    assert "numericOperandsNeedCast" in numeric
    assert "semanticReferenceTypesCompatible" in operators
    assert "semanticSpecializationIsSubtype" in operators
    assert "lowerStringComparisonValues" in generator
    assert 'freshTemp("__btrc_cmp_left")' in generator
    assert 'freshTemp("__btrc_cmp_right")' in generator
    assert 'self.useHelper("__btrc_div")' not in generator
    assert 'string helper = "__btrc_div";' in generator
    assert 'self.useHelper("__btrc_hash_real")' in generator
    assert "lowerIndirectAssignment" in generator
    assert "lowerIndirectIncDec" in generator
    assert "lowerGenericIntrinsic" in generator
    assert 'irCast("uintptr_t", args.get(0))' in generator
    assert "IRK_INVALID_EXPR" in helpers
    assert "irInvalidExpr" in helpers
    pointer = identity.index('component = component + "_p"')
    nullable = identity.index('component = component + "_n"')
    array = identity.index('component = component + "_a"')
    assert pointer < nullable < array
    assert "__builtin_choose_expr" not in helpers
    assert "__typeof__" not in helpers
    assert "#define __btrc_div" in helpers
    assert "#define __btrc_mod" in helpers
    assert "__btrc_hash_real" in helpers
    for obsolete in ("__btrc_eq", "__btrc_lt", "__btrc_gt", "__btrc_hash"):
        assert f'if (name == "{obsolete}")' not in helpers
        assert f'order.push("{obsolete}")' not in helpers


def test_destroyed_query_has_its_own_helper_node() -> None:
    state = _source("cycle_runtime_state.btrc")
    dependencies = _source("cycle_runtime_dependencies_state.btrc")
    state_start = state.index('if (name == "__btrc_destroyed_tracking")')
    query_start = state.index('if (name == "__btrc_is_destroyed")')
    capacity_start = state.index('if (name == "__btrc_destroyed_capacity")')

    assert "__btrc_is_destroyed(void* ptr)" not in state[state_start:query_start]
    assert "__btrc_is_destroyed(void* ptr)" in state[query_start:capacity_start]
    marker = 'if (name == "__btrc_is_destroyed")'
    dependency_start = dependencies.index(marker)
    dependency_end = dependencies.index("if (name ==", dependency_start + len(marker))
    assert 'out.push("__btrc_destroyed_tracking")' in dependencies[dependency_start:dependency_end]


def test_cycle_suspect_callable_is_split_from_thread_state() -> None:
    state = _source("cycle_runtime_state.btrc")
    dependencies = _source("cycle_runtime_dependencies_state.btrc")

    assert "static inline void __btrc_suspect(" in state
    assert '"static void __btrc_suspect(' not in state
    assert 'if (name == "__btrc_suspect_state")' in state
    assert 'if (name == "__btrc_suspect")' in state
    assert 'if (name == "__btrc_suspect")' in dependencies
    assert "__btrc_suspect_buf" not in state + dependencies


def test_optional_launder_callable_is_split_from_cleanup_state() -> None:
    runtime = _source("trycatch_runtime_state.btrc")
    dependencies = _source("trycatch_runtime_dependencies.btrc")

    assert 'if (name == "__btrc_launder_state")' in runtime
    assert 'if (name == "__btrc_launder")' in runtime
    cleanup = dependencies[dependencies.index('else if (name == "__btrc_try_state_cleanup")') :]
    assert 'out.push("__btrc_launder_state")' in cleanup
    assert 'out.push("__btrc_launder")' not in cleanup


def test_selfhost_runtime_helpers_mirror_portable_python_contracts() -> None:
    helpers = _source("ir_nodes.btrc")
    generator = _source("irgen.btrc")

    modulo = helpers[helpers.index('if (name == "__btrc_mod")') : helpers.index('if (name == "__btrc_div_int")')]
    assert "a != a || b != b" in modulo
    assert "a <= lower || a >= upper" in modulo
    assert "truncl" not in modulo
    assert "isfinite" not in modulo

    parse = helpers[
        helpers.index('if (name == "__btrc_parseLong")') : helpers.index('if (name == "__btrc_intToString")')
    ]
    assert "unsigned long limit = negative" in parse
    assert "__btrc_parseLong(s)" in parse
    assert "__btrc_parseBool" in parse
    assert "strtol" not in parse
    assert 'if (name == "__btrc_parseInt") { out.push("__btrc_parseLong"); }' in helpers
    assert 'self.useHelper("__btrc_parseBool")' in generator

    real_hash = helpers[
        helpers.index('if (name == "__btrc_hash_real")') : helpers.index('if (name == "__btrc_hash_str")')
    ]
    assert "double canonical = (double)value;" in real_hash
    assert "memcpy(bytes, &canonical, sizeof canonical);" in real_hash
    for obsolete in ("isnan", "isinf", "signbit", "frexpl", "fabsl"):
        assert obsolete not in real_hash


def test_pragma_pack_is_struct_metadata_not_a_raw_section() -> None:
    nodes = _source("ir_nodes.btrc")
    generator = _source("irgen.btrc")
    emitter = _source("emitter.btrc")

    assert "public int pack_alignment;" in nodes
    assert "declarationPackAlignments(prog)" in generator
    assert "sd.pack_alignment = self.packAlignments.get" in generator
    assert "if (isPackPragma(text)) { return; }" in generator
    assert 'self.line("#pragma pack(push, "' in emitter
    assert 'self.line("#pragma pack(pop)")' in emitter
