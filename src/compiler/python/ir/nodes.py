"""IR (Intermediate Representation) node definitions for the btrc compiler.

Tree-structured IR between the analyzed AST and C text emission.
Rationale: C is structured, so a tree IR produces readable output.

Key design: all AST lowering (class layout, generics, method-to-function,
new/delete expansion, for-in expansion, f-string expansion, lambda lifting)
happens during IR generation. The C emitter is a simple tree walk.
"""

from __future__ import annotations
from dataclasses import dataclass, field


# --- C type representation ---

@dataclass
class CType:
    """Fully-resolved C type string (e.g., 'int', 'btrc_List_int*')."""
    text: str

    def __str__(self) -> str:
        return self.text


# --- IR Module (root) ---

@dataclass
class IRModule:
    """Root of the IR tree — represents one translation unit (.c file)."""
    includes: list[str] = field(default_factory=list)         # e.g., ["stdio.h", "stdlib.h"]
    forward_decls: list[str] = field(default_factory=list)    # forward struct/function declarations
    helper_decls: list[IRHelperDecl] = field(default_factory=list)  # runtime helpers
    struct_defs: list[IRStructDef] = field(default_factory=list)
    vtable_defs: list[str] = field(default_factory=list)      # vtable struct/instance text
    global_vars: list[str] = field(default_factory=list)       # global variable declarations
    function_defs: list[IRFunctionDef] = field(default_factory=list)
    raw_sections: list[str] = field(default_factory=list)      # pre-rendered C text sections


# --- Runtime helpers ---

@dataclass
class IRHelperDecl:
    """A runtime helper function with its pre-rendered C source text.

    category: grouping tag (e.g., "alloc", "string", "trycatch")
    name: C function name (e.g., "__btrc_trim")
    c_source: complete C source text for this helper
    depends_on: categories this helper requires
    """
    category: str
    name: str
    c_source: str
    depends_on: list[str] = field(default_factory=list)


# --- Struct definitions ---

@dataclass
class IRStructField:
    """A field in a C struct."""
    c_type: CType
    name: str

@dataclass
class IRStructDef:
    """C struct definition."""
    name: str
    fields: list[IRStructField] = field(default_factory=list)


# --- Function definitions ---

@dataclass
class IRParam:
    """A C function parameter."""
    c_type: CType
    name: str

@dataclass
class IRFunctionDef:
    """C function definition."""
    name: str
    return_type: CType
    params: list[IRParam] = field(default_factory=list)
    body: IRBlock = None
    is_static: bool = False


# --- Statements ---

@dataclass
class IRBlock:
    """A block of IR statements."""
    stmts: list[IRStmt] = field(default_factory=list)


@dataclass
class IRStmt:
    """Base for IR statements."""
    pass


@dataclass
class IRVarDecl(IRStmt):
    """Local variable declaration: `type name [= init];`"""
    c_type: CType
    name: str
    init: IRExpr = None


@dataclass
class IRAssign(IRStmt):
    """Assignment: `target = value;`"""
    target: IRExpr = None
    value: IRExpr = None


@dataclass
class IRReturn(IRStmt):
    """Return statement."""
    value: IRExpr = None


@dataclass
class IRIf(IRStmt):
    """If/else (structured)."""
    condition: IRExpr = None
    then_block: IRBlock = None
    else_block: IRBlock = None  # None for no-else


@dataclass
class IRWhile(IRStmt):
    """While loop."""
    condition: IRExpr = None
    body: IRBlock = None


@dataclass
class IRDoWhile(IRStmt):
    """Do-while loop."""
    body: IRBlock = None
    condition: IRExpr = None


@dataclass
class IRFor(IRStmt):
    """C-style for loop: `for (init; cond; update) { body }`"""
    init: str = ""       # pre-rendered C text for init
    condition: str = ""  # pre-rendered C text for condition
    update: str = ""     # pre-rendered C text for update
    body: IRBlock = None


@dataclass
class IRSwitch(IRStmt):
    """Switch/case statement."""
    value: IRExpr = None
    cases: list[IRCase] = field(default_factory=list)


@dataclass
class IRCase:
    """A case clause in a switch."""
    value: IRExpr = None  # None for default
    body: list[IRStmt] = field(default_factory=list)


@dataclass
class IRExprStmt(IRStmt):
    """Expression as statement."""
    expr: IRExpr = None


@dataclass
class IRRawC(IRStmt):
    """Escape hatch: pre-rendered C text (for setjmp boilerplate, etc.)."""
    text: str = ""
    helper_refs: list[str] = field(default_factory=list)


@dataclass
class IRBreak(IRStmt):
    """Break statement."""
    pass


@dataclass
class IRContinue(IRStmt):
    """Continue statement."""
    pass


# --- Expressions ---

@dataclass
class IRExpr:
    """Base for IR expressions."""
    pass


@dataclass
class IRLiteral(IRExpr):
    """C literal text (e.g., '42', '"hello"', 'NULL')."""
    text: str = ""


@dataclass
class IRVar(IRExpr):
    """Variable reference by C name."""
    name: str = ""


@dataclass
class IRBinOp(IRExpr):
    """Binary operator."""
    left: IRExpr = None
    op: str = ""
    right: IRExpr = None


@dataclass
class IRUnaryOp(IRExpr):
    """Unary operator."""
    op: str = ""
    operand: IRExpr = None
    prefix: bool = True


@dataclass
class IRCall(IRExpr):
    """Function call."""
    callee: str = ""      # C function name or expression text
    args: list[IRExpr] = field(default_factory=list)
    helper_ref: str = ""  # if non-empty, tracks which runtime helper is used (for DCE)


@dataclass
class IRFieldAccess(IRExpr):
    """Struct field access (. or ->)."""
    obj: IRExpr = None
    field: str = ""
    arrow: bool = False


@dataclass
class IRCast(IRExpr):
    """C type cast."""
    target_type: CType = None
    expr: IRExpr = None


@dataclass
class IRTernary(IRExpr):
    """Ternary expression: `cond ? true_expr : false_expr`."""
    condition: IRExpr = None
    true_expr: IRExpr = None
    false_expr: IRExpr = None


@dataclass
class IRSizeof(IRExpr):
    """sizeof expression."""
    operand: str = ""  # C type or expression text


@dataclass
class IRIndex(IRExpr):
    """Array/pointer indexing: `obj[index]`."""
    obj: IRExpr = None
    index: IRExpr = None


@dataclass
class IRAddressOf(IRExpr):
    """Address-of operator: `&expr`."""
    expr: IRExpr = None


@dataclass
class IRDeref(IRExpr):
    """Dereference operator: `*expr`."""
    expr: IRExpr = None


@dataclass
class IRRawExpr(IRExpr):
    """Escape hatch: pre-rendered C expression text."""
    text: str = ""


@dataclass
class IRStmtExpr(IRExpr):
    """GCC statement expression: ({ stmt; stmt; result; })"""
    stmts: list = field(default_factory=list)
    result: 'IRExpr' = None


@dataclass
class IRSpawnThread(IRExpr):
    """Spawn a thread: __btrc_thread_spawn(fn_ptr, capture_arg)."""
    fn_ptr: str = ""       # C function name (from lambda lowering)
    capture_arg: IRExpr = None  # Capture struct pointer (or NULL)
