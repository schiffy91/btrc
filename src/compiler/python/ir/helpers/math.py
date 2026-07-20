"""Math runtime helpers -- Math stdlib helpers."""

from .core import HelperDef

MATH = {
    "__btrc_math_factorial": HelperDef(
        c_source=(
            "static inline long long __btrc_math_factorial(int n) {\n"
            '    if (n < 0) { fprintf(stderr, "btrc: factorial of negative number\\n"); exit(1); }\n'
            '    if (n > 20) { fprintf(stderr, "btrc: factorial overflow (n=%d)\\n", n); exit(1); }\n'
            "    long long r = 1;\n"
            "    for (int i = 2; i <= n; i++) r *= i;\n"
            "    return r;\n"
            "}"
        ),
    ),
    "__btrc_math_gcd": HelperDef(
        c_source=(
            "static inline int __btrc_math_gcd(int a, int b) {\n"
            "    unsigned int ua = a < 0 ? 0u - (unsigned int)a : (unsigned int)a;\n"
            "    unsigned int ub = b < 0 ? 0u - (unsigned int)b : (unsigned int)b;\n"
            "    while (ub) { unsigned int t = ub; ub = ua % ub; ua = t; }\n"
            '    if (ua > INT_MAX) { fprintf(stderr, "btrc: gcd result overflow\\n"); exit(1); }\n'
            "    return (int)ua;\n"
            "}"
        ),
    ),
    "__btrc_math_lcm": HelperDef(
        c_source=(
            "static inline int __btrc_math_lcm(int a, int b) {\n"
            "    if (a == 0 || b == 0) return 0;\n"
            "    int g = __btrc_math_gcd(a, b);\n"
            "    long long result = ((long long)a / g) * (long long)b;\n"
            "    if (result < 0) result = -result;\n"
            '    if (result > INT_MAX) { fprintf(stderr, "btrc: lcm result overflow\\n"); exit(1); }\n'
            "    return (int)result;\n"
            "}"
        ),
        depends_on=["__btrc_math_gcd"],
    ),
    "__btrc_math_fibonacci": HelperDef(
        c_source=(
            "static inline int __btrc_math_fibonacci(int n) {\n"
            "    if (n <= 0) return 0;\n"
            "    if (n == 1) return 1;\n"
            '    if (n > 46) { fprintf(stderr, "btrc: fibonacci result overflow\\n"); exit(1); }\n'
            "    int a = 0, b = 1;\n"
            "    for (int i = 2; i <= n; i++) { int t = a + b; a = b; b = t; }\n"
            "    return b;\n"
            "}"
        ),
    ),
    "__btrc_math_isPrime": HelperDef(
        c_source=(
            "static inline bool __btrc_math_isPrime(int n) {\n"
            "    if (n < 2) return false;\n"
            "    if (n < 4) return true;\n"
            "    if (n % 2 == 0 || n % 3 == 0) return false;\n"
            "    for (int i = 5; i <= n / i; i += 6)\n"
            "        if (n % i == 0 || n % (i + 2) == 0) return false;\n"
            "    return true;\n"
            "}"
        ),
    ),
    "__btrc_math_sum_int": HelperDef(
        c_source=(
            "static inline int __btrc_math_sum_int(int* data, int size) {\n"
            "    if (size <= 0) return 0;\n"
            '    if (!data) { fprintf(stderr, "btrc: sum received null data\\n"); exit(1); }\n'
            "    long long sum = 0;\n"
            "    for (int i = 0; i < size; i++) sum += data[i];\n"
            '    if (sum < INT_MIN || sum > INT_MAX) { fprintf(stderr, "btrc: sum result overflow\\n"); exit(1); }\n'
            "    return (int)sum;\n"
            "}"
        ),
    ),
    "__btrc_math_fsum": HelperDef(
        c_source=(
            "static inline float __btrc_math_fsum(float* data, int size) {\n"
            "    if (size <= 0) return 0.0f;\n"
            '    if (!data) { fprintf(stderr, "btrc: fsum received null data\\n"); exit(1); }\n'
            "    float s = 0.0f;\n"
            "    for (int i = 0; i < size; i++) s += data[i];\n"
            "    return s;\n"
            "}"
        ),
    ),
}
