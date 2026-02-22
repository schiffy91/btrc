"""Divmod runtime helpers -- division / modulo by-zero runtime checks (always emitted)."""

from .core import HelperDef

DIVMOD = {
    "__btrc_div_int": HelperDef(
        c_source=(
            "static inline int __btrc_div_int(int a, int b) {\n"
            '    if (b == 0) { fprintf(stderr, "Division by zero\\n"); exit(1); }\n'
            "    return a / b;\n"
            "}"
        ),
    ),
    "__btrc_div_double": HelperDef(
        c_source=(
            "static inline double __btrc_div_double(double a, double b) {\n"
            '    if (b == 0.0) { fprintf(stderr, "Division by zero\\n"); exit(1); }\n'
            "    return a / b;\n"
            "}"
        ),
    ),
    "__btrc_mod_int": HelperDef(
        c_source=(
            "static inline int __btrc_mod_int(int a, int b) {\n"
            '    if (b == 0) { fprintf(stderr, "Modulo by zero\\n"); exit(1); }\n'
            "    return a % b;\n"
            "}"
        ),
    ),
}
