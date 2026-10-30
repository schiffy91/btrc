"""Exact reachability contracts for top-level IR declarations."""

import subprocess
from pathlib import Path

import pytest

from src.compiler.python.application.pipeline import CompilationPipeline
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.ir.nodes import (
    CType,
    IRAddressOf,
    IRBlock,
    IRCall,
    IRCast,
    IREnumDef,
    IREnumValue,
    IRExprStmt,
    IRFunctionDecl,
    IRFunctionDef,
    IRFunctionPointerTypedef,
    IRFunctionRef,
    IRGlobalDecl,
    IRHelperDecl,
    IRInitializerList,
    IRLiteral,
    IRMacroDef,
    IRModule,
    IRParam,
    IRReturn,
    IRStructDef,
    IRStructField,
    IRStructForward,
    IRTaggedUnionDef,
    IRTaggedUnionVariant,
    IRTypedefDef,
    IRVar,
    IRVarDecl,
)
from src.compiler.python.ir.optimizer import IROptimizer
from src.tests.c_toolchains import HOST_C_COMPILERS, requires_host_c_compiler
from src.tests.process_limits import C_COMPILE_TIMEOUT


def _main(stmts=None):
    return IRFunctionDef(
        name="main",
        return_type=CType("int"),
        body=IRBlock(stmts=stmts or [IRReturn(IRLiteral("0"))]),
    )


def _extern(name, params=None):
    return IRFunctionDecl(
        name=name,
        return_type=CType("int"),
        params=params or [],
    )


def test_extern_roots_are_structured_symbols_not_incidental_text():
    module = IRModule(
        function_decls=[
            _extern("called_extern"),
            _extern("addressed_extern"),
            _extern("literal_extern"),
            _extern("local_name_extern"),
        ],
        function_defs=[
            _main(
                [
                    IRVarDecl(CType("int"), "local_name_extern", IRLiteral("0")),
                    IRExprStmt(IRLiteral('"literal_extern"')),
                    IRExprStmt(IRCall("called_extern")),
                    IRExprStmt(IRFunctionRef("addressed_extern")),
                    IRReturn(IRLiteral("0")),
                ]
            )
        ],
    )

    IROptimizer(module).optimize()

    assert {declaration.name for declaration in module.function_decls} == {
        "called_extern",
        "addressed_extern",
    }


def test_only_emitted_opaque_boundaries_root_externs():
    module = IRModule(
        preprocessor_decls=[IRMacroDef(name="CALL_EXTERNAL", replacement="macro_extern()")],
        function_decls=[
            _extern("macro_extern"),
            _extern("helper_extern"),
            _extern("dead_helper_extern"),
        ],
        helper_decls=[
            IRHelperDecl(
                category="live",
                name="live_helper",
                c_source="static void live_helper(void) { helper_extern(); }",
            ),
            IRHelperDecl(
                category="dead",
                name="dead_helper",
                c_source="static void dead_helper(void) { dead_helper_extern(); }",
            ),
        ],
        function_defs=[
            _main(
                [
                    IRExprStmt(IRCall("live_helper", helper_ref="live_helper")),
                    IRReturn(IRLiteral("0")),
                ]
            )
        ],
    )

    IROptimizer(module).optimize()

    assert [helper.name for helper in module.helper_decls] == ["live_helper"]
    assert {declaration.name for declaration in module.function_decls} == {
        "macro_extern",
        "helper_extern",
    }


def test_opaque_boundaries_root_types_but_literals_and_names_do_not():
    module = IRModule(
        preprocessor_decls=[IRMacroDef(name="TYPE_SIZE", replacement="sizeof(MacroType)")],
        enum_defs=[
            IREnumDef("HelperEnum", [IREnumValue("HelperEnum_Value", IRLiteral("1"))]),
            IREnumDef("LiteralEnum", [IREnumValue("LiteralEnum_Value", IRLiteral("2"))]),
        ],
        typedef_defs=[
            IRTypedefDef(CType("int"), "MacroType"),
            IRTypedefDef(CType("int"), "HelperType"),
            IRTypedefDef(CType("int"), "LocalNameType"),
        ],
        helper_decls=[
            IRHelperDecl(
                category="live",
                name="typed_helper",
                c_source="static HelperType typed_helper(void) { return HelperEnum_Value; }",
            )
        ],
        function_defs=[
            _main(
                [
                    IRVarDecl(CType("int"), "LocalNameType", IRLiteral("0")),
                    IRExprStmt(IRLiteral('"LiteralEnum_Value"')),
                    IRExprStmt(IRCall("typed_helper", helper_ref="typed_helper")),
                    IRReturn(IRLiteral("0")),
                ]
            )
        ],
    )

    IROptimizer(module).optimize()

    assert [enum.name for enum in module.enum_defs] == ["HelperEnum"]
    assert [alias.name for alias in module.typedef_defs] == ["MacroType", "HelperType"]


@pytest.mark.parametrize(
    ("field_name", "declaration"),
    (
        ("enum_defs", IREnumDef("OnlyEnum", [IREnumValue("OnlyEnum_Value", IRLiteral("0"))])),
        ("struct_forwards", IRStructForward("OnlyForward")),
        ("function_pointer_typedefs", IRFunctionPointerTypedef("OnlyCallback", CType("void"))),
        ("typedef_defs", IRTypedefDef(CType("int"), "OnlyAlias")),
        ("tagged_union_defs", IRTaggedUnionDef("OnlyTagged", CType("int"))),
        ("struct_defs", IRStructDef("OnlyStruct")),
    ),
)
def test_single_unreferenced_type_declaration_is_removed(field_name, declaration):
    module = IRModule(function_defs=[_main()], **{field_name: [declaration]})

    IROptimizer(module).optimize()

    assert getattr(module, field_name) == []


def _strict_declaration_module():
    return IRModule(
        enum_defs=[
            IREnumDef("Color", [IREnumValue("Color_Red", IRLiteral("1"))]),
            IREnumDef("DeadEnum", [IREnumValue("DeadEnum_Value", IRLiteral("0"))]),
        ],
        struct_forwards=[IRStructForward("Event"), IRStructForward("Box"), IRStructForward("DeadStruct")],
        function_pointer_typedefs=[
            IRFunctionPointerTypedef("Callback", CType("int"), [CType("int")]),
            IRFunctionPointerTypedef("DeadCallback", CType("void")),
        ],
        typedef_defs=[
            IRTypedefDef(CType("Callback"), "Handler"),
            IRTypedefDef(CType("int"), "DeadAlias"),
        ],
        tagged_union_defs=[
            IRTaggedUnionDef(
                "Event",
                CType("Color"),
                [IRTaggedUnionVariant("Handler", [IRStructField(CType("Handler"), "callback")])],
            ),
            IRTaggedUnionDef("DeadTagged", CType("int")),
        ],
        struct_defs=[
            IRStructDef("Box", [IRStructField(CType("Event"), "event")]),
            IRStructDef("DeadStruct"),
        ],
        function_decls=[
            _extern("live_extern", [IRParam(CType("Color"), "color")]),
            _extern("dead_extern"),
        ],
        function_defs=[
            _main(
                [
                    IRVarDecl(CType("Box"), "box", IRInitializerList([IRLiteral("0")])),
                    IRExprStmt(IRCast(CType("void"), IRVar("box"))),
                    IRReturn(IRCall("live_extern", [IRVar("Color_Red")])),
                ]
            )
        ],
    )


def test_type_declarations_follow_transitive_typed_references():
    module = _strict_declaration_module()

    IROptimizer(module).optimize()

    assert [enum.name for enum in module.enum_defs] == ["Color"]
    assert [forward.name for forward in module.struct_forwards] == ["Event", "Box"]
    assert [callback.name for callback in module.function_pointer_typedefs] == ["Callback"]
    assert [alias.name for alias in module.typedef_defs] == ["Handler"]
    assert [tagged.name for tagged in module.tagged_union_defs] == ["Event"]
    assert [struct.name for struct in module.struct_defs] == ["Box"]
    assert [declaration.name for declaration in module.function_decls] == ["live_extern"]


@requires_host_c_compiler
@pytest.mark.parametrize("c_compiler", HOST_C_COMPILERS, ids=lambda path: Path(path).name)
def test_pruned_declaration_closure_is_strict_c11(tmp_path: Path, c_compiler: str):
    module = _strict_declaration_module()
    pipeline = CompilationPipeline()
    module = pipeline.optimize(module, CompilerOptions())
    source = tmp_path / "optimized_declarations.c"
    source.write_text(pipeline.emit(module))

    subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-c",
            str(source),
            "-o",
            str(tmp_path / "optimized_declarations.o"),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=C_COMPILE_TIMEOUT,
    )


@pytest.mark.parametrize("root", ["unused", "function", "global", "macro"])
def test_module_arc_descriptor_reachability_preserves_live_dependencies(root):
    name = "__btrc_Cell_arc_type"
    descriptor = IRGlobalDecl(
        CType("const __btrc_arc_type"),
        name,
        IRInitializerList([IRFunctionRef("destroy_cell")]),
        is_static=False,
    )
    module = IRModule(
        global_decls=[descriptor],
        function_defs=[
            IRFunctionDef(
                name="destroy_cell",
                return_type=CType("void"),
                body=IRBlock([]),
                is_static=True,
            ),
            _main(),
        ],
    )
    if root == "function":
        module.function_defs[-1].body.stmts.insert(0, IRExprStmt(IRAddressOf(IRVar(name))))
    elif root == "global":
        module.global_decls.append(
            IRGlobalDecl(
                CType("const __btrc_arc_type*"),
                "exported_descriptor",
                IRAddressOf(IRVar(name)),
                is_static=False,
            )
        )
    elif root == "macro":
        module.preprocessor_decls.append(IRMacroDef(name="CELL_DESCRIPTOR", replacement=f"(&{name})"))

    IROptimizer(module, module_unit=True).optimize()

    assert (name in {declaration.name for declaration in module.global_decls}) == (root != "unused")
    assert ("destroy_cell" in {function.name for function in module.function_defs}) == (root != "unused")
    if root == "global":
        assert "exported_descriptor" in {declaration.name for declaration in module.global_decls}


@pytest.mark.parametrize("called", [False, True])
def test_catalog_helper_local_name_does_not_root_application_extern(called):
    body = [
        IRExprStmt(IRCall("__btrc_discard_cleanups_to", [IRLiteral("-1")], helper_ref="__btrc_discard_cleanups_to"))
    ]
    if called:
        body.append(IRExprStmt(IRCall("mark", [IRLiteral("1")])))
    body.append(IRReturn(IRLiteral("0")))
    module = IRModule(
        function_decls=[_extern("mark", [IRParam(CType("int"), "value")])],
        function_defs=[_main(body)],
    )
    IROptimizer(module).optimize()
    assert any(helper.name == "__btrc_discard_cleanups_to" for helper in module.helper_decls)
    assert [declaration.name for declaration in module.function_decls] == (["mark"] if called else [])


def test_custom_source_under_catalog_helper_name_keeps_opaque_references():
    name = "__btrc_discard_cleanups_to"
    module = IRModule(
        function_decls=[_extern("helper_extern")],
        helper_decls=[
            IRHelperDecl(category="custom", name=name, c_source=f"static void {name}(void) {{ helper_extern(); }}")
        ],
        function_defs=[_main([IRExprStmt(IRCall(name, helper_ref=name)), IRReturn(IRLiteral("0"))])],
    )
    IROptimizer(module).optimize()
    assert [declaration.name for declaration in module.function_decls] == ["helper_extern"]
