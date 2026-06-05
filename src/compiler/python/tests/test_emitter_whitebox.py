"""White-box CEmitter tests: build IR modules directly and assert the emitted C.
These reach module-assembly branches (vtables, globals, multi-field structs,
GPU-kernel string constants) and statement forms (volatile declarations, the
two C-for init shapes, a GPU kernel emitted in statement position) that specific
source programs don't reliably produce."""

from src.compiler.python.ir.emitter import CEmitter
from src.compiler.python.ir.nodes import (
    CType,
    IRAssign,
    IRBlock,
    IRFor,
    IRFunctionDef,
    IRGpuKernel,
    IRLiteral,
    IRModule,
    IRReturn,
    IRStructDef,
    IRStructField,
    IRVar,
    IRVarDecl,
)


def test_emit_vtables_globals_and_multifield_struct():
    m = IRModule(
        vtable_defs=["typedef struct { void* speak; } VT_Animal;"],
        global_vars=["int g_counter = 0;"],
        struct_defs=[IRStructDef(name="Pt", fields=[
            IRStructField(c_type=CType(text="int"), name="x"),
            IRStructField(c_type=CType(text="int"), name="y"),
        ])],
    )
    c = CEmitter().emit(m)
    assert "VT_Animal" in c          # vtable text emitted
    assert "g_counter" in c          # global emitted
    assert "Pt" in c and "x" in c and "y" in c   # multi-field struct


def test_emit_volatile_declaration_and_for_init_forms():
    body = IRBlock(stmts=[
        IRVarDecl(c_type=CType(text="int"), name="vv", init=None, is_volatile=True),
        IRFor(init=IRVarDecl(c_type=CType(text="int"), name="i", init=None),
              condition=None, update=None, body=IRBlock(stmts=[])),
        IRFor(init=IRAssign(target=IRVar(name="i"), value=IRLiteral(text="0")),
              condition=None, update=None, body=IRBlock(stmts=[])),
        IRReturn(value=IRLiteral(text="0")),
    ])
    m = IRModule(function_defs=[IRFunctionDef(
        name="f", return_type=CType(text="int"), body=body)])
    c = CEmitter().emit(m)
    assert "volatile int vv;" in c       # volatile decl, no initializer
    assert "for (int i" in c             # for-init: bare var decl
    assert "for (i = 0" in c             # for-init: assignment


def test_emit_volatile_pointer_declaration():
    body = IRBlock(stmts=[
        IRVarDecl(c_type=CType(text="Item*"), name="it",
                  init=IRLiteral(text="NULL"), is_volatile=True),
        IRReturn(value=IRLiteral(text="0")),
    ])
    m = IRModule(function_defs=[IRFunctionDef(
        name="f", return_type=CType(text="int"), body=body)])
    c = CEmitter().emit(m)
    assert "Item* volatile it" in c       # volatile pointer (not pointer-to-volatile)


def test_emit_gpu_kernel_in_statement_position():
    kernel = IRGpuKernel(name="kern", wgsl_source="@compute @workgroup_size(64)\nfn main() {}")
    body = IRBlock(stmts=[kernel, IRReturn(value=IRLiteral(text="0"))])
    m = IRModule(function_defs=[IRFunctionDef(
        name="f", return_type=CType(text="int"), body=body)])
    c = CEmitter().emit(m)
    assert "kern_wgsl" in c                # kernel WGSL string constant emitted
