"""The C2 schema's IR shapes (docs/design/c-compatibility.md, "Schema commit").

No lowering produces these shapes until each C2 row lands, so the tests build
IR directly: the emitter must spell each shape as strict C11, and IRVerifier
must refuse every violation of the one IRStructField shape invariant.
"""

import subprocess
from pathlib import Path

import pytest

from src.compiler.python.backend.c_emitter import CEmitter
from src.compiler.python.ir.nodes import (
    CType,
    GpuDispatchNames,
    IRAddressOf,
    IRBlock,
    IRCall,
    IRCompoundLiteral,
    IRDesignation,
    IRExprStmt,
    IRFieldAccess,
    IRFunctionDef,
    IRGlobalDecl,
    IRInclude,
    IRInitializerList,
    IRLiteral,
    IRModule,
    IRObjectiveCClass,
    IRStructDef,
    IRStructField,
    IRStructForward,
    IRTaggedUnionDef,
    IRTaggedUnionVariant,
    IRVar,
)
from src.compiler.python.ir.optimizer import IROptimizer
from src.compiler.python.ir.verifier import IRVerifier
from src.tests.c_toolchains import HOST_C_COMPILERS, requires_host_c_compiler
from src.tests.process_limits import C_COMPILE_TIMEOUT
from src.tests.python.reference_pipeline import lower_gpu_dispatch


def _field(c_type: str, name: str, **facets) -> IRStructField:
    return IRStructField(c_type=CType(c_type), name=name, **facets)


def _record(*fields: IRStructField) -> list[IRStructField]:
    return list(fields)


def _module(*structs: IRStructDef, globals_: tuple[IRGlobalDecl, ...] = ()) -> IRModule:
    module = IRModule(
        preprocessor_decls=[IRInclude(header="stdbool.h", is_system=True)],
        struct_forwards=[IRStructForward(name=struct.name, is_union=struct.is_union) for struct in structs],
        struct_defs=list(structs),
        global_decls=list(globals_),
    )
    IROptimizer.refresh_type_declarations(module)
    return module


def _shapes_module() -> IRModule:
    value = IRStructDef(
        name="Value",
        fields=[
            _field("int", "kind"),
            _field("union", "", record_fields=_record(_field("int", "integer"), _field("double", "real"))),
        ],
    )
    number = IRStructDef(name="Number", fields=[_field("int", "i"), _field("float", "f")], is_union=True)
    buffer = IRStructDef(name="Buffer", fields=[_field("int", "count"), _field("int", "data", is_unsized_array=True)])
    flags = IRStructDef(
        name="Flags",
        fields=[
            _field("unsigned int", "ready", bit_width=1),
            _field("unsigned int", "", bit_width=0),
            _field("int", "level", bit_width=3),
            _field("bool", "on", bit_width=1),
        ],
    )
    globals_ = (
        IRGlobalDecl(
            c_type=CType("Value"),
            name="value",
            is_static=False,
            init=IRInitializerList(elements=[IRDesignation(field="integer", value=IRLiteral("7"))]),
        ),
        IRGlobalDecl(
            c_type=CType("int"),
            name="table",
            is_static=False,
            array_size=IRLiteral("4"),
            init=IRInitializerList(
                elements=[IRDesignation(index=IRLiteral("2"), value=IRLiteral("7")), IRLiteral("8")]
            ),
        ),
        IRGlobalDecl(
            c_type=CType("int*"),
            name="row",
            is_static=False,
            init=IRCompoundLiteral(
                c_type=CType("int[3]"),
                fields=[("", IRDesignation(index=IRLiteral("1"), value=IRLiteral("5"))), ("", IRLiteral("6"))],
            ),
        ),
        IRGlobalDecl(
            c_type=CType("Number*"),
            name="number",
            is_static=False,
            init=IRAddressOf(expr=IRCompoundLiteral(c_type=CType("Number"), fields=[("f", IRLiteral("2.5f"))])),
        ),
    )
    return _module(value, number, buffer, flags, globals_=globals_)


def test_c2_shapes_emit_their_c_spelling() -> None:
    module = _shapes_module()
    IRVerifier(module).validate()
    emitted = CEmitter().emit(module)
    for line in (
        "typedef union Number Number;",
        "union Number {",
        "    union {",
        "        int integer;",
        "    int data[];",
        "    unsigned int ready : 1;",
        "    unsigned int : 0;",
        "    bool on : 1;",
        "Value value = {.integer = 7};",
        "int table[4] = {[2] = 7, 8};",
        "int* row = (int[3]){[1] = 5, 6};",
        "Number* number = (&(Number){.f = 2.5f});",
    ):
        assert line in emitted, line


@requires_host_c_compiler
@pytest.mark.parametrize("c_compiler", HOST_C_COMPILERS)
def test_c2_shapes_are_strict_c11(c_compiler: str, tmp_path: Path) -> None:
    source = tmp_path / "shapes.c"
    source.write_text(CEmitter().emit(_shapes_module()) + "\nint main(void) { return value.integer - 7; }\n")
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
            str(tmp_path / "shapes.o"),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=C_COMPILE_TIMEOUT,
    )


def _struct(*fields: IRStructField, name: str = "S", is_union: bool = False) -> IRStructDef:
    return IRStructDef(name=name, fields=list(fields), is_union=is_union)


@pytest.mark.parametrize(
    ("struct", "message"),
    [
        (_struct(_field("int", "a", array_size=IRLiteral("2"), bit_width=3)), "combines"),
        (_struct(_field("int", "n"), _field("int", "a", is_unsized_array=True, bit_width=3)), "combines"),
        (_struct(_field("int", "")), "unnamed IRStructField"),
        (_struct(_field("int", "", record_fields=_record(_field("int", "x")))), "record requires"),
        (_struct(_field("struct", "s")), "record requires"),
        (_struct(_field("struct", "u", record_fields=_record(_field("int", "x")))), "anonymous member"),
        (_struct(_field("struct", "", record_fields=_record())), "anonymous member"),
        (_struct(_field("int", "data", is_unsized_array=True), _field("int", "n")), "flexible array"),
        (_struct(_field("int", "data", is_unsized_array=True)), "flexible array"),
        (_struct(_field("int", "n"), _field("int", "data", is_unsized_array=True), is_union=True), "flexible array"),
        (
            _struct(
                _field(
                    "struct", "", record_fields=_record(_field("int", "n"), _field("int", "d", is_unsized_array=True))
                )
            ),
            "flexible array",
        ),
        (_struct(_field("char", "c", bit_width=3)), "int or bool C type"),
        (_struct(_field("int", "c", bit_width=0)), "width 0"),
        (_struct(_field("int", "c", bit_width=-1)), "non-negative"),
        (_struct(_field("int", "x"), name=""), "untagged record"),
        (_struct(_field("int", "x", bit_width=3), name="__gpu_dispatch_1_uniforms_type"), "GPU"),
        (_struct(_field("int", "", bit_width=3), _field("int", "d", is_unsized_array=True)), "flexible array"),
    ],
)
def test_struct_field_shape_violations_are_refused(struct: IRStructDef, message: str) -> None:
    module = IRModule(struct_defs=[struct])
    with pytest.raises((TypeError, ValueError), match=message):
        IRVerifier(module).validate_schema()


def test_tagged_union_payloads_hold_plain_fields_only() -> None:
    variant = IRTaggedUnionVariant(name="V", fields=[_field("int", "x", bit_width=3)])
    module = IRModule(tagged_union_defs=[IRTaggedUnionDef(name="E", tag_type=CType("int"), variants=[variant])])
    with pytest.raises(ValueError, match="tagged-union payload"):
        IRVerifier(module).validate_schema()


@pytest.mark.parametrize(
    "value",
    [
        _field("int", "x", bit_width=3),
        _field("int", "x", is_unsized_array=True),
        _field("struct", "u", record_fields=_record(_field("int", "x"))),
    ],
)
def test_objective_c_adapters_refuse_c2_field_shapes(value: IRStructField) -> None:
    declaration = IRObjectiveCClass(name="Adapter", superclass="NSObject", fields=[value])
    with pytest.raises(ValueError, match="fixed native layout"):
        declaration.validate()


def _function(*expressions) -> IRFunctionDef:
    return IRFunctionDef(
        name="f",
        return_type=CType("void"),
        body=IRBlock(stmts=[IRExprStmt(expr=expression) for expression in expressions]),
    )


@pytest.mark.parametrize(
    ("expression", "message"),
    [
        (IRCall(callee="g", args=[IRDesignation(field="x", value=IRLiteral("1"))]), "legal only"),
        (
            IRCompoundLiteral(c_type=CType("P"), fields=[("x", IRDesignation(field="x", value=IRLiteral("1")))]),
            "legal only",
        ),
        (IRInitializerList(elements=[IRDesignation(value=IRLiteral("1"))]), "exactly one"),
        (
            IRInitializerList(elements=[IRDesignation(field="x", index=IRLiteral("1"), value=IRLiteral("1"))]),
            "exactly one",
        ),
        (IRInitializerList(elements=[IRDesignation(index=IRVar(name="i"), value=IRLiteral("1"))]), "folded IRLiteral"),
        (IRInitializerList(elements=[IRDesignation(field="x")]), "requires an IRExpr"),
        (
            IRInitializerList(
                elements=[IRDesignation(field="x", value=IRDesignation(field="y", value=IRLiteral("1")))]
            ),
            "legal only",
        ),
        (IRAddressOf(expr=IRFieldAccess(obj=IRVar(name="s"), field="f", bit_field=True)), "bit-field"),
        (
            IRAddressOf(
                expr=IRFieldAccess(obj=IRFieldAccess(obj=IRVar(name="s"), field="f", bit_field=True), field="g")
            ),
            "bit-field",
        ),
    ],
)
def test_designations_and_bit_field_addresses_are_checked(expression, message: str) -> None:
    module = IRModule(function_defs=[_function(expression)])
    with pytest.raises((TypeError, ValueError), match=message):
        IRVerifier(module).validate_schema()


def test_bit_field_reads_and_designated_initializers_pass() -> None:
    module = IRModule(
        function_defs=[
            _function(
                IRFieldAccess(obj=IRVar(name="s"), field="f", bit_field=True),
                IRAddressOf(expr=IRFieldAccess(obj=IRVar(name="s"), field="g")),
                IRInitializerList(elements=[IRDesignation(index=IRLiteral("0"), value=IRLiteral("1"))]),
            )
        ]
    )
    IRVerifier(module).validate_schema()


def test_const_bit_fields_and_union_forwards_are_valid_shapes() -> None:
    flags = IRStructDef(name="Flags", fields=[_field("const unsigned int", "ready", bit_width=1)], is_union=True)
    IRVerifier(_module(flags)).validate()


def test_lowered_gpu_uniform_records_are_recognized() -> None:
    module = lower_gpu_dispatch(
        "@gpu\nvoid scale(int[] xs) { int i = gpu_id(); xs[i] *= 2; }\n"
        "int main() { int[] xs = {1, 2}; scale(xs); return 0; }"
    )
    uniforms = [struct for struct in module.struct_defs if GpuDispatchNames.is_uniforms_record(struct.name)]
    assert len(uniforms) == 1
    uniforms[0].fields.append(_field("int", "flag", bit_width=1))
    with pytest.raises(ValueError, match="GPU"):
        IRVerifier(module).validate_schema()
