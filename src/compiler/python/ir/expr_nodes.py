"""Expression nodes and resolved C types for the structured IR."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CType:
    """Fully-resolved C type string (e.g., ``int`` or ``btrc_List_int*``)."""

    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("CType.text must be a string")
        if not self.text:
            raise ValueError("CType.text must not be empty")
        if self.text != self.text.strip():
            raise ValueError("CType.text must not have surrounding whitespace")
        if any(character in self.text for character in "\0\r\n;{}"):
            raise ValueError("CType.text must be one declaration-free line")

    def __str__(self) -> str:
        return self.text


@dataclass
class IRExpr:
    """Base for IR expressions."""


@dataclass
class IRLiteral(IRExpr):
    """C literal text (e.g., ``42``, ``"hello"``, or ``NULL``)."""

    text: str = ""


@dataclass
class IRVar(IRExpr):
    """Variable reference by C name."""

    name: str = ""


@dataclass(frozen=True)
class IRCleanupSlot:
    """Typed automatic slot held by the exception-cleanup registry."""

    name: str
    c_type: CType
    take_function: str

    def __post_init__(self) -> None:
        if not self.name or not self.take_function:
            raise ValueError("cleanup slot names and take functions must not be empty")
        if not isinstance(self.c_type, CType):
            raise TypeError("IRCleanupSlot.c_type must be CType")


@dataclass
class IRBinOp(IRExpr):
    """Binary operator."""

    left: IRExpr = None
    op: str = ""
    right: IRExpr = None


@dataclass
class IRCommaExpr(IRExpr):
    """A left-to-right sequence of C expressions, yielding the final value."""

    expressions: list[IRExpr] = field(default_factory=list)


@dataclass
class IRUnaryOp(IRExpr):
    """Unary operator."""

    op: str = ""
    operand: IRExpr = None
    prefix: bool = True


@dataclass
class IRCall(IRExpr):
    """Function call."""

    callee: str | IRExpr = ""
    args: list[IRExpr] = field(default_factory=list)
    helper_ref: str = ""
    cleanup_slot: IRCleanupSlot | None = None


@dataclass
class IRFieldAccess(IRExpr):
    """Struct field access (``.`` or ``->``)."""

    obj: IRExpr = None
    field: str = ""
    arrow: bool = False


@dataclass
class IRCast(IRExpr):
    """C type cast."""

    target_type: CType
    expr: IRExpr

    def __post_init__(self) -> None:
        if not isinstance(self.target_type, CType):
            raise TypeError("IRCast.target_type must be CType")
        if not isinstance(self.expr, IRExpr):
            raise TypeError("IRCast.expr must be IRExpr")


@dataclass
class IRTernary(IRExpr):
    """Ternary expression."""

    condition: IRExpr = None
    true_expr: IRExpr = None
    false_expr: IRExpr = None


@dataclass
class IRSizeof(IRExpr):
    """Sizeof expression."""

    operand: CType | IRExpr

    def __post_init__(self) -> None:
        if not isinstance(self.operand, (CType, IRExpr)):
            raise TypeError("IRSizeof.operand must be CType or IRExpr")


@dataclass
class IRInitializerList(IRExpr):
    """Positional C initializer list used in declaration contexts."""

    elements: list[IRExpr] = field(default_factory=list)


@dataclass
class IRCompoundLiteral(IRExpr):
    """Typed C compound literal with named field initializers."""

    c_type: CType = None
    fields: list[tuple[str, IRExpr]] = field(default_factory=list)


@dataclass
class IRIndex(IRExpr):
    """Array or pointer indexing."""

    obj: IRExpr = None
    index: IRExpr = None


@dataclass
class IRAddressOf(IRExpr):
    """Address-of operator."""

    expr: IRExpr = None


@dataclass
class IRDeref(IRExpr):
    """Dereference operator."""

    expr: IRExpr = None


@dataclass
class IRStmtExpr(IRExpr):
    """Hoistable declarations followed by an expression-local result.

    ``stmts`` must contain only uninitialized declarations. Runtime work belongs
    in ``result`` (normally an :class:`IRCommaExpr`) so control-sensitive
    evaluation is preserved.
    """

    stmts: list = field(default_factory=list)
    result: IRExpr = None
