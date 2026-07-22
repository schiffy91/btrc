"""IR (Intermediate Representation) node definitions for the btrc compiler.

Tree-structured IR between analyzed AST and C text; structured C keeps it readable.

All AST lowering happens during IR generation; the emitter is a tree walk.
"""

# ruff: noqa: F401 - compatibility facade for existing explicit imports

from __future__ import annotations

from dataclasses import dataclass, field

from .expr_nodes import (
    CType,
    IRAddressOf,
    IRBinOp,
    IRCall,
    IRCast,
    IRCleanupSlot,
    IRCommaExpr,
    IRCompoundLiteral,
    IRDeref,
    IRExpr,
    IRFieldAccess,
    IRFunctionRef,
    IRIndex,
    IRInitializerList,
    IRLiteral,
    IRSizeof,
    IRStmtExpr,
    IRTernary,
    IRUnaryOp,
    IRVar,
)
from .module import IRModule
from .top_nodes import (
    IREnumDef,
    IREnumValue,
    IRFunctionDecl,
    IRFunctionPointerTypedef,
    IRGlobalDecl,
    IRHelperDecl,
    IRInclude,
    IRMacroDef,
    IRStructDef,
    IRStructField,
    IRStructForward,
    IRTaggedUnionDef,
    IRTaggedUnionVariant,
    IRTypedefDef,
)

# --- Statements ---


@dataclass
class IRStmt:
    """Base for IR statements."""

    pass


# --- Function definitions ---


@dataclass
class IRParam:
    """A C function parameter."""

    c_type: CType
    name: str
    is_volatile: bool = False
    effective_is_volatile: bool = False


@dataclass
class IRFunctionDef:
    """C function definition."""

    name: str
    return_type: CType
    params: list[IRParam] = field(default_factory=list)
    body: IRBlock = None
    is_static: bool = False
    archive_export: bool = False


@dataclass
class IRBlock(IRStmt):
    """A block of IR statements, optionally nested as a lexical scope."""

    stmts: list[IRStmt] = field(default_factory=list)


@dataclass
class IRLineMarker(IRStmt):
    """A ``#line N "file"`` directive (emitted only under --debug).

    Re-points the C compiler's notion of the current source location at the
    originating .btrc file/line, so the generated binary's DWARF references btrc
    source directly — giving native breakpoints and step locations in .btrc."""

    file: str = ""
    line: int = 0


@dataclass
class IRVarDecl(IRStmt):
    """Local variable declaration: `type name [= init];`"""

    c_type: CType
    name: str
    init: IRExpr = None
    array_size: IRExpr = None
    is_unsized_array: bool = False
    is_volatile: bool = False
    is_static: bool = False
    is_extern: bool = False
    cleanup_slot: IRCleanupSlot | None = None
    is_cycle_return_temp: bool = False
    effective_is_volatile: bool = False


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

    init: IRStmt = None  # var decl or expr stmt (None for empty init)
    condition: IRExpr = None  # loop condition (None for infinite loop)
    update: IRExpr = None  # update expression (None for no update)
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
    falls_through: bool = False


@dataclass
class IRExprStmt(IRStmt):
    """Expression as statement."""

    expr: IRExpr = None


@dataclass
class IRBreak(IRStmt):
    """Break statement."""

    pass


@dataclass
class IRContinue(IRStmt):
    """Continue statement."""

    pass


# --- GPU compute ---


@dataclass
class IRGpuBuffer:
    """Metadata for a GPU buffer parameter."""

    name: str = ""
    elem_type: str = ""  # "f32", "i32"
    access: str = "read"  # "read", "read_write"
    binding: int = 0


@dataclass
class IRGpuKernel(IRStmt):
    """A GPU compute kernel (WGSL source + metadata).

    Emitted as a static C string constant containing the WGSL shader.
    """

    name: str = ""
    wgsl_source: str = ""
    workgroup_size: int = 64
    param_buffers: list[IRGpuBuffer] = field(default_factory=list)
    output_buffer: IRGpuBuffer = None  # None for void-returning kernels
    uniform_params: list[tuple] = field(default_factory=list)  # (name, wgsl_type) pairs
    status_binding: int = -1
