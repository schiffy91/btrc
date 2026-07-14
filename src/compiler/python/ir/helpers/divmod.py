"""Divmod runtime helpers -- division / modulo by-zero runtime checks (always emitted)."""

from .core import HelperDef

_GENERIC_DIV = r"""
static inline int __btrc_div_g_int(int a, int b) {
    if (b == 0) { fprintf(stderr, "Division by zero\n"); exit(1); }
    if (a == INT_MIN && b == -1) { fprintf(stderr, "Integer division overflow\n"); exit(1); }
    return a / b;
}
static inline unsigned int __btrc_div_g_uint(unsigned int a, unsigned int b) {
    if (b == 0U) { fprintf(stderr, "Division by zero\n"); exit(1); }
    return a / b;
}
static inline long __btrc_div_g_long(long a, long b) {
    if (b == 0L) { fprintf(stderr, "Division by zero\n"); exit(1); }
    if (a == LONG_MIN && b == -1L) { fprintf(stderr, "Integer division overflow\n"); exit(1); }
    return a / b;
}
static inline unsigned long __btrc_div_g_ulong(unsigned long a, unsigned long b) {
    if (b == 0UL) { fprintf(stderr, "Division by zero\n"); exit(1); }
    return a / b;
}
static inline long long __btrc_div_g_llong(long long a, long long b) {
    if (b == 0LL) { fprintf(stderr, "Division by zero\n"); exit(1); }
    if (a == LLONG_MIN && b == -1LL) { fprintf(stderr, "Integer division overflow\n"); exit(1); }
    return a / b;
}
static inline unsigned long long __btrc_div_g_ullong(unsigned long long a, unsigned long long b) {
    if (b == 0ULL) { fprintf(stderr, "Division by zero\n"); exit(1); }
    return a / b;
}
static inline float __btrc_div_g_float(float a, float b) {
    if (b == 0.0F) { fprintf(stderr, "Division by zero\n"); exit(1); }
    return a / b;
}
static inline double __btrc_div_g_double(double a, double b) {
    if (b == 0.0) { fprintf(stderr, "Division by zero\n"); exit(1); }
    return a / b;
}
static inline long double __btrc_div_g_ldouble(long double a, long double b) {
    if (b == 0.0L) { fprintf(stderr, "Division by zero\n"); exit(1); }
    return a / b;
}
#define __btrc_div(a, b) (_Generic(((a) + (b)), \
    int: __btrc_div_g_int, unsigned int: __btrc_div_g_uint, \
    long: __btrc_div_g_long, unsigned long: __btrc_div_g_ulong, \
    long long: __btrc_div_g_llong, unsigned long long: __btrc_div_g_ullong, \
    float: __btrc_div_g_float, double: __btrc_div_g_double, \
    long double: __btrc_div_g_ldouble)((a), (b)))
""".strip()

_GENERIC_MOD = r"""
static inline int __btrc_mod_g_int(int a, int b) {
    if (b == 0) { fprintf(stderr, "Modulo by zero\n"); exit(1); }
    if (a == INT_MIN && b == -1) return 0;
    return a % b;
}
static inline unsigned int __btrc_mod_g_uint(unsigned int a, unsigned int b) {
    if (b == 0U) { fprintf(stderr, "Modulo by zero\n"); exit(1); }
    return a % b;
}
static inline long __btrc_mod_g_long(long a, long b) {
    if (b == 0L) { fprintf(stderr, "Modulo by zero\n"); exit(1); }
    if (a == LONG_MIN && b == -1L) return 0L;
    return a % b;
}
static inline unsigned long __btrc_mod_g_ulong(unsigned long a, unsigned long b) {
    if (b == 0UL) { fprintf(stderr, "Modulo by zero\n"); exit(1); }
    return a % b;
}
static inline long long __btrc_mod_g_llong(long long a, long long b) {
    if (b == 0LL) { fprintf(stderr, "Modulo by zero\n"); exit(1); }
    if (a == LLONG_MIN && b == -1LL) return 0LL;
    return a % b;
}
static inline unsigned long long __btrc_mod_g_ullong(unsigned long long a, unsigned long long b) {
    if (b == 0ULL) { fprintf(stderr, "Modulo by zero\n"); exit(1); }
    return a % b;
}
static inline int __btrc_mod_g_real(long double a, long double b) {
    /* Converting a real to int is defined exactly when its truncated value is
       representable.  Reject NaN/infinity and the two open boundary regions
       before casting, without requiring hosted libm helpers. */
    const long double lower = (long double)INT_MIN - 1.0L;
    const long double upper = (long double)INT_MAX + 1.0L;
    if (a != a || b != b || a <= lower || a >= upper
            || b <= lower || b >= upper) {
        fprintf(stderr, "Floating modulo conversion out of range\n"); exit(1);
    }
    return __btrc_mod_g_int((int)a, (int)b);
}
#define __btrc_mod(a, b) (_Generic(((a) + (b)), \
    int: __btrc_mod_g_int, unsigned int: __btrc_mod_g_uint, \
    long: __btrc_mod_g_long, unsigned long: __btrc_mod_g_ulong, \
    long long: __btrc_mod_g_llong, unsigned long long: __btrc_mod_g_ullong, \
    float: __btrc_mod_g_real, double: __btrc_mod_g_real, \
    long double: __btrc_mod_g_real)((a), (b)))
""".strip()

DIVMOD = {
    "__btrc_div": HelperDef(c_source=_GENERIC_DIV),
    "__btrc_mod": HelperDef(c_source=_GENERIC_MOD),
    "__btrc_div_int": HelperDef(
        c_source=(
            "static inline int __btrc_div_int(int a, int b) {\n"
            '    if (b == 0) { fprintf(stderr, "Division by zero\\n"); exit(1); }\n'
            '    if (a == INT_MIN && b == -1) { fprintf(stderr, "Integer division overflow\\n"); exit(1); }\n'
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
            "    if (a == INT_MIN && b == -1) return 0;\n"
            "    return a % b;\n"
            "}"
        ),
    ),
}
