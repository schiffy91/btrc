"""Cohesive types IR lowering owner."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import TYPE_CHECKING

from src.compiler.python.analyzer.types import (
    GENERIC_COMPARISON_INTRINSICS,
    GENERIC_INTRINSICS,
    OperatorSemantics,
    OperatorTypeError,
    TypeIdentity,
    TypeSystem,
)
from src.compiler.python.ir.nodes import (
    CType,
    IRBinOp,
    IRCall,
    IRCast,
    IRCommaExpr,
    IRCompoundLiteral,
    IRDeref,
    IRExpr,
    IRFunctionPointerTypedef,
    IRLiteral,
    IRSizeof,
    IRStmtExpr,
    IRTernary,
    IRVar,
    IRVarDecl,
)
from src.compiler.python.syntax.ast.generated import TypeExpr

if TYPE_CHECKING:
    from src.compiler.python.analyzer.program import AnalyzedProgram

    from .session import LoweringSession
_PRIMITIVE_MAP = {
    "int": "int",
    "float": "float",
    "double": "double",
    "bool": "bool",
    "char": "char",
    "string": "char*",
    "void": "void",
    "long": "long",
    "short": "short",
    "byte": "unsigned char",
    "uint": "unsigned int",
    "size_t": "size_t",
}
_RUNTIME_GENERIC_TYPES = {
    "Thread": ("__btrc_thread_t*", "__btrc_thread_types"),
    "Mutex": ("__btrc_mutex_val_t*", "__btrc_mutex_val_types"),
}
_FnPtrSignature = tuple[str, tuple[str, ...]]


class CodegenError(RuntimeError):
    """Raised when analyzed source cannot be represented by structured IR."""


class TypedOperatorError(CodegenError):
    """A concrete operator specialization has no portable lowering."""


@dataclass(slots=True)
class DefaultArgumentTypeState:
    """Task-local concrete substitutions active while lowering one default."""

    identity: TypeIdentity
    _state: ContextVar[Mapping[str, TypeExpr] | None] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._state = ContextVar(
            f"btrc_default_argument_types_{id(self)}",
            default=None,
        )

    @contextmanager
    def scope(self, substitutions: Mapping[str, TypeExpr] | None) -> Iterator[None]:
        active = self._state.get()
        if substitutions:
            active = MappingProxyType(dict(substitutions))
        token = self._state.set(active)
        try:
            yield
        finally:
            self._state.reset(token)

    def resolve(self, type_expr: TypeExpr | None) -> TypeExpr | None:
        substitutions = self._state.get()
        if not substitutions or type_expr is None:
            return type_expr
        return self.identity.substitute(type_expr, substitutions)


class FunctionPointerTypedefRegistry:
    """Own ordered callback declarations for one C translation unit."""

    def __init__(self, type_identity: TypeIdentity) -> None:
        self._type_identity = type_identity
        self._definitions: dict[str, _FnPtrSignature] = {}
        self._emitted: set[str] = set()

    def register(self, type_expr: TypeExpr, *, return_type: str, parameter_types: list[str]) -> str:
        name = self._type_identity.function_pointer_symbol(type_expr.generic_args)
        self._definitions.setdefault(name, (return_type, tuple(parameter_types)))
        return name

    def consume_pending(self) -> list[IRFunctionPointerTypedef]:
        pending = [
            IRFunctionPointerTypedef(
                name=name,
                return_type=CType(text=return_type),
                param_types=[CType(text=parameter) for parameter in parameters],
            )
            for name, (return_type, parameters) in self._definitions.items()
            if name not in self._emitted
        ]
        self._emitted.update(self._definitions)
        return pending


class CTypeLowerer:
    """Own types lowering for one run."""

    def __init__(
        self,
        session: LoweringSession,
        analyzed: AnalyzedProgram,
        type_identity: TypeIdentity | None = None,
        default_type_state: DefaultArgumentTypeState | None = None,
    ) -> None:
        self._session = session
        self._analyzed = analyzed
        self._identity = type_identity if type_identity is not None else TypeIdentity()
        self._default_type_state = default_type_state
        self._typedefs = MappingProxyType(dict(analyzed.typedef_table))
        self._operator_types = OperatorSemantics(
            self._identity,
            class_table=analyzed.class_table,
            interface_table=analyzed.interface_table,
            enum_names=analyzed.enum_table,
        )
        self._function_pointers = FunctionPointerTypedefRegistry(self._identity)

    def substitute_concrete_type(
        self, type_expr: TypeExpr | None, substitutions: dict[str, TypeExpr]
    ) -> TypeExpr | None:
        """Substitute generics while resolving typedefs only for shape."""
        return self._identity.substitute(
            type_expr,
            substitutions,
            reference_resolver=self.canonical_type,
        )

    def render(self, type_expr: TypeExpr | None) -> str:
        """Convert one btrc type to its source-preserving C spelling."""
        type_expr = self.resolve_active_type(type_expr)
        if type_expr is None:
            return "void"

        base = type_expr.base
        prefix = "const " if getattr(type_expr, "is_const", False) else ""
        if base == "__fn_ptr" and type_expr.generic_args:
            c_type = self._function_pointer_name(type_expr)
        elif base == "Atomic" and len(type_expr.generic_args) == 1:
            self._session.require_runtime_header("stdatomic.h")
            c_type = f"_Atomic({self.render(type_expr.generic_args[0])})"
        elif base == "MemoryOrder" and not type_expr.generic_args:
            self._session.require_runtime_header("stdatomic.h")
            c_type = "memory_order"
        elif base == "Span" and len(type_expr.generic_args) == 1:
            c_type = self._identity.generic_symbol("Span", type_expr.generic_args)
        elif base in _RUNTIME_GENERIC_TYPES and type_expr.generic_args:
            c_type, provider = _RUNTIME_GENERIC_TYPES[base]
            self._session.require_helper(provider)
        elif base in _PRIMITIVE_MAP and (not type_expr.generic_args):
            c_type = _PRIMITIVE_MAP[base]
        elif base == "Tuple" or base.startswith("("):
            c_type = (
                self._identity.generic_symbol("Tuple", type_expr.generic_args)
                if type_expr.generic_args
                else "btrc_Tuple"
            )
        elif type_expr.generic_args:
            self._identity.ensure_supported_generic_arguments(type_expr.generic_args)
            c_type = self._identity.generic_symbol(base, type_expr.generic_args)
        else:
            c_type = base
        depth = type_expr.pointer_depth
        base_is_reference = c_type.endswith("*") or base == "__fn_ptr" or self._typedef_base_is_reference(base)
        if TypeSystem.nullable_collapses_reference_layer(type_expr, base_is_reference=base_is_reference):
            depth -= 1
        c_type += "*" * depth
        if type_expr.is_array:
            c_type += "*"
        return prefix + c_type

    def resolve_active_type(self, type_expr: TypeExpr | None) -> TypeExpr | None:
        """Apply every active lowering substitution to one semantic type."""
        specialization = self._session.active_specialization
        if specialization is not None:
            type_expr = specialization.substitution.resolve(type_expr)
        if self._default_type_state is not None:
            type_expr = self._default_type_state.resolve(type_expr)
        return type_expr

    def element_type(self, type_expr: TypeExpr) -> str:
        """Render a collection's element C type."""
        if type_expr.generic_args:
            return self.render(type_expr.generic_args[0])
        return "void*"

    def format_spec(self, type_expr: TypeExpr | None) -> str:
        """Return the portable printf format for one source type."""
        if type_expr is None:
            return "%d"
        base = type_expr.base
        if base == "__fn_ptr":
            return "%s"
        if self._identity.is_scalar_string(type_expr) or self._identity.is_c_string_pointer(type_expr):
            return "%s"
        if self.render(type_expr).rstrip().endswith("*") or type_expr.is_array:
            return "%p"
        if base in ("int", "short", "short int", "signed int", "signed short", "signed short int"):
            return "%d"
        if base in ("byte", "uint", "unsigned int", "unsigned short", "unsigned short int", "unsigned char"):
            return "%u"
        if base in ("long", "long int", "signed long", "signed long int"):
            return "%ld"
        if base in ("unsigned long", "unsigned long int"):
            return "%lu"
        if base in ("long long", "long long int", "signed long long", "signed long long int"):
            return "%lld"
        if base in ("unsigned long long", "unsigned long long int"):
            return "%llu"
        if base == "size_t":
            return "%zu"
        if base in ("float", "double"):
            return "%f"
        if base == "long double":
            return "%Lf"
        if base == "char":
            return "%c"
        if base == "bool":
            return "%s"
        return "%d"

    def consume_function_pointer_typedefs(self) -> list[IRFunctionPointerTypedef]:
        """Drain callback declarations registered since the previous phase."""
        return self._function_pointers.consume_pending()

    def _function_pointer_name(self, type_expr: TypeExpr) -> str:
        return_type = self.render(type_expr.generic_args[0])
        parameter_types = [self.render(argument) for argument in type_expr.generic_args[1:]]
        return self._function_pointers.register(type_expr, return_type=return_type, parameter_types=parameter_types)

    def _typedef_base_is_reference(self, base: str) -> bool:
        if base not in self._typedefs:
            return False
        resolved = self.canonical_type(TypeExpr(base=base))
        return bool(resolved and TypeSystem.resolved_reference_shape(resolved))

    @staticmethod
    def format_c_integer_literal(raw: str | None, value: int) -> str:
        """Return a strict-C11 spelling for one parsed integer literal.

        Binary literals are a btrc source feature, not a C11 feature.  Hexadecimal
        is the equivalent C11 spelling that retains the non-decimal integer-type
        selection rules.  Integer suffix spelling is preserved verbatim.
        """
        if not raw:
            return str(value)
        body_end = len(raw)
        while body_end and raw[body_end - 1] in "uUlL":
            body_end -= 1
        body = raw[:body_end]
        suffix = raw[body_end:]
        if body.startswith(("0b", "0B")):
            return f"0x{int(body[2:], 2):x}{suffix}"
        if body.startswith(("0o", "0O")):
            return f"0{body[2:]}{suffix}"
        return raw

    def optional_zero_value(self, type_expr):
        """Return the strict-C zero/null value for an analyzed expression type."""
        canonical = self.canonical_type(type_expr)
        if canonical is None:
            return IRLiteral(text="0")
        if canonical.base == "void":
            return IRCast(target_type=CType(text="void"), expr=IRLiteral(text="0"))
        c_type = self.render(type_expr)
        if (
            canonical.pointer_depth > 0
            or canonical.is_array
            or canonical.base == "string"
            or (canonical.base in self._analyzed.class_table)
            or c_type.endswith("*")
        ):
            return IRLiteral(text="NULL")
        if (
            canonical.base == "Tuple"
            or canonical.base.removeprefix("struct ") in self._analyzed.struct_table
            or canonical.base in self._analyzed.rich_enum_table
        ):
            return IRCompoundLiteral(c_type=CType(text=c_type), fields=[])
        return IRLiteral(text="0")

    def has_to_string(self, source_type) -> bool:
        source_type = self.canonical_type(source_type)
        if (
            source_type is None
            or source_type.base not in self._analyzed.class_table
            or source_type.pointer_depth != 1
            or source_type.is_array
        ):
            return False
        method = self._analyzed.class_table[source_type.base].methods.get("toString")
        return_type = self.canonical_type(method.return_type if method is not None else None)
        return bool(method and not method.params and self._identity.is_scalar_string(return_type))

    def to_string_call(self, source_type, value: IRExpr) -> IRExpr:
        cls = self._analyzed.class_table[source_type.base]
        if source_type.generic_args and cls.generic_params:
            prefix = self._identity.specialization_symbol(source_type.base, source_type.generic_args)
        else:
            prefix = source_type.base
        return IRCall(callee=f"{prefix}_toString", args=[value])

    def canonical_type(
        self,
        type_expr: TypeExpr | None,
    ) -> TypeExpr | None:
        """Resolve typedef aliases while composing every use-site modifier."""
        return self._resolve_typedef(self.resolve_active_type(type_expr), frozenset())

    def concrete_value_compatible(
        self,
        target_type: TypeExpr | None,
        source_type: TypeExpr | None,
    ) -> bool:
        """Whether one fully specialized value has a portable implicit C conversion."""
        target = self.canonical_type(target_type)
        source = self.canonical_type(source_type)
        if target is None or source is None:
            return False
        if self.render(target) == self.render(source):
            return True
        if TypeSystem.is_numeric_type(target, self._analyzed.enum_table) and TypeSystem.is_numeric_type(
            source,
            self._analyzed.enum_table,
        ):
            return True

        classes = self._analyzed.class_table
        interfaces = self._analyzed.interface_table
        target_is_reference = self._identity.is_reference(target, classes, interfaces)
        source_is_reference = self._identity.is_reference(source, classes, interfaces)
        if source_is_reference and target_is_reference and source.is_const and (not target.is_const):
            return False
        if not self._identity.references_compatible(target, source, classes, interfaces):
            return False

        nominal_types = {*classes, *interfaces}
        if target.base in nominal_types and source.base in nominal_types:
            return self._identity.specialization_is_subtype(source, target, classes, interfaces)
        return True

    def _resolve_typedef(
        self,
        type_expr: TypeExpr | None,
        seen: frozenset[str],
    ) -> TypeExpr | None:
        if type_expr is None or type_expr.base not in self._typedefs or type_expr.base in seen:
            return type_expr
        resolved = self._resolve_typedef(self._typedefs[type_expr.base], seen | {type_expr.base})
        assert resolved is not None
        return TypeSystem.compose_type_expr(type_expr, resolved, reference_shape=resolved)

    def function_pointer_signature(self, type_expr):
        """Return ``(return, params...)`` only for a directly callable value."""
        resolved = self.canonical_type(type_expr)
        if (
            resolved is None
            or resolved.base != "__fn_ptr"
            or resolved.pointer_depth != 0
            or resolved.is_array
            or (not resolved.generic_args)
        ):
            return None
        return resolved.generic_args

    def lower_numeric_operation(
        self, operator: str, left: IRExpr, right: IRExpr, left_type: TypeExpr | None, right_type: TypeExpr | None
    ) -> IRExpr:
        result_type = TypeSystem.numeric_result_type(left_type, right_type, self._analyzed.enum_table)
        if result_type is None:
            raise TypedOperatorError(f"cannot resolve numeric result type for operator '{operator}'")
        target = CType(text=self.render(result_type))
        if (
            left_type is not None
            and right_type is not None
            and (not TypeSystem.numeric_operands_need_cast(left_type, right_type, self._analyzed.enum_table))
        ):
            return IRBinOp(left=left, op=operator, right=right)
        return IRBinOp(
            left=IRCast(target_type=target, expr=left), op=operator, right=IRCast(target_type=target, expr=right)
        )

    def lower_numeric_comparison(
        self, operator: str, left: IRExpr, right: IRExpr, left_type: TypeExpr | None, right_type: TypeExpr | None
    ) -> IRExpr:
        """Compare mixed numeric types in their explicit language-level domain."""
        result_type = TypeSystem.numeric_result_type(left_type, right_type, self._analyzed.enum_table)
        if result_type is None:
            raise TypedOperatorError(f"cannot resolve numeric result type for operator '{operator}'")
        if left_type is not None and right_type is not None and (left_type.base == right_type.base):
            return IRBinOp(left=left, op=operator, right=right)
        target = CType(text=self.render(result_type))
        return IRBinOp(
            left=IRCast(target_type=target, expr=left), op=operator, right=IRCast(target_type=target, expr=right)
        )

    def lower_checked_divmod(
        self, operator: str, left: IRExpr, right: IRExpr, left_type: TypeExpr | None, right_type: TypeExpr | None
    ) -> IRExpr:
        if not (
            TypeSystem.is_numeric_type(left_type, self._analyzed.enum_table)
            and TypeSystem.is_numeric_type(right_type, self._analyzed.enum_table)
        ):
            raise TypedOperatorError(f"operator '{operator}' requires numeric operands")
        result_type = TypeSystem.numeric_result_type(left_type, right_type, self._analyzed.enum_table)
        if result_type is None:
            raise TypedOperatorError("cannot resolve divmod result type")
        target = CType(text=self.render(result_type))
        helper = "__btrc_mod" if operator == "%" else "__btrc_div"
        self._session.require_helper(helper)
        call = IRCall(
            callee=helper,
            args=[IRCast(target_type=target, expr=left), IRCast(target_type=target, expr=right)],
            helper_ref=helper,
        )
        return IRCast(target_type=target, expr=call)

    def lower_typed_ternary(
        self,
        condition: IRExpr,
        true_expr: IRExpr,
        false_expr: IRExpr,
        true_type: TypeExpr | None,
        false_type: TypeExpr | None,
    ) -> IRExpr:
        true_type = self.canonical_type(true_type)
        false_type = self.canonical_type(false_type)
        result_type = TypeSystem.numeric_result_type(true_type, false_type, self._analyzed.enum_table)
        if (
            result_type is not None
            and true_type is not None
            and (false_type is not None)
            and TypeSystem.numeric_operands_need_cast(true_type, false_type, self._analyzed.enum_table)
        ):
            target = CType(text=self.render(result_type))
            true_expr = IRCast(target_type=target, expr=true_expr)
            false_expr = IRCast(target_type=target, expr=false_expr)
        return IRTernary(condition=condition, true_expr=true_expr, false_expr=false_expr)

    def lower_typed_binary(
        self,
        operator: str,
        left: IRExpr,
        right: IRExpr,
        left_type: TypeExpr | None,
        right_type: TypeExpr | None,
        *,
        allow_unresolved_c_operands: bool = False,
        left_is_optional_value: bool = False,
    ) -> IRExpr | None:
        """Lower an operation owned by the shared portable type contract."""
        left_type = self.canonical_type(left_type)
        right_type = self.canonical_type(right_type)
        if allow_unresolved_c_operands and (left_type is None or right_type is None):
            return IRBinOp(left=left, op=operator, right=right)
        if (
            operator == "+"
            and (self._identity.is_scalar_string(left_type) or self._identity.is_c_string_pointer(left_type))
            and (self._identity.is_scalar_string(right_type) or self._identity.is_c_string_pointer(right_type))
            and (self._identity.is_scalar_string(left_type) or self._identity.is_scalar_string(right_type))
        ):
            self._session.require_helper("__btrc_strcat")
            self._session.require_helper("__btrc_str_track")
            joined = IRCall(callee="__btrc_strcat", args=[left, right], helper_ref="__btrc_strcat")
            return IRCall(callee="__btrc_str_track", args=[joined], helper_ref="__btrc_str_track")
        if operator in {"==", "!=", "<", ">", "<=", ">="}:
            return self.lower_typed_comparison(operator, left, right, left_type, right_type)
        if (
            operator in {"+", "-", "*", "&", "|", "^"}
            and TypeSystem.is_numeric_type(left_type, self._analyzed.enum_table)
            and TypeSystem.is_numeric_type(right_type, self._analyzed.enum_table)
        ):
            return self.lower_numeric_operation(operator, left, right, left_type, right_type)
        if operator in {"/", "%"}:
            return self.lower_checked_divmod(operator, left, right, left_type, right_type)
        if operator == "??":
            return self._lower_null_coalesce(
                left, right, left_type, right_type, left_is_optional_value=left_is_optional_value
            )
        return None

    def lower_typed_comparison(
        self, operator: str, left: IRExpr, right: IRExpr, left_type: TypeExpr | None, right_type: TypeExpr | None
    ) -> IRExpr:
        left_type = self.canonical_type(left_type)
        right_type = self.canonical_type(right_type)
        try:
            domain = self._operator_types.comparison_domain(operator, left_type, right_type)
        except OperatorTypeError as error:
            raise TypedOperatorError(str(error)) from error
        if domain == "string":
            return self._lower_string_comparison(operator, left, right)
        if domain == "reference":
            return self._lower_reference_equality(operator, left, right, left_type, right_type)
        return self.lower_numeric_comparison(operator, left, right, left_type, right_type)

    def lower_generic_intrinsic(
        self,
        name: str,
        operands: list[IRExpr],
        operand_types: list[TypeExpr | None],
    ) -> IRExpr | None:
        """Lower one compiler-owned generic operation through concrete type policy."""
        if name not in GENERIC_INTRINSICS:
            return None
        expected = 1 if name == "__btrc_hash" else 2
        if len(operands) != expected:
            raise CodegenError(f"{name} expects {expected} operand(s), got {len(operands)}")
        if len(operand_types) != expected or any(type_expr is None for type_expr in operand_types):
            raise CodegenError(f"cannot resolve all operand types for {name}")
        if name in GENERIC_COMPARISON_INTRINSICS:
            return self.lower_typed_comparison(
                GENERIC_COMPARISON_INTRINSICS[name],
                operands[0],
                operands[1],
                operand_types[0],
                operand_types[1],
            )
        return self.lower_typed_hash(operands[0], operand_types[0])

    def lower_typed_hash(self, operand: IRExpr, operand_type: TypeExpr | None) -> IRExpr:
        """Lower portable hashing for one concrete analyzed operand type."""
        operand_type = self.canonical_type(operand_type)
        try:
            domain = self._operator_types.hash_domain(operand_type)
        except OperatorTypeError as error:
            raise TypedOperatorError(str(error)) from error
        if domain == "string":
            helper = "__btrc_hash_str"
            self._session.require_helper(helper)
            return IRCall(callee=helper, args=[operand], helper_ref=helper)
        if domain == "integral":
            return IRCast(target_type=CType(text="unsigned int"), expr=operand)
        if domain == "floating":
            helper = "__btrc_hash_real"
            self._session.require_helper(helper)
            return IRCall(callee=helper, args=[operand], helper_ref=helper)
        return IRCast(
            target_type=CType(text="unsigned int"),
            expr=IRCast(target_type=CType(text="uintptr_t"), expr=operand),
        )

    def _lower_string_comparison(self, operator: str, left: IRExpr, right: IRExpr) -> IRExpr:
        left_name = self._session.fresh_temp("__btrc_cmp_left")
        right_name = self._session.fresh_temp("__btrc_cmp_right")
        left_var = IRVar(name=left_name)
        right_var = IRVar(name=right_name)
        zero = IRLiteral(text="0")
        null = IRLiteral(text="NULL")
        compare_value = IRTernary(
            condition=IRBinOp(left=left_var, op="==", right=right_var),
            true_expr=zero,
            false_expr=IRTernary(
                condition=IRBinOp(left=left_var, op="==", right=null),
                true_expr=IRLiteral(text="-1"),
                false_expr=IRTernary(
                    condition=IRBinOp(left=right_var, op="==", right=null),
                    true_expr=IRLiteral(text="1"),
                    false_expr=IRCall(callee="strcmp", args=[left_var, right_var]),
                ),
            ),
        )
        return IRStmtExpr(
            stmts=[
                IRVarDecl(c_type=CType(text="const char*"), name=left_name),
                IRVarDecl(c_type=CType(text="const char*"), name=right_name),
            ],
            result=IRCommaExpr(
                expressions=[
                    IRBinOp(left=left_var, op="=", right=left),
                    IRBinOp(left=right_var, op="=", right=right),
                    IRBinOp(left=compare_value, op=operator, right=zero),
                ]
            ),
        )

    def _lower_reference_equality(
        self, operator: str, left: IRExpr, right: IRExpr, left_type: TypeExpr | None, right_type: TypeExpr | None
    ) -> IRExpr:
        identity = self._identity
        if identity.is_null(left_type) or identity.is_null(right_type):
            function_type = next(
                (item for item in (left_type, right_type) if item is not None and item.base == "__fn_ptr"), None
            )
            if function_type is not None:
                null_value = IRCast(target_type=CType(text=self.render(function_type)), expr=IRLiteral(text="0"))
                if identity.is_null(left_type):
                    left = null_value
                else:
                    right = null_value
            return IRBinOp(left=left, op=operator, right=right)
        if left_type and right_type and (left_type.base == right_type.base == "__fn_ptr"):
            left_name = self._session.fresh_temp("__btrc_fn_left")
            right_name = self._session.fresh_temp("__btrc_fn_right")
            left_var = IRVar(name=left_name)
            right_var = IRVar(name=right_name)
            pointer_type = CType(text=self.render(left_type))
            return IRStmtExpr(
                stmts=[IRVarDecl(c_type=pointer_type, name=left_name), IRVarDecl(c_type=pointer_type, name=right_name)],
                result=IRCommaExpr(
                    expressions=[
                        IRBinOp(left=left_var, op="=", right=left),
                        IRBinOp(left=right_var, op="=", right=right),
                        IRBinOp(left=left_var, op=operator, right=right_var),
                    ]
                ),
            )
        void_ptr = CType(text="const void*")
        return IRBinOp(
            left=IRCast(target_type=void_ptr, expr=left), op=operator, right=IRCast(target_type=void_ptr, expr=right)
        )

    def _lower_null_coalesce(
        self,
        left: IRExpr,
        right: IRExpr,
        left_type: TypeExpr | None,
        right_type: TypeExpr | None,
        *,
        left_is_optional_value: bool,
    ) -> IRExpr:
        try:
            domain = self._operator_types.coalesce_domain(
                left_type, right_type, left_is_optional_value=left_is_optional_value
            )
        except OperatorTypeError as error:
            raise TypedOperatorError(str(error)) from error
        if domain == "optional_value":
            optional = CTypeLowerer.replace_optional_fallback(left, right)
            if optional is None:
                raise TypedOperatorError("optional-chain coalescing requires structured ternary IR")
            return optional
        result_type = right_type if self._identity.is_null(left_type) else left_type
        if result_type is None:
            raise TypedOperatorError("cannot resolve null-coalescing result type")
        temp_name = self._session.fresh_temp("__nc")
        temp = IRVar(name=temp_name)
        return IRStmtExpr(
            stmts=[IRVarDecl(c_type=CType(text=self.render(result_type)), name=temp_name)],
            result=IRCommaExpr(
                expressions=[
                    IRBinOp(left=temp, op="=", right=left),
                    IRTernary(
                        condition=IRBinOp(left=temp, op="!=", right=IRLiteral(text="NULL")),
                        true_expr=temp,
                        false_expr=right,
                    ),
                ]
            ),
        )

    @staticmethod
    def replace_optional_fallback(left: IRExpr, fallback: IRExpr) -> IRExpr | None:
        """Fuse ``??`` into an optional chain's value-producing IR path."""
        return CTypeLowerer._replace_value_fallback(left, fallback)

    @staticmethod
    def _replace_value_fallback(expr: IRExpr, fallback: IRExpr) -> IRExpr | None:
        if isinstance(expr, IRTernary):
            return replace(expr, false_expr=fallback)
        if isinstance(expr, IRStmtExpr):
            result = CTypeLowerer._replace_value_fallback(expr.result, fallback)
            return replace(expr, result=result) if result is not None else None
        if isinstance(expr, IRCommaExpr) and expr.expressions:
            expressions = list(expr.expressions)
            rewritten = CTypeLowerer._replace_value_fallback(expressions[-1], fallback)
            if rewritten is not None:
                expressions[-1] = rewritten
                return replace(expr, expressions=expressions)
            result_name = CTypeLowerer._result_var_name(expressions[-1])
            if result_name is None:
                return None
            for index in range(len(expressions) - 2, -1, -1):
                definition = expressions[index]
                if not CTypeLowerer._assigns_var(definition, result_name):
                    continue
                rewritten = CTypeLowerer._replace_value_fallback(definition.right, fallback)
                if rewritten is None:
                    return None
                expressions[index] = replace(definition, right=rewritten)
                return replace(expr, expressions=expressions)
            return None
        if isinstance(expr, IRBinOp) and expr.op == "=":
            right = CTypeLowerer._replace_value_fallback(expr.right, fallback)
            return replace(expr, right=right) if right is not None else None
        if isinstance(expr, IRCast):
            inner = CTypeLowerer._replace_value_fallback(expr.expr, fallback)
            return replace(expr, expr=inner) if inner is not None else None
        return None

    @staticmethod
    def _result_var_name(expr: IRExpr) -> str | None:
        return expr.name if isinstance(expr, IRVar) else None

    @staticmethod
    def _assigns_var(expr: IRExpr, name: str) -> bool:
        return bool(
            isinstance(expr, IRBinOp) and expr.op == "=" and isinstance(expr.left, IRVar) and expr.left.name == name
        )

    @staticmethod
    def is_numeric_type(t: TypeExpr | None) -> bool:
        """Check if a type is numeric."""
        if t is None:
            return False
        return t.base in {"int", "float", "double", "long", "short", "byte", "uint"}

    def is_generic_class_type(self, t: TypeExpr | None) -> bool:
        """Check if a type is a generic class (registered with generic_params)."""
        if t is None or not t.generic_args:
            return False
        info = self._analyzed.class_table.get(t.base)
        return info is not None and bool(info.generic_params)

    def is_direct_generic_instance_reference(self, t: TypeExpr | None) -> bool:
        """Whether ``t`` is one generic heap reference, not storage around it."""
        if not self.is_generic_class_type(t) or t.is_array:
            return False
        depth = t.pointer_depth - int(TypeSystem.nullable_collapses_reference_layer(t))
        return depth <= 1

    def is_subclass(self, sub: str | None, base: str | None) -> bool:
        """True if `base` is a (transitive) parent class of `sub`."""
        if not sub or not base:
            return False
        ct = self._analyzed.class_table
        seen: set[str] = set()
        cur = sub
        while cur and cur not in seen:
            if cur == base:
                return True
            seen.add(cur)
            info = ct.get(cur)
            cur = info.parent if info else None
        return False

    def upcast_class_pointer(
        self,
        target_type: TypeExpr | None,
        source_type: TypeExpr | None,
        value: IRExpr,
    ) -> IRExpr:
        """Wrap `value` in an explicit ``(Base*)`` cast for a Derived→Base upcast.

        Returns `value` unchanged unless ALL of the following hold:
          - `target_type` is a concrete class in the class table with NO generic args
            (a sibling/derived struct pointer is otherwise incompatible C);
          - `source_type` names a DIFFERENT class that is a strict subclass of
            `target_type.base`.

        Generic class targets are skipped: all instances of a generic share one
        mangled struct, so no upcast is needed (and the cast text would be wrong).
        """
        if target_type is None or source_type is None:
            return value
        ct = self._analyzed.class_table
        if target_type.base not in ct or target_type.generic_args:
            return value
        if source_type.base == target_type.base:
            return value
        if not self.is_subclass(source_type.base, target_type.base):
            return value
        return IRCast(target_type=CType(text=self.render(target_type)), expr=value)

    def box_exact_value(self, expr, type_expr: TypeExpr | None, *, prefix: str):
        """Evaluate ``expr`` once and copy its exact C representation to a box."""
        canonical = self.canonical_value_type(type_expr)
        if canonical is None or CTypeLowerer.is_scalar_void(canonical):
            return IRLiteral(text="NULL")
        self._session.require_helper("__btrc_safe_realloc")
        storage_c = self.value_storage_c_type(canonical)
        box_name = self._session.fresh_temp(f"{prefix}_box")
        value_name = self._session.fresh_temp(f"{prefix}_value")
        box = IRVar(name=box_name)
        value = IRVar(name=value_name)
        return IRStmtExpr(
            stmts=[
                IRVarDecl(c_type=CType(text=f"{storage_c}*"), name=box_name),
                IRVarDecl(c_type=CType(text=storage_c), name=value_name),
            ],
            result=IRCommaExpr(
                expressions=[
                    IRBinOp(left=value, op="=", right=expr),
                    IRBinOp(
                        left=box,
                        op="=",
                        right=IRCast(
                            target_type=CType(text=f"{storage_c}*"),
                            expr=IRCall(
                                callee="__btrc_safe_realloc",
                                args=[IRLiteral(text="NULL"), IRSizeof(operand=IRDeref(expr=box))],
                                helper_ref="__btrc_safe_realloc",
                            ),
                        ),
                    ),
                    IRBinOp(left=IRDeref(expr=box), op="=", right=value),
                    IRCast(target_type=CType(text="void*"), expr=box),
                ]
            ),
        )

    def unbox_exact_value(self, payload_call, type_expr: TypeExpr | None, *, prefix: str):
        """Copy a boxed value, free its transport, and yield the typed copy."""
        canonical = self.canonical_value_type(type_expr)
        if canonical is None or CTypeLowerer.is_scalar_void(canonical):
            return payload_call
        storage_c = self.value_storage_c_type(canonical)
        payload_name = self._session.fresh_temp(f"{prefix}_payload")
        value_name = self._session.fresh_temp(f"{prefix}_value")
        payload = IRVar(name=payload_name)
        value = IRVar(name=value_name)
        return IRStmtExpr(
            stmts=[
                IRVarDecl(c_type=CType(text="void*"), name=payload_name),
                IRVarDecl(c_type=CType(text=storage_c), name=value_name),
            ],
            result=IRCommaExpr(
                expressions=[
                    IRBinOp(left=payload, op="=", right=payload_call),
                    IRBinOp(
                        left=value,
                        op="=",
                        right=IRDeref(expr=IRCast(target_type=CType(text=f"{storage_c}*"), expr=payload)),
                    ),
                    IRCall(callee="free", args=[payload]),
                    value,
                ]
            ),
        )

    def canonical_value_type(self, type_expr: TypeExpr | None) -> TypeExpr | None:
        """Resolve typedefs while preserving use-site pointer and qualifiers."""
        return self.canonical_type(type_expr)

    def value_storage_c_type(self, type_expr: TypeExpr) -> str:
        """Return one assignable local-storage spelling for ``type_expr``."""
        return self.render(replace(type_expr, is_const=False, is_static=False, is_extern=False, is_volatile=False))

    @staticmethod
    def is_scalar_void(type_expr: TypeExpr) -> bool:
        return type_expr.base == "void" and type_expr.pointer_depth == 0
