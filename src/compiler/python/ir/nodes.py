"""Complete typed intermediate-representation model for the Python compiler."""

from __future__ import annotations

import copy
import dataclasses
import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..runtime.generated import GeneratedRuntimeHelperRow


class IRNode:
    """Base for typed IR values with one owned acyclic tree traversal."""

    def walk(self) -> Iterator[object]:
        yield from self.walk_value(self)

    @classmethod
    def walk_value(cls, value: object) -> Iterator[object]:
        if dataclasses.is_dataclass(value):
            yield value
            for node_field in dataclasses.fields(value):
                if not node_field.metadata.get("ir_traverse", True):
                    continue
                yield from cls.walk_value(getattr(value, node_field.name))
            return
        if isinstance(value, dict):
            for item in value.values():
                yield from cls.walk_value(item)
            return
        if isinstance(value, (list, tuple, set, frozenset)):
            for item in value:
                yield from cls.walk_value(item)


@dataclass(frozen=True)
class CType(IRNode):
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

    @staticmethod
    def qualify_volatile_object(c_type: str, is_volatile: bool) -> str:
        """Qualify the declared object, rather than a pointer's pointee."""
        if not is_volatile:
            return c_type
        return f"{c_type} volatile" if c_type.endswith("*") else f"volatile {c_type}"

    def __str__(self) -> str:
        return self.text


@dataclass
class IRExpr(IRNode):
    """Base for IR expressions and their automatic-storage provenance."""

    def direct_storage_root(self) -> str | None:
        """Return the automatic object changed by an lvalue, never its pointee."""
        if isinstance(self, IRVar):
            return self.name
        if isinstance(self, IRFieldAccess):
            return None if self.arrow or not isinstance(self.obj, IRExpr) else self.obj.direct_storage_root()
        if isinstance(self, (IRIndex, IRDeref)) and self.storage_root_known:
            return self.storage_root or None
        if isinstance(self, IRIndex) and isinstance(self.obj, IRExpr):
            return self.obj.direct_storage_root()
        return None

    def array_storage_root_value(self) -> str | None:
        """Return the original automatic root carried by an array value."""
        if isinstance(self, (IRVar, IRFieldAccess)) and self.array_storage_known:
            return self.array_storage_root or None
        return self.direct_storage_root()

    def record_array_stabilization(self, source: object, semantic_type: object | None) -> IRExpr:
        """Carry array storage identity across one operand temporary."""
        if semantic_type is not None and getattr(semantic_type, "is_array", False):
            self.array_storage_known = True
            self.array_storage_root = (source.array_storage_root_value() if isinstance(source, IRExpr) else None) or ""
        return self

    def record_index_storage(self, receiver_type: object | None) -> IRExpr:
        """Annotate a source index with its semantic array-vs-pointer identity."""
        self.storage_root_known = True
        if receiver_type is not None and getattr(receiver_type, "is_array", False):
            self.storage_root = (self.obj.array_storage_root_value() if isinstance(self.obj, IRExpr) else None) or ""
        return self

    def record_array_projection(self, result_type: object | None) -> IRExpr:
        """Annotate an array-valued field with its enclosing automatic root."""
        if result_type is not None and getattr(result_type, "is_array", False):
            self.array_storage_known = True
            self.array_storage_root = self.direct_storage_root() or ""
        return self

    def record_array_value(self, result_type: object | None) -> IRExpr:
        """Annotate a bare array-valued binding before C array-to-pointer decay."""
        if result_type is not None and getattr(result_type, "is_array", False):
            self.array_storage_known = True
            self.array_storage_root = self.direct_storage_root() or ""
        return self


@dataclass
class IRLiteral(IRExpr):
    """C literal text (e.g., ``42``, ``"hello"``, or ``NULL``)."""

    text: str = ""


@dataclass
class IRVar(IRExpr):
    """Variable reference by C name."""

    name: str = ""
    array_storage_root: str = ""
    array_storage_known: bool = False


@dataclass
class IRFunctionRef(IRExpr):
    """Reference to a C function symbol used as a first-class value."""

    name: str = ""


@dataclass(frozen=True)
class IRCleanupSlot(IRNode):
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
    never_returns: bool = False


@dataclass
class IRFieldAccess(IRExpr):
    """Struct field access (``.`` or ``->``)."""

    obj: IRExpr = None
    field: str = ""
    arrow: bool = False
    array_storage_root: str = ""
    array_storage_known: bool = False


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
    storage_root: str = ""
    storage_root_known: bool = False


@dataclass
class IRAddressOf(IRExpr):
    """Address-of operator."""

    expr: IRExpr = None
    source_expression: bool = False


@dataclass
class IRDeref(IRExpr):
    """Dereference operator."""

    expr: IRExpr = None
    storage_root: str = ""
    storage_root_known: bool = False


@dataclass
class IRStmtExpr(IRExpr):
    """Hoistable declarations followed by an expression-local result.

    ``stmts`` must contain only uninitialized or literal-zero-initialized
    declarations. Runtime work belongs in ``result`` (normally an
    :class:`IRCommaExpr`) so control-sensitive evaluation is preserved.
    """

    stmts: list = field(default_factory=list)
    result: IRExpr = None


@dataclass
class IRStructForward(IRNode):
    """A ``typedef struct Name Name`` declaration."""

    name: str


@dataclass
class IRFunctionPointerTypedef(IRNode):
    """A named C function-pointer type."""

    name: str
    return_type: CType
    param_types: list[CType] = field(default_factory=list)


@dataclass
class IRFunctionDecl(IRNode):
    """A function prototype with explicit storage metadata."""

    name: str
    return_type: CType
    params: list[IRParam] = field(default_factory=list)
    is_static: bool = False


@dataclass(frozen=True)
class IRInclude(IRNode):
    """A system ``<header>`` or local ``"header"`` include."""

    header: str
    is_system: bool = True

    @staticmethod
    def _contains_c11_trigraph(value: str) -> bool:
        suffixes = "=/'()!<>-"
        return any(value[index : index + 2] == "??" and value[index + 2] in suffixes for index in range(len(value) - 2))

    def __post_init__(self) -> None:
        if not isinstance(self.header, str):
            raise TypeError("IRInclude.header must be a string")
        if not isinstance(self.is_system, bool):
            raise TypeError("IRInclude.is_system must be a bool")
        has_control = any(ord(char) < 0x20 or ord(char) == 0x7F for char in self.header)
        if (
            not self.header
            or has_control
            or any(char in self.header for char in '<>"')
            or self._contains_c11_trigraph(self.header)
        ):
            raise ValueError(f"invalid structured include: {self.header!r}")


@dataclass
class IRMacroDef(IRNode):
    """An object-like or function-like preprocessor macro."""

    name: str
    params: list[str] | None = None
    replacement: str = ""

    @staticmethod
    def _is_c_identifier(value: object) -> bool:
        return (
            isinstance(value, str)
            and value.isascii()
            and bool(value)
            and (value[0].isalpha() or value[0] == "_")
            and all(char.isalnum() or char == "_" for char in value[1:])
        )

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if not isinstance(self.name, str):
            raise TypeError("IRMacroDef.name must be a string")
        if not self._is_c_identifier(self.name):
            raise ValueError(f"invalid macro name: {self.name!r}")
        if self.params is not None:
            if not isinstance(self.params, list):
                raise TypeError("IRMacroDef.params must be a list or None")
            if any(
                not self._is_c_identifier(param) and not (param == "..." and index == len(self.params) - 1)
                for index, param in enumerate(self.params)
            ):
                raise ValueError("invalid macro parameter")
            if len(self.params) != len(set(self.params)):
                raise ValueError("duplicate macro parameter")
        if not isinstance(self.replacement, str):
            raise TypeError("IRMacroDef.replacement must be a string")
        if any(char in self.replacement for char in "\0\r\n"):
            raise ValueError("macro replacement must fit on one source line")
        if self.replacement.endswith("\\"):
            raise ValueError("multi-line macros are unsupported")


@dataclass
class IRStructField(IRNode):
    """A field in a C struct."""

    c_type: CType
    name: str
    array_size: IRExpr = None
    is_volatile: bool = False
    effective_is_volatile: bool = False


@dataclass
class IRStructDef(IRNode):
    """A C struct definition."""

    name: str
    fields: list[IRStructField] = field(default_factory=list)
    pack_alignment: int | None = None


@dataclass
class IRTypedefDef(IRNode):
    """A named alias for a resolved C type."""

    target_type: CType
    name: str
    is_volatile: bool = False


@dataclass
class IRTaggedUnionVariant(IRNode):
    """One payload variant in a tagged-union definition."""

    name: str
    fields: list[IRStructField] = field(default_factory=list)


@dataclass
class IRTaggedUnionDef(IRNode):
    """A named struct containing a tag and optional variant payload union."""

    name: str
    tag_type: CType
    variants: list[IRTaggedUnionVariant] = field(default_factory=list)


@dataclass
class IRGlobalDecl(IRNode):
    """A typed file-scope variable declaration."""

    c_type: CType
    name: str
    init: IRExpr = None
    array_size: IRExpr = None
    is_unsized_array: bool = False
    is_static: bool = True
    is_extern: bool = False
    is_volatile: bool = False
    effective_is_volatile: bool = False


@dataclass
class IRHelperDecl(IRNode):
    """A runtime helper with its source and dependency metadata."""

    category: str
    name: str
    c_source: str
    depends_on: list[str] = field(default_factory=list)
    required_headers: list[str] = field(default_factory=list)

    @classmethod
    def from_runtime(
        cls,
        definition: GeneratedRuntimeHelperRow,
    ) -> IRHelperDecl:
        """Project one generated runtime definition into structured IR."""

        return cls(
            category=definition.category,
            name=definition.name,
            c_source=definition.c_source,
            depends_on=list(definition.depends_on),
            required_headers=list(definition.required_headers),
        )


@dataclass
class IREnumValue(IRNode):
    """A value in a C enum."""

    name: str
    value: IRExpr | None = None


@dataclass
class IREnumDef(IRNode):
    """A named C enum typedef, or an anonymous C enum declaration."""

    name: str | None
    values: list[IREnumValue] = field(default_factory=list)


@dataclass
class IRStmt(IRNode):
    """Base for IR statements."""

    pass


@dataclass
class IRParam(IRNode):
    """A C function parameter."""

    c_type: CType
    name: str
    is_volatile: bool = False
    effective_is_volatile: bool = False


@dataclass
class IRFunctionDef(IRNode):
    """C function definition."""

    name: str
    return_type: CType
    params: list[IRParam] = field(default_factory=list)
    body: IRBlock = None
    is_static: bool = False
    archive_export: bool = False
    is_realtime: bool = False


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
    realtime_bounded: bool = False


@dataclass
class IRSwitch(IRStmt):
    """Switch/case statement."""

    value: IRExpr = None
    cases: list[IRCase] = field(default_factory=list)
    can_fall_through: bool = True


@dataclass
class IRCase(IRNode):
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


@dataclass
class IRGpuBuffer(IRNode):
    """Metadata for a GPU buffer parameter."""

    name: str = ""
    elem_type: object = None
    access: str = "read"  # "read", "read_write"
    binding: int = 0


@dataclass
class IRGpuShaderModule(IRNode):
    """Backend-neutral, analyzed shader body retained until emission."""

    body: object = None
    node_types: dict[int, object] = field(default_factory=dict)
    output_type: object = None
    bool_uniform_params: list[str] = field(default_factory=list)


@dataclass
class IRGpuKernel(IRStmt):
    """A structured GPU compute kernel plus host-dispatch metadata."""

    name: str = ""
    shader_module: IRGpuShaderModule = None
    workgroup_size: int = 64
    param_buffers: list[IRGpuBuffer] = field(default_factory=list)
    output_buffer: IRGpuBuffer = None  # None for void-returning kernels
    uniform_params: list[tuple] = field(default_factory=list)  # (name, wgsl_type) pairs
    status_binding: int = -1


@dataclass(frozen=True)
class GpuDispatchNames(IRNode):
    """Names derived from the IR-assigned dispatch-site prefix."""

    prefix: str

    def __post_init__(self) -> None:
        if not self.prefix:
            raise ValueError("GPU dispatch is missing its local prefix")

    def local(self, role: str) -> str:
        return f"{self.prefix}_{role}"

    def buffer(self, parameter: str) -> str:
        return self.local(f"buf_{parameter}")

    @property
    def gpu(self) -> str:
        return self.local("gpu")

    @property
    def length(self) -> str:
        return self.local("len")

    @property
    def ok(self) -> str:
        return self.local("ok")

    @property
    def uniforms(self) -> str:
        return self.local("uniforms")

    @property
    def uniform_buffer(self) -> str:
        return self.local("buf_uniforms")

    @property
    def output_buffer(self) -> str:
        return self.local("buf_output")

    @property
    def status_buffer(self) -> str:
        return self.local("buf_status")

    @property
    def status_code(self) -> str:
        return self.local("status")

    @property
    def dispatch_started(self) -> str:
        return self.local("dispatch_started")

    @property
    def shader(self) -> str:
        return self.local("shader")

    @property
    def pipeline(self) -> str:
        return self.local("pipeline")

    @property
    def bindings(self) -> str:
        return self.local("bindings")

    @property
    def bind_group(self) -> str:
        return self.local("bind_group")

    @property
    def chunk(self) -> str:
        return self.local("chunk")

    @property
    def result(self) -> str:
        return self.local("result")

    @property
    def offset(self) -> str:
        return self.local("offset")

    @property
    def work_items(self) -> str:
        return self.local("work_items")

    @property
    def workgroups(self) -> str:
        return self.local("workgroups")


class IRStatementSequence:
    """A structured statement sequence and its conservative flow facts."""

    def __init__(self, statements: list[IRStmt]) -> None:
        self.statements = statements

    def may_fall_through(self) -> bool:
        return all(self._statement_may_fall_through(statement) for statement in self.statements)

    def references_variable(self, name: str) -> bool:
        return any(isinstance(node, IRVar) and node.name == name for node in IRNode.walk_value(self.statements))

    @classmethod
    def _statement_may_fall_through(cls, statement) -> bool:
        if isinstance(statement, (IRReturn, IRBreak, IRContinue)):
            return False
        if isinstance(statement, IRExprStmt) and isinstance(statement.expr, IRCall) and statement.expr.never_returns:
            return False
        if isinstance(statement, IRBlock):
            return cls(statement.stmts).may_fall_through()
        if isinstance(statement, IRSwitch):
            return statement.can_fall_through
        if isinstance(statement, IRIf) and statement.else_block is not None:
            return cls._statement_may_fall_through(statement.then_block) or cls._statement_may_fall_through(
                statement.else_block
            )
        return True


@dataclass
class IRModule(IRNode):
    """One C translation unit before formatting."""

    preprocessor_decls: list[IRInclude | IRMacroDef] = field(default_factory=list)
    freestanding: bool = False
    runtime_roots: set[str] = field(default_factory=set)
    realtime_safe_externals: set[str] = field(default_factory=set)
    needs_runtime: bool = False
    debug: bool = False
    debug_cfile: str = ""
    struct_forwards: list[IRStructForward] = field(default_factory=list)
    function_pointer_typedefs: list[IRFunctionPointerTypedef] = field(default_factory=list)
    function_decls: list[IRFunctionDecl] = field(default_factory=list)
    helper_decls: list[IRHelperDecl] = field(default_factory=list)
    enum_defs: list[IREnumDef] = field(default_factory=list)
    typedef_defs: list[IRTypedefDef] = field(default_factory=list)
    tagged_union_defs: list[IRTaggedUnionDef] = field(default_factory=list)
    struct_defs: list[IRStructDef] = field(default_factory=list)
    ordered_type_declarations: list[
        IREnumDef | IRFunctionPointerTypedef | IRTypedefDef | IRTaggedUnionDef | IRStructDef
    ] = field(default_factory=list, init=False, repr=False, compare=False)
    _type_declaration_snapshot: object = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
        metadata={"ir_traverse": False},
    )
    _ordered_type_declaration_keys: tuple[tuple[str, int], ...] = field(
        default_factory=tuple,
        init=False,
        repr=False,
        compare=False,
        metadata={"ir_traverse": False},
    )
    global_decls: list[IRGlobalDecl] = field(default_factory=list)
    function_defs: list[IRFunctionDef] = field(default_factory=list)
    gpu_kernels: list[IRGpuKernel] = field(default_factory=list)
    _generated_runtime_preprocessor: list[IRInclude | IRMacroDef] = field(
        default_factory=list,
        repr=False,
        compare=False,
    )
    _freestanding_system_includes_lowered: bool = field(
        default=False,
        repr=False,
        compare=False,
    )

    def type_declaration_groups(self) -> tuple[tuple[str, tuple[IRNode, ...]], ...]:
        """Return the typed declaration collections in canonical group order."""

        return (
            ("enum_defs", tuple(self.enum_defs)),
            ("function_pointer_typedefs", tuple(self.function_pointer_typedefs)),
            ("typedef_defs", tuple(self.typedef_defs)),
            ("tagged_union_defs", tuple(self.tagged_union_defs)),
            ("struct_defs", tuple(self.struct_defs)),
        )

    def record_type_declaration_plan(
        self,
        declarations: list[IREnumDef | IRFunctionPointerTypedef | IRTypedefDef | IRTaggedUnionDef | IRStructDef],
    ) -> None:
        """Install one declaration plan and snapshot the inputs that justify it."""

        groups = self.type_declaration_groups()
        keys_by_identity = {
            id(declaration): (field_name, index)
            for field_name, entries in groups
            for index, declaration in enumerate(entries)
        }
        self.ordered_type_declarations = list(declarations)
        self._ordered_type_declaration_keys = tuple(keys_by_identity[id(declaration)] for declaration in declarations)
        self._type_declaration_snapshot = copy.deepcopy(groups)

    def type_declaration_plan_is_current(self) -> bool:
        """Return whether the recorded declaration plan still matches its inputs."""

        groups = self.type_declaration_groups()
        if self._type_declaration_snapshot is None:
            return not any(entries for _, entries in groups) and not self.ordered_type_declarations
        if self._type_declaration_snapshot != groups:
            return False
        declarations_by_key = {
            (field_name, index): declaration
            for field_name, entries in groups
            for index, declaration in enumerate(entries)
        }
        try:
            expected = tuple(declarations_by_key[key] for key in self._ordered_type_declaration_keys)
        except KeyError:
            return False
        return len(self.ordered_type_declarations) == len(expected) and all(
            actual is planned for actual, planned in zip(self.ordered_type_declarations, expected)
        )

    def record_generated_runtime_preprocessor(
        self,
        declarations: list[IRInclude | IRMacroDef],
    ) -> None:
        """Remember runtime declarations installed by the current finalization."""

        self._generated_runtime_preprocessor.extend(declarations)

    def take_generated_runtime_preprocessor(self) -> tuple[IRInclude | IRMacroDef, ...]:
        """Transfer and forget runtime declarations installed by finalization."""

        declarations = tuple(self._generated_runtime_preprocessor)
        self._generated_runtime_preprocessor.clear()
        return declarations

    def needs_freestanding_system_include_lowering(self) -> bool:
        """Return whether hosted system includes still need the runtime seam."""

        return self.freestanding and not self._freestanding_system_includes_lowered

    def mark_freestanding_system_includes_lowered(self) -> None:
        """Record that hosted system includes have been replaced for this module."""

        self._freestanding_system_includes_lowered = True


class IRCanonicalRenderer:
    """Serialize one complete structured IR module without consulting a backend."""

    FORMAT = "btrc-ir-v1"
    _AST_MODULE = "src.compiler.python.syntax.ast.generated"

    def __init__(self) -> None:
        self._active_ids: set[int] = set()

    def render(self, module: IRModule) -> str:
        """Return deterministic, typed JSON for one IR stage boundary."""

        if not isinstance(module, IRModule):
            raise TypeError(f"IRCanonicalRenderer requires IRModule, got {type(module).__name__}")
        self._active_ids.clear()
        try:
            value = {
                "$format": self.FORMAT,
                "module": self._encode(module, "$.module"),
            }
        finally:
            self._active_ids.clear()
        return json.dumps(value, ensure_ascii=False, indent=2)

    def _encode(self, value: object, path: str) -> object:
        if value is None or isinstance(value, (bool, int, str)):
            return value
        if isinstance(value, float):
            return {"$float": value.hex()}
        if isinstance(value, Enum):
            return {"$enum": {"type": type(value).__name__, "name": value.name}}
        if isinstance(value, list):
            return self._encode_sequence(value, path, None)
        if isinstance(value, tuple):
            return self._encode_sequence(value, path, "$tuple")
        if isinstance(value, set):
            return self._encode_set(value, path, "$set")
        if isinstance(value, frozenset):
            return self._encode_set(value, path, "$frozenset")
        if isinstance(value, Mapping):
            return self._encode_mapping(value, path)
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            value_type = type(value)
            if isinstance(value, IRNode) and value_type.__module__ == __name__:
                return self._encode_dataclass(value, path)
            if value_type.__module__ == self._AST_MODULE:
                return self._encode_dataclass(value, path)
        raise TypeError(f"unsupported canonical IR value at {path}: {type(value).__name__}")

    def _encode_sequence(self, value: list | tuple, path: str, tag: str | None) -> object:
        self._enter(value, path)
        try:
            items = [self._encode(item, f"{path}[{index}]") for index, item in enumerate(value)]
        finally:
            self._leave(value)
        return items if tag is None else {tag: items}

    def _encode_set(self, value: set | frozenset, path: str, tag: str) -> object:
        self._enter(value, path)
        try:
            items = [self._encode(item, f"{path}[*]") for item in value]
        finally:
            self._leave(value)
        items.sort(key=self._sort_token)
        return {tag: items}

    def _encode_mapping(self, value: Mapping, path: str) -> object:
        self._enter(value, path)
        try:
            entries = [
                (
                    self._encode(key, f"{path}.<key>"),
                    self._encode(item, f"{path}[{self._mapping_path_key(key)}]"),
                )
                for key, item in value.items()
            ]
        finally:
            self._leave(value)
        entries.sort(key=lambda entry: self._sort_token(entry[0]))
        tokens = [self._sort_token(key) for key, _ in entries]
        if len(tokens) != len(set(tokens)):
            raise ValueError(f"canonical IR mapping keys collide at {path}")
        return {"$map": [[key, item] for key, item in entries]}

    def _encode_dataclass(self, value: object, path: str) -> object:
        self._enter(value, path)
        try:
            encoded = {"$type": type(value).__name__}
            for node_field in dataclasses.fields(value):
                field_value = getattr(value, node_field.name)
                field_path = f"{path}.{node_field.name}"
                if isinstance(value, IRModule) and node_field.name == "ordered_type_declarations":
                    encoded[node_field.name] = self._ordered_type_references(value, field_value, field_path)
                elif isinstance(value, IRGpuShaderModule) and node_field.name == "node_types":
                    encoded[node_field.name] = self._shader_node_types(value, field_value, field_path)
                else:
                    encoded[node_field.name] = self._encode(field_value, field_path)
            return encoded
        finally:
            self._leave(value)

    def _ordered_type_references(self, module: IRModule, declarations: object, path: str) -> object:
        if not isinstance(declarations, list):
            raise TypeError(f"ordered type declarations must be a list at {path}")
        references: dict[int, tuple[str, int]] = {}
        for field_name, entries in module.type_declaration_groups():
            for index, declaration in enumerate(entries):
                identity = id(declaration)
                if identity in references:
                    raise ValueError(f"type declaration has multiple canonical locations at {path}")
                references[identity] = (field_name, index)
        encoded = []
        for index, declaration in enumerate(declarations):
            reference = references.get(id(declaration))
            if reference is None:
                raise ValueError(f"ordered type declaration at {path}[{index}] is not owned by IRModule")
            encoded.append({"$ref": {"field": reference[0], "index": reference[1]}})
        return encoded

    def _shader_node_types(self, shader: IRGpuShaderModule, node_types: object, path: str) -> object:
        if not isinstance(node_types, dict):
            raise TypeError(f"shader node types must be a dict at {path}")
        if any(isinstance(key, bool) or not isinstance(key, int) for key in node_types):
            raise TypeError(f"shader node type keys must be integer identities at {path}")
        nodes = self._dataclass_preorder(shader.body)
        entries = [
            {
                "node": ordinal,
                "type": self._encode(node_types[id(node)], f"{path}[node={ordinal}].type"),
            }
            for ordinal, node in enumerate(nodes)
            if id(node) in node_types
        ]
        return {
            "$scope": "shader-body-dataclass-preorder",
            "entries": entries,
        }

    def _dataclass_preorder(self, root: object) -> list[object]:
        ordered: list[object] = []
        seen: set[int] = set()

        def visit(value: object) -> None:
            if dataclasses.is_dataclass(value) and not isinstance(value, type):
                identity = id(value)
                if identity in seen:
                    return
                seen.add(identity)
                ordered.append(value)
                for node_field in dataclasses.fields(value):
                    visit(getattr(value, node_field.name))
                return
            if isinstance(value, Mapping):
                ordered_items = sorted(
                    value.items(), key=lambda item: self._sort_token(self._encode(item[0], "$gpu-key"))
                )
                for key, item in ordered_items:
                    visit(key)
                    visit(item)
                return
            if isinstance(value, (list, tuple)):
                for item in value:
                    visit(item)
                return
            if isinstance(value, (set, frozenset)):
                for item in sorted(value, key=lambda item: self._sort_token(self._encode(item, "$gpu-set"))):
                    visit(item)

        visit(root)
        return ordered

    @staticmethod
    def _sort_token(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _mapping_path_key(value: object) -> str:
        if value is None or isinstance(value, (bool, int, float, str)):
            return str(value)
        return type(value).__name__

    def _enter(self, value: object, path: str) -> None:
        identity = id(value)
        if identity in self._active_ids:
            raise ValueError(f"canonical IR contains a cycle at {path}")
        self._active_ids.add(identity)

    def _leave(self, value: object) -> None:
        self._active_ids.remove(id(value))


__all__ = (
    "CType",
    "GpuDispatchNames",
    "IRAddressOf",
    "IRAssign",
    "IRBinOp",
    "IRBlock",
    "IRBreak",
    "IRCall",
    "IRCanonicalRenderer",
    "IRCase",
    "IRCast",
    "IRCleanupSlot",
    "IRCommaExpr",
    "IRCompoundLiteral",
    "IRContinue",
    "IRDeref",
    "IRDoWhile",
    "IREnumDef",
    "IREnumValue",
    "IRExpr",
    "IRExprStmt",
    "IRFieldAccess",
    "IRFor",
    "IRFunctionDecl",
    "IRFunctionDef",
    "IRFunctionPointerTypedef",
    "IRFunctionRef",
    "IRGlobalDecl",
    "IRGpuBuffer",
    "IRGpuKernel",
    "IRGpuShaderModule",
    "IRHelperDecl",
    "IRIf",
    "IRInclude",
    "IRIndex",
    "IRInitializerList",
    "IRLineMarker",
    "IRLiteral",
    "IRMacroDef",
    "IRModule",
    "IRNode",
    "IRParam",
    "IRReturn",
    "IRSizeof",
    "IRStatementSequence",
    "IRStmt",
    "IRStmtExpr",
    "IRStructDef",
    "IRStructField",
    "IRStructForward",
    "IRSwitch",
    "IRTaggedUnionDef",
    "IRTaggedUnionVariant",
    "IRTernary",
    "IRTypedefDef",
    "IRUnaryOp",
    "IRVar",
    "IRVarDecl",
    "IRWhile",
)
