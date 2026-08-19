"""White-box CEmitter tests: build IR modules directly and assert the emitted C.
These reach module-assembly branches (globals, multi-field structs, GPU-kernel
string constants) and statement forms (volatile declarations, the
two C-for init shapes, a GPU kernel emitted in statement position) that specific
source programs don't reliably produce."""

from src.compiler.python.backend.c_emitter import CEmitter
from src.compiler.python.ir.nodes import (
    CType,
    IRAssign,
    IRBinOp,
    IRBlock,
    IRBreak,
    IRCase,
    IRFor,
    IRFunctionDef,
    IRGlobalDecl,
    IRGpuKernel,
    IRGpuShaderModule,
    IRIf,
    IRLiteral,
    IRModule,
    IRReturn,
    IRStructDef,
    IRStructField,
    IRSwitch,
    IRVar,
    IRVarDecl,
)
from src.compiler.python.ir.optimizer import IROptimizer
from src.compiler.python.syntax.ast.generated import Block


def test_emit_typed_global_and_multifield_struct():
    m = IRModule(
        global_decls=[
            IRGlobalDecl(
                c_type=CType(text="int"),
                name="g_counter",
                init=IRLiteral(text="0"),
            )
        ],
        struct_defs=[
            IRStructDef(
                name="Pt",
                fields=[
                    IRStructField(c_type=CType(text="int"), name="x"),
                    IRStructField(c_type=CType(text="int"), name="y"),
                ],
            )
        ],
    )
    IROptimizer.refresh_type_declarations(m)
    c = CEmitter().emit(m)
    assert "g_counter" in c  # global emitted
    assert "Pt" in c and "x" in c and "y" in c  # multi-field struct


def test_emit_volatile_declaration_and_for_init_forms():
    body = IRBlock(
        stmts=[
            IRVarDecl(c_type=CType(text="int"), name="vv", init=None, is_volatile=True),
            IRFor(
                init=IRVarDecl(c_type=CType(text="int"), name="i", init=None),
                condition=None,
                update=None,
                body=IRBlock(stmts=[]),
            ),
            IRFor(
                init=IRAssign(target=IRVar(name="i"), value=IRLiteral(text="0")),
                condition=None,
                update=None,
                body=IRBlock(stmts=[]),
            ),
            IRReturn(value=IRLiteral(text="0")),
        ]
    )
    m = IRModule(function_defs=[IRFunctionDef(name="f", return_type=CType(text="int"), body=body)])
    c = CEmitter().emit(m)
    assert "volatile int vv;" in c  # volatile decl, no initializer
    assert "for (int i" in c  # for-init: bare var decl
    assert "for (i = 0" in c  # for-init: assignment


def test_emit_volatile_pointer_declaration():
    body = IRBlock(
        stmts=[
            IRVarDecl(c_type=CType(text="Item*"), name="it", init=IRLiteral(text="NULL"), is_volatile=True),
            IRReturn(value=IRLiteral(text="0")),
        ]
    )
    m = IRModule(function_defs=[IRFunctionDef(name="f", return_type=CType(text="int"), body=body)])
    c = CEmitter().emit(m)
    assert "Item* volatile it" in c  # volatile pointer (not pointer-to-volatile)


def test_emit_gpu_kernel_in_statement_position():
    kernel = IRGpuKernel(
        name="kern",
        shader_module=IRGpuShaderModule(body=Block(statements=[])),
    )
    body = IRBlock(stmts=[kernel, IRReturn(value=IRLiteral(text="0"))])
    m = IRModule(function_defs=[IRFunctionDef(name="f", return_type=CType(text="int"), body=body)])
    c = CEmitter().emit(m)
    assert "kern_wgsl" in c  # kernel WGSL string constant emitted


def test_condition_parenthesis_scan_ignores_character_literal_delimiters():
    body = IRBlock(
        stmts=[
            IRIf(
                condition=IRBinOp(
                    left=IRVar(name="value"),
                    op="==",
                    right=IRLiteral(text="')'"),
                ),
                then_block=IRBlock(),
            )
        ]
    )
    module = IRModule(function_defs=[IRFunctionDef(name="probe", return_type=CType(text="void"), body=body)])

    emitted = CEmitter().emit(module)

    assert "if (value == ')')" in emitted
    assert "if ((value == ')'))" not in emitted


def test_switch_emits_only_explicit_nonterminal_fallthrough_annotations():
    switch = IRSwitch(
        value=IRVar(name="value"),
        cases=[
            IRCase(
                value=IRLiteral(text="1"),
                body=[IRAssign(target=IRVar(name="value"), value=IRLiteral(text="2"))],
                falls_through=True,
            ),
            IRCase(value=IRLiteral(text="2"), body=[IRBreak()]),
            IRCase(value=None, body=[], falls_through=True),
        ],
    )
    module = IRModule(
        function_defs=[
            IRFunctionDef(
                name="probe",
                return_type=CType(text="void"),
                params=[],
                body=IRBlock(stmts=[switch]),
            )
        ]
    )

    emitted = CEmitter().emit(module)

    assert emitted.count("/* fall through */") == 1
    assert "}\n        /* fall through */\n        case 2:" in emitted
