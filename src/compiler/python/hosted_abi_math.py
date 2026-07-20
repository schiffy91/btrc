"""Owned C11 ``math.h`` names and common exact scalar ABI specs."""

from .hosted_abi_model import DOUBLE, FLOAT, LDOUBLE, HostedFunction, uniform

_UNARY = (
    "acos acosh asin asinh atan atanh cbrt ceil cos cosh erf erfc exp exp2 "
    "expm1 fabs floor lgamma log log10 log1p log2 logb nearbyint rint round "
    "sin sinh sqrt tan tanh tgamma trunc"
)
_BINARY = "atan2 copysign fdim fmax fmin fmod hypot nextafter pow remainder"
_TERNARY = "fma"
_SPECIAL = "frexp ldexp modf scalbn scalbln ilogb lrint llrint lround llround nan nexttoward remquo"


def _families(names: str) -> set[str]:
    return {variant for name in names.split() for variant in (name, f"{name}f", f"{name}l")}


HOSTED_MATH_NAMES = frozenset(_families(f"{_UNARY} {_BINARY} {_TERNARY} {_SPECIAL}"))

HOSTED_MATH_FUNCTIONS: dict[str, HostedFunction] = {
    **uniform(_UNARY, DOUBLE, DOUBLE),
    **uniform(" ".join(f"{name}f" for name in _UNARY.split()), FLOAT, FLOAT),
    **uniform(" ".join(f"{name}l" for name in _UNARY.split()), LDOUBLE, LDOUBLE),
    **uniform(_BINARY, DOUBLE, DOUBLE, DOUBLE),
    **uniform(" ".join(f"{name}f" for name in _BINARY.split()), FLOAT, FLOAT, FLOAT),
    **uniform(" ".join(f"{name}l" for name in _BINARY.split()), LDOUBLE, LDOUBLE, LDOUBLE),
    **uniform(_TERNARY, DOUBLE, DOUBLE, DOUBLE, DOUBLE),
    **uniform("fmaf", FLOAT, FLOAT, FLOAT, FLOAT),
    **uniform("fmal", LDOUBLE, LDOUBLE, LDOUBLE, LDOUBLE),
}

__all__ = ["HOSTED_MATH_FUNCTIONS", "HOSTED_MATH_NAMES"]
