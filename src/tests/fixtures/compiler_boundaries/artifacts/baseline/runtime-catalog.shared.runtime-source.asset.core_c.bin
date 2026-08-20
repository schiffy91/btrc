/* btrc-runtime-helper:begin __btrc_strdup */
static inline char* __btrc_strdup(const char* s) {
    if (!s) return NULL;
    size_t len = strlen(s);
    if (len == SIZE_MAX) { fprintf(stderr, "btrc: strdup size overflow\n"); exit(1); }
    len++;
    char* copy = (char*)malloc(len);
    if (!copy) { fprintf(stderr, "btrc: out of memory (strdup %zu bytes)\n", len); exit(1); }
    memcpy(copy, s, len);
    return copy;
}
/* btrc-runtime-helper:end __btrc_strdup */
/* btrc-runtime-helper:begin __btrc_safe_realloc */
static inline void* __btrc_safe_realloc(void* ptr, size_t size) {
    if (size == 0) { free(ptr); return NULL; }
    void* result = realloc(ptr, size);
    if (!result) { fprintf(stderr, "btrc: out of memory (realloc %zu bytes)\n", size); exit(1); }
    return result;
}
/* btrc-runtime-helper:end __btrc_safe_realloc */
/* btrc-runtime-helper:begin __btrc_safe_calloc */
static inline void* __btrc_safe_calloc(size_t count, size_t size) {
    if (size != 0 && count > SIZE_MAX / size) { fprintf(stderr, "btrc: calloc size overflow\n"); exit(1); }
    void* result = calloc(count, size);
    if (!result && count != 0 && size != 0) { fprintf(stderr, "btrc: out of memory (calloc %zu bytes)\n", count * size); exit(1); }
    return result;
}
/* btrc-runtime-helper:end __btrc_safe_calloc */
/* btrc-runtime-helper:begin __btrc_div */
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
/* btrc-runtime-helper:end __btrc_div */
/* btrc-runtime-helper:begin __btrc_mod */
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
/* btrc-runtime-helper:end __btrc_mod */
/* btrc-runtime-helper:begin __btrc_div_int */
static inline int __btrc_div_int(int a, int b) {
    if (b == 0) { fprintf(stderr, "Division by zero\n"); exit(1); }
    if (a == INT_MIN && b == -1) { fprintf(stderr, "Integer division overflow\n"); exit(1); }
    return a / b;
}
/* btrc-runtime-helper:end __btrc_div_int */
/* btrc-runtime-helper:begin __btrc_div_double */
static inline double __btrc_div_double(double a, double b) {
    if (b == 0.0) { fprintf(stderr, "Division by zero\n"); exit(1); }
    return a / b;
}
/* btrc-runtime-helper:end __btrc_div_double */
/* btrc-runtime-helper:begin __btrc_mod_int */
static inline int __btrc_mod_int(int a, int b) {
    if (b == 0) { fprintf(stderr, "Modulo by zero\n"); exit(1); }
    if (a == INT_MIN && b == -1) return 0;
    return a % b;
}
/* btrc-runtime-helper:end __btrc_mod_int */
/* btrc-runtime-helper:begin __btrc_math_factorial */
static inline long long __btrc_math_factorial(int n) {
    if (n < 0) { fprintf(stderr, "btrc: factorial of negative number\n"); exit(1); }
    if (n > 20) { fprintf(stderr, "btrc: factorial overflow (n=%d)\n", n); exit(1); }
    long long r = 1;
    for (int i = 2; i <= n; i++) r *= i;
    return r;
}
/* btrc-runtime-helper:end __btrc_math_factorial */
/* btrc-runtime-helper:begin __btrc_math_gcd */
static inline int __btrc_math_gcd(int a, int b) {
    unsigned int ua = a < 0 ? 0u - (unsigned int)a : (unsigned int)a;
    unsigned int ub = b < 0 ? 0u - (unsigned int)b : (unsigned int)b;
    while (ub) { unsigned int t = ub; ub = ua % ub; ua = t; }
    if (ua > INT_MAX) { fprintf(stderr, "btrc: gcd result overflow\n"); exit(1); }
    return (int)ua;
}
/* btrc-runtime-helper:end __btrc_math_gcd */
/* btrc-runtime-helper:begin __btrc_math_lcm */
static inline int __btrc_math_lcm(int a, int b) {
    if (a == 0 || b == 0) return 0;
    int g = __btrc_math_gcd(a, b);
    long long result = ((long long)a / g) * (long long)b;
    if (result < 0) result = -result;
    if (result > INT_MAX) { fprintf(stderr, "btrc: lcm result overflow\n"); exit(1); }
    return (int)result;
}
/* btrc-runtime-helper:end __btrc_math_lcm */
/* btrc-runtime-helper:begin __btrc_math_fibonacci */
static inline int __btrc_math_fibonacci(int n) {
    if (n <= 0) return 0;
    if (n == 1) return 1;
    if (n > 46) { fprintf(stderr, "btrc: fibonacci result overflow\n"); exit(1); }
    int a = 0, b = 1;
    for (int i = 2; i <= n; i++) { int t = a + b; a = b; b = t; }
    return b;
}
/* btrc-runtime-helper:end __btrc_math_fibonacci */
/* btrc-runtime-helper:begin __btrc_math_isPrime */
static inline bool __btrc_math_isPrime(int n) {
    if (n < 2) return false;
    if (n < 4) return true;
    if (n % 2 == 0 || n % 3 == 0) return false;
    for (int i = 5; i <= n / i; i += 6)
        if (n % i == 0 || n % (i + 2) == 0) return false;
    return true;
}
/* btrc-runtime-helper:end __btrc_math_isPrime */
/* btrc-runtime-helper:begin __btrc_math_sum_int */
static inline int __btrc_math_sum_int(int* data, int size) {
    if (size <= 0) return 0;
    if (!data) { fprintf(stderr, "btrc: sum received null data\n"); exit(1); }
    long long sum = 0;
    for (int i = 0; i < size; i++) sum += data[i];
    if (sum < INT_MIN || sum > INT_MAX) { fprintf(stderr, "btrc: sum result overflow\n"); exit(1); }
    return (int)sum;
}
/* btrc-runtime-helper:end __btrc_math_sum_int */
/* btrc-runtime-helper:begin __btrc_math_fsum */
static inline float __btrc_math_fsum(float* data, int size) {
    if (size <= 0) return 0.0f;
    if (!data) { fprintf(stderr, "btrc: fsum received null data\n"); exit(1); }
    float s = 0.0f;
    for (int i = 0; i < size; i++) s += data[i];
    return s;
}
/* btrc-runtime-helper:end __btrc_math_fsum */
/* btrc-runtime-helper:begin __btrc_hash_real */
static inline unsigned int __btrc_hash_real(long double value) {
    if (value == 0.0L) return 0U;
    /* Hash a canonical-width conversion, not long-double padding.
       Equal real values convert to equal doubles; unequal values
       may collide, which is permitted by the hash contract. */
    double canonical = (double)value;
    unsigned char bytes[sizeof canonical];
    memcpy(bytes, &canonical, sizeof canonical);
    unsigned int h = 2166136261U;
    for (size_t i = 0; i < sizeof canonical; ++i) {
        h ^= (unsigned int)bytes[i];
        h *= 16777619U;
    }
    return h;
}
/* btrc-runtime-helper:end __btrc_hash_real */
/* btrc-runtime-helper:begin __btrc_hash_str */
static inline unsigned int __btrc_hash_str(const char* s) {
    if (!s) return 0;
    unsigned int h = 5381;
    while (*s) { h = ((h << 5) + h) + (unsigned char)*s++; }
    return h;
}
/* btrc-runtime-helper:end __btrc_hash_str */
