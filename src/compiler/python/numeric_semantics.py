"""Platform-independent numeric domains and canonical expression results."""

from collections.abc import Set

from .ast_nodes import TypeExpr

_FLOATING_BASES = frozenset(("float", "double", "long double"))
_INTEGRAL_KINDS = {
    "bool": (3, False),
    "byte": (3, False),
    "char": (3, False),
    "signed char": (3, False),
    "unsigned char": (3, False),
    "short": (3, False),
    "short int": (3, False),
    "signed short": (3, False),
    "signed short int": (3, False),
    "unsigned short": (3, False),
    "unsigned short int": (3, False),
    "int": (3, False),
    "signed": (3, False),
    "signed int": (3, False),
    "uint": (3, True),
    "unsigned": (3, True),
    "unsigned int": (3, True),
    "long": (4, False),
    "long int": (4, False),
    "signed long": (4, False),
    "signed long int": (4, False),
    "unsigned long": (4, True),
    "unsigned long int": (4, True),
    "long long": (5, False),
    "long long int": (5, False),
    "signed long long": (5, False),
    "signed long long int": (5, False),
    "unsigned long long": (5, True),
    "unsigned long long int": (5, True),
}
_STANDARD_INTEGER_TYPEDEFS = frozenset(
    (
        "int8_t",
        "uint8_t",
        "int16_t",
        "uint16_t",
        "int32_t",
        "uint32_t",
        "int64_t",
        "uint64_t",
        "int_least8_t",
        "uint_least8_t",
        "int_least16_t",
        "uint_least16_t",
        "int_least32_t",
        "uint_least32_t",
        "int_least64_t",
        "uint_least64_t",
        "int_fast8_t",
        "uint_fast8_t",
        "int_fast16_t",
        "uint_fast16_t",
        "int_fast32_t",
        "uint_fast32_t",
        "int_fast64_t",
        "uint_fast64_t",
        "intptr_t",
        "uintptr_t",
        "intmax_t",
        "uintmax_t",
        "ptrdiff_t",
        "size_t",
        "wchar_t",
        "wint_t",
        "sig_atomic_t",
        "ssize_t",
        "pid_t",
        "uid_t",
        "gid_t",
        "off_t",
        "mode_t",
        "dev_t",
        "ino_t",
        "nlink_t",
        "blksize_t",
        "blkcnt_t",
        "time_t",
        "clock_t",
        "suseconds_t",
        "useconds_t",
        "socklen_t",
    )
)
_PORTABLE_WIDTH_TYPEDEFS = frozenset(
    {
        "int8_t",
        "uint8_t",
        "int16_t",
        "uint16_t",
        "int32_t",
        "uint32_t",
        "int64_t",
        "uint64_t",
        "int_least8_t",
        "uint_least8_t",
        "int_least16_t",
        "uint_least16_t",
        "int_least32_t",
        "uint_least32_t",
        "int_least64_t",
        "uint_least64_t",
    }
)
_ABI_DEPENDENT_INTEGER_TYPEDEFS = _STANDARD_INTEGER_TYPEDEFS - _PORTABLE_WIDTH_TYPEDEFS
_UNSIGNED_TYPEDEFS = frozenset(
    (
        "uint8_t",
        "uint16_t",
        "uint32_t",
        "uint64_t",
        "uint_least8_t",
        "uint_least16_t",
        "uint_least32_t",
        "uint_least64_t",
        "uint_fast8_t",
        "uint_fast16_t",
        "uint_fast32_t",
        "uint_fast64_t",
        "uintptr_t",
        "uintmax_t",
        "size_t",
        "uid_t",
        "gid_t",
        "mode_t",
        "dev_t",
        "ino_t",
        "nlink_t",
        "useconds_t",
        "socklen_t",
    )
)
_RESULT_BASE = {
    (3, False): "int",
    (3, True): "uint",
    (4, False): "long",
    (4, True): "unsigned long",
    (5, False): "long long",
    (5, True): "unsigned long long",
}


def is_floating_type(type_expr: TypeExpr | None) -> bool:
    return bool(_is_scalar(type_expr) and type_expr.base in _FLOATING_BASES)


def is_numeric_type(
    type_expr: TypeExpr | None,
    enum_names: Set[str] = frozenset(),
) -> bool:
    if not _is_scalar(type_expr):
        return False
    assert type_expr is not None
    return (
        type_expr.base in _INTEGRAL_KINDS
        or type_expr.base in _FLOATING_BASES
        or type_expr.base in _STANDARD_INTEGER_TYPEDEFS
        or type_expr.base in enum_names
        or type_expr.base.startswith("enum ")
    )


def is_known_integer_typedef_name(name: str) -> bool:
    """Whether an undeclared C/POSIX typedef has a known integer contract."""
    return name in _STANDARD_INTEGER_TYPEDEFS


def integer_mix_is_portable(
    left: TypeExpr | None,
    right: TypeExpr | None,
) -> bool:
    """Whether integer conversions have one result on every supported ABI."""
    if left is None or right is None:
        return True
    if is_floating_type(left) or is_floating_type(right):
        return True
    if left.base == right.base:
        return True
    return not (left.base in _ABI_DEPENDENT_INTEGER_TYPEDEFS or right.base in _ABI_DEPENDENT_INTEGER_TYPEDEFS)


def numeric_result_type(
    left: TypeExpr | None,
    right: TypeExpr | None,
    enum_names: Set[str] = frozenset(),
) -> TypeExpr | None:
    """Return an operand-order-independent btrc arithmetic result type."""
    if not (is_numeric_type(left, enum_names) and is_numeric_type(right, enum_names)):
        return None
    assert left is not None and right is not None
    floating = [base for base in (left.base, right.base) if base in _FLOATING_BASES]
    if floating:
        rank = {"float": 1, "double": 2, "long double": 3}
        return TypeExpr(base=max(floating, key=rank.__getitem__))
    if not integer_mix_is_portable(left, right):
        return None
    if left.base == right.base and left.base in _STANDARD_INTEGER_TYPEDEFS:
        return TypeExpr(base=left.base)
    left_rank, left_unsigned = _integral_kind(left.base, enum_names)
    right_rank, right_unsigned = _integral_kind(right.base, enum_names)
    rank = max(left_rank, right_rank)
    unsigned = left_unsigned or right_unsigned
    return TypeExpr(base=_RESULT_BASE[(rank, unsigned)])


def numeric_operands_need_cast(
    left: TypeExpr,
    right: TypeExpr,
    enum_names: Set[str] = frozenset(),
) -> bool:
    """Whether host C usual conversions can differ from btrc's result rule."""
    if left.base == right.base:
        return False
    if not integer_mix_is_portable(left, right):
        return False
    if left.base in _STANDARD_INTEGER_TYPEDEFS or (right.base in _STANDARD_INTEGER_TYPEDEFS):
        return True
    if is_floating_type(left) or is_floating_type(right):
        return False
    left_rank, left_unsigned = _integral_kind(left.base, enum_names)
    right_rank, right_unsigned = _integral_kind(right.base, enum_names)
    if left_unsigned == right_unsigned:
        return False
    signed_rank = left_rank if not left_unsigned else right_rank
    unsigned_rank = left_rank if left_unsigned else right_rank
    return signed_rank > unsigned_rank


def _integral_kind(base: str, enum_names: Set[str]) -> tuple[int, bool]:
    if base in _INTEGRAL_KINDS:
        return _INTEGRAL_KINDS[base]
    if base in enum_names or base.startswith("enum "):
        return 3, False
    if base in _PORTABLE_WIDTH_TYPEDEFS:
        digits = next((item for item in (64, 32, 16, 8) if str(item) in base), 64)
        rank = 5 if digits >= 64 else 3
        return rank, base in _UNSIGNED_TYPEDEFS
    if base in _ABI_DEPENDENT_INTEGER_TYPEDEFS:
        raise ValueError(f"ABI-dependent integer typedef has no portable rank: {base}")
    raise ValueError(f"not an integral type: {base}")


def _is_scalar(type_expr: TypeExpr | None) -> bool:
    return bool(type_expr and type_expr.pointer_depth == 0 and not type_expr.is_array and not type_expr.generic_args)
