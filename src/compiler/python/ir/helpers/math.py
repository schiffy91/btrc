"""Math runtime helpers -- Math stdlib helpers."""

from .core import HelperDef

MATH = {
    "__btrc_math_factorial": HelperDef(
        c_source=(
            "static inline int __btrc_math_factorial(int n) {\n"
            "    int r = 1;\n"
            "    for (int i = 2; i <= n; i++) r *= i;\n"
            "    return r;\n"
            "}"
        ),
    ),
    "__btrc_math_gcd": HelperDef(
        c_source=(
            "static inline int __btrc_math_gcd(int a, int b) {\n"
            "    if (a < 0) a = -a;\n"
            "    if (b < 0) b = -b;\n"
            "    while (b) { int t = b; b = a % b; a = t; }\n"
            "    return a;\n"
            "}"
        ),
    ),
    "__btrc_math_lcm": HelperDef(
        c_source=(
            "static inline int __btrc_math_lcm(int a, int b) {\n"
            "    if (a == 0 || b == 0) return 0;\n"
            "    int g = __btrc_math_gcd(a, b);\n"
            "    return (a / g) * b;\n"
            "}"
        ),
        depends_on=["__btrc_math_gcd"],
    ),
    "__btrc_math_fibonacci": HelperDef(
        c_source=(
            "static inline int __btrc_math_fibonacci(int n) {\n"
            "    if (n <= 0) return 0;\n"
            "    if (n == 1) return 1;\n"
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
            "    for (int i = 5; i * i <= n; i += 6)\n"
            "        if (n % i == 0 || n % (i + 2) == 0) return false;\n"
            "    return true;\n"
            "}"
        ),
    ),
    "__btrc_math_sum_int": HelperDef(
        c_source=(
            "static inline int __btrc_math_sum_int(int* data, int size) {\n"
            "    int s = 0;\n"
            "    for (int i = 0; i < size; i++) s += data[i];\n"
            "    return s;\n"
            "}"
        ),
    ),
    "__btrc_math_fsum": HelperDef(
        c_source=(
            "static inline float __btrc_math_fsum(float* data, int size) {\n"
            "    float s = 0.0f;\n"
            "    for (int i = 0; i < size; i++) s += data[i];\n"
            "    return s;\n"
            "}"
        ),
    ),
}
