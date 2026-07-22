"""White-box coverage for typed IR declarations and their C ordering."""

import shutil
import subprocess
from dataclasses import fields
from pathlib import Path

import pytest

from src.compiler.python.analyzer.analyzer import Analyzer
from src.compiler.python.ir import nodes as ir_nodes
from src.compiler.python.ir.emitter import CEmitter
from src.compiler.python.ir.gen.errors import CodegenError
from src.compiler.python.ir.gen.generator import IRGenerator
from src.compiler.python.ir.nodes import (
    CType,
    IRBlock,
    IRCompoundLiteral,
    IRFunctionDecl,
    IRFunctionDef,
    IRFunctionPointerTypedef,
    IRGlobalDecl,
    IRInclude,
    IRInitializerList,
    IRLiteral,
    IRMacroDef,
    IRModule,
    IRParam,
    IRReturn,
    IRStructField,
    IRStructForward,
    IRTaggedUnionDef,
    IRTaggedUnionVariant,
    IRTypedefDef,
    IRVarDecl,
)
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def _generate(source: str, *, freestanding: bool = False):
    program = Parser(Lexer(source, "<ir-decls>").tokenize()).parse()
    analyzed = Analyzer().analyze(program)
    assert not analyzed.errors
    return IRGenerator(analyzed, freestanding=freestanding).generate()


def test_ir_schema_has_no_raw_c_escape_nodes():
    assert not hasattr(ir_nodes, "IRRawExpr")
    assert not hasattr(ir_nodes, "IRRawC")
    assert not hasattr(ir_nodes, "IRSpawnThread")
    assert not hasattr(ir_nodes, "IRGpuDispatch")
    field_names = {field.name for field in fields(IRModule)}
    assert "forward_decls" not in field_names
    assert "raw_sections" not in field_names
    assert "vtable_defs" not in field_names
    assert "global_vars" not in field_names
    assert "includes" not in field_names
    assert "macro_defs" not in field_names
    assert "preprocessor_decls" in field_names


@pytest.mark.parametrize(
    "field_name",
    (
        "struct_forwards",
        "function_pointer_typedefs",
        "function_decls",
        "preprocessor_decls",
    ),
)
def test_ir_declaration_lists_reject_raw_strings(field_name: str):
    with pytest.raises(TypeError, match=rf"IRModule\.{field_name} requires"):
        IRModule(**{field_name: ["int untyped;"]})

    module = IRModule()
    getattr(module, field_name).append("int untyped;")
    with pytest.raises(TypeError, match=rf"IRModule\.{field_name} requires"):
        CEmitter().emit(module)


@pytest.mark.parametrize(
    "kwargs, error_type",
    [
        ({"header": 7}, TypeError),
        ({"header": ""}, ValueError),
        ({"header": "bad\nheader.h"}, ValueError),
        ({"header": "bad\theader.h"}, ValueError),
        ({"header": "bad??/header.h"}, ValueError),
        ({"header": "<bad.h>"}, ValueError),
        ({"header": 'bad"header.h'}, ValueError),
        ({"header": "ok.h", "is_system": "yes"}, TypeError),
    ],
)
def test_include_node_validates_its_schema(kwargs: dict, error_type: type[Exception]):
    with pytest.raises(error_type):
        IRInclude(**kwargs)


def test_archive_impl_rejects_an_unquotable_header_name():
    with pytest.raises(ValueError, match="invalid structured include"):
        CEmitter().emit_impl(IRModule(), 'bad"header.h')


@pytest.mark.parametrize(
    "kwargs, error_type",
    [
        ({"name": 7}, TypeError),
        ({"name": "7BAD"}, ValueError),
        ({"name": "NON_ASCII_é"}, ValueError),
        ({"name": "BAD", "params": ("x",)}, TypeError),
        ({"name": "BAD", "params": ["x", "x"]}, ValueError),
        ({"name": "BAD", "params": ["bad-name"]}, ValueError),
        ({"name": "BAD", "replacement": 7}, TypeError),
        ({"name": "BAD", "replacement": "one\ntwo"}, ValueError),
        ({"name": "BAD", "replacement": "one\0two"}, ValueError),
        ({"name": "BAD", "replacement": "continued\\"}, ValueError),
    ],
)
def test_macro_node_validates_its_schema(kwargs: dict, error_type: type[Exception]):
    with pytest.raises(error_type):
        IRMacroDef(**kwargs)


def test_mutated_macro_is_revalidated_before_emission():
    macro = IRMacroDef(name="PAIR", params=["left", "right"])
    module = IRModule(preprocessor_decls=[macro])
    macro.params.append("left")

    with pytest.raises(ValueError, match="duplicate macro parameter"):
        CEmitter().emit(module)


def test_source_declarations_lower_to_typed_module_nodes():
    module = _generate("""
        typedef int Score;
        enum class Payload { Number(int value), Empty }
        int apply(__fn_ptr<int, int> callback, int value);
        int values[8];
        int main() { return 0; }
    """)

    assert [(item.name, item.target_type.text) for item in module.typedef_defs] == [("Score", "int")]
    assert [item.name for item in module.tagged_union_defs] == ["Payload"]
    assert [(item.name, item.c_type.text) for item in module.global_decls] == [("values", "int")]
    assert all(isinstance(item, IRStructForward) for item in module.struct_forwards)
    assert all(isinstance(item, IRFunctionPointerTypedef) for item in module.function_pointer_typedefs)
    assert all(isinstance(item, IRFunctionDecl) for item in module.function_decls)
    assert all(isinstance(item, (IRInclude, IRMacroDef)) for item in module.preprocessor_decls)


def test_aggregate_fields_and_typedefs_keep_volatile_ir_metadata():
    module = _generate("""
        typedef volatile int VolatileInt;
        typedef volatile int* VolatilePointer;
        struct Storage {
            volatile int scalar;
            volatile int* pointer;
            volatile int values[2];
        };
        class Box {
            public volatile int scalar;
            public volatile int* pointer;
            public volatile int values[2];
        }
        enum class Payload {
            Value(volatile int scalar, volatile int* pointer), Empty
        }
        int inspect((volatile int, volatile int*) tuple) { return 0; }
        int main() { return 0; }
    """)

    assert all(definition.is_volatile for definition in module.typedef_defs)
    source_fields = [
        field
        for definition in (*module.struct_defs, *module.tagged_union_defs)
        for field in (
            definition.fields
            if isinstance(definition, ir_nodes.IRStructDef)
            else [field for variant in definition.variants for field in variant.fields]
        )
        if field.name in {"scalar", "pointer", "values", "_0", "_1"}
    ]
    assert source_fields
    assert all(field.is_volatile for field in source_fields)

    emitted = CEmitter().emit(module)
    assert "typedef volatile int VolatileInt;" in emitted
    assert "typedef int* volatile VolatilePointer;" in emitted
    assert "volatile int values[2];" in emitted
    assert "volatile int _0;" in emitted
    assert "int* volatile _1;" in emitted


def test_generic_callable_prototypes_are_typed():
    module = _generate("""
        class Box<T> {
            public T value;
            public Box(T value) { self.value = value; }
            public T get() { return self.value; }
            public U pick<U>(U value) { return value; }
        }
        int main() {
            Box<int> box = Box(1);
            return box.pick(2) - box.get();
        }
    """)

    generic_definitions = {
        function.name for function in module.function_defs if function.name.startswith("btrc_Box_int")
    }
    declarations = {function.name for function in module.function_decls}
    assert generic_definitions <= declarations
    assert module.preprocessor_decls[:2] == [
        IRMacroDef(name="_DEFAULT_SOURCE"),
        IRMacroDef(name="_DARWIN_C_SOURCE"),
    ]


def test_source_macros_lower_to_typed_shapes():
    module = _generate("""
        #define MAXN 10
        #define SQUARE(x) ((x) * (x))
        #define EMPTY()
        int main() { return SQUARE(MAXN) == 100 ? 0 : 1; }
    """)

    user_macros = [
        declaration
        for declaration in module.preprocessor_decls
        if isinstance(declaration, IRMacroDef) and declaration.name not in {"_DEFAULT_SOURCE", "_DARWIN_C_SOURCE"}
    ]
    assert user_macros == [
        IRMacroDef(name="MAXN", replacement="10"),
        IRMacroDef(
            name="SQUARE",
            params=["x"],
            replacement="((x) * (x))",
        ),
        IRMacroDef(name="EMPTY", params=[]),
    ]
    emitted = CEmitter().emit(module)
    assert emitted.index("#define _DEFAULT_SOURCE") < emitted.index("#include <stdio.h>")
    assert emitted.index("#include <stdio.h>") < emitted.index("#define MAXN 10")


@pytest.mark.parametrize(
    "directive, message",
    [
        ("#define", "malformed #define"),
        ("#define 7BAD value", "malformed #define"),
        ("#define BAD(x,x) x", "duplicate function-like macro parameter"),
        ("#define BAD(x", "malformed function-like #define"),
        ("#include HEADER", "malformed #include"),
        ("#pragma once", "unsupported #pragma"),
        ("#undef NAME", "unsupported preprocessor directive '#undef'"),
        ("#define CONTINUED 1\\", "multi-line preprocessor directive"),
        ("#define CONTINUED ??/", "C11 trigraphs"),
    ],
)
def test_malformed_or_unsupported_directives_fail_closed(
    directive: str,
    message: str,
):
    with pytest.raises(CodegenError, match=message):
        _generate(f"{directive}\nint main() {{ return 0; }}")


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
@pytest.mark.parametrize("freestanding", (False, True), ids=("hosted", "freestanding"))
def test_local_include_keeps_quotes_and_compiles(
    tmp_path: Path,
    c_compiler: str,
    freestanding: bool,
):
    (tmp_path / "local_contract.h").write_text(
        "#ifndef CONFIG_VALUE\n"
        '#error "CONFIG_VALUE must precede local_contract.h"\n'
        "#endif\n"
        "#define LOCAL_VALUE CONFIG_VALUE\n"
    )
    (tmp_path / "btrc_rt.h").write_text("")
    module = _generate(
        """
        #define CONFIG_VALUE 37
        #include "local_contract.h"
        #include <stddef.h>
        int main() { return LOCAL_VALUE == 37 ? 0 : 1; }
        """,
        freestanding=freestanding,
    )
    emitted = CEmitter().emit(module)
    assert '#include "local_contract.h"' in emitted
    assert "#include <local_contract.h>" not in emitted
    assert emitted.index("#define CONFIG_VALUE 37") < emitted.index('#include "local_contract.h"')
    if freestanding:
        assert '#include "btrc_rt.h"' in emitted
        assert "#include <stddef.h>" not in emitted
    else:
        assert "#include <stddef.h>" in emitted

    source = tmp_path / f"include_{'free' if freestanding else 'hosted'}.c"
    executable = source.with_suffix("")
    source.write_text(emitted)
    subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(source),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([str(executable)], check=True)


def test_source_include_then_macro_order_is_preserved():
    module = _generate("""
        #include "first.h"
        #define AFTER_INCLUDE 1
        int main() { return 0; }
    """)

    declarations = module.preprocessor_decls
    include_index = declarations.index(IRInclude(header="first.h", is_system=False))
    macro_index = declarations.index(IRMacroDef(name="AFTER_INCLUDE", replacement="1"))
    assert include_index < macro_index
    emitted = CEmitter().emit(module)
    assert emitted.index('#include "first.h"') < emitted.index("#define AFTER_INCLUDE 1")


def test_freestanding_system_include_replacement_keeps_source_position():
    module = IRModule(
        freestanding=True,
        preprocessor_decls=[
            IRMacroDef(name="CONFIG_VALUE", replacement="37"),
            IRInclude(header="stddef.h"),
            IRInclude(header="local_contract.h", is_system=False),
        ],
    )

    from src.compiler.python.ir.runtime_dependencies import refresh_runtime_dependencies

    refresh_runtime_dependencies(module)
    emitted = CEmitter().emit(module)
    assert emitted.index("#define CONFIG_VALUE 37") < emitted.index('#include "btrc_rt.h"')
    assert emitted.index('#include "btrc_rt.h"') < emitted.index('#include "local_contract.h"')
    assert "#include <stddef.h>" not in emitted


def test_typed_typedef_and_tagged_union_precede_function_prototypes():
    module = IRModule(
        enum_defs=[],
        struct_forwards=[IRStructForward(name="Payload")],
        function_decls=[
            IRFunctionDecl(
                name="identity",
                return_type=CType("Payload"),
                params=[IRParam(CType("Payload"), "value")],
            )
        ],
        typedef_defs=[IRTypedefDef(CType("int"), "Score")],
        tagged_union_defs=[
            IRTaggedUnionDef(
                name="Payload",
                tag_type=CType("Payload_Tag"),
                variants=[
                    IRTaggedUnionVariant(
                        name="Number",
                        fields=[IRStructField(CType("int"), "value")],
                    )
                ],
            )
        ],
    )

    emitted = CEmitter().emit(module)
    assert "typedef int Score;" in emitted
    assert "typedef struct Payload_Number_Data" in emitted
    assert "struct Payload {" in emitted
    assert emitted.index("struct Payload {") < emitted.index("Payload identity(Payload value);")


def test_callback_type_aliases_precede_source_aliases_and_payload_fields():
    module = IRModule(
        struct_forwards=[IRStructForward(name="Event")],
        function_pointer_typedefs=[
            IRFunctionPointerTypedef(
                name="Callback",
                return_type=CType("int"),
                param_types=[CType("int")],
            )
        ],
        function_decls=[
            IRFunctionDecl(
                name="invoke",
                return_type=CType("Event"),
                params=[IRParam(CType("Event"), "value")],
            )
        ],
        typedef_defs=[IRTypedefDef(CType("Callback"), "Handler")],
        tagged_union_defs=[
            IRTaggedUnionDef(
                name="Event",
                tag_type=CType("Event_Tag"),
                variants=[
                    IRTaggedUnionVariant(
                        name="Handler",
                        fields=[IRStructField(CType("Callback"), "callback")],
                    )
                ],
            )
        ],
    )

    emitted = CEmitter().emit(module)
    callback = emitted.index("typedef int (*Callback)(int);")
    assert callback < emitted.index("typedef Callback Handler;")
    assert callback < emitted.index("Callback callback;")
    assert emitted.index("struct Event {") < emitted.index("Event invoke(Event value);")


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_typed_declaration_order_is_strict_c11(
    tmp_path: Path,
    c_compiler: str,
):
    module = IRModule(
        struct_forwards=[IRStructForward(name="Event")],
        function_pointer_typedefs=[
            IRFunctionPointerTypedef(
                name="Callback",
                return_type=CType("int"),
                param_types=[CType("int")],
            )
        ],
        typedef_defs=[IRTypedefDef(CType("Callback"), "Handler")],
        tagged_union_defs=[
            IRTaggedUnionDef(
                name="Event",
                tag_type=CType("int"),
                variants=[
                    IRTaggedUnionVariant(
                        name="Handler",
                        fields=[IRStructField(CType("Handler"), "callback")],
                    )
                ],
            )
        ],
        function_decls=[
            IRFunctionDecl(
                name="invoke",
                return_type=CType("Event"),
                params=[IRParam(CType("Event"), "value")],
            )
        ],
        function_defs=[
            IRFunctionDef(
                name="main",
                return_type=CType("int"),
                body=IRBlock(stmts=[IRReturn(IRLiteral("0"))]),
            )
        ],
    )
    source = tmp_path / "typed_declarations.c"
    source.write_text(CEmitter().emit(module))

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
            str(tmp_path / "typed_declarations.o"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_local_storage_qualifiers_are_declaration_metadata():
    body = IRBlock(
        stmts=[
            IRVarDecl(
                CType("int"),
                "counter",
                IRLiteral("0"),
                is_static=True,
                is_volatile=True,
            ),
            IRVarDecl(CType("int"), "external", is_extern=True),
            IRReturn(IRLiteral("0")),
        ]
    )
    module = IRModule(function_defs=[IRFunctionDef(name="main", return_type=CType("int"), body=body)])

    emitted = CEmitter().emit(module)
    assert "static volatile int counter = 0;" in emitted
    assert "extern int external;" in emitted


@pytest.mark.parametrize("c_compiler", COMPILERS)
def test_unused_local_extern_has_portable_unevaluated_use(tmp_path, c_compiler):
    module = _generate("""
        void declareExternal() {
            extern int external_only_declaration;
        }
        int main() {
            declareExternal();
            return 0;
        }
    """)
    emitted = CEmitter().emit(module)
    assert "extern int external_only_declaration;" in emitted
    assert "sizeof((&external_only_declaration))" in emitted

    source = tmp_path / "unused_local_extern.c"
    executable = tmp_path / "unused_local_extern"
    source.write_text(emitted)
    subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(source),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_fixed_array_global_has_structured_declarator():
    module = IRModule(
        global_decls=[
            IRGlobalDecl(
                c_type=CType("int"),
                name="values",
                array_size=IRLiteral("8"),
            )
        ]
    )

    emitted = CEmitter().emit(module)
    assert "static int values[8];" in emitted
    assert "int* values" not in emitted


def test_fixed_array_struct_field_has_structured_declarator():
    module = _generate("""
        struct Buffer { int values[8]; };
        int main() { return 0; }
    """)

    field = module.struct_defs[0].fields[0]
    assert field.name == "values"
    assert isinstance(field.array_size, IRLiteral)
    assert CEmitter().emit(module).count("int values[8];") == 1


def test_pragma_pack_is_struct_metadata_and_wraps_its_declaration():
    module = _generate("""
        #pragma pack(push, 1)
        struct Packed { char tag; int value; };
        #pragma pack(pop)
        int main() { return sizeof(struct Packed) == (size_t)5 ? 0 : 1; }
    """)

    packed = module.struct_defs[0]
    assert packed.pack_alignment == 1
    assert {declaration.name for declaration in module.preprocessor_decls if isinstance(declaration, IRMacroDef)} == {
        "_DEFAULT_SOURCE",
        "_DARWIN_C_SOURCE",
    }
    emitted = CEmitter().emit(module)
    assert emitted.index("#pragma pack(push, 1)") < emitted.index("struct Packed {")
    assert emitted.index("struct Packed {") < emitted.index("#pragma pack(pop)")


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_macros_and_pack_execute_under_strict_c11(
    tmp_path: Path,
    c_compiler: str,
):
    module = _generate("""
        #define WIDTH 4
        #define SQUARE(x) ((x) * (x))
        #pragma pack(push, 1)
        struct Packed { char tag; int value; };
        #pragma pack(pop)
        int main() {
            struct Packed packed = {65, SQUARE(WIDTH)};
            return sizeof(struct Packed) == (size_t)5 && packed.value == 16 ? 0 : 1;
        }
    """)
    source = tmp_path / "macros_and_pack.c"
    executable = tmp_path / "macros_and_pack"
    source.write_text(CEmitter().emit(module))

    subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(source),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [str(executable)],
        check=True,
        capture_output=True,
        text=True,
    )


def test_initializers_and_compound_literals_remain_structured():
    module = _generate("""
        int answer = 42;
        int main() {
            int values[] = [1, 2];
            var pair = (answer, values[0]);
            return pair._0;
        }
    """)

    assert isinstance(module.global_decls[0].init, IRLiteral)
    declarations = [statement for statement in module.function_defs[-1].body.stmts if isinstance(statement, IRVarDecl)]
    assert isinstance(declarations[0].init, IRInitializerList)
    assert isinstance(declarations[1].init, IRCompoundLiteral)
