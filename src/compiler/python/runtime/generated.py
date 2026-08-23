"""Generated shared runtime data. Do not edit by hand."""

from typing import NamedTuple


class GeneratedRuntimeHelperRow(NamedTuple):
    category: str
    name: str
    c_source: str
    depends_on: tuple[str, ...]
    required_headers: tuple[str, ...]
    provided_types: tuple[str, ...]
    provided_objects: tuple[str, ...]
    source_visible: bool


RUNTIME_HELPER_ROWS: tuple[GeneratedRuntimeHelperRow, ...] = (
    GeneratedRuntimeHelperRow(
        category='alloc',
        name='__btrc_strdup',
        c_source=(
            'static inline char* __btrc_strdup(const char* s) {\n    if (!s) return NU'
            'LL;\n    size_t len = strlen(s);\n    if (len == SIZE_MAX) { fprintf(stder'
            'r, "btrc: strdup size overflow\\n"); exit(1); }\n    len++;\n    char* copy'
            ' = (char*)malloc(len);\n    if (!copy) { fprintf(stderr, "btrc: out of me'
            'mory (strdup %zu bytes)\\n", len); exit(1); }\n    memcpy(copy, s, len);\n '
            '   return copy;\n}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=True,
    ),
    GeneratedRuntimeHelperRow(
        category='alloc',
        name='__btrc_safe_realloc',
        c_source=(
            'static inline void* __btrc_safe_realloc(void* ptr, size_t size) {\n    if'
            ' (size == 0) { free(ptr); return NULL; }\n    void* result = realloc(ptr,'
            ' size);\n    if (!result) { fprintf(stderr, "btrc: out of memory (realloc'
            ' %zu bytes)\\n", size); exit(1); }\n    return result;\n}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=True,
    ),
    GeneratedRuntimeHelperRow(
        category='alloc',
        name='__btrc_safe_calloc',
        c_source=(
            'static inline void* __btrc_safe_calloc(size_t count, size_t size) {\n    '
            'if (size != 0 && count > SIZE_MAX / size) { fprintf(stderr, "btrc: callo'
            'c size overflow\\n"); exit(1); }\n    void* result = calloc(count, size);\n'
            '    if (!result && count != 0 && size != 0) { fprintf(stderr, "btrc: out'
            ' of memory (calloc %zu bytes)\\n", count * size); exit(1); }\n    return r'
            'esult;\n}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=True,
    ),
    GeneratedRuntimeHelperRow(
        category='divmod',
        name='__btrc_div',
        c_source=(
            'static inline int __btrc_div_g_int(int a, int b) {\n    if (b == 0) { fpr'
            'intf(stderr, "Division by zero\\n"); exit(1); }\n    if (a == INT_MIN && b'
            ' == -1) { fprintf(stderr, "Integer division overflow\\n"); exit(1); }\n   '
            ' return a / b;\n}\nstatic inline unsigned int __btrc_div_g_uint(unsigned i'
            'nt a, unsigned int b) {\n    if (b == 0U) { fprintf(stderr, "Division by '
            'zero\\n"); exit(1); }\n    return a / b;\n}\nstatic inline long __btrc_div_g'
            '_long(long a, long b) {\n    if (b == 0L) { fprintf(stderr, "Division by '
            'zero\\n"); exit(1); }\n    if (a == LONG_MIN && b == -1L) { fprintf(stderr'
            ', "Integer division overflow\\n"); exit(1); }\n    return a / b;\n}\nstatic '
            'inline unsigned long __btrc_div_g_ulong(unsigned long a, unsigned long b'
            ') {\n    if (b == 0UL) { fprintf(stderr, "Division by zero\\n"); exit(1); '
            '}\n    return a / b;\n}\nstatic inline long long __btrc_div_g_llong(long lo'
            'ng a, long long b) {\n    if (b == 0LL) { fprintf(stderr, "Division by ze'
            'ro\\n"); exit(1); }\n    if (a == LLONG_MIN && b == -1LL) { fprintf(stderr'
            ', "Integer division overflow\\n"); exit(1); }\n    return a / b;\n}\nstatic '
            'inline unsigned long long __btrc_div_g_ullong(unsigned long long a, unsi'
            'gned long long b) {\n    if (b == 0ULL) { fprintf(stderr, "Division by ze'
            'ro\\n"); exit(1); }\n    return a / b;\n}\nstatic inline float __btrc_div_g_'
            'float(float a, float b) {\n    if (b == 0.0F) { fprintf(stderr, "Division'
            ' by zero\\n"); exit(1); }\n    return a / b;\n}\nstatic inline double __btrc'
            '_div_g_double(double a, double b) {\n    if (b == 0.0) { fprintf(stderr, '
            '"Division by zero\\n"); exit(1); }\n    return a / b;\n}\nstatic inline long'
            ' double __btrc_div_g_ldouble(long double a, long double b) {\n    if (b ='
            '= 0.0L) { fprintf(stderr, "Division by zero\\n"); exit(1); }\n    return a'
            ' / b;\n}\n#define __btrc_div(a, b) (_Generic(((a) + (b)), \\\n    int: __btr'
            'c_div_g_int, unsigned int: __btrc_div_g_uint, \\\n    long: __btrc_div_g_l'
            'ong, unsigned long: __btrc_div_g_ulong, \\\n    long long: __btrc_div_g_ll'
            'ong, unsigned long long: __btrc_div_g_ullong, \\\n    float: __btrc_div_g_'
            'float, double: __btrc_div_g_double, \\\n    long double: __btrc_div_g_ldou'
            'ble)((a), (b)))'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='divmod',
        name='__btrc_mod',
        c_source=(
            'static inline int __btrc_mod_g_int(int a, int b) {\n    if (b == 0) { fpr'
            'intf(stderr, "Modulo by zero\\n"); exit(1); }\n    if (a == INT_MIN && b ='
            '= -1) return 0;\n    return a % b;\n}\nstatic inline unsigned int __btrc_mo'
            'd_g_uint(unsigned int a, unsigned int b) {\n    if (b == 0U) { fprintf(st'
            'derr, "Modulo by zero\\n"); exit(1); }\n    return a % b;\n}\nstatic inline '
            'long __btrc_mod_g_long(long a, long b) {\n    if (b == 0L) { fprintf(stde'
            'rr, "Modulo by zero\\n"); exit(1); }\n    if (a == LONG_MIN && b == -1L) r'
            'eturn 0L;\n    return a % b;\n}\nstatic inline unsigned long __btrc_mod_g_u'
            'long(unsigned long a, unsigned long b) {\n    if (b == 0UL) { fprintf(std'
            'err, "Modulo by zero\\n"); exit(1); }\n    return a % b;\n}\nstatic inline l'
            'ong long __btrc_mod_g_llong(long long a, long long b) {\n    if (b == 0LL'
            ') { fprintf(stderr, "Modulo by zero\\n"); exit(1); }\n    if (a == LLONG_M'
            'IN && b == -1LL) return 0LL;\n    return a % b;\n}\nstatic inline unsigned '
            'long long __btrc_mod_g_ullong(unsigned long long a, unsigned long long b'
            ') {\n    if (b == 0ULL) { fprintf(stderr, "Modulo by zero\\n"); exit(1); }'
            '\n    return a % b;\n}\nstatic inline int __btrc_mod_g_real(long double a, '
            'long double b) {\n    /* Converting a real to int is defined exactly when'
            ' its truncated value is\n       representable.  Reject NaN/infinity and t'
            'he two open boundary regions\n       before casting, without requiring ho'
            'sted libm helpers. */\n    const long double lower = (long double)INT_MIN'
            ' - 1.0L;\n    const long double upper = (long double)INT_MAX + 1.0L;\n    '
            'if (a != a || b != b || a <= lower || a >= upper\n            || b <= low'
            'er || b >= upper) {\n        fprintf(stderr, "Floating modulo conversion '
            'out of range\\n"); exit(1);\n    }\n    return __btrc_mod_g_int((int)a, (in'
            't)b);\n}\n#define __btrc_mod(a, b) (_Generic(((a) + (b)), \\\n    int: __btr'
            'c_mod_g_int, unsigned int: __btrc_mod_g_uint, \\\n    long: __btrc_mod_g_l'
            'ong, unsigned long: __btrc_mod_g_ulong, \\\n    long long: __btrc_mod_g_ll'
            'ong, unsigned long long: __btrc_mod_g_ullong, \\\n    float: __btrc_mod_g_'
            'real, double: __btrc_mod_g_real, \\\n    long double: __btrc_mod_g_real)(('
            'a), (b)))'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='divmod',
        name='__btrc_div_int',
        c_source=(
            'static inline int __btrc_div_int(int a, int b) {\n    if (b == 0) { fprin'
            'tf(stderr, "Division by zero\\n"); exit(1); }\n    if (a == INT_MIN && b ='
            '= -1) { fprintf(stderr, "Integer division overflow\\n"); exit(1); }\n    r'
            'eturn a / b;\n}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='divmod',
        name='__btrc_div_double',
        c_source=(
            'static inline double __btrc_div_double(double a, double b) {\n    if (b ='
            '= 0.0) { fprintf(stderr, "Division by zero\\n"); exit(1); }\n    return a '
            '/ b;\n}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='divmod',
        name='__btrc_mod_int',
        c_source=(
            'static inline int __btrc_mod_int(int a, int b) {\n    if (b == 0) { fprin'
            'tf(stderr, "Modulo by zero\\n"); exit(1); }\n    if (a == INT_MIN && b == '
            '-1) return 0;\n    return a % b;\n}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='gpu',
        name='__btrc_gpu_index_check',
        c_source=(
            'static inline int __btrc_gpu_index_check(int index, int length) {\n    if'
            ' (index < 0 || index >= length) {\n        fputs("GPU array index out of '
            'bounds\\n", stderr); exit(1);\n    }\n    return index;\n}'
        ),
        depends_on=(),
        required_headers=('stdio.h', 'stdlib.h'),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string_ownership',
        name='__btrc_string_registry',
        c_source=(
            'typedef struct __btrc_string_entry {\n    char* value;\n    size_t referen'
            'ces;\n    struct __btrc_string_entry* next;\n} __btrc_string_entry;\n\nstati'
            'c __btrc_string_entry* __btrc_string_inline_buckets[64] = {0};\nstatic __'
            'btrc_string_entry** __btrc_string_buckets =\n    __btrc_string_inline_buc'
            'kets;\nstatic size_t __btrc_string_bucket_count = 64;'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string_ownership',
        name='__btrc_string_registry_lock_state',
        c_source=(
            'static atomic_flag __btrc_string_lock = ATOMIC_FLAG_INIT;'
        ),
        depends_on=(),
        required_headers=('stdatomic.h',),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string_ownership',
        name='__btrc_string_registry_lock',
        c_source=(
            'static inline void __btrc_string_registry_lock(void) {\n    unsigned int '
            'delay = 1;\n    while (atomic_flag_test_and_set_explicit(\n            &__'
            'btrc_string_lock, memory_order_acquire)) {\n        for (unsigned int spi'
            'n = 0; spin < delay; spin++) {\n            atomic_signal_fence(memory_or'
            'der_seq_cst);\n        }\n        if (delay < 1024) delay *= 2;\n    }\n}\n\ns'
            'tatic inline void __btrc_string_registry_unlock(void) {\n    atomic_flag_'
            'clear_explicit(&__btrc_string_lock, memory_order_release);\n}'
        ),
        depends_on=('__btrc_string_registry_lock_state',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string_ownership',
        name='__btrc_string_registry_hash',
        c_source=(
            'static inline size_t __btrc_string_hash(const char* value, size_t bucket'
            's) {\n    uintptr_t bits = (uintptr_t)(const void*)value;\n    bits ^= bit'
            's >> 17;\n    bits *= (uintptr_t)0xed5ad4bbU;\n    bits ^= bits >> 11;\n   '
            ' return (size_t)(bits % (uintptr_t)buckets);\n}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string_ownership',
        name='__btrc_string_registry_slot',
        c_source=(
            'static inline __btrc_string_entry** __btrc_string_slot(const char* value'
            ') {\n    size_t index = __btrc_string_hash(value, __btrc_string_bucket_co'
            'unt);\n    __btrc_string_entry** slot = &__btrc_string_buckets[index];\n  '
            '  while (*slot && (*slot)->value != value) slot = &(*slot)->next;\n    re'
            'turn slot;\n}'
        ),
        depends_on=('__btrc_string_registry', '__btrc_string_registry_hash'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string_ownership',
        name='__btrc_string_registry_count',
        c_source=(
            'static size_t __btrc_string_entry_count = 0;'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string_ownership',
        name='__btrc_string_registry_resize',
        c_source=(
            'static inline void __btrc_string_registry_resize(size_t capacity) {\n    '
            '__btrc_string_entry** old_buckets = __btrc_string_buckets;\n    size_t ol'
            'd_capacity = __btrc_string_bucket_count;\n    __btrc_string_entry** bucke'
            'ts = (__btrc_string_entry**)\n        __btrc_safe_calloc(capacity, sizeof'
            '(__btrc_string_entry*));\n    for (size_t index = 0; index < old_capacity'
            '; index++) {\n        __btrc_string_entry* entry = old_buckets[index];\n  '
            '      while (entry) {\n            __btrc_string_entry* next = entry->nex'
            't;\n            size_t target = __btrc_string_hash(entry->value, capacity'
            ');\n            entry->next = buckets[target];\n            buckets[target'
            '] = entry;\n            entry = next;\n        }\n    }\n    if (old_buckets'
            ' == __btrc_string_inline_buckets) {\n        memset(__btrc_string_inline_'
            'buckets, 0,\n            sizeof(__btrc_string_inline_buckets));\n    } els'
            'e {\n        free(old_buckets);\n    }\n    __btrc_string_buckets = buckets'
            ';\n    __btrc_string_bucket_count = capacity;\n}'
        ),
        depends_on=('__btrc_string_registry', '__btrc_string_registry_hash', '__btrc_safe_calloc'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string_ownership',
        name='__btrc_string_adopt',
        c_source=(
            'static inline char* __btrc_string_adopt(char* value) {\n    if (!value) r'
            'eturn NULL;\n    __btrc_string_entry* candidate = (__btrc_string_entry*)\n'
            '        __btrc_safe_realloc(NULL, sizeof(__btrc_string_entry));\n    cand'
            'idate->value = value;\n    candidate->references = 1;\n    candidate->next'
            ' = NULL;\n\n    __btrc_string_registry_lock();\n    __btrc_string_entry** s'
            'lot = __btrc_string_slot(value);\n    if (*slot) {\n        __btrc_string_'
            'registry_unlock();\n        free(candidate);\n        return value;\n    }\n'
            '    if (__btrc_string_entry_count >= __btrc_string_bucket_count\n        '
            '    - __btrc_string_bucket_count / 4) {\n        if (__btrc_string_bucket'
            '_count > SIZE_MAX / 2) {\n            __btrc_string_registry_unlock();\n  '
            '          fprintf(stderr, "btrc: string registry overflow\\n");\n         '
            '   exit(1);\n        }\n        __btrc_string_registry_resize(__btrc_strin'
            'g_bucket_count * 2);\n        slot = __btrc_string_slot(value);\n    }\n   '
            ' candidate->next = *slot;\n    *slot = candidate;\n    __btrc_string_entry'
            '_count++;\n    __btrc_string_registry_unlock();\n    return value;\n}'
        ),
        depends_on=('__btrc_string_registry_resize', '__btrc_string_registry_slot', '__btrc_string_registry_lock', '__btrc_string_registry_count', '__btrc_safe_realloc'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=True,
    ),
    GeneratedRuntimeHelperRow(
        category='string_ownership',
        name='__btrc_string_retain',
        c_source=(
            'static inline char* __btrc_string_retain(const char* value) {\n    if (!v'
            'alue) return NULL;\n    __btrc_string_registry_lock();\n    if (__btrc_str'
            'ing_bucket_count != 0) {\n        __btrc_string_entry* entry = *__btrc_st'
            'ring_slot(value);\n        if (entry) {\n            if (entry->references'
            ' == SIZE_MAX) {\n                __btrc_string_registry_unlock();\n       '
            '         fprintf(stderr, "btrc: string reference overflow\\n");\n         '
            '       exit(1);\n            }\n            entry->references++;\n        }'
            '\n    }\n    __btrc_string_registry_unlock();\n    return (char*)value;\n}'
        ),
        depends_on=('__btrc_string_registry_slot', '__btrc_string_registry_lock'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string_ownership',
        name='__btrc_string_release',
        c_source=(
            'static inline void __btrc_string_release(const char* value) {\n    if (!v'
            'alue) return;\n    __btrc_string_entry* removed = NULL;\n    __btrc_string'
            '_entry** retired_buckets = NULL;\n    __btrc_string_registry_lock();\n    '
            '__btrc_string_entry** slot = __btrc_string_slot(value);\n    __btrc_strin'
            'g_entry* entry = *slot;\n    if (entry && entry->references > 1) {\n      '
            '  entry->references--;\n    } else if (entry) {\n        *slot = entry->ne'
            'xt;\n        removed = entry;\n        __btrc_string_entry_count--;\n      '
            '  if (__btrc_string_entry_count == 0\n                && __btrc_string_bu'
            'ckets != __btrc_string_inline_buckets) {\n            retired_buckets = _'
            '_btrc_string_buckets;\n            __btrc_string_buckets = __btrc_string_'
            'inline_buckets;\n            __btrc_string_bucket_count = 64;\n           '
            ' memset(__btrc_string_inline_buckets, 0,\n                sizeof(__btrc_s'
            'tring_inline_buckets));\n        }\n    }\n    __btrc_string_registry_unloc'
            'k();\n    if (removed) {\n        free(removed->value);\n        free(remov'
            'ed);\n    }\n    free(retired_buckets);\n}'
        ),
        depends_on=('__btrc_string_registry_slot', '__btrc_string_registry_lock', '__btrc_string_registry_count'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string_ownership',
        name='__btrc_string_release_cleanup',
        c_source=(
            'static inline void __btrc_string_release_cleanup(void* value) {\n    __bt'
            'rc_string_release((const char*)value);\n}'
        ),
        depends_on=('__btrc_string_release',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string_ownership',
        name='__btrc_string_live_count',
        c_source=(
            'static inline size_t __btrc_string_live_count(void) {\n    __btrc_string_'
            'registry_lock();\n    size_t result = __btrc_string_entry_count;\n    __bt'
            'rc_string_registry_unlock();\n    return result;\n}'
        ),
        depends_on=('__btrc_string_registry_lock', '__btrc_string_registry_count'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=True,
    ),
    GeneratedRuntimeHelperRow(
        category='string_pool',
        name='__btrc_str_track',
        c_source=(
            'static inline char* __btrc_str_track(char* s) {\n    return __btrc_string'
            '_adopt(s);\n}'
        ),
        depends_on=('__btrc_string_adopt',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=True,
    ),
    GeneratedRuntimeHelperRow(
        category='string_pool',
        name='__btrc_str_flush',
        c_source=(
            'static inline void __btrc_str_flush(void) {\n    /* Retained for source c'
            'ompatibility; ownership is explicit. */\n}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_string_or_empty',
        c_source=(
            'static inline const char* __btrc_string_or_empty(const char* s) {\n    re'
            'turn s ? s : "";\n}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=True,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_string_length',
        c_source=(
            'static inline int __btrc_string_length(const char* s) {\n    if (!s) retu'
            'rn 0;\n    size_t length = strlen(s);\n    if (length > (size_t)INT_MAX) {'
            '\n        fprintf(stderr, "btrc: string length overflow\\n"); exit(1);\n   '
            ' }\n    return (int)length;\n}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=True,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_string_alloc',
        c_source=(
            'static inline char* __btrc_string_alloc(int length) {\n    if (length < 0'
            ') {\n        fprintf(stderr, "btrc: negative string allocation\\n"); exit('
            '1);\n    }\n    char* result = (char*)__btrc_safe_realloc(\n        NULL, ('
            "size_t)length + 1);\n    result[length] = '\\0';\n    return __btrc_string_"
            'adopt(result);\n}'
        ),
        depends_on=('__btrc_safe_realloc', '__btrc_string_adopt'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=True,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_ascii_upper',
        c_source=(
            'static inline char __btrc_ascii_upper(char value) {\n    unsigned char by'
            "te = (unsigned char)value;\n    return (byte >= 'a' && byte <= 'z') ? (ch"
            "ar)(byte - 'a' + 'A') : value;\n}"
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_ascii_lower',
        c_source=(
            'static inline char __btrc_ascii_lower(char value) {\n    unsigned char by'
            "te = (unsigned char)value;\n    return (byte >= 'A' && byte <= 'Z') ? (ch"
            "ar)(byte - 'A' + 'a') : value;\n}"
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_ascii_space',
        c_source=(
            'static inline bool __btrc_ascii_space(char value) {\n    unsigned char by'
            "te = (unsigned char)value;\n    return byte == ' ' || (byte >= '\\t' && by"
            "te <= '\\r');\n}"
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_substring',
        c_source=(
            'static inline char* __btrc_substring(const char* s, int start, int len) '
            '{\n    if (!s) return __btrc_string_alloc(0);\n    int slen = __btrc_strin'
            'g_length(s);\n    if (start < 0) start = 0;\n    if (start > slen) start ='
            ' slen;\n    if (len < 0) len = 0;\n    if (len > slen - start) len = slen '
            '- start;\n    char* result = __btrc_string_alloc(len);\n    memcpy(result,'
            ' s + start, (size_t)len);\n    return result;\n}'
        ),
        depends_on=('__btrc_string_length', '__btrc_string_alloc'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_trim',
        c_source=(
            'static inline char* __btrc_trim(const char* s) {\n    if (!s) return __bt'
            'rc_string_alloc(0);\n    int slen = __btrc_string_length(s);\n    int star'
            't = 0;\n    while (start < slen && __btrc_ascii_space(s[start])) start++;'
            '\n    int end = slen;\n    while (end > start && __btrc_ascii_space(s[end '
            '- 1])) end--;\n    int length = end - start;\n    char* result = __btrc_st'
            'ring_alloc(length);\n    memcpy(result, s + start, (size_t)length);\n    r'
            'eturn result;\n}'
        ),
        depends_on=('__btrc_string_length', '__btrc_string_alloc', '__btrc_ascii_space'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_toUpper',
        c_source=(
            'static inline char* __btrc_toUpper(const char* s) {\n    if (!s) return _'
            '_btrc_string_alloc(0);\n    int len = __btrc_string_length(s);\n    char* '
            'result = __btrc_string_alloc(len);\n    for (int i = 0; i < len; i++) res'
            'ult[i] = __btrc_ascii_upper(s[i]);\n    return result;\n}'
        ),
        depends_on=('__btrc_string_length', '__btrc_string_alloc', '__btrc_ascii_upper'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_toLower',
        c_source=(
            'static inline char* __btrc_toLower(const char* s) {\n    if (!s) return _'
            '_btrc_string_alloc(0);\n    int len = __btrc_string_length(s);\n    char* '
            'result = __btrc_string_alloc(len);\n    for (int i = 0; i < len; i++) res'
            'ult[i] = __btrc_ascii_lower(s[i]);\n    return result;\n}'
        ),
        depends_on=('__btrc_string_length', '__btrc_string_alloc', '__btrc_ascii_lower'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_replace',
        c_source=(
            'static inline char* __btrc_replace(const char* s, const char* old, const'
            ' char* rep) {\n    if (!s) return __btrc_string_alloc(0);\n    if (!old ||'
            ' !old[0]) return __btrc_strdup(s);\n    if (!rep) rep = "";\n    int slen '
            '= __btrc_string_length(s);\n    int oldlen = __btrc_string_length(old);\n '
            '   int replen = __btrc_string_length(rep);\n    int matches = 0;\n    cons'
            't char* scan = s;\n    while ((scan = strstr(scan, old)) != NULL) { match'
            'es++; scan += oldlen; }\n    long long total = (long long)slen\n        + '
            '(long long)matches * ((long long)replen - (long long)oldlen);\n    if (to'
            'tal < 0 || total > INT_MAX) {\n        fprintf(stderr, "btrc: string repl'
            'ace overflow\\n"); exit(1);\n    }\n    char* result = __btrc_string_alloc('
            '(int)total);\n    const char* input = s;\n    char* output = result;\n    c'
            'onst char* found;\n    while ((found = strstr(input, old)) != NULL) {\n   '
            '     size_t prefix = (size_t)(found - input);\n        memcpy(output, inp'
            'ut, prefix); output += prefix;\n        memcpy(output, rep, (size_t)reple'
            'n); output += replen;\n        input = found + oldlen;\n    }\n    memcpy(o'
            'utput, input, strlen(input));\n    return result;\n}'
        ),
        depends_on=('__btrc_string_length', '__btrc_string_alloc', '__btrc_strdup'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_split',
        c_source=(
            'static inline char** __btrc_split(const char* s, const char* delim) {\n  '
            '  if (!s || !delim) { char** r = (char**)__btrc_safe_realloc(NULL, sizeo'
            'f(char*)); r[0] = NULL; return r; }\n    int slen = __btrc_string_length('
            's);\n    int dlen = __btrc_string_length(delim);\n    if (dlen == 0) { fpr'
            'intf(stderr, "Empty delimiter in split()\\n"); exit(1); }\n    int cap = 8'
            ';\n    char** result = (char**)__btrc_safe_realloc(NULL, sizeof(char*) * '
            '(size_t)cap);\n    int count = 0;\n    const char* p = s;\n    for (;;) {\n '
            '       const char* found = strstr(p, delim);\n        int offset = (int)('
            'p - s);\n        int seglen = found ? (int)(found - p) : slen - offset;\n '
            '       if (count > INT_MAX - 2) { fprintf(stderr, "btrc: split result ov'
            'erflow\\n"); exit(1); }\n        if (count + 2 > cap) {\n            if (ca'
            'p > INT_MAX / 2\n                    || (size_t)(cap * 2) > SIZE_MAX / si'
            'zeof(char*)) {\n                fprintf(stderr, "btrc: split result overf'
            'low\\n"); exit(1);\n            }\n            cap *= 2;\n            result'
            ' = (char**)__btrc_safe_realloc(\n                result, sizeof(char*) * '
            '(size_t)cap);\n        }\n        result[count] = __btrc_string_alloc(segl'
            'en);\n        memcpy(result[count], p, (size_t)seglen);\n        count++;\n'
            '        if (!found) break;\n        p = found + dlen;\n    }\n    result[co'
            'unt] = NULL;\n    return result;\n}'
        ),
        depends_on=('__btrc_safe_realloc', '__btrc_string_length', '__btrc_string_alloc'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_repeat',
        c_source=(
            'static inline char* __btrc_repeat(const char* s, int count) {\n    if (!s'
            ') return __btrc_string_alloc(0);\n    if (count <= 0) return __btrc_strin'
            'g_alloc(0);\n    int slen = __btrc_string_length(s);\n    if (slen == 0) r'
            'eturn __btrc_string_alloc(0);\n    if (slen > 0 && count > INT_MAX / slen'
            ') {\n        fprintf(stderr, "btrc: string repeat overflow\\n"); exit(1);\n'
            '    }\n    int total = slen * count;\n    char* result = __btrc_string_all'
            'oc(total);\n    for (int i = 0; i < count; i++)\n        memcpy(result + ('
            'size_t)i * (size_t)slen, s, (size_t)slen);\n    return result;\n}'
        ),
        depends_on=('__btrc_string_length', '__btrc_string_alloc'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_reverse',
        c_source=(
            'static inline char* __btrc_reverse(const char* s) {\n    if (!s) return _'
            '_btrc_string_alloc(0);\n    int len = __btrc_string_length(s);\n    char* '
            'result = __btrc_string_alloc(len);\n    for (int i = 0; i < len; i++) res'
            'ult[i] = s[len - 1 - i];\n    return result;\n}'
        ),
        depends_on=('__btrc_string_length', '__btrc_string_alloc'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_removePrefix',
        c_source=(
            'static inline char* __btrc_removePrefix(const char* s, const char* prefi'
            'x) {\n    if (!s) return __btrc_string_alloc(0);\n    if (!prefix) return '
            '__btrc_strdup(s);\n    int slen = __btrc_string_length(s);\n    int plen ='
            ' __btrc_string_length(prefix);\n    if (plen <= slen && memcmp(s, prefix,'
            ' (size_t)plen) == 0) {\n        int length = slen - plen;\n        char* r'
            'esult = __btrc_string_alloc(length);\n        memcpy(result, s + plen, (s'
            'ize_t)length);\n        return result;\n    }\n    return __btrc_strdup(s);'
            '\n}'
        ),
        depends_on=('__btrc_string_length', '__btrc_string_alloc', '__btrc_strdup'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_removeSuffix',
        c_source=(
            'static inline char* __btrc_removeSuffix(const char* s, const char* suffi'
            'x) {\n    if (!s) return __btrc_string_alloc(0);\n    if (!suffix) return '
            '__btrc_strdup(s);\n    int slen = __btrc_string_length(s);\n    int suflen'
            ' = __btrc_string_length(suffix);\n    if (suflen <= slen\n            && m'
            'emcmp(s + slen - suflen, suffix, (size_t)suflen) == 0) {\n        int len'
            'gth = slen - suflen;\n        char* result = __btrc_string_alloc(length);'
            '\n        memcpy(result, s, (size_t)length);\n        return result;\n    }'
            '\n    return __btrc_strdup(s);\n}'
        ),
        depends_on=('__btrc_string_length', '__btrc_string_alloc', '__btrc_strdup'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_capitalize',
        c_source=(
            'static inline char* __btrc_capitalize(const char* s) {\n    if (!s) retur'
            'n __btrc_string_alloc(0);\n    int len = __btrc_string_length(s);\n    cha'
            'r* result = __btrc_string_alloc(len);\n    for (int i = 0; i < len; i++) '
            'result[i] = __btrc_ascii_lower(s[i]);\n    if (len > 0) result[0] = __btr'
            'c_ascii_upper(result[0]);\n    return result;\n}'
        ),
        depends_on=('__btrc_string_length', '__btrc_string_alloc', '__btrc_ascii_lower', '__btrc_ascii_upper'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_title',
        c_source=(
            'static inline char* __btrc_title(const char* s) {\n    if (!s) return __b'
            'trc_string_alloc(0);\n    int len = __btrc_string_length(s);\n    char* re'
            'sult = __btrc_string_alloc(len);\n    int cap_next = 1;\n    for (int i = '
            '0; i < len; i++) {\n        if (__btrc_ascii_space(s[i])) { result[i] = s'
            '[i]; cap_next = 1; }\n        else if (cap_next) { result[i] = __btrc_asc'
            'ii_upper(s[i]); cap_next = 0; }\n        else { result[i] = __btrc_ascii_'
            'lower(s[i]); }\n    }\n    return result;\n}'
        ),
        depends_on=('__btrc_string_length', '__btrc_string_alloc', '__btrc_ascii_lower', '__btrc_ascii_space', '__btrc_ascii_upper'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_swapCase',
        c_source=(
            'static inline char* __btrc_swapCase(const char* s) {\n    if (!s) return '
            '__btrc_string_alloc(0);\n    int len = __btrc_string_length(s);\n    char*'
            ' result = __btrc_string_alloc(len);\n    for (int i = 0; i < len; i++) {\n'
            "        unsigned char byte = (unsigned char)s[i];\n        if (byte >= 'A"
            "' && byte <= 'Z') result[i] = __btrc_ascii_lower(s[i]);\n        else if "
            "(byte >= 'a' && byte <= 'z') result[i] = __btrc_ascii_upper(s[i]);\n     "
            '   else result[i] = s[i];\n    }\n    return result;\n}'
        ),
        depends_on=('__btrc_string_length', '__btrc_string_alloc', '__btrc_ascii_lower', '__btrc_ascii_upper'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_padLeft',
        c_source=(
            'static inline char* __btrc_padLeft(const char* s, int width, char fill) '
            '{\n    if (!s) return __btrc_string_alloc(0);\n    int len = __btrc_string'
            '_length(s);\n    int result_len = len >= width ? len : width;\n    char* r'
            'esult = __btrc_string_alloc(result_len);\n    int pad = result_len - len;'
            '\n    memset(result, (unsigned char)fill, (size_t)pad);\n    memcpy(result'
            ' + pad, s, (size_t)len);\n    return result;\n}'
        ),
        depends_on=('__btrc_string_length', '__btrc_string_alloc'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_padRight',
        c_source=(
            'static inline char* __btrc_padRight(const char* s, int width, char fill)'
            ' {\n    if (!s) return __btrc_string_alloc(0);\n    int len = __btrc_strin'
            'g_length(s);\n    int result_len = len >= width ? len : width;\n    char* '
            'result = __btrc_string_alloc(result_len);\n    memcpy(result, s, (size_t)'
            'len);\n    memset(result + len, (unsigned char)fill, (size_t)(result_len '
            '- len));\n    return result;\n}'
        ),
        depends_on=('__btrc_string_length', '__btrc_string_alloc'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_center',
        c_source=(
            'static inline char* __btrc_center(const char* s, int width, char fill) {'
            '\n    if (!s) return __btrc_string_alloc(0);\n    int len = __btrc_string_'
            'length(s);\n    int result_len = len >= width ? len : width;\n    char* re'
            'sult = __btrc_string_alloc(result_len);\n    int left = (result_len - len'
            ') / 2;\n    int right = result_len - len - left;\n    memset(result, (unsi'
            'gned char)fill, (size_t)left);\n    memcpy(result + left, s, (size_t)len)'
            ';\n    memset(result + left + len, (unsigned char)fill, (size_t)right);\n '
            '   return result;\n}'
        ),
        depends_on=('__btrc_string_length', '__btrc_string_alloc'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_lstrip',
        c_source=(
            'static inline char* __btrc_lstrip(const char* s) {\n    if (!s) return __'
            'btrc_string_alloc(0);\n    int len = __btrc_string_length(s);\n    int sta'
            'rt = 0;\n    while (start < len && __btrc_ascii_space(s[start])) start++;'
            '\n    int result_len = len - start;\n    char* result = __btrc_string_allo'
            'c(result_len);\n    memcpy(result, s + start, (size_t)result_len);\n    re'
            'turn result;\n}'
        ),
        depends_on=('__btrc_string_length', '__btrc_string_alloc', '__btrc_ascii_space'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_rstrip',
        c_source=(
            'static inline char* __btrc_rstrip(const char* s) {\n    if (!s) return __'
            'btrc_string_alloc(0);\n    int len = __btrc_string_length(s);\n    while ('
            'len > 0 && __btrc_ascii_space(s[len - 1])) len--;\n    char* result = __b'
            'trc_string_alloc(len);\n    memcpy(result, s, (size_t)len);\n    return re'
            'sult;\n}'
        ),
        depends_on=('__btrc_string_length', '__btrc_string_alloc', '__btrc_ascii_space'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_zfill',
        c_source=(
            'static inline char* __btrc_zfill(const char* s, int width) {\n    if (!s)'
            ' return __btrc_string_alloc(0);\n    int len = __btrc_string_length(s);\n '
            '   int result_len = len >= width ? len : width;\n    char* result = __btr'
            "c_string_alloc(result_len);\n    int start = (len > 0 && (s[0] == '-' || "
            "s[0] == '+')) ? 1 : 0;\n    int pad = result_len - len;\n    if (start) re"
            "sult[0] = s[0];\n    memset(result + start, '0', (size_t)pad);\n    memcpy"
            '(result + start + pad, s + start, (size_t)(len - start));\n    return res'
            'ult;\n}'
        ),
        depends_on=('__btrc_string_length', '__btrc_string_alloc'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_strcat',
        c_source=(
            'static inline char* __btrc_strcat(const char* a, const char* b) {\n    if'
            ' (!a && !b) return __btrc_string_alloc(0);\n    if (!a) return __btrc_str'
            'dup(b);\n    if (!b) return __btrc_strdup(a);\n    int left_len = __btrc_s'
            'tring_length(a);\n    int right_len = __btrc_string_length(b);\n    if (ri'
            'ght_len > INT_MAX - left_len) {\n        fprintf(stderr, "btrc: string co'
            'ncatenation overflow\\n"); exit(1);\n    }\n    int total = left_len + righ'
            't_len;\n    char* result = __btrc_string_alloc(total);\n    memcpy(result,'
            ' a, (size_t)left_len);\n    memcpy(result + left_len, b, (size_t)right_le'
            'n);\n    return result;\n}'
        ),
        depends_on=('__btrc_string_length', '__btrc_string_alloc', '__btrc_strdup'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_join',
        c_source=(
            'static inline char* __btrc_join(char** items, int count, const char* sep'
            ') {\n    if (count <= 0 || !items) return __btrc_string_alloc(0);\n    if '
            '(!sep) sep = "";\n    int separator_len = __btrc_string_length(sep);\n    '
            'long long total = (long long)separator_len * (long long)(count - 1);\n   '
            ' if (total > INT_MAX) {\n        fprintf(stderr, "btrc: string join overf'
            'low\\n"); exit(1);\n    }\n    for (int i = 0; i < count; i++) {\n        in'
            't item_len = __btrc_string_length(items[i]);\n        if (item_len > INT_'
            'MAX - (int)total) {\n            fprintf(stderr, "btrc: string join overf'
            'low\\n"); exit(1);\n        }\n        total += item_len;\n    }\n    char* r'
            'esult = __btrc_string_alloc((int)total);\n    int position = 0;\n    for ('
            'int i = 0; i < count; i++) {\n        if (i > 0) {\n            memcpy(res'
            'ult + position, sep, (size_t)separator_len);\n            position += sep'
            'arator_len;\n        }\n        const char* item = items[i] ? items[i] : "'
            '";\n        int item_len = __btrc_string_length(item);\n        memcpy(res'
            'ult + position, item, (size_t)item_len);\n        position += item_len;\n '
            '   }\n    return result;\n}'
        ),
        depends_on=('__btrc_string_length', '__btrc_string_alloc'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_charAt',
        c_source=(
            'static inline char __btrc_charAt(const char* s, int idx) {\n    if (!s) {'
            ' fprintf(stderr, "String index on NULL\\n"); exit(1); }\n    int len = __b'
            'trc_string_length(s);\n    if (idx < 0 || idx >= len) { fprintf(stderr, "'
            'String index out of bounds: %d (length %d)\\n", idx, len); exit(1); }\n   '
            ' return s[idx];\n}'
        ),
        depends_on=('__btrc_string_length',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_indexOf',
        c_source=(
            'static inline int __btrc_indexOf(const char* s, const char* sub) {\n    i'
            'f (!s || !sub) return -1;\n    (void)__btrc_string_length(s);\n    (void)_'
            '_btrc_string_length(sub);\n    const char* found = strstr(s, sub);\n    re'
            'turn found ? (int)(found - s) : -1;\n}'
        ),
        depends_on=('__btrc_string_length',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_lastIndexOf',
        c_source=(
            'static inline int __btrc_lastIndexOf(const char* s, const char* sub) {\n '
            '   if (!s || !sub) return -1;\n    int slen = __btrc_string_length(s);\n  '
            '  int sublen = __btrc_string_length(sub);\n    if (sublen == 0) return sl'
            'en;\n    for (int i = slen - sublen; i >= 0; i--) {\n        if (memcmp(s '
            '+ i, sub, (size_t)sublen) == 0) return i;\n    }\n    return -1;\n}'
        ),
        depends_on=('__btrc_string_length',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_isEmpty',
        c_source=(
            'static inline bool __btrc_isEmpty(const char* s) {\n    return !s || s[0]'
            " == '\\0';\n}"
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_startsWith',
        c_source=(
            'static inline bool __btrc_startsWith(const char* s, const char* prefix) '
            '{\n    if (!s || !prefix) return false;\n    int slen = __btrc_string_leng'
            'th(s);\n    int prefix_len = __btrc_string_length(prefix);\n    return pre'
            'fix_len <= slen\n        && memcmp(s, prefix, (size_t)prefix_len) == 0;\n}'
        ),
        depends_on=('__btrc_string_length',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_endsWith',
        c_source=(
            'static inline bool __btrc_endsWith(const char* s, const char* suffix) {\n'
            '    if (!s || !suffix) return false;\n    int slen = __btrc_string_length'
            '(s);\n    int suffix_len = __btrc_string_length(suffix);\n    return suffi'
            'x_len <= slen\n        && memcmp(s + slen - suffix_len, suffix, (size_t)s'
            'uffix_len) == 0;\n}'
        ),
        depends_on=('__btrc_string_length',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_strContains',
        c_source=(
            'static inline bool __btrc_strContains(const char* s, const char* sub) {\n'
            '    if (!s || !sub) return false;\n    (void)__btrc_string_length(s);\n   '
            ' (void)__btrc_string_length(sub);\n    return strstr(s, sub) != NULL;\n}'
        ),
        depends_on=('__btrc_string_length',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_count',
        c_source=(
            'static inline int __btrc_count(const char* s, const char* sub) {\n    if '
            '(!s || !sub) return 0;\n    (void)__btrc_string_length(s);\n    int sublen'
            ' = __btrc_string_length(sub);\n    if (sublen == 0) return 0;\n    int cou'
            'nt = 0;\n    const char* cursor = s;\n    while ((cursor = strstr(cursor, '
            'sub)) != NULL) {\n        count++; cursor += sublen;\n    }\n    return cou'
            'nt;\n}'
        ),
        depends_on=('__btrc_string_length',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_find',
        c_source=(
            'static inline int __btrc_find(const char* s, const char* sub, int start)'
            ' {\n    if (!s || !sub) return -1;\n    int len = __btrc_string_length(s);'
            '\n    int sublen = __btrc_string_length(sub);\n    if (start < 0) start = '
            '0;\n    if (start > len) return -1;\n    if (sublen == 0) return start;\n  '
            '  const char* found = strstr(s + start, sub);\n    return found ? (int)(f'
            'ound - s) : -1;\n}'
        ),
        depends_on=('__btrc_string_length',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_isDigitStr',
        c_source=(
            'static inline bool __btrc_isDigitStr(const char* s) {\n    if (!s || !*s)'
            " return false;\n    for (; *s; s++) if (*s < '0' || *s > '9') return fals"
            'e;\n    return true;\n}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_isAlphaStr',
        c_source=(
            'static inline bool __btrc_isAlphaStr(const char* s) {\n    if (!s || !*s)'
            ' return false;\n    for (; *s; s++) {\n        unsigned char byte = (unsig'
            "ned char)*s;\n        if (!((byte >= 'A' && byte <= 'Z')\n                "
            "|| (byte >= 'a' && byte <= 'z'))) return false;\n    }\n    return true;\n}"
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_isBlank',
        c_source=(
            'static inline bool __btrc_isBlank(const char* s) {\n    if (!s) return tr'
            'ue;\n    for (; *s; s++) if (!__btrc_ascii_space(*s)) return false;\n    r'
            'eturn true;\n}'
        ),
        depends_on=('__btrc_ascii_space',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_isUpper',
        c_source=(
            "static inline bool __btrc_isUpper(const char* s) {\n    if (!s || *s == '"
            "\\0') return false;\n    for (; *s; s++) {\n        unsigned char byte = (u"
            "nsigned char)*s;\n        if (!(byte >= 'A' && byte <= 'Z') && !__btrc_as"
            'cii_space(*s))\n            return false;\n    }\n    return true;\n}'
        ),
        depends_on=('__btrc_ascii_space',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_isLower',
        c_source=(
            "static inline bool __btrc_isLower(const char* s) {\n    if (!s || *s == '"
            "\\0') return false;\n    for (; *s; s++) {\n        unsigned char byte = (u"
            "nsigned char)*s;\n        if (!(byte >= 'a' && byte <= 'z') && !__btrc_as"
            'cii_space(*s))\n            return false;\n    }\n    return true;\n}'
        ),
        depends_on=('__btrc_ascii_space',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_isAlnumStr',
        c_source=(
            'static inline bool __btrc_isAlnumStr(const char* s) {\n    if (!s || *s ='
            "= '\\0') return false;\n    for (; *s; s++) {\n        unsigned char byte ="
            " (unsigned char)*s;\n        if (!((byte >= '0' && byte <= '9')\n         "
            "       || (byte >= 'A' && byte <= 'Z')\n                || (byte >= 'a' &"
            "& byte <= 'z'))) return false;\n    }\n    return true;\n}"
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_utf8_charlen',
        c_source=(
            'static inline int __btrc_utf8_charlen(const char* s) {\n    if (!s) retur'
            'n 0;\n    int length = __btrc_string_length(s);\n    int count = 0;\n    in'
            't index = 0;\n    while (index < length) {\n        int remaining = length'
            ' - index;\n        unsigned char c0 = (unsigned char)s[index];\n        un'
            'signed char c1 = remaining > 1 ? (unsigned char)s[index + 1] : 0;\n      '
            '  unsigned char c2 = remaining > 2 ? (unsigned char)s[index + 2] : 0;\n  '
            '      unsigned char c3 = remaining > 3 ? (unsigned char)s[index + 3] : 0'
            ';\n        int advance = 1;\n        if (c0 >= 0xC2 && c0 <= 0xDF\n        '
            '        && c1 >= 0x80 && c1 <= 0xBF) advance = 2;\n        else if (((c0 '
            '== 0xE0 && c1 >= 0xA0 && c1 <= 0xBF)\n                    || (c0 >= 0xE1 '
            '&& c0 <= 0xEC && c1 >= 0x80 && c1 <= 0xBF)\n                    || (c0 =='
            ' 0xED && c1 >= 0x80 && c1 <= 0x9F)\n                    || (c0 >= 0xEE &&'
            ' c0 <= 0xEF && c1 >= 0x80 && c1 <= 0xBF))\n                && c2 >= 0x80 '
            '&& c2 <= 0xBF) advance = 3;\n        else if (((c0 == 0xF0 && c1 >= 0x90 '
            '&& c1 <= 0xBF)\n                    || (c0 >= 0xF1 && c0 <= 0xF3 && c1 >='
            ' 0x80 && c1 <= 0xBF)\n                    || (c0 == 0xF4 && c1 >= 0x80 &&'
            ' c1 <= 0x8F))\n                && c2 >= 0x80 && c2 <= 0xBF\n              '
            '  && c3 >= 0x80 && c3 <= 0xBF) advance = 4;\n        index += advance;\n  '
            '      count++;\n    }\n    return count;\n}'
        ),
        depends_on=('__btrc_string_length',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_charLen',
        c_source=(
            'static inline int __btrc_charLen(const char* s) {\n    return __btrc_utf8'
            '_charlen(s);\n}'
        ),
        depends_on=('__btrc_utf8_charlen',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_parseLong',
        c_source=(
            'static inline long __btrc_parseLong(const char* s) {\n    if (!s) return '
            "0;\n    while (*s == ' ' || *s == '\\t' || *s == '\\n'\n            || *s =="
            " '\\r' || *s == '\\v' || *s == '\\f') ++s;\n    bool negative = false;\n    i"
            "f (*s == '-' || *s == '+') { negative = *s == '-'; ++s; }\n    unsigned l"
            'ong limit = negative\n        ? (unsigned long)LONG_MAX + 1UL : (unsigned'
            ' long)LONG_MAX;\n    unsigned long value = 0UL;\n    bool any = false;\n   '
            " while (*s >= '0' && *s <= '9') {\n        unsigned long digit = (unsigne"
            "d long)(*s - '0');\n        any = true;\n        if (value > (limit - digi"
            't) / 10UL)\n            return negative ? LONG_MIN : LONG_MAX;\n        va'
            'lue = value * 10UL + digit;\n        ++s;\n    }\n    if (!any) return 0L;\n'
            '    if (!negative) return (long)value;\n    if (value == (unsigned long)L'
            'ONG_MAX + 1UL) return LONG_MIN;\n    return -(long)value;\n}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_parseInt',
        c_source=(
            'static inline int __btrc_parseInt(const char* s) {\n    long value = __bt'
            'rc_parseLong(s);\n    if (value > INT_MAX) return INT_MAX;\n    if (value '
            '< INT_MIN) return INT_MIN;\n    return (int)value;\n}'
        ),
        depends_on=('__btrc_parseLong',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_parseBool',
        c_source=(
            'static inline bool __btrc_parseBool(const char* s) {\n    return s && *s '
            '!= \'\\0\' && strcmp(s, "false") != 0\n        && strcmp(s, "0") != 0;\n}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_intToString',
        c_source=(
            'static inline char* __btrc_intToString(int n) {\n    char* buf = __btrc_s'
            'tring_alloc(31);\n    snprintf(buf, 32, "%d", n);\n    return buf;\n}'
        ),
        depends_on=('__btrc_string_alloc',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_longToString',
        c_source=(
            'static inline char* __btrc_longToString(long n) {\n    char* buf = __btrc'
            '_string_alloc(31);\n    snprintf(buf, 32, "%ld", n);\n    return buf;\n}'
        ),
        depends_on=('__btrc_string_alloc',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_longLongToString',
        c_source=(
            'static inline char* __btrc_longLongToString(long long n) {\n    char* buf'
            ' = __btrc_string_alloc(31);\n    snprintf(buf, 32, "%lld", n);\n    return'
            ' buf;\n}'
        ),
        depends_on=('__btrc_string_alloc',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_uintToString',
        c_source=(
            'static inline char* __btrc_uintToString(unsigned int n) {\n    char* buf '
            '= __btrc_string_alloc(31);\n    snprintf(buf, 32, "%u", n);\n    return bu'
            'f;\n}'
        ),
        depends_on=('__btrc_string_alloc',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_ulongToString',
        c_source=(
            'static inline char* __btrc_ulongToString(unsigned long n) {\n    char* bu'
            'f = __btrc_string_alloc(31);\n    snprintf(buf, 32, "%lu", n);\n    return'
            ' buf;\n}'
        ),
        depends_on=('__btrc_string_alloc',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_ulongLongToString',
        c_source=(
            'static inline char* __btrc_ulongLongToString(unsigned long long n) {\n   '
            ' char* buf = __btrc_string_alloc(31);\n    snprintf(buf, 32, "%llu", n);\n'
            '    return buf;\n}'
        ),
        depends_on=('__btrc_string_alloc',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_floatToString',
        c_source=(
            'static inline char* __btrc_floatToString(float f) {\n    char* buf = __bt'
            'rc_string_alloc(63);\n    snprintf(buf, 64, "%g", (double)f);\n    return '
            'buf;\n}'
        ),
        depends_on=('__btrc_string_alloc',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_doubleToString',
        c_source=(
            'static inline char* __btrc_doubleToString(double d) {\n    char* buf = __'
            'btrc_string_alloc(63);\n    snprintf(buf, 64, "%g", d);\n    return buf;\n}'
        ),
        depends_on=('__btrc_string_alloc',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_longDoubleToString',
        c_source=(
            'static inline char* __btrc_longDoubleToString(long double d) {\n    char*'
            ' buf = __btrc_string_alloc(63);\n    snprintf(buf, 64, "%Lg", d);\n    ret'
            'urn buf;\n}'
        ),
        depends_on=('__btrc_string_alloc',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_charToString',
        c_source=(
            'static inline char* __btrc_charToString(char c) {\n    char* buf = __btrc'
            "_string_alloc(1);\n    buf[0] = c; buf[1] = '\\0';\n    return buf;\n}"
        ),
        depends_on=('__btrc_string_alloc',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_fromInt',
        c_source=(
            'static inline char* __btrc_fromInt(int n) {\n    char* r = __btrc_string_'
            'alloc(20);\n    snprintf(r, 21, "%d", n);\n    return r;\n}'
        ),
        depends_on=('__btrc_string_alloc',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='string',
        name='__btrc_fromFloat',
        c_source=(
            'static inline char* __btrc_fromFloat(float f) {\n    char* r = __btrc_str'
            'ing_alloc(31);\n    snprintf(r, 32, "%g", (double)f);\n    return r;\n}'
        ),
        depends_on=('__btrc_string_alloc',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='math',
        name='__btrc_math_factorial',
        c_source=(
            'static inline long long __btrc_math_factorial(int n) {\n    if (n < 0) { '
            'fprintf(stderr, "btrc: factorial of negative number\\n"); exit(1); }\n    '
            'if (n > 20) { fprintf(stderr, "btrc: factorial overflow (n=%d)\\n", n); e'
            'xit(1); }\n    long long r = 1;\n    for (int i = 2; i <= n; i++) r *= i;\n'
            '    return r;\n}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='math',
        name='__btrc_math_gcd',
        c_source=(
            'static inline int __btrc_math_gcd(int a, int b) {\n    unsigned int ua = '
            'a < 0 ? 0u - (unsigned int)a : (unsigned int)a;\n    unsigned int ub = b '
            '< 0 ? 0u - (unsigned int)b : (unsigned int)b;\n    while (ub) { unsigned '
            'int t = ub; ub = ua % ub; ua = t; }\n    if (ua > INT_MAX) { fprintf(stde'
            'rr, "btrc: gcd result overflow\\n"); exit(1); }\n    return (int)ua;\n}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='math',
        name='__btrc_math_lcm',
        c_source=(
            'static inline int __btrc_math_lcm(int a, int b) {\n    if (a == 0 || b =='
            ' 0) return 0;\n    int g = __btrc_math_gcd(a, b);\n    long long result = '
            '((long long)a / g) * (long long)b;\n    if (result < 0) result = -result;'
            '\n    if (result > INT_MAX) { fprintf(stderr, "btrc: lcm result overflow\\'
            'n"); exit(1); }\n    return (int)result;\n}'
        ),
        depends_on=('__btrc_math_gcd',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='math',
        name='__btrc_math_fibonacci',
        c_source=(
            'static inline int __btrc_math_fibonacci(int n) {\n    if (n <= 0) return '
            '0;\n    if (n == 1) return 1;\n    if (n > 46) { fprintf(stderr, "btrc: fi'
            'bonacci result overflow\\n"); exit(1); }\n    int a = 0, b = 1;\n    for (i'
            'nt i = 2; i <= n; i++) { int t = a + b; a = b; b = t; }\n    return b;\n}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='math',
        name='__btrc_math_isPrime',
        c_source=(
            'static inline bool __btrc_math_isPrime(int n) {\n    if (n < 2) return fa'
            'lse;\n    if (n < 4) return true;\n    if (n % 2 == 0 || n % 3 == 0) retur'
            'n false;\n    for (int i = 5; i <= n / i; i += 6)\n        if (n % i == 0 '
            '|| n % (i + 2) == 0) return false;\n    return true;\n}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='math',
        name='__btrc_math_sum_int',
        c_source=(
            'static inline int __btrc_math_sum_int(int* data, int size) {\n    if (siz'
            'e <= 0) return 0;\n    if (!data) { fprintf(stderr, "btrc: sum received n'
            'ull data\\n"); exit(1); }\n    long long sum = 0;\n    for (int i = 0; i < '
            'size; i++) sum += data[i];\n    if (sum < INT_MIN || sum > INT_MAX) { fpr'
            'intf(stderr, "btrc: sum result overflow\\n"); exit(1); }\n    return (int)'
            'sum;\n}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='math',
        name='__btrc_math_fsum',
        c_source=(
            'static inline float __btrc_math_fsum(float* data, int size) {\n    if (si'
            'ze <= 0) return 0.0f;\n    if (!data) { fprintf(stderr, "btrc: fsum recei'
            'ved null data\\n"); exit(1); }\n    float s = 0.0f;\n    for (int i = 0; i '
            '< size; i++) s += data[i];\n    return s;\n}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='trycatch',
        name='__btrc_try_level',
        c_source=(
            'static _Thread_local volatile int __btrc_try_top = -1;'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='trycatch',
        name='__btrc_trycatch_globals',
        c_source=(
            '/* btrc try/catch runtime (dynamic) */\ntypedef struct { jmp_buf env; } _'
            '_btrc_try_frame;\nstatic _Thread_local __btrc_try_frame** __btrc_try_stac'
            'k = NULL;\nstatic _Thread_local char __btrc_error_msg[1024] = "";'
        ),
        depends_on=('__btrc_try_level',),
        required_headers=('setjmp.h',),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='trycatch',
        name='__btrc_copy_error_message',
        c_source=(
            'static inline void __btrc_copy_error_message(\n        char* destination,'
            ' size_t capacity, const char* source) {\n    if (!destination || capacity'
            " == 0) return;\n    if (!source) {\n        destination[0] = '\\0';\n       "
            ' return;\n    }\n    size_t length = 0;\n    while (length < capacity - 1 &'
            "& source[length] != '\\0') length++;\n    memmove(destination, source, len"
            "gth);\n    destination[length] = '\\0';\n}"
        ),
        depends_on=(),
        required_headers=('string.h',),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='trycatch',
        name='__btrc_try_capacity',
        c_source=(
            'static _Thread_local int __btrc_try_cap = 16;'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='trycatch',
        name='__btrc_launder_state',
        c_source=(
            'static _Thread_local void* volatile __btrc_launder_slot;'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='trycatch',
        name='__btrc_launder',
        c_source=(
            '/* Opaque pointer launder used when returning a freshly-built object\n * '
            "out of a try/catch. gcc -O2 (e.g. nix's fortify hardening) runs\n * point"
            's-to / store-merging across the setjmp(...)==0 vs catch\n * branches and,'
            ' for an object that does not otherwise escape, folds\n * the two branches'
            "' field inits together -- dropping the catch\n * object's initialization "
            "(its fields read back as the other\n * branch's values). Routing the poin"
            'ter through a volatile slot\n * forces the object to escape, which defeat'
            's that miscompilation.\n * Pure C11; the volatile access is the optimizat'
            'ion barrier. */\nstatic inline void* __btrc_launder(void* p) {\n    __btrc'
            '_launder_slot = p;\n    return __btrc_launder_slot;\n}'
        ),
        depends_on=('__btrc_launder_state',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='trycatch',
        name='__btrc_push_try',
        c_source=(
            'static inline void __btrc_push_try(void) {\n    if (__btrc_try_cap < 1) _'
            '_btrc_try_cap = 16;\n    if (__btrc_try_top == INT_MAX) { fprintf(stderr,'
            ' "btrc: try stack overflow\\n"); exit(1); }\n    if (!__btrc_try_stack) {\n'
            '        if ((size_t)__btrc_try_cap > SIZE_MAX / sizeof(*__btrc_try_stack'
            ')) { fprintf(stderr, "btrc: try stack size overflow\\n"); exit(1); }\n    '
            '    __btrc_try_stack = (__btrc_try_frame**)__btrc_safe_realloc(\n        '
            '    NULL, sizeof(*__btrc_try_stack) * (size_t)__btrc_try_cap);\n        f'
            'or (int i = 0; i < __btrc_try_cap; i++) __btrc_try_stack[i] = NULL;\n    '
            '}\n    if (__btrc_try_top + 1 >= __btrc_try_cap) {\n        if (__btrc_try'
            '_cap > INT_MAX / 2) { fprintf(stderr, "btrc: try stack capacity overflow'
            '\\n"); exit(1); }\n        int old_cap = __btrc_try_cap;\n        int new_c'
            'ap = __btrc_try_cap * 2;\n        if ((size_t)new_cap > SIZE_MAX / sizeof'
            '(*__btrc_try_stack)) { fprintf(stderr, "btrc: try stack size overflow\\n"'
            '); exit(1); }\n        __btrc_try_stack = (__btrc_try_frame**)__btrc_safe'
            '_realloc(\n            __btrc_try_stack, sizeof(*__btrc_try_stack) * (siz'
            'e_t)new_cap);\n        for (int i = old_cap; i < new_cap; i++) __btrc_try'
            '_stack[i] = NULL;\n        __btrc_try_cap = new_cap;\n    }\n    __btrc_try'
            '_top++;\n    if (!__btrc_try_stack[__btrc_try_top]) {\n        __btrc_try_'
            'stack[__btrc_try_top] = (__btrc_try_frame*)\n            __btrc_safe_real'
            'loc(NULL, sizeof(__btrc_try_frame));\n    }\n}'
        ),
        depends_on=('__btrc_trycatch_globals', '__btrc_try_capacity', '__btrc_safe_realloc'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='trycatch',
        name='__btrc_cleanup_types',
        c_source=(
            '/* Cleanup slots are opaque; generated adapters access their exact type.'
            ' */\ntypedef __btrc_destroy_fn __btrc_cleanup_fn;\ntypedef void* (*__btrc_'
            'cleanup_take_fn)(void*);\ntypedef struct { void* slot; __btrc_cleanup_tak'
            'e_fn take; __btrc_cleanup_fn fn; __btrc_visit_fn visit; int try_level; i'
            'nt direct; } __btrc_cleanup_entry;\nstatic _Thread_local __btrc_cleanup_e'
            'ntry* __btrc_cleanup_stack = NULL;\nstatic _Thread_local int __btrc_clean'
            'up_top = -1;'
        ),
        depends_on=('__btrc_try_level', '__btrc_arc_callback_types'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='trycatch',
        name='__btrc_cleanup_capacity',
        c_source=(
            'static _Thread_local int __btrc_cleanup_cap = 64;'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='trycatch',
        name='__btrc_register_cleanup_kind',
        c_source=(
            'static inline void __btrc_register_cleanup_kind(\n        void* slot, __b'
            'trc_cleanup_take_fn take,\n        __btrc_cleanup_fn fn, __btrc_visit_fn '
            'visit, int direct) {\n    if (!slot || !take || !fn) return;\n    /* Look '
            'for a superseded entry among the most recent registrations only.\n     *\n'
            '     * Finding one is an optimization, not a correctness requirement:\n  '
            '   * __btrc_run_cleanups takes every slot in the batch before running an'
            'y\n     * cleanup, and a take clears the slot it reads, so a duplicate le'
            'ft behind\n     * reads back NULL and is skipped. What the search prevent'
            's is a slot that\n     * is assigned repeatedly -- a loop body, say -- pu'
            'shing one entry per\n     * assignment, and the entry to reuse in that ca'
            'se is the one this scope\n     * pushed most recently. Scanning the whole'
            ' stack to find it made every\n     * managed assignment linear in the num'
            'ber of live entries: over a single\n     * compile of a thirty-line input'
            ', the self-hosted compiler ran 1.54 billion\n     * iterations of this lo'
            'op to serve 41,267 matches, averaging 99.9 iterations\n     * per call fo'
            'r a 0.27% hit rate. Entries are never moved, so a window\n     * measured'
            ' down from the top is stable. */\n    /* Each _Thread_local read is an ou'
            't-of-line call on some targets, so read\n     * the ones this path needs '
            'once. The reallocating branch below refreshes\n     * `stack`, which is t'
            'he only local a resize can invalidate. */\n    const int recent = 16;\n   '
            ' const int try_level = __btrc_try_top;\n    int top = __btrc_cleanup_top;'
            '\n    __btrc_cleanup_entry* stack = __btrc_cleanup_stack;\n    int oldest '
            '= top - (recent - 1);\n    if (oldest < 0) oldest = 0;\n    for (int i = t'
            'op; i >= oldest; i--) {\n        __btrc_cleanup_entry* existing = &stack['
            'i];\n        if (existing->try_level == try_level && existing->slot == sl'
            'ot) {\n            existing->take = take;\n            existing->fn = fn;\n'
            '            existing->visit = visit;\n            existing->direct = dire'
            'ct;\n            return;\n        }\n    }\n    if (__btrc_cleanup_cap < 1) '
            '__btrc_cleanup_cap = 64;\n    if (!stack) {\n        if ((size_t)__btrc_cl'
            'eanup_cap > SIZE_MAX / sizeof(__btrc_cleanup_entry)) { fprintf(stderr, "'
            'btrc: cleanup stack size overflow\\n"); exit(1); }\n        stack = (__btr'
            'c_cleanup_entry*)__btrc_safe_realloc(\n            NULL, sizeof(__btrc_cl'
            'eanup_entry) * (size_t)__btrc_cleanup_cap);\n        __btrc_cleanup_stack'
            ' = stack;\n    }\n    if (top == INT_MAX) { fprintf(stderr, "btrc: cleanup'
            ' stack overflow\\n"); exit(1); }\n    if (top + 1 >= __btrc_cleanup_cap) {'
            '\n        if (__btrc_cleanup_cap > INT_MAX / 2) { fprintf(stderr, "btrc: '
            'cleanup stack capacity overflow\\n"); exit(1); }\n        int new_cap = __'
            'btrc_cleanup_cap * 2;\n        if ((size_t)new_cap > SIZE_MAX / sizeof(__'
            'btrc_cleanup_entry)) { fprintf(stderr, "btrc: cleanup stack size overflo'
            'w\\n"); exit(1); }\n        stack = (__btrc_cleanup_entry*)__btrc_safe_rea'
            'lloc(\n            stack, sizeof(__btrc_cleanup_entry) * (size_t)new_cap)'
            ';\n        __btrc_cleanup_stack = stack;\n        __btrc_cleanup_cap = new'
            '_cap;\n    }\n    top++;\n    __btrc_cleanup_top = top;\n    stack[top] = (_'
            '_btrc_cleanup_entry){\n        slot, take, fn, visit, try_level, direct};'
            '\n}'
        ),
        depends_on=('__btrc_cleanup_types', '__btrc_cleanup_capacity', '__btrc_safe_realloc'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='trycatch',
        name='__btrc_register_cleanup',
        c_source=(
            'static inline void __btrc_register_cleanup(\n        void* slot, __btrc_c'
            'leanup_take_fn take,\n        __btrc_cleanup_fn fn, __btrc_visit_fn visit'
            ') {\n    __btrc_register_cleanup_kind(slot, take, fn, visit, 0);\n}'
        ),
        depends_on=('__btrc_register_cleanup_kind',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='trycatch',
        name='__btrc_register_direct_cleanup',
        c_source=(
            'static inline void __btrc_register_direct_cleanup(\n        void* slot, _'
            '_btrc_cleanup_take_fn take, __btrc_cleanup_fn fn) {\n    __btrc_register_'
            'cleanup_kind(slot, take, fn, NULL, 1);\n}'
        ),
        depends_on=('__btrc_register_cleanup_kind',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='trycatch',
        name='__btrc_run_cleanup_guarded',
        c_source=(
            'static void __btrc_run_cleanup_guarded(\n        __btrc_cleanup_entry ent'
            'ry, void* object) {\n    __btrc_push_try();\n    int guard_level = __btrc_'
            'try_top;\n    if (setjmp(__btrc_try_stack[guard_level]->env) != 0) return'
            ';\n    if (entry.direct) {\n        entry.fn(object);\n    } else {\n       '
            ' __btrc_arc_type type = {\n            .visit = entry.visit, .destroy = e'
            'ntry.fn,\n            .hook = NULL, .guard = NULL, .raise = NULL};\n      '
            '  /* The slot metadata is only a fallback. A base-typed slot\n         * '
            'may hold a cyclic subclass, so the concrete ARC header\n         * must c'
            'hoose whether release discovers a cycle. */\n        __btrc_arc_release(o'
            'bject, &type);\n    }\n    __btrc_try_top--;\n}'
        ),
        depends_on=('__btrc_cleanup_types', '__btrc_push_try', '__btrc_arc_release'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='trycatch',
        name='__btrc_arc_guard_hook',
        c_source=(
            'static int __btrc_arc_guard_hook(\n        __btrc_hook_fn hook, void* obj'
            'ect,\n        char* error, size_t error_capacity) {\n    char ambient[size'
            'of __btrc_error_msg];\n    memcpy(ambient, __btrc_error_msg, sizeof ambie'
            "nt);\n    if (error && error_capacity) error[0] = '\\0';\n    __btrc_push_t"
            'ry();\n    int guard_level = __btrc_try_top;\n    if (setjmp(__btrc_try_st'
            'ack[guard_level]->env) != 0) {\n        __btrc_copy_error_message(\n      '
            '      error, error_capacity, __btrc_error_msg);\n        memcpy(__btrc_er'
            'ror_msg, ambient, sizeof ambient);\n        return 1;\n    }\n    hook(obje'
            'ct);\n    __btrc_try_top--;\n    memcpy(__btrc_error_msg, ambient, sizeof '
            'ambient);\n    return 0;\n}'
        ),
        depends_on=('__btrc_arc_callback_types', '__btrc_push_try', '__btrc_copy_error_message'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='trycatch',
        name='__btrc_raise_captured',
        c_source=(
            'static _Noreturn void __btrc_raise_captured(\n        __btrc_raise_fn rai'
            'se, const char* message) {\n    if (raise) raise(message);\n    fprintf(st'
            'derr, "Unhandled exception: %s\\n", message);\n    exit(1);\n}'
        ),
        depends_on=('__btrc_arc_callback_types',),
        required_headers=('stdio.h', 'stdlib.h'),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='trycatch',
        name='__btrc_flush_cycles_guarded',
        c_source=(
            'static void __btrc_flush_cycles_guarded(void) {\n    __btrc_push_try();\n '
            '   int guard_level = __btrc_try_top;\n    if (setjmp(__btrc_try_stack[gua'
            'rd_level]->env) != 0) return;\n    __btrc_flush_cycles();\n    __btrc_try_'
            'top--;\n}'
        ),
        depends_on=('__btrc_push_try', '__btrc_flush_cycles'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='trycatch',
        name='__btrc_run_cleanups',
        c_source=(
            'static inline void __btrc_run_cleanups(int level) {\n    int base = __btr'
            'c_cleanup_top;\n    while (base >= 0 && __btrc_cleanup_stack[base].try_le'
            'vel >= level) base--;\n    base++;\n    if (base > __btrc_cleanup_top) ret'
            'urn;\n    int count = __btrc_cleanup_top - base + 1;\n    if ((size_t)coun'
            't > SIZE_MAX / sizeof(__btrc_cleanup_entry)) { fprintf(stderr, "btrc: cl'
            'eanup batch size overflow\\n"); exit(1); }\n    __btrc_cleanup_entry* entr'
            'ies = (__btrc_cleanup_entry*)__btrc_safe_realloc(\n        NULL, sizeof(_'
            '_btrc_cleanup_entry) * (size_t)count);\n    memcpy(entries, &__btrc_clean'
            'up_stack[base],\n        sizeof(__btrc_cleanup_entry) * (size_t)count);\n '
            '   __btrc_cleanup_top = base - 1;\n    if ((size_t)count > SIZE_MAX / siz'
            'eof(void*)) { fprintf(stderr, "btrc: cleanup object batch size overflow\\'
            'n"); exit(1); }\n    void** objects = (void**)__btrc_safe_realloc(\n      '
            '  NULL, sizeof(void*) * (size_t)count);\n    for (int i = count - 1; i >='
            ' 0; i--) {\n        __btrc_cleanup_entry entry = entries[i];\n        obje'
            'cts[i] = (!entry.fn || !entry.slot || !entry.take)\n            ? NULL : '
            'entry.take(entry.slot);\n    }\n    char primary_error[sizeof __btrc_error'
            '_msg];\n    memcpy(primary_error, __btrc_error_msg, sizeof primary_error)'
            ';\n    __btrc_destroyed_tracking_begin();\n    for (int i = count - 1; i >'
            '= 0; i--) {\n        __btrc_cleanup_entry entry = entries[i];\n        voi'
            'd* object = objects[i];\n        if (!object) continue;\n        if (!entr'
            'y.direct && __btrc_is_destroyed(object)) continue;\n        __btrc_run_cl'
            'eanup_guarded(entry, object);\n        memcpy(__btrc_error_msg, primary_e'
            'rror, sizeof primary_error);\n    }\n    __btrc_flush_cycles_guarded();\n  '
            '  memcpy(__btrc_error_msg, primary_error, sizeof primary_error);\n    __b'
            'trc_destroyed_tracking_end();\n    free(objects);\n    free(entries);\n}'
        ),
        depends_on=('__btrc_cleanup_types', '__btrc_safe_realloc', '__btrc_destroyed_tracking_scope', '__btrc_is_destroyed', '__btrc_run_cleanup_guarded', '__btrc_flush_cycles_guarded'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='trycatch',
        name='__btrc_discard_cleanups',
        c_source=(
            'static inline void __btrc_discard_cleanups(int level) {\n    while (__btr'
            'c_cleanup_top >= 0 &&\n           __btrc_cleanup_stack[__btrc_cleanup_top'
            '].try_level >= level) {\n        __btrc_cleanup_top--;\n    }\n}'
        ),
        depends_on=('__btrc_cleanup_types',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='trycatch',
        name='__btrc_cleanup_mark',
        c_source=(
            'static inline int __btrc_cleanup_mark(void) { return __btrc_cleanup_top;'
            ' }'
        ),
        depends_on=('__btrc_cleanup_types',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='trycatch',
        name='__btrc_discard_cleanups_to',
        c_source=(
            'static inline void __btrc_discard_cleanups_to(int mark) {\n    if (mark <'
            ' -1 || mark > __btrc_cleanup_top) {\n        fprintf(stderr, "btrc: inval'
            'id cleanup scope marker\\n");\n        exit(1);\n    }\n    __btrc_cleanup_t'
            'op = mark;\n}'
        ),
        depends_on=('__btrc_cleanup_types',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='trycatch',
        name='__btrc_throw',
        c_source=(
            'static _Noreturn void __btrc_throw(const char* msg) {\n    const char* te'
            'xt = msg ? msg : "Unknown exception";\n    __btrc_copy_error_message(\n   '
            '     __btrc_error_msg, sizeof __btrc_error_msg, text);\n    if (__btrc_tr'
            'y_top < 0) {\n        __btrc_run_cleanups(-1);\n        fprintf(stderr, "U'
            'nhandled exception: %s\\n", __btrc_error_msg);\n        exit(1);\n    }\n   '
            ' __btrc_run_cleanups(__btrc_try_top);\n    int level = __btrc_try_top;\n  '
            '  __btrc_try_top--;\n    longjmp(__btrc_try_stack[level]->env, 1);\n}'
        ),
        depends_on=('__btrc_trycatch_globals', '__btrc_copy_error_message', '__btrc_run_cleanups'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='trycatch',
        name='__btrc_try_state_cleanup',
        c_source=(
            'static void __btrc_try_state_cleanup(void) {\n    for (int i = 0; i < __b'
            'trc_try_cap; i++) {\n        free(__btrc_try_stack ? __btrc_try_stack[i] '
            ': NULL);\n    }\n    free(__btrc_try_stack);\n    free(__btrc_cleanup_stack'
            ');\n    __btrc_try_stack = NULL;\n    __btrc_cleanup_stack = NULL;\n    __b'
            'trc_try_cap = 16;\n    __btrc_cleanup_cap = 64;\n    __btrc_try_top = -1;\n'
            "    __btrc_cleanup_top = -1;\n    __btrc_error_msg[0] = '\\0';\n    __btrc_"
            'launder_slot = NULL;\n}'
        ),
        depends_on=('__btrc_trycatch_globals', '__btrc_try_capacity', '__btrc_cleanup_types', '__btrc_cleanup_capacity', '__btrc_launder_state'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='hash',
        name='__btrc_hash_real',
        c_source=(
            'static inline unsigned int __btrc_hash_real(long double value) {\n    if '
            '(value == 0.0L) return 0U;\n    /* Hash a canonical-width conversion, not'
            ' long-double padding.\n       Equal real values convert to equal doubles;'
            ' unequal values\n       may collide, which is permitted by the hash contr'
            'act. */\n    double canonical = (double)value;\n    unsigned char bytes[si'
            'zeof canonical];\n    memcpy(bytes, &canonical, sizeof canonical);\n    un'
            'signed int h = 2166136261U;\n    for (size_t i = 0; i < sizeof canonical;'
            ' ++i) {\n        h ^= (unsigned int)bytes[i];\n        h *= 16777619U;\n   '
            ' }\n    return h;\n}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='hash',
        name='__btrc_hash_str',
        c_source=(
            'static inline unsigned int __btrc_hash_str(const char* s) {\n    if (!s) '
            'return 0;\n    unsigned int h = 5381;\n    while (*s) { h = ((h << 5) + h)'
            ' + (unsigned char)*s++; }\n    return h;\n}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='collections',
        name='List_forEach',
        c_source=(
            'static inline void {name}_forEach({name}* l, void (*fn)({c_type}, void*)'
            ', void* __ctx) {{\n    if (!l || !fn) return;\n    for (int i = 0; i < l->'
            'len; i++) fn(l->data[i], __ctx);\n}}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='collections',
        name='List_filter',
        c_source=(
            'static inline {name}* {name}_filter({name}* l, bool (*fn)({c_type}, void'
            '*), void* __ctx) {{\n    {name}* result = {name}_new();\n    if (!l || !fn'
            ') return result;\n    for (int i = 0; i < l->len; i++) {{\n        if (fn('
            'l->data[i], __ctx)) {name}_push(result, l->data[i]);\n    }}\n    return r'
            'esult;\n}}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='collections',
        name='List_any',
        c_source=(
            'static inline bool {name}_any({name}* l, bool (*fn)({c_type}, void*), vo'
            'id* __ctx) {{\n    if (!l || !fn) return false;\n    for (int i = 0; i < l'
            '->len; i++) {{ if (fn(l->data[i], __ctx)) return true; }}\n    return fal'
            'se;\n}}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='collections',
        name='List_all',
        c_source=(
            'static inline bool {name}_all({name}* l, bool (*fn)({c_type}, void*), vo'
            'id* __ctx) {{\n    if (!l || !fn) return false;\n    for (int i = 0; i < l'
            '->len; i++) {{ if (!fn(l->data[i], __ctx)) return false; }}\n    return t'
            'rue;\n}}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='collections',
        name='List_findIndex',
        c_source=(
            'static inline int {name}_findIndex({name}* l, bool (*fn)({c_type}, void*'
            '), void* __ctx) {{\n    if (!l || !fn) return -1;\n    for (int i = 0; i <'
            ' l->len; i++) {{ if (fn(l->data[i], __ctx)) return i; }}\n    return -1;\n'
            '}}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='collections',
        name='List_map',
        c_source=(
            'static inline {name}* {name}_map({name}* l, {c_type} (*fn)({c_type}, voi'
            'd*), void* __ctx) {{\n    {name}* result = {name}_new();\n    if (!l || !f'
            'n) return result;\n    for (int i = 0; i < l->len; i++) {name}_push(resul'
            't, fn(l->data[i], __ctx));\n    return result;\n}}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='collections',
        name='List_reduce',
        c_source=(
            'static inline {c_type} {name}_reduce({name}* l, {c_type} init, {c_type} '
            '(*fn)({c_type}, {c_type})) {{\n    if (!l || !fn) return init;\n    {c_typ'
            'e} acc = init;\n    for (int i = 0; i < l->len; i++) acc = fn(acc, l->dat'
            'a[i]);\n    return acc;\n}}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='collections',
        name='Map_forEach',
        c_source=(
            'static inline void {name}_forEach({name}* m, void (*fn)({k_type}, {v_typ'
            'e}, void*), void* __ctx) {{\n    if (!m || !fn) return;\n    for (int i = '
            '0; i < m->cap; i++) {{\n        if (m->occupied[i]) fn(m->keys[i], m->val'
            'ues[i], __ctx);\n    }}\n}}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='collections',
        name='Map_containsValue',
        c_source=(
            'static inline bool {name}_containsValue({name}* m, {v_type} value) {{\n  '
            '  if (!m) return false;\n    for (int i = 0; i < m->cap; i++) {{\n        '
            'if (m->occupied[i] && {val_eq}) return true;\n    }}\n    return false;\n}}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='collections',
        name='Set_forEach',
        c_source=(
            'static inline void {name}_forEach({name}* s, void (*fn)({c_type}, void*)'
            ', void* __ctx) {{\n    if (!s || !fn) return;\n    for (int i = 0; i < s->'
            'cap; i++) {{\n        if (s->occupied[i]) fn(s->keys[i], __ctx);\n    }}\n}'
            '}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='collections',
        name='Set_filter',
        c_source=(
            'static inline {name}* {name}_filter({name}* s, bool (*fn)({c_type}, void'
            '*), void* __ctx) {{\n    {name}* result = {name}_new();\n    if (!s || !fn'
            ') return result;\n    for (int i = 0; i < s->cap; i++) {{\n        if (s->'
            'occupied[i] && fn(s->keys[i], __ctx)) {{\n            {name}_add(result, '
            's->keys[i]);\n        }}\n    }}\n    return result;\n}}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='collections',
        name='Set_any',
        c_source=(
            'static inline bool {name}_any({name}* s, bool (*fn)({c_type}, void*), vo'
            'id* __ctx) {{\n    if (!s || !fn) return false;\n    for (int i = 0; i < s'
            '->cap; i++) {{\n        if (s->occupied[i] && fn(s->keys[i], __ctx)) retu'
            'rn true;\n    }}\n    return false;\n}}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='collections',
        name='Set_all',
        c_source=(
            'static inline bool {name}_all({name}* s, bool (*fn)({c_type}, void*), vo'
            'id* __ctx) {{\n    if (!s || !fn) return false;\n    for (int i = 0; i < s'
            '->cap; i++) {{\n        if (s->occupied[i] && !fn(s->keys[i], __ctx)) ret'
            'urn false;\n    }}\n    return true;\n}}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='collections',
        name='Set_findIndex',
        c_source=(
            'static inline int {name}_findIndex({name}* s, bool (*fn)({c_type}, void*'
            '), void* __ctx) {{\n    if (!s || !fn) return -1;\n    for (int i = 0; i <'
            ' s->cap; i++) {{\n        if (s->occupied[i] && fn(s->keys[i], __ctx)) re'
            'turn i;\n    }}\n    return -1;\n}}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_callback_types',
        c_source=(
            '/* Type-erased ARC metadata shared by ownership paths. */\ntypedef int __'
            'btrc_arc_count;\ntypedef struct __btrc_arc_type __btrc_arc_type;\ntypedef '
            'struct __btrc_arc_incoming __btrc_arc_incoming;\ntypedef enum {\n    __BTR'
            'C_ARC_LIVE = 1,\n    __BTRC_ARC_QUEUED = 2,\n    __BTRC_ARC_DESTROYING = 3'
            '\n} __btrc_arc_state;\ntypedef struct __btrc_arc_header {\n    __btrc_arc_c'
            'ount rc;\n    __btrc_arc_count edge_rc;\n    /* One current incoming-edge '
            'owner, or self as a full-snapshot sentinel. */\n    void* live_witness;\n '
            '   const __btrc_arc_type* type;\n    __btrc_arc_incoming* incoming;\n    v'
            'oid* deferred_next;\n    unsigned char suppress_hook;\n    __btrc_arc_stat'
            'e state;\n} __btrc_arc_header;\nstruct __btrc_arc_incoming {\n    void* own'
            'er;\n    __btrc_arc_incoming* next;\n};\ntypedef void (*__btrc_destroy_fn)('
            'void*);\ntypedef void* (*__btrc_arc_slot_access_fn)(\n    volatile void*, '
            'void*, void*, int);\ntypedef void (*__btrc_field_visit_fn)(\n    volatile '
            'void*, __btrc_arc_slot_access_fn,\n    const __btrc_arc_type*, void*);\nty'
            'pedef void (*__btrc_visit_fn)(\n    void*, __btrc_field_visit_fn, void*);'
            '\ntypedef void (*__btrc_hook_fn)(void*);\ntypedef int (*__btrc_hook_guard_'
            'fn)(\n    __btrc_hook_fn, void*, char*, size_t);\ntypedef void (*__btrc_ra'
            'ise_fn)(const char*);\nstruct __btrc_arc_type {\n    __btrc_visit_fn visit'
            ';\n    __btrc_destroy_fn destroy;\n    __btrc_hook_fn hook;\n    __btrc_hoo'
            'k_guard_fn guard;\n    __btrc_raise_fn raise;\n};'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=('__btrc_arc_count', '__btrc_arc_type', '__btrc_arc_incoming', '__btrc_arc_state', '__btrc_arc_header', '__btrc_destroy_fn', '__btrc_arc_slot_access_fn', '__btrc_field_visit_fn', '__btrc_visit_fn', '__btrc_hook_fn', '__btrc_hook_guard_fn', '__btrc_raise_fn'),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_header_of',
        c_source=(
            'static inline __btrc_arc_header* __btrc_arc_header_of(void* object) {\n  '
            '  return (__btrc_arc_header*)object;\n}'
        ),
        depends_on=('__btrc_arc_callback_types',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_type_of',
        c_source=(
            'static inline const __btrc_arc_type* __btrc_arc_type_of(\n        void* o'
            'bject, const __btrc_arc_type* fallback) {\n    if (object && __btrc_arc_h'
            'eader_of(object)->type)\n        return __btrc_arc_header_of(object)->typ'
            'e;\n    return fallback;\n}'
        ),
        depends_on=('__btrc_arc_header_of',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_validate',
        c_source=(
            'static inline void __btrc_arc_validate(void* object) {\n    if (!object) '
            'return;\n    __btrc_arc_header* header = __btrc_arc_header_of(object);\n  '
            '  int live = header->state == __BTRC_ARC_LIVE\n        && header->rc > 0 '
            '&& header->edge_rc >= 0\n        && header->edge_rc <= header->rc\n       '
            ' && header->deferred_next == NULL && !header->suppress_hook;\n    int que'
            'ued = header->state == __BTRC_ARC_QUEUED\n        && header->rc == 0 && h'
            'eader->edge_rc == 0\n        && header->live_witness == NULL && header->i'
            'ncoming == NULL;\n    int destroying = header->state == __BTRC_ARC_DESTRO'
            'YING\n        && header->rc == 0 && header->edge_rc == 0\n        && heade'
            'r->live_witness == NULL && header->incoming == NULL\n        && header->d'
            'eferred_next == NULL && !header->suppress_hook;\n    if ((!live && !queue'
            'd && !destroying) || !header->type\n            || !header->type->destroy'
            '\n            || (header->type->hook\n                && (!header->type->g'
            'uard || !header->type->raise))) {\n        fprintf(stderr, "btrc: invalid'
            ' ARC header\\n");\n        exit(1);\n    }\n}'
        ),
        depends_on=('__btrc_arc_header_of',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_destroyed_tracking',
        c_source=(
            '/* ARC cascade-destroy tracking: avoid reading freed memory */\nstatic _T'
            'hread_local int __btrc_tracking = 0;\nstatic _Thread_local void** __btrc_'
            'destroyed = NULL;\nstatic _Thread_local int __btrc_destroyed_count = 0;'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_destroyed_tracking_scope',
        c_source=(
            'static void __btrc_destroyed_tracking_begin(void) {\n    __btrc_arc_lock_'
            'mutation();\n    int active = __btrc_tracking;\n    if (active == 0) {\n   '
            '     __btrc_destroyed_count = 0;\n        if (__btrc_arc_active_unwinds ='
            '= INT_MAX) {\n            fprintf(stderr, "btrc: active unwind count over'
            'flow\\n");\n            exit(1);\n        }\n        __btrc_arc_active_unwin'
            'ds++;\n    }\n    if (active == INT_MAX) {\n        fprintf(stderr, "btrc: '
            'destroyed tracking depth overflow\\n");\n        exit(1);\n    }\n    __btrc'
            '_tracking = active + 1;\n    __btrc_arc_unlock_mutation();\n}\nstatic void '
            '__btrc_destroyed_tracking_end(void) {\n    __btrc_arc_lock_mutation();\n  '
            '  int active = __btrc_tracking;\n    if (active <= 0) {\n        fprintf(s'
            'tderr, "btrc: unbalanced destroyed tracking scope\\n");\n        exit(1);\n'
            '    }\n    active--;\n    __btrc_tracking = active;\n    if (active == 0) {'
            '\n        __btrc_destroyed_count = 0;\n        if (__btrc_arc_active_unwin'
            'ds <= 0) {\n            fprintf(stderr, "btrc: invalid active unwind coun'
            't\\n");\n            exit(1);\n        }\n        __btrc_arc_active_unwinds-'
            '-;\n    }\n    __btrc_arc_unlock_mutation();\n}'
        ),
        depends_on=('__btrc_destroyed_tracking', '__btrc_arc_mutation_lock', '__btrc_arc_active_unwinds_state'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_is_destroyed',
        c_source=(
            'static int __btrc_is_destroyed(void* ptr) {\n    if (!ptr) return 0;\n    '
            '__btrc_arc_lock_mutation();\n    for (int i = 0; i < __btrc_destroyed_cou'
            'nt; i++) {\n        if (__btrc_destroyed[i] != ptr) continue;\n        __b'
            'trc_arc_unlock_mutation();\n        return 1;\n    }\n    __btrc_arc_unlock'
            '_mutation();\n    return 0;\n}'
        ),
        depends_on=('__btrc_destroyed_tracking', '__btrc_arc_mutation_lock'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_destroyed_capacity',
        c_source=(
            'static _Thread_local int __btrc_destroyed_cap = 0;'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_mark_destroyed',
        c_source=(
            'static void __btrc_mark_destroyed(void* ptr) {\n    if (!ptr) return;\n   '
            ' __btrc_arc_lock_mutation();\n    if (!__btrc_tracking) {\n        __btrc_'
            'arc_unlock_mutation();\n        return;\n    }\n    if (__btrc_destroyed_co'
            'unt < 0 || __btrc_destroyed_cap < 0\n            || __btrc_destroyed_coun'
            't > __btrc_destroyed_cap) {\n        fprintf(stderr, "btrc: invalid destr'
            'oyed tracking capacity\\n");\n        exit(1);\n    }\n    for (int i = 0; i'
            ' < __btrc_destroyed_count; i++) {\n        if (__btrc_destroyed[i] != ptr'
            ') continue;\n        __btrc_arc_unlock_mutation();\n        return;\n    }\n'
            '    if (__btrc_destroyed_count >= __btrc_destroyed_cap) {\n        if (__'
            'btrc_destroyed_cap > INT_MAX / 2) { fprintf(stderr, "btrc: destroyed tra'
            'cking overflow\\n"); exit(1); }\n        int new_cap = __btrc_destroyed_ca'
            'p ? __btrc_destroyed_cap * 2 : 256;\n        if ((size_t)new_cap > SIZE_M'
            'AX / sizeof(void*)) { fprintf(stderr, "btrc: destroyed tracking size ove'
            'rflow\\n"); exit(1); }\n        size_t bytes = sizeof(void*) * (size_t)new'
            '_cap;\n        __btrc_destroyed = (void**)__btrc_safe_realloc(\n          '
            '  __btrc_destroyed, bytes);\n        __btrc_destroyed_cap = new_cap;\n    '
            '}\n    __btrc_destroyed[__btrc_destroyed_count++] = ptr;\n    __btrc_arc_u'
            'nlock_mutation();\n}'
        ),
        depends_on=('__btrc_destroyed_tracking', '__btrc_destroyed_capacity', '__btrc_safe_realloc', '__btrc_arc_mutation_lock'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_suspect_state',
        c_source=(
            '/* ARC cycle detection: suspect buffer */\nstatic void** __btrc_suspects '
            '= NULL;\nstatic int __btrc_suspect_count = 0;\nstatic __btrc_visit_fn* __b'
            'trc_visit_table = NULL;\nstatic __btrc_destroy_fn* __btrc_destroy_table ='
            ' NULL;\nstatic void** __btrc_suspect_keys = NULL;\nstatic int __btrc_suspe'
            'ct_key_cap = 0;'
        ),
        depends_on=('__btrc_arc_callback_types',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_suspect_capacity',
        c_source=(
            'static int __btrc_suspect_cap = 0;'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_ptr_hash',
        c_source=(
            'static size_t __btrc_ptr_hash(const void* ptr) {\n    uintptr_t value = ('
            'uintptr_t)ptr;\n    value ^= value >> 17;\n    value ^= value >> 9;\n    re'
            'turn (size_t)value;\n}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_suspect_locked',
        c_source=(
            'static int __btrc_suspect_next_capacity(\n        int capacity, const cha'
            'r* message) {\n    if (capacity < 0 || capacity > INT_MAX / 2) {\n        '
            'fprintf(stderr, "btrc: %s\\n", message);\n        exit(1);\n    }\n    retur'
            'n capacity ? capacity * 2 : 256;\n}\nstatic size_t __btrc_suspect_capacity'
            '_bytes(\n        int capacity, size_t element_size, const char* message) '
            '{\n    if (capacity < 0 || (element_size != 0\n            && (size_t)capa'
            'city > SIZE_MAX / element_size)) {\n        fprintf(stderr, "btrc: %s\\n",'
            ' message);\n        exit(1);\n    }\n    return (size_t)capacity * element_'
            'size;\n}\nstatic void __btrc_grow_suspect_keys_locked(void) {\n    int cap '
            '= __btrc_suspect_next_capacity(\n        __btrc_suspect_key_cap, "cycle s'
            'uspect hash overflow");\n    size_t bytes = __btrc_suspect_capacity_bytes'
            '(\n        cap, sizeof(void*), "cycle suspect hash size overflow");\n    v'
            'oid** keys = (void**)__btrc_safe_calloc(1, bytes);\n    for (int i = 0; i'
            ' < __btrc_suspect_count; i++) {\n        size_t index = __btrc_ptr_hash(_'
            '_btrc_suspects[i]) & ((size_t)cap - 1);\n        while (keys[index]) inde'
            'x = (index + 1) & ((size_t)cap - 1);\n        keys[index] = __btrc_suspec'
            'ts[i];\n    }\n    free(__btrc_suspect_keys);\n    __btrc_suspect_keys = ke'
            'ys;\n    __btrc_suspect_key_cap = cap;\n}\nstatic inline void __btrc_suspec'
            't_locked(void* obj, __btrc_visit_fn visit,\n                           __'
            'btrc_destroy_fn destroy) {\n    if (!obj) return;\n    __btrc_arc_validate'
            '(obj);\n    __btrc_arc_header* header = __btrc_arc_header_of(obj);\n    if'
            ' (header->rc > header->edge_rc) return;\n    __btrc_arc_type fallback = {'
            '\n        .visit = visit, .destroy = destroy,\n        .hook = NULL, .guar'
            'd = NULL, .raise = NULL};\n    const __btrc_arc_type* type = __btrc_arc_t'
            'ype_of(obj, &fallback);\n    if (!type || !type->visit || !type->destroy)'
            ' return;\n    if (__btrc_suspect_count < 0 || __btrc_suspect_count == INT'
            '_MAX\n            || __btrc_suspect_cap < 0\n            || __btrc_suspect'
            '_count > __btrc_suspect_cap) {\n        fprintf(stderr, "btrc: cycle susp'
            'ect overflow\\n");\n        exit(1);\n    }\n    if (__btrc_suspect_key_cap '
            '== 0\n            || __btrc_suspect_count >= __btrc_suspect_key_cap / 2)\n'
            '        __btrc_grow_suspect_keys_locked();\n    size_t key = __btrc_ptr_h'
            'ash(obj)\n        & ((size_t)__btrc_suspect_key_cap - 1);\n    while (__bt'
            'rc_suspect_keys[key]) {\n        if (__btrc_suspect_keys[key] == obj) ret'
            'urn;\n        key = (key + 1) & ((size_t)__btrc_suspect_key_cap - 1);\n   '
            ' }\n    if (__btrc_suspect_count >= __btrc_suspect_cap) {\n        int new'
            '_cap = __btrc_suspect_next_capacity(\n            __btrc_suspect_cap, "cy'
            'cle suspect overflow");\n        size_t object_bytes = __btrc_suspect_cap'
            'acity_bytes(\n            new_cap, sizeof(void*), "cycle suspect size ove'
            'rflow");\n        size_t visit_bytes = __btrc_suspect_capacity_bytes(\n   '
            '         new_cap, sizeof(__btrc_visit_fn),\n            "cycle suspect si'
            'ze overflow");\n        size_t destroy_bytes = __btrc_suspect_capacity_by'
            'tes(\n            new_cap, sizeof(__btrc_destroy_fn),\n            "cycle '
            'suspect size overflow");\n        __btrc_suspects = (void**)__btrc_safe_r'
            'ealloc(\n            __btrc_suspects, object_bytes);\n        __btrc_visit'
            '_table = (__btrc_visit_fn*)__btrc_safe_realloc(\n            __btrc_visit'
            '_table, visit_bytes);\n        __btrc_destroy_table = (__btrc_destroy_fn*'
            ')__btrc_safe_realloc(\n            __btrc_destroy_table, destroy_bytes);\n'
            '        __btrc_suspect_cap = new_cap;\n    }\n    __btrc_suspects[__btrc_s'
            'uspect_count] = obj;\n    __btrc_visit_table[__btrc_suspect_count] = type'
            '->visit;\n    __btrc_destroy_table[__btrc_suspect_count] = type->destroy;'
            '\n    __btrc_suspect_keys[key] = obj;\n    __btrc_suspect_count++;\n}'
        ),
        depends_on=('__btrc_suspect_state', '__btrc_suspect_capacity', '__btrc_ptr_hash', '__btrc_safe_calloc', '__btrc_safe_realloc', '__btrc_arc_type_of', '__btrc_arc_validate'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_suspect',
        c_source=(
            'static inline void __btrc_suspect(\n        void* obj, __btrc_visit_fn vi'
            'sit, __btrc_destroy_fn destroy) {\n    __btrc_arc_lock_mutation();\n    __'
            'btrc_suspect_locked(obj, visit, destroy);\n    __btrc_arc_unlock_mutation'
            '();\n}'
        ),
        depends_on=('__btrc_suspect_locked', '__btrc_arc_mutation_lock'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_lock_state',
        c_source=(
            '/* One process-wide lock domain for ARC topology. */\nstatic atomic_flag '
            '__btrc_arc_lock_flag = ATOMIC_FLAG_INIT;\n\nstatic void __btrc_arc_lock_ra'
            'w(void) {\n    while (atomic_flag_test_and_set_explicit(\n            &__b'
            'trc_arc_lock_flag, memory_order_acquire)) {}\n}\nstatic void __btrc_arc_un'
            'lock_raw(void) {\n    atomic_flag_clear_explicit(\n        &__btrc_arc_loc'
            'k_flag, memory_order_release);\n}'
        ),
        depends_on=(),
        required_headers=('stdatomic.h',),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_shutdown_state',
        c_source=(
            'static int __btrc_arc_shutdown = 0;'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_active_drains_state',
        c_source=(
            'static int __btrc_arc_active_drains = 0;'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_active_unwinds_state',
        c_source=(
            'static int __btrc_arc_active_unwinds = 0;'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_snapshot_state',
        c_source=(
            'static _Atomic int __btrc_arc_snapshotting = 0;'
        ),
        depends_on=(),
        required_headers=('stdatomic.h',),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_mutation_lock',
        c_source=(
            'static void __btrc_arc_lock_mutation(void) {\n    for (;;) {\n        __bt'
            'rc_arc_lock_raw();\n        if (__btrc_arc_shutdown) {\n            __btrc'
            '_arc_unlock_raw();\n            fprintf(stderr, "btrc: ARC operation afte'
            'r shutdown\\n");\n            exit(1);\n        }\n        if (!atomic_load_'
            'explicit(\n                &__btrc_arc_snapshotting, memory_order_acquire'
            '))\n            return;\n        __btrc_arc_unlock_raw();\n        while (a'
            'tomic_load_explicit(\n                &__btrc_arc_snapshotting, memory_or'
            'der_acquire)) {}\n    }\n}\nstatic void __btrc_arc_unlock_mutation(void) {\n'
            '    __btrc_arc_unlock_raw();\n}'
        ),
        depends_on=('__btrc_arc_lock_state', '__btrc_arc_snapshot_state', '__btrc_arc_shutdown_state'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_topology_state',
        c_source=(
            'static int __btrc_arc_topology_active = 0;\nstatic int __btrc_arc_topolog'
            'y_flush_pending = 0;'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_topology_depth_state',
        c_source=(
            'static _Thread_local int __btrc_arc_topology_depth = 0;\nstatic _Thread_l'
            'ocal int __btrc_arc_draining = 0;'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_topology_begin',
        c_source=(
            'static void* __btrc_arc_topology_begin(void) {\n    if (__btrc_arc_topolo'
            'gy_depth > 0) {\n        if (__btrc_arc_topology_depth == INT_MAX) {\n    '
            '        fprintf(stderr, "btrc: ARC topology scope overflow\\n");\n        '
            '    exit(1);\n        }\n        __btrc_arc_topology_depth++;\n        retu'
            'rn (void*)&__btrc_arc_topology_active;\n    }\n    for (;;) {\n        __bt'
            'rc_arc_lock_raw();\n        if (__btrc_arc_shutdown) {\n            __btrc'
            '_arc_unlock_raw();\n            fprintf(stderr, "btrc: ARC operation afte'
            'r shutdown\\n");\n            exit(1);\n        }\n        if (!atomic_load_'
            'explicit(\n                &__btrc_arc_snapshotting, memory_order_acquire'
            ')\n                && !atomic_load_explicit(\n                    &__btrc_'
            'arc_snapshot_pending, memory_order_acquire)\n                && (!__btrc_'
            'arc_topology_flush_pending\n                    || __btrc_arc_draining)) '
            '{\n            if (__btrc_arc_topology_active == INT_MAX) {\n             '
            '   fprintf(stderr, "btrc: ARC topology scope overflow\\n");\n             '
            '   exit(1);\n            }\n            __btrc_arc_topology_active++;\n    '
            '        __btrc_arc_topology_depth = 1;\n            __btrc_arc_unlock_raw'
            '();\n            return (void*)&__btrc_arc_topology_active;\n        }\n   '
            '     __btrc_arc_unlock_raw();\n        while (atomic_load_explicit(\n     '
            '               &__btrc_arc_snapshot_pending, memory_order_acquire)\n     '
            '           || atomic_load_explicit(\n                    &__btrc_arc_snap'
            'shotting, memory_order_acquire)) {}\n    }\n}'
        ),
        depends_on=('__btrc_arc_lock_state', '__btrc_arc_snapshot_state', '__btrc_arc_snapshot_gate_state', '__btrc_arc_shutdown_state', '__btrc_arc_topology_state', '__btrc_arc_topology_depth_state'),
        required_headers=('limits.h', 'stdio.h', 'stdlib.h'),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_topology_leave',
        c_source=(
            'static int __btrc_arc_topology_leave(void* token) {\n    if (!token) retu'
            'rn 0;\n    if (token != (void*)&__btrc_arc_topology_active\n            ||'
            ' __btrc_arc_topology_depth <= 0) {\n        fprintf(stderr, "btrc: invali'
            'd ARC topology scope\\n");\n        exit(1);\n    }\n    __btrc_arc_topology'
            '_depth--;\n    if (__btrc_arc_topology_depth > 0) return 0;\n    __btrc_ar'
            'c_lock_raw();\n    if (__btrc_arc_shutdown) {\n        __btrc_arc_unlock_r'
            'aw();\n        fprintf(stderr, "btrc: ARC operation after shutdown\\n");\n '
            '       exit(1);\n    }\n    if (__btrc_arc_topology_active <= 0) {\n       '
            ' fprintf(stderr, "btrc: invalid ARC topology scope\\n");\n        exit(1);'
            '\n    }\n    __btrc_arc_topology_active--;\n    int should_flush = __btrc_a'
            'rc_topology_active == 0\n        && __btrc_arc_topology_flush_pending;\n  '
            '  __btrc_arc_unlock_raw();\n    return should_flush;\n}'
        ),
        depends_on=('__btrc_arc_lock_state', '__btrc_arc_shutdown_state', '__btrc_arc_topology_state', '__btrc_arc_topology_depth_state'),
        required_headers=('stdio.h', 'stdlib.h'),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_topology_cleanup',
        c_source=(
            'static void __btrc_arc_topology_cleanup(void* token) {\n    int should_fl'
            'ush = __btrc_arc_topology_leave(token);\n    __btrc_arc_drain_pending_aba'
            'ndons();\n    if (should_flush)\n        (void)__btrc_flush_cycles();\n    '
            '__btrc_arc_drain_deferred(0);\n}'
        ),
        depends_on=('__btrc_arc_topology_leave', '__btrc_arc_abandon_queue_drain', '__btrc_flush_cycles', '__btrc_arc_drain'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_topology_complete',
        c_source=(
            'static void __btrc_arc_topology_complete(\n        void* volatile* token_'
            'ref) {\n    if (!token_ref || !*token_ref) return;\n    void* token = *tok'
            'en_ref;\n    *token_ref = NULL;\n    int should_flush = __btrc_arc_topolog'
            'y_leave(token);\n    __btrc_arc_drain_pending_abandons();\n    if (should_'
            'flush)\n        (void)__btrc_flush_cycles();\n    __btrc_arc_drain_deferre'
            'd(0);\n}'
        ),
        depends_on=('__btrc_arc_topology_leave', '__btrc_arc_abandon_queue_drain', '__btrc_flush_cycles', '__btrc_arc_drain'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_deferred_state',
        c_source=(
            '/* Per-thread intrusive FIFO for terminal ARC work. */\nstatic _Thread_lo'
            'cal void* __btrc_arc_deferred_head = NULL;\nstatic _Thread_local void* __'
            'btrc_arc_deferred_tail = NULL;\n\nstatic _Noreturn void __btrc_arc_raise_u'
            'nlocked(\n        const __btrc_arc_type* type, const char* message) {\n   '
            ' if (type && type->raise) type->raise(message);\n    fprintf(stderr, "Unh'
            'andled exception: %s\\n", message);\n    exit(1);\n}\n\nstatic void __btrc_ar'
            'c_enqueue_locked(void* object) {\n    __btrc_arc_header* header = __btrc_'
            'arc_header_of(object);\n    if (header->state != __BTRC_ARC_LIVE\n        '
            '    || header->rc != 0 || header->edge_rc != 0\n            || header->in'
            'coming != NULL || header->deferred_next != NULL) {\n        fprintf(stder'
            'r, "btrc: invalid ARC enqueue\\n");\n        exit(1);\n    }\n    header->li'
            've_witness = NULL;\n    header->state = __BTRC_ARC_QUEUED;\n    if (__btrc'
            '_arc_deferred_tail) {\n        __btrc_arc_header_of(__btrc_arc_deferred_t'
            'ail)->deferred_next = object;\n    } else {\n        __btrc_arc_deferred_h'
            'ead = object;\n    }\n    __btrc_arc_deferred_tail = object;\n}'
        ),
        depends_on=('__btrc_arc_callback_types', '__btrc_arc_header_of'),
        required_headers=('stdio.h', 'stdlib.h'),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_snapshot_gate_state',
        c_source=(
            '/* Publish snapshot intent before waiting for topology owners. */\nstatic'
            ' _Atomic int __btrc_arc_snapshot_pending = 0;'
        ),
        depends_on=(),
        required_headers=('stdatomic.h',),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_exclusive_snapshot',
        c_source=(
            'static void __btrc_arc_exclusive_snapshot_begin(void) {\n    for (;;) {\n '
            '       __btrc_arc_lock_raw();\n        if (__btrc_arc_shutdown) {\n       '
            '     __btrc_arc_unlock_raw();\n            fprintf(stderr, "btrc: ARC ope'
            'ration after shutdown\\n");\n            exit(1);\n        }\n        if (__'
            'btrc_arc_topology_depth != 0) {\n            fprintf(stderr, "btrc: ARC s'
            'napshot inside topology mutation\\n");\n            exit(1);\n        }\n   '
            '     if (!atomic_load_explicit(\n                    &__btrc_arc_snapshot'
            '_pending, memory_order_acquire)\n                && !atomic_load_explicit'
            '(\n                    &__btrc_arc_snapshotting, memory_order_acquire)) {'
            '\n            atomic_store_explicit(\n                &__btrc_arc_snapshot'
            '_pending, 1, memory_order_release);\n            __btrc_arc_unlock_raw();'
            '\n            break;\n        }\n        __btrc_arc_unlock_raw();\n        w'
            'hile (atomic_load_explicit(\n                    &__btrc_arc_snapshot_pen'
            'ding, memory_order_acquire)\n                || atomic_load_explicit(\n   '
            '                 &__btrc_arc_snapshotting, memory_order_acquire)) {}\n   '
            ' }\n    for (;;) {\n        __btrc_arc_lock_raw();\n        if (__btrc_arc_'
            'shutdown) {\n            __btrc_arc_unlock_raw();\n            fprintf(std'
            'err, "btrc: ARC operation after shutdown\\n");\n            exit(1);\n     '
            '   }\n        if (__btrc_arc_topology_active == 0) {\n            atomic_s'
            'tore_explicit(\n                &__btrc_arc_snapshotting, 1, memory_order'
            '_release);\n            atomic_store_explicit(\n                &__btrc_ar'
            'c_snapshot_pending, 0, memory_order_release);\n            __btrc_arc_unl'
            'ock_raw();\n            return;\n        }\n        __btrc_arc_unlock_raw()'
            ';\n    }\n}\n\nstatic void __btrc_arc_exclusive_snapshot_end(void) {\n    __b'
            'trc_arc_lock_raw();\n    if (!atomic_load_explicit(\n            &__btrc_a'
            'rc_snapshotting, memory_order_acquire)) {\n        fprintf(stderr, "btrc:'
            ' invalid ARC snapshot completion\\n");\n        exit(1);\n    }\n    atomic_'
            'store_explicit(\n        &__btrc_arc_snapshotting, 0, memory_order_releas'
            'e);\n    __btrc_arc_unlock_raw();\n}'
        ),
        depends_on=('__btrc_arc_lock_state', '__btrc_arc_snapshot_state', '__btrc_arc_snapshot_gate_state', '__btrc_arc_shutdown_state', '__btrc_arc_topology_state', '__btrc_arc_topology_depth_state'),
        required_headers=('limits.h', 'stdio.h', 'stdlib.h'),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_reverse_state',
        c_source=(
            '/* Scratch state for exact reverse-root classification. */\nstatic void**'
            ' __btrc_reverse_queue = NULL;\nstatic int __btrc_reverse_queue_cap = 0;\ns'
            'tatic void** __btrc_reverse_keys = NULL;\nstatic unsigned int* __btrc_rev'
            'erse_marks = NULL;\nstatic int __btrc_reverse_key_cap = 0;\nstatic int __b'
            'trc_reverse_count = 0;\nstatic unsigned int __btrc_reverse_epoch = 0;'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_register_incoming',
        c_source=(
            'static void __btrc_arc_register_incoming(\n        void* object, void* ow'
            'ner) {\n    if (!owner) {\n        fprintf(stderr, "btrc: managed edge req'
            'uires an owner\\n");\n        exit(1);\n    }\n    __btrc_arc_incoming* inco'
            'ming = (__btrc_arc_incoming*)\n        __btrc_safe_realloc(NULL, sizeof(_'
            '_btrc_arc_incoming));\n    incoming->owner = owner;\n    incoming->next = '
            '__btrc_arc_header_of(object)->incoming;\n    __btrc_arc_header_of(object)'
            '->incoming = incoming;\n    if (owner != object) __btrc_arc_header_of(obj'
            'ect)->live_witness = owner;\n}'
        ),
        depends_on=('__btrc_arc_header_of', '__btrc_safe_realloc'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_unregister_incoming',
        c_source=(
            'static void __btrc_arc_unregister_incoming(\n        void* object, void* '
            'owner) {\n    __btrc_arc_header* header = __btrc_arc_header_of(object);\n '
            '   if (!owner) {\n        header->live_witness = NULL;\n        return;\n  '
            '  }\n    __btrc_arc_incoming** link = &header->incoming;\n    while (*link'
            ' && (*link)->owner != owner) link = &(*link)->next;\n    if (!*link) {\n  '
            '      fprintf(stderr, "btrc: missing managed incoming edge\\n");\n        '
            'exit(1);\n    }\n    __btrc_arc_incoming* removed = *link;\n    *link = rem'
            'oved->next;\n    free(removed);\n    if (header->live_witness == object ||'
            ' header->live_witness == owner) {\n        header->live_witness = NULL;\n '
            '       for (__btrc_arc_incoming* edge = header->incoming;\n              '
            '  edge; edge = edge->next) {\n            if (edge->owner != object) {\n  '
            '              header->live_witness = edge->owner;\n                break;'
            '\n            }\n        }\n    }\n}'
        ),
        depends_on=('__btrc_arc_header_of',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_incoming_teardown_pending',
        c_source=(
            'static int __btrc_arc_incoming_teardown_pending(\n        void* object) {'
            '\n    __btrc_arc_header* header = __btrc_arc_header_of(object);\n    if (!'
            'header->incoming) return 0;\n    for (__btrc_arc_incoming* edge = header-'
            '>incoming;\n            edge; edge = edge->next) {\n        void* owner = '
            'edge->owner;\n        if (!owner || owner == object) return 0;\n        __'
            'btrc_arc_validate(owner);\n        if (__btrc_arc_header_of(owner)->state'
            ' != __BTRC_ARC_DESTROYING)\n            return 0;\n    }\n    return 1;\n}'
        ),
        depends_on=('__btrc_arc_validate',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_reverse_proves_live',
        c_source=(
            'static int __btrc_reverse_next_capacity(\n        int capacity, const cha'
            'r* message) {\n    if (capacity < 0 || capacity > INT_MAX / 2) {\n        '
            'fprintf(stderr, "btrc: %s\\n", message);\n        exit(1);\n    }\n    retur'
            'n capacity ? capacity * 2 : 256;\n}\nstatic size_t __btrc_reverse_capacity'
            '_bytes(\n        int capacity, size_t element_size, const char* message) '
            '{\n    if (capacity < 0 || (element_size != 0\n            && (size_t)capa'
            'city > SIZE_MAX / element_size)) {\n        fprintf(stderr, "btrc: %s\\n",'
            ' message);\n        exit(1);\n    }\n    return (size_t)capacity * element_'
            'size;\n}\nstatic void __btrc_reverse_reserve_queue(int needed) {\n    if (n'
            'eeded < 0 || __btrc_reverse_queue_cap < 0) {\n        fprintf(stderr, "bt'
            'rc: reverse ARC queue overflow\\n");\n        exit(1);\n    }\n    if (neede'
            'd <= __btrc_reverse_queue_cap) return;\n    int cap = __btrc_reverse_queu'
            'e_cap;\n    while (cap < needed)\n        cap = __btrc_reverse_next_capaci'
            'ty(\n            cap, "reverse ARC queue overflow");\n    size_t bytes = _'
            '_btrc_reverse_capacity_bytes(\n        cap, sizeof(void*), "reverse ARC q'
            'ueue size overflow");\n    __btrc_reverse_queue = (void**)__btrc_safe_rea'
            'lloc(\n        __btrc_reverse_queue, bytes);\n    __btrc_reverse_queue_cap'
            ' = cap;\n}\nstatic void __btrc_reverse_grow_keys(void) {\n    int cap = __b'
            'trc_reverse_next_capacity(\n        __btrc_reverse_key_cap, "reverse ARC '
            'hash overflow");\n    size_t key_bytes = __btrc_reverse_capacity_bytes(\n '
            '       cap, sizeof(void*), "reverse ARC hash size overflow");\n    size_t'
            ' mark_bytes = __btrc_reverse_capacity_bytes(\n        cap, sizeof(unsigne'
            'd int), "reverse ARC hash size overflow");\n    void** keys = (void**)__b'
            'trc_safe_calloc(1, key_bytes);\n    unsigned int* marks = (unsigned int*)'
            '__btrc_safe_calloc(1, mark_bytes);\n    for (int i = 0; i < __btrc_revers'
            'e_count; i++) {\n        void* object = __btrc_reverse_queue[i];\n        '
            'size_t slot = __btrc_ptr_hash(object) & ((size_t)cap - 1);\n        while'
            ' (marks[slot] == __btrc_reverse_epoch)\n            slot = (slot + 1) & ('
            '(size_t)cap - 1);\n        marks[slot] = __btrc_reverse_epoch;\n        ke'
            'ys[slot] = object;\n    }\n    free(__btrc_reverse_keys);\n    free(__btrc_'
            'reverse_marks);\n    __btrc_reverse_keys = keys;\n    __btrc_reverse_marks'
            ' = marks;\n    __btrc_reverse_key_cap = cap;\n}\nstatic int __btrc_reverse_'
            'add(void* object) {\n    if (!object) return 0;\n    if (__btrc_reverse_co'
            'unt < 0 || __btrc_reverse_count == INT_MAX) {\n        fprintf(stderr, "b'
            'trc: reverse ARC count overflow\\n");\n        exit(1);\n    }\n    if (__bt'
            'rc_reverse_key_cap == 0\n            || __btrc_reverse_count >= __btrc_re'
            'verse_key_cap / 2)\n        __btrc_reverse_grow_keys();\n    size_t slot ='
            ' __btrc_ptr_hash(object)\n        & ((size_t)__btrc_reverse_key_cap - 1);'
            '\n    while (__btrc_reverse_marks[slot] == __btrc_reverse_epoch) {\n      '
            '  if (__btrc_reverse_keys[slot] == object) return 0;\n        slot = (slo'
            't + 1) & ((size_t)__btrc_reverse_key_cap - 1);\n    }\n    __btrc_reverse_'
            'reserve_queue(__btrc_reverse_count + 1);\n    __btrc_reverse_marks[slot] '
            '= __btrc_reverse_epoch;\n    __btrc_reverse_keys[slot] = object;\n    __bt'
            'rc_reverse_queue[__btrc_reverse_count++] = object;\n    return 1;\n}\nstati'
            'c int __btrc_arc_reverse_proves_live(void* object) {\n    __btrc_reverse_'
            'count = 0;\n    __btrc_reverse_epoch++;\n    if (__btrc_reverse_epoch == 0'
            ') {\n        if (__btrc_reverse_marks) {\n            size_t bytes = __btr'
            'c_reverse_capacity_bytes(\n                __btrc_reverse_key_cap, sizeof'
            '(unsigned int),\n                "reverse ARC hash size overflow");\n     '
            '       memset(__btrc_reverse_marks, 0, bytes);\n        }\n        __btrc_'
            'reverse_epoch = 1;\n    }\n    __btrc_reverse_add(object);\n    for (int he'
            'ad = 0; head < __btrc_reverse_count; head++) {\n        void* current = _'
            '_btrc_reverse_queue[head];\n        __btrc_arc_validate(current);\n       '
            ' __btrc_arc_header* header = __btrc_arc_header_of(current);\n        if ('
            'header->rc > header->edge_rc) return 1;\n        for (__btrc_arc_incoming'
            '* edge = header->incoming;\n                edge; edge = edge->next)\n    '
            '        __btrc_reverse_add(edge->owner);\n    }\n    return 0;\n}'
        ),
        depends_on=('__btrc_arc_reverse_state', '__btrc_arc_validate', '__btrc_ptr_hash', '__btrc_safe_calloc', '__btrc_safe_realloc'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_retain',
        c_source=(
            'static inline int __btrc_arc_retain(void* object) {\n    if (!object) ret'
            'urn 0;\n    __btrc_arc_lock_mutation();\n    __btrc_arc_validate(object);\n'
            '    __btrc_arc_header* header = __btrc_arc_header_of(object);\n    const '
            '__btrc_arc_type* type = header->type;\n    if (header->state != __BTRC_AR'
            'C_LIVE) {\n        __btrc_arc_unlock_mutation();\n        __btrc_arc_raise'
            '_unlocked(\n            type, "cannot retain destroying managed object");'
            '\n    }\n    if (header->rc == INT_MAX) { fprintf(stderr, "btrc: reference'
            ' count overflow\\n"); exit(1); }\n    if (header->live_witness == object) '
            'header->live_witness = NULL;\n    header->rc++;\n    __btrc_arc_validate(o'
            'bject);\n    __btrc_arc_unlock_mutation();\n    return 0;\n}'
        ),
        depends_on=('__btrc_arc_validate', '__btrc_arc_mutation_lock', '__btrc_arc_deferred_state'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_retain_edge',
        c_source=(
            'static inline int __btrc_arc_retain_edge(\n        void* object, void* ow'
            'ner) {\n    if (!object) return 0;\n    __btrc_arc_lock_mutation();\n    __'
            'btrc_arc_validate(object);\n    if (owner) __btrc_arc_validate(owner);\n  '
            '  __btrc_arc_header* header = __btrc_arc_header_of(object);\n    const __'
            'btrc_arc_type* error_type = header->type;\n    if (header->state != __BTR'
            'C_ARC_LIVE\n            || (owner && __btrc_arc_header_of(owner)->state\n '
            '               != __BTRC_ARC_LIVE)) {\n        if (owner && __btrc_arc_he'
            'ader_of(owner)->state\n                != __BTRC_ARC_LIVE)\n            er'
            'ror_type = __btrc_arc_header_of(owner)->type;\n        __btrc_arc_unlock_'
            'mutation();\n        __btrc_arc_raise_unlocked(\n            error_type, "'
            'cannot retain destroying managed object");\n    }\n    if (header->rc == I'
            'NT_MAX || header->edge_rc == INT_MAX) { fprintf(stderr, "btrc: reference'
            ' count overflow\\n"); exit(1); }\n    __btrc_arc_register_incoming(object,'
            ' owner);\n    header->rc++;\n    header->edge_rc++;\n    __btrc_arc_validat'
            'e(object);\n    __btrc_arc_unlock_mutation();\n    return 0;\n}'
        ),
        depends_on=('__btrc_arc_register_incoming', '__btrc_arc_mutation_lock', '__btrc_arc_deferred_state'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_adopt_edge',
        c_source=(
            'static inline int __btrc_arc_adopt_edge(\n        void* object, void* own'
            'er) {\n    if (!object) return 0;\n    __btrc_arc_lock_mutation();\n    __b'
            'trc_arc_validate(object);\n    if (owner) __btrc_arc_validate(owner);\n   '
            ' __btrc_arc_header* header = __btrc_arc_header_of(object);\n    const __b'
            'trc_arc_type* error_type = header->type;\n    if (header->state != __BTRC'
            '_ARC_LIVE\n            || (owner && __btrc_arc_header_of(owner)->state\n  '
            '              != __BTRC_ARC_LIVE)) {\n        if (owner && __btrc_arc_hea'
            'der_of(owner)->state\n                != __BTRC_ARC_LIVE)\n            err'
            'or_type = __btrc_arc_header_of(owner)->type;\n        __btrc_arc_unlock_m'
            'utation();\n        __btrc_arc_raise_unlocked(\n            error_type, "c'
            'annot retain destroying managed object");\n    }\n    if (header->edge_rc '
            '== INT_MAX || header->edge_rc >= header->rc) { fprintf(stderr, "btrc: in'
            'valid owned-edge adoption\\n"); exit(1); }\n    __btrc_arc_register_incomi'
            'ng(object, owner);\n    header->edge_rc++;\n    __btrc_arc_validate(object'
            ');\n    __btrc_arc_unlock_mutation();\n    return 0;\n}'
        ),
        depends_on=('__btrc_arc_register_incoming', '__btrc_arc_mutation_lock', '__btrc_arc_deferred_state'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_unlink_edge',
        c_source=(
            'static inline int __btrc_arc_unlink_edge(\n        void* object, void* ow'
            'ner) {\n    if (!object) return 0;\n    __btrc_arc_lock_mutation();\n    __'
            'btrc_arc_validate(object);\n    if (owner) __btrc_arc_validate(owner);\n  '
            '  __btrc_arc_header* header = __btrc_arc_header_of(object);\n    if (head'
            'er->state != __BTRC_ARC_LIVE\n            || (owner && __btrc_arc_header_'
            'of(owner)->state\n                != __BTRC_ARC_LIVE\n                && _'
            '_btrc_arc_header_of(owner)->state\n                != __BTRC_ARC_DESTROYI'
            'NG)) {\n        const __btrc_arc_type* type = header->type;\n        if (o'
            'wner && __btrc_arc_header_of(owner)->state\n                != __BTRC_ARC'
            '_LIVE\n                && __btrc_arc_header_of(owner)->state\n            '
            '    != __BTRC_ARC_DESTROYING)\n            type = __btrc_arc_header_of(ow'
            'ner)->type;\n        __btrc_arc_unlock_mutation();\n        __btrc_arc_rai'
            'se_unlocked(\n            type, "cannot retain destroying managed object"'
            ');\n    }\n    __btrc_arc_unregister_incoming(object, owner);\n    __btrc_a'
            'rc_unlock_mutation();\n    return 0;\n}'
        ),
        depends_on=('__btrc_arc_unregister_incoming', '__btrc_arc_mutation_lock', '__btrc_arc_deferred_state'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_forget_suspect',
        c_source=(
            'static void __btrc_forget_suspect(void* obj) {\n    if (!obj || __btrc_su'
            'spect_key_cap == 0) return;\n    size_t mask = (size_t)__btrc_suspect_key'
            '_cap - 1;\n    size_t hole = __btrc_ptr_hash(obj) & mask;\n    while (__bt'
            'rc_suspect_keys[hole]\n            && __btrc_suspect_keys[hole] != obj)\n '
            '       hole = (hole + 1) & mask;\n    if (!__btrc_suspect_keys[hole]) ret'
            'urn;\n    __btrc_suspect_keys[hole] = NULL;\n    size_t scan = (hole + 1) '
            '& mask;\n    while (__btrc_suspect_keys[scan]) {\n        void* displaced '
            '= __btrc_suspect_keys[scan];\n        __btrc_suspect_keys[scan] = NULL;\n '
            '       size_t target = __btrc_ptr_hash(displaced) & mask;\n        while '
            '(__btrc_suspect_keys[target])\n            target = (target + 1) & mask;\n'
            '        __btrc_suspect_keys[target] = displaced;\n        scan = (scan + '
            '1) & mask;\n    }\n    for (int i = 0; i < __btrc_suspect_count; i++) {\n  '
            '      if (__btrc_suspects[i] != obj) continue;\n        int last = --__bt'
            'rc_suspect_count;\n        if (i != last) {\n            __btrc_suspects[i'
            '] = __btrc_suspects[last];\n            __btrc_visit_table[i] = __btrc_vi'
            'sit_table[last];\n            __btrc_destroy_table[i] = __btrc_destroy_ta'
            'ble[last];\n        }\n        return;\n    }\n}'
        ),
        depends_on=('__btrc_suspect_state', '__btrc_ptr_hash'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_release_impl',
        c_source=(
            'static inline int __btrc_arc_release_impl(\n        void* object, const _'
            '_btrc_arc_type* fallback,\n        int edge, void* replacement) {\n    if '
            '(!object) return 0;\n    __btrc_arc_validate(object);\n    __btrc_arc_head'
            'er* header = __btrc_arc_header_of(object);\n    const __btrc_arc_type* ty'
            'pe = __btrc_arc_type_of(object, fallback);\n    if (!type || !type->destr'
            'oy) { fprintf(stderr, "btrc: untyped managed release\\n"); exit(1); }\n   '
            ' if (header->state != __BTRC_ARC_LIVE) {\n        fprintf(stderr, "btrc: '
            'release of non-live managed object\\n");\n        exit(1);\n    }\n    if (h'
            'eader->rc <= 0 || (edge && header->edge_rc <= 0)) { fprintf(stderr, "btr'
            'c: reference count underflow\\n"); exit(1); }\n    if (edge) {\n        /* '
            'The slot-specific unlink atom invalidated only the removed owner. */\n   '
            '     (void)replacement;\n        header->edge_rc--;\n    }\n    header->rc-'
            '-;\n    if (header->rc == 0) {\n        if (header->edge_rc != 0 || header'
            '->incoming != NULL) {\n            fprintf(stderr, "btrc: terminal object'
            ' retained an incoming edge\\n");\n            exit(1);\n        }\n        _'
            '_btrc_forget_suspect(object);\n        __btrc_arc_enqueue_locked(object);'
            '\n        return 0;\n    }\n    __btrc_arc_validate(object);\n    if (type->'
            'visit && header->rc == header->edge_rc\n            && !__btrc_arc_incomi'
            'ng_teardown_pending(object)\n            && !__btrc_arc_reverse_proves_li'
            've(object))\n        __btrc_suspect_locked(object, type->visit, type->des'
            'troy);\n    return 0;\n}'
        ),
        depends_on=('__btrc_suspect_locked', '__btrc_arc_incoming_teardown_pending', '__btrc_arc_reverse_proves_live', '__btrc_forget_suspect', '__btrc_arc_deferred_state'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_replace_edge',
        c_source=(
            'static inline int __btrc_arc_replace_edge(\n        volatile void* slot_s'
            'torage, __btrc_arc_slot_access_fn access,\n        void* replacement, voi'
            'd* owner,\n        const __btrc_arc_type* fallback, int adopt) {\n    if ('
            '!slot_storage || !access || !owner) {\n        fprintf(stderr, "btrc: man'
            'aged edge replacement requires a slot and owner\\n");\n        exit(1);\n  '
            '  }\n    __btrc_arc_lock_mutation();\n    void* object = access(slot_stora'
            'ge, NULL, NULL, 0);\n    __btrc_arc_validate(owner);\n    __btrc_arc_heade'
            'r* owner_header = __btrc_arc_header_of(owner);\n    const __btrc_arc_type'
            '* error_type = owner_header->type;\n    int invalid_publication = replace'
            'ment\n        && owner_header->state != __BTRC_ARC_LIVE;\n    if (replacem'
            'ent) {\n        __btrc_arc_validate(replacement);\n        if (__btrc_arc_'
            'header_of(replacement)->state\n                != __BTRC_ARC_LIVE) {\n    '
            '        invalid_publication = 1;\n            error_type = __btrc_arc_hea'
            'der_of(replacement)->type;\n        }\n    }\n    if (invalid_publication) '
            '{\n        __btrc_arc_unlock_mutation();\n        __btrc_arc_raise_unlocke'
            'd(\n            error_type, "cannot retain destroying managed object");\n '
            '       return -1;\n    }\n    if (!replacement && owner_header->state != _'
            '_BTRC_ARC_LIVE\n            && owner_header->state != __BTRC_ARC_DESTROYI'
            'NG) {\n        __btrc_arc_unlock_mutation();\n        __btrc_arc_raise_unl'
            'ocked(\n            error_type, "cannot retain destroying managed object"'
            ');\n        return -1;\n    }\n    if (object == replacement) {\n        if '
            '(replacement && adopt)\n            __btrc_arc_release_impl(replacement, '
            'fallback, 0, NULL);\n        __btrc_arc_unlock_mutation();\n        __btrc'
            '_arc_drain_deferred(0);\n        return 0;\n    }\n    if (access(slot_stor'
            'age, object, replacement, 1) != object) {\n        __btrc_arc_unlock_muta'
            'tion();\n        fprintf(stderr, "btrc: managed edge changed during trans'
            'action\\n");\n        exit(1);\n    }\n    if (object) {\n        __btrc_arc_'
            'validate(object);\n        __btrc_arc_unregister_incoming(object, owner);'
            '\n    }\n    if (replacement) {\n        __btrc_arc_header* next = __btrc_a'
            'rc_header_of(replacement);\n        if (adopt) {\n            if (next->ed'
            'ge_rc == INT_MAX || next->edge_rc >= next->rc) {\n                fprintf'
            '(stderr, "btrc: invalid owned-edge adoption\\n");\n                exit(1)'
            ';\n            }\n            __btrc_arc_register_incoming(replacement, ow'
            'ner);\n            next->edge_rc++;\n        } else {\n            if (next'
            '->rc == INT_MAX || next->edge_rc == INT_MAX) {\n                fprintf(s'
            'tderr, "btrc: reference count overflow\\n");\n                exit(1);\n   '
            '         }\n            __btrc_arc_register_incoming(replacement, owner);'
            '\n            next->rc++;\n            next->edge_rc++;\n        }\n        '
            '__btrc_arc_validate(replacement);\n    }\n    if (object)\n        __btrc_a'
            'rc_release_impl(object, fallback, 1, replacement);\n    __btrc_arc_unlock'
            '_mutation();\n    __btrc_arc_drain_deferred(0);\n    return 0;\n}'
        ),
        depends_on=('__btrc_arc_release_impl', '__btrc_arc_register_incoming', '__btrc_arc_unregister_incoming', '__btrc_arc_mutation_lock', '__btrc_arc_drain'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_release',
        c_source=(
            'static inline int __btrc_arc_release(\n        void* object, const __btrc'
            '_arc_type* type) {\n    if (!object) return 0;\n    __btrc_arc_lock_mutati'
            'on();\n    __btrc_arc_release_impl(object, type, 0, NULL);\n    __btrc_arc'
            '_unlock_mutation();\n    __btrc_arc_drain_deferred(0);\n    return 0;\n}'
        ),
        depends_on=('__btrc_arc_release_impl', '__btrc_arc_mutation_lock', '__btrc_arc_drain'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_release_edge',
        c_source=(
            'static inline int __btrc_arc_release_edge(\n        void* object, const _'
            '_btrc_arc_type* type, void* replacement) {\n    if (!object) return 0;\n  '
            '  __btrc_arc_lock_mutation();\n    __btrc_arc_release_impl(object, type, '
            '1, replacement);\n    __btrc_arc_unlock_mutation();\n    __btrc_arc_drain_'
            'deferred(0);\n    return 0;\n}'
        ),
        depends_on=('__btrc_arc_release_impl', '__btrc_arc_mutation_lock', '__btrc_arc_drain'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_release_acyclic',
        c_source=(
            'static inline int __btrc_arc_release_acyclic(\n        void* object, cons'
            't __btrc_arc_type* type) {\n    if (!object) return 0;\n    __btrc_arc_loc'
            'k_mutation();\n    __btrc_arc_validate(object);\n    __btrc_arc_header* he'
            'ader = __btrc_arc_header_of(object);\n    const __btrc_arc_type* runtime_'
            'type = __btrc_arc_type_of(object, type);\n    if (!runtime_type || !runti'
            'me_type->destroy) { fprintf(stderr, "btrc: untyped managed release\\n"); '
            'exit(1); }\n    if (header->state != __BTRC_ARC_LIVE || header->rc <= 0) '
            '{ fprintf(stderr, "btrc: reference count underflow\\n"); exit(1); }\n    h'
            'eader->rc--;\n    if (header->rc == 0) {\n        if (header->edge_rc != 0'
            ' || header->incoming != NULL) {\n            fprintf(stderr, "btrc: termi'
            'nal object retained an incoming edge\\n");\n            exit(1);\n        }'
            '\n        __btrc_arc_enqueue_locked(object);\n    } else {\n        __btrc_'
            'arc_validate(object);\n    }\n    __btrc_arc_unlock_mutation();\n    __btrc'
            '_arc_drain_deferred(0);\n    return 0;\n}'
        ),
        depends_on=('__btrc_arc_type_of', '__btrc_arc_validate', '__btrc_arc_mutation_lock', '__btrc_arc_drain'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_invalidate',
        c_source=(
            'static inline int __btrc_arc_invalidate(void* object) {\n    __btrc_arc_l'
            'ock_mutation();\n    __btrc_arc_validate(object);\n    __btrc_arc_unlock_m'
            'utation();\n    return 0;\n}'
        ),
        depends_on=('__btrc_arc_validate', '__btrc_arc_mutation_lock'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_destroy_slot',
        c_source=(
            'static inline int __btrc_arc_destroy_slot(\n        volatile void* slot_s'
            'torage, __btrc_arc_slot_access_fn access,\n        const __btrc_arc_type*'
            ' fallback) {\n    if (!slot_storage || !access) return 0;\n    __btrc_arc_'
            'lock_mutation();\n    void* object = access(slot_storage, NULL, NULL, 0);'
            '\n    if (!object) {\n        __btrc_arc_unlock_mutation();\n        return'
            ' 0;\n    }\n    __btrc_arc_validate(object);\n    const __btrc_arc_type* ty'
            'pe = __btrc_arc_type_of(object, fallback);\n    if (!type || !type->destr'
            'oy) { fprintf(stderr, "btrc: untyped managed destroy\\n"); exit(1); }\n   '
            ' __btrc_arc_header* header = __btrc_arc_header_of(object);\n    if (heade'
            'r->state != __BTRC_ARC_LIVE || header->rc != 1\n            || header->ed'
            'ge_rc != 0 || header->incoming != NULL) {\n        __btrc_arc_unlock_muta'
            'tion();\n        __btrc_arc_raise_unlocked(\n            type, "cannot del'
            'ete shared managed object");\n    }\n    if (access(slot_storage, object, '
            'NULL, 1) != object) {\n        __btrc_arc_unlock_mutation();\n        fpri'
            'ntf(stderr, "btrc: managed delete slot changed during transaction\\n");\n '
            '       exit(1);\n    }\n    header->rc = 0;\n    header->live_witness = NUL'
            'L;\n    __btrc_forget_suspect(object);\n    __btrc_arc_enqueue_locked(obje'
            'ct);\n    __btrc_arc_unlock_mutation();\n    __btrc_arc_drain_deferred(0);'
            '\n    return 0;\n}'
        ),
        depends_on=('__btrc_forget_suspect', '__btrc_arc_type_of', '__btrc_arc_validate', '__btrc_arc_mutation_lock', '__btrc_arc_deferred_state', '__btrc_arc_drain'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_destroy_edge',
        c_source=(
            'static inline int __btrc_arc_destroy_edge(\n        volatile void* slot_s'
            'torage, __btrc_arc_slot_access_fn access, void* owner,\n        const __b'
            'trc_arc_type* fallback) {\n    if (!slot_storage || !access || !owner) re'
            'turn 0;\n    __btrc_arc_lock_mutation();\n    void* object = access(slot_s'
            'torage, NULL, NULL, 0);\n    if (!object) {\n        __btrc_arc_unlock_mut'
            'ation();\n        return 0;\n    }\n    __btrc_arc_validate(owner);\n    __b'
            'trc_arc_validate(object);\n    const __btrc_arc_type* type = __btrc_arc_t'
            'ype_of(object, fallback);\n    __btrc_arc_header* owner_header = __btrc_a'
            'rc_header_of(owner);\n    __btrc_arc_header* header = __btrc_arc_header_o'
            'f(object);\n    int owner_valid = owner_header->state == __BTRC_ARC_LIVE\n'
            '        || owner_header->state == __BTRC_ARC_DESTROYING;\n    int unique '
            '= header->state == __BTRC_ARC_LIVE\n        && header->rc == 1 && header-'
            '>edge_rc == 1\n        && header->incoming && header->incoming->owner == '
            'owner\n        && header->incoming->next == NULL;\n    if (!owner_valid ||'
            ' !unique) {\n        __btrc_arc_unlock_mutation();\n        __btrc_arc_rai'
            'se_unlocked(\n            type, "cannot delete shared managed object");\n '
            '   }\n    if (access(slot_storage, object, NULL, 1) != object) {\n        '
            '__btrc_arc_unlock_mutation();\n        fprintf(stderr, "btrc: managed del'
            'ete slot changed during transaction\\n");\n        exit(1);\n    }\n    __bt'
            'rc_arc_unregister_incoming(object, owner);\n    header->rc = 0;\n    heade'
            'r->edge_rc = 0;\n    header->live_witness = NULL;\n    __btrc_forget_suspe'
            'ct(object);\n    __btrc_arc_enqueue_locked(object);\n    __btrc_arc_unlock'
            '_mutation();\n    __btrc_arc_drain_deferred(0);\n    return 0;\n}'
        ),
        depends_on=('__btrc_forget_suspect', '__btrc_arc_unregister_incoming', '__btrc_arc_type_of', '__btrc_arc_validate', '__btrc_arc_mutation_lock', '__btrc_arc_deferred_state', '__btrc_arc_drain'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_cycle_collector_state',
        c_source=(
            '\n/* ARC cycle collector: typed graph snapshot, O(vertices + edges). */\nt'
            'ypedef struct {\n    void* object;\n    __btrc_visit_fn visit;\n    __btrc_'
            'destroy_fn destroy;\n    int internal;\n    int first_edge;\n    unsigned c'
            'har live;\n    unsigned char state;\n    unsigned char root;\n} __btrc_cycl'
            'e_vertex;\ntypedef struct {\n    volatile void* slot_storage;\n    __btrc_a'
            'rc_slot_access_fn access;\n    int source;\n    int target;\n    int next;\n'
            '} __btrc_cycle_edge;\ntypedef struct {\n    __btrc_cycle_vertex* vertices;'
            '\n    __btrc_cycle_edge* edges;\n    int* queue;\n    int vertex_count;\n   '
            ' int vertex_cap;\n    int edge_count;\n    int edge_cap;\n    int queue_cap'
            ';\n    int queue_count;\n    int source;\n    void** object_keys;\n    int* '
            'object_values;\n    unsigned int* object_marks;\n    int object_cap;\n    u'
            'nsigned int object_epoch;\n    volatile void** slot_keys;\n    int* slot_v'
            'alues;\n    unsigned int* slot_marks;\n    int slot_cap;\n    unsigned int '
            'slot_epoch;\n} __btrc_cycle_context;\nstatic __btrc_cycle_context __btrc_c'
            'ycle_scratch;\nstatic int __btrc_collecting = 0;\n'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_graph_primitives',
        c_source=(
            '\nstatic void __btrc_cycle_fail(const char* message) {\n    fprintf(stderr'
            ', "btrc: %s\\n", message);\n    exit(1);\n}\nstatic int __btrc_cycle_next_ca'
            'pacity(\n        int capacity, const char* message) {\n    if (capacity < '
            '0 || capacity > INT_MAX / 2)\n        __btrc_cycle_fail(message);\n    ret'
            'urn capacity ? capacity * 2 : 256;\n}\nstatic size_t __btrc_cycle_capacity'
            '_bytes(\n        int capacity, size_t element_size, const char* message) '
            '{\n    if (capacity < 0 || (element_size != 0\n            && (size_t)capa'
            'city > SIZE_MAX / element_size))\n        __btrc_cycle_fail(message);\n   '
            ' return (size_t)capacity * element_size;\n}\nstatic void __btrc_cycle_next'
            '_epoch(\n        unsigned int* epoch, unsigned int* marks, int cap) {\n   '
            ' (*epoch)++;\n    if (*epoch == 0) {\n        if (marks) {\n            siz'
            'e_t bytes = __btrc_cycle_capacity_bytes(\n                cap, sizeof(uns'
            'igned int), "cycle epoch size overflow");\n            memset(marks, 0, b'
            'ytes);\n        }\n        *epoch = 1;\n    }\n}\nstatic void __btrc_cycle_re'
            'serve_vertices(\n        __btrc_cycle_context* context, int needed) {\n   '
            ' if (needed < 0 || context->vertex_cap < 0)\n        __btrc_cycle_fail("c'
            'ycle vertex overflow");\n    if (needed <= context->vertex_cap) return;\n '
            '   int cap = context->vertex_cap;\n    while (cap < needed)\n        cap ='
            ' __btrc_cycle_next_capacity(cap, "cycle vertex overflow");\n    size_t by'
            'tes = __btrc_cycle_capacity_bytes(\n        cap, sizeof(__btrc_cycle_vert'
            'ex), "cycle vertex size overflow");\n    context->vertices = (__btrc_cycl'
            'e_vertex*)__btrc_safe_realloc(\n        context->vertices, bytes);\n    co'
            'ntext->vertex_cap = cap;\n}\nstatic void __btrc_cycle_reserve_edges(\n     '
            '   __btrc_cycle_context* context, int needed) {\n    if (needed < 0 || co'
            'ntext->edge_cap < 0)\n        __btrc_cycle_fail("cycle edge overflow");\n '
            '   if (needed <= context->edge_cap) return;\n    int cap = context->edge_'
            'cap;\n    while (cap < needed)\n        cap = __btrc_cycle_next_capacity(c'
            'ap, "cycle edge overflow");\n    size_t bytes = __btrc_cycle_capacity_byt'
            'es(\n        cap, sizeof(__btrc_cycle_edge), "cycle edge size overflow");'
            '\n    context->edges = (__btrc_cycle_edge*)__btrc_safe_realloc(\n        c'
            'ontext->edges, bytes);\n    context->edge_cap = cap;\n}\nstatic void __btrc'
            '_cycle_reserve_queue(\n        __btrc_cycle_context* context, int needed)'
            ' {\n    if (needed < 0 || context->queue_cap < 0)\n        __btrc_cycle_fa'
            'il("cycle queue overflow");\n    if (needed <= context->queue_cap) return'
            ';\n    int cap = context->queue_cap;\n    while (cap < needed)\n        cap'
            ' = __btrc_cycle_next_capacity(cap, "cycle queue overflow");\n    size_t b'
            'ytes = __btrc_cycle_capacity_bytes(\n        cap, sizeof(int), "cycle que'
            'ue size overflow");\n    context->queue = (int*)__btrc_safe_realloc(\n    '
            '    context->queue, bytes);\n    context->queue_cap = cap;\n}\nstatic void '
            '__btrc_cycle_push_queue(\n        __btrc_cycle_context* context, int valu'
            'e) {\n    if (context->queue_count < 0 || context->queue_count == INT_MAX'
            ')\n        __btrc_cycle_fail("cycle queue overflow");\n    __btrc_cycle_re'
            'serve_queue(context, context->queue_count + 1);\n    context->queue[conte'
            'xt->queue_count++] = value;\n}\nstatic void __btrc_cycle_grow_objects(__bt'
            'rc_cycle_context* context) {\n    int cap = __btrc_cycle_next_capacity(\n '
            '       context->object_cap, "cycle object hash overflow");\n    size_t ke'
            'y_bytes = __btrc_cycle_capacity_bytes(\n        cap, sizeof(void*), "cycl'
            'e object hash size overflow");\n    size_t value_bytes = __btrc_cycle_cap'
            'acity_bytes(\n        cap, sizeof(int), "cycle object hash size overflow"'
            ');\n    size_t mark_bytes = __btrc_cycle_capacity_bytes(\n        cap, siz'
            'eof(unsigned int), "cycle object hash size overflow");\n    void** keys ='
            ' (void**)__btrc_safe_calloc(1, key_bytes);\n    int* values = (int*)__btr'
            'c_safe_realloc(NULL, value_bytes);\n    unsigned int* marks = (unsigned i'
            'nt*)__btrc_safe_calloc(1, mark_bytes);\n    for (int i = 0; i < context->'
            'vertex_count; i++) {\n        void* object = context->vertices[i].object;'
            '\n        size_t slot = __btrc_ptr_hash(object) & ((size_t)cap - 1);\n    '
            '    while (marks[slot] == context->object_epoch)\n            slot = (slo'
            't + 1) & ((size_t)cap - 1);\n        marks[slot] = context->object_epoch;'
            '\n        keys[slot] = object;\n        values[slot] = i;\n    }\n    free(c'
            'ontext->object_keys);\n    free(context->object_values);\n    free(context'
            '->object_marks);\n    context->object_keys = keys;\n    context->object_va'
            'lues = values;\n    context->object_marks = marks;\n    context->object_ca'
            'p = cap;\n}\nstatic int __btrc_cycle_find_object(\n        __btrc_cycle_con'
            'text* context, void* object) {\n    if (context->object_cap == 0) return '
            '-1;\n    size_t slot = __btrc_ptr_hash(object)\n        & ((size_t)context'
            '->object_cap - 1);\n    while (context->object_marks[slot] == context->ob'
            'ject_epoch) {\n        if (context->object_keys[slot] == object)\n        '
            '    return context->object_values[slot];\n        slot = (slot + 1) & ((s'
            'ize_t)context->object_cap - 1);\n    }\n    return -1;\n}\nstatic int __btrc'
            '_cycle_add_object(__btrc_cycle_context* context,\n        void* object, c'
            'onst __btrc_arc_type* fallback) {\n    if (!object) __btrc_cycle_fail("nu'
            'll managed cycle edge");\n    __btrc_arc_validate(object);\n    const __bt'
            'rc_arc_type* type = __btrc_arc_type_of(object, fallback);\n    if (!type '
            '|| !type->destroy)\n        __btrc_cycle_fail("untyped managed cycle edge'
            '");\n    int found = __btrc_cycle_find_object(context, object);\n    if (f'
            'ound >= 0) {\n        __btrc_cycle_vertex* vertex = &context->vertices[fo'
            'und];\n        if (vertex->visit != type->visit || vertex->destroy != typ'
            'e->destroy)\n            __btrc_cycle_fail("conflicting runtime types for'
            ' cycle object");\n        return found;\n    }\n    if (context->vertex_cou'
            'nt < 0 || context->vertex_count == INT_MAX)\n        __btrc_cycle_fail("c'
            'ycle vertex overflow");\n    if (context->object_cap == 0\n            || '
            'context->vertex_count >= context->object_cap / 2)\n        __btrc_cycle_g'
            'row_objects(context);\n    __btrc_cycle_reserve_vertices(context, context'
            '->vertex_count + 1);\n    int index = context->vertex_count++;\n    contex'
            't->vertices[index] = (__btrc_cycle_vertex){\n        object, type->visit,'
            ' type->destroy, 0, -1, 0, 0, 0};\n    size_t slot = __btrc_ptr_hash(objec'
            't)\n        & ((size_t)context->object_cap - 1);\n    while (context->obje'
            'ct_marks[slot] == context->object_epoch)\n        slot = (slot + 1) & ((s'
            'ize_t)context->object_cap - 1);\n    context->object_marks[slot] = contex'
            't->object_epoch;\n    context->object_keys[slot] = object;\n    context->o'
            'bject_values[slot] = index;\n    return index;\n}\nstatic void __btrc_cycle'
            '_grow_slots(__btrc_cycle_context* context) {\n    int cap = __btrc_cycle_'
            'next_capacity(\n        context->slot_cap, "cycle slot hash overflow");\n '
            '   size_t key_bytes = __btrc_cycle_capacity_bytes(\n        cap, sizeof(v'
            'olatile void*), "cycle slot hash size overflow");\n    size_t value_bytes'
            ' = __btrc_cycle_capacity_bytes(\n        cap, sizeof(int), "cycle slot ha'
            'sh size overflow");\n    size_t mark_bytes = __btrc_cycle_capacity_bytes('
            '\n        cap, sizeof(unsigned int), "cycle slot hash size overflow");\n  '
            '  volatile void** keys = (volatile void**)__btrc_safe_calloc(\n        1,'
            ' key_bytes);\n    int* values = (int*)__btrc_safe_realloc(NULL, value_byt'
            'es);\n    unsigned int* marks = (unsigned int*)__btrc_safe_calloc(1, mark'
            '_bytes);\n    for (int i = 0; i < context->edge_count; i++) {\n        vol'
            'atile void* storage = context->edges[i].slot_storage;\n        size_t slo'
            't = __btrc_ptr_hash((const void*)storage)\n            & ((size_t)cap - 1'
            ');\n        while (marks[slot] == context->slot_epoch)\n            slot ='
            ' (slot + 1) & ((size_t)cap - 1);\n        marks[slot] = context->slot_epo'
            'ch;\n        keys[slot] = storage;\n        values[slot] = i;\n    }\n    fr'
            'ee(context->slot_keys);\n    free(context->slot_values);\n    free(context'
            '->slot_marks);\n    context->slot_keys = keys;\n    context->slot_values ='
            ' values;\n    context->slot_marks = marks;\n    context->slot_cap = cap;\n}'
            '\nstatic int __btrc_cycle_find_slot(\n        __btrc_cycle_context* contex'
            't, volatile void* storage) {\n    if (context->slot_cap == 0) return -1;\n'
            '    size_t slot = __btrc_ptr_hash((const void*)storage)\n        & ((size'
            '_t)context->slot_cap - 1);\n    while (context->slot_marks[slot] == conte'
            'xt->slot_epoch) {\n        if (context->slot_keys[slot] == storage)\n     '
            '       return context->slot_values[slot];\n        slot = (slot + 1) & (('
            'size_t)context->slot_cap - 1);\n    }\n    return -1;\n}\nstatic void __btrc'
            '_cycle_reset_context(__btrc_cycle_context* context) {\n    context->verte'
            'x_count = 0;\n    context->edge_count = 0;\n    context->source = -1;\n    '
            'context->queue_count = 0;\n    __btrc_cycle_next_epoch(&context->object_e'
            'poch,\n        context->object_marks, context->object_cap);\n    __btrc_cy'
            'cle_next_epoch(&context->slot_epoch,\n        context->slot_marks, contex'
            't->slot_cap);\n}\n'
        ),
        depends_on=('__btrc_cycle_collector_state', '__btrc_ptr_hash', '__btrc_safe_calloc', '__btrc_safe_realloc', '__btrc_arc_type_of', '__btrc_arc_validate'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_abandon_graph',
        c_source=(
            'static void __btrc_abandon_snapshot_edge(\n        volatile void* slot_st'
            'orage, __btrc_arc_slot_access_fn access,\n        const __btrc_arc_type* '
            'type, void* opaque) {\n    __btrc_cycle_context* context = (__btrc_cycle_'
            'context*)opaque;\n    if (!slot_storage || !access) return;\n    void* obj'
            'ect = access(slot_storage, NULL, NULL, 0);\n    if (!object) return;\n    '
            'if (__btrc_cycle_find_slot(context, slot_storage) >= 0) return;\n    if ('
            'context->slot_cap == 0\n            || context->edge_count >= context->sl'
            'ot_cap / 2)\n        __btrc_cycle_grow_slots(context);\n    int target = _'
            '_btrc_cycle_add_object(context, object, type);\n    if (context->vertices'
            '[target].internal == INT_MAX)\n        __btrc_cycle_fail("partial-constru'
            'ction edge overflow");\n    context->vertices[target].internal++;\n    if '
            '(context->edge_count < 0 || context->edge_count == INT_MAX)\n        __bt'
            'rc_cycle_fail("cycle edge overflow");\n    __btrc_cycle_reserve_edges(con'
            'text, context->edge_count + 1);\n    int edge = context->edge_count++;\n  '
            '  context->edges[edge] = (__btrc_cycle_edge){\n        slot_storage, acce'
            'ss, context->source, target,\n        context->vertices[context->source].'
            'first_edge};\n    context->vertices[context->source].first_edge = edge;\n '
            '   size_t slot = __btrc_ptr_hash((const void*)slot_storage)\n        & (('
            'size_t)context->slot_cap - 1);\n    while (context->slot_marks[slot] == c'
            'ontext->slot_epoch)\n        slot = (slot + 1) & ((size_t)context->slot_c'
            'ap - 1);\n    context->slot_marks[slot] = context->slot_epoch;\n    contex'
            't->slot_keys[slot] = slot_storage;\n    context->slot_values[slot] = edge'
            ';\n    if (context->vertices[target].state == 0) {\n        context->verti'
            'ces[target].state = 3;\n        __btrc_cycle_push_queue(context, target);'
            '\n    }\n}\n\nstatic void __btrc_abandon_snapshot(\n        __btrc_cycle_cont'
            'ext* context,\n        void** roots, int root_count) {\n    if (!roots || '
            'root_count <= 0)\n        __btrc_cycle_fail("invalid construction roots")'
            ';\n    __btrc_cycle_reserve_queue(context, root_count);\n    for (int i = '
            '0; i < root_count; i++) {\n        void* root = roots[i];\n        int roo'
            't_index = __btrc_cycle_add_object(\n            context, root, __btrc_arc'
            '_header_of(root)->type);\n        __btrc_cycle_vertex* vertex = &context-'
            '>vertices[root_index];\n        if (vertex->root)\n            __btrc_cycl'
            'e_fail("duplicate construction root");\n        vertex->root = 1;\n       '
            ' if (vertex->state == 0) {\n            vertex->state = 3;\n            __'
            'btrc_cycle_push_queue(context, root_index);\n        }\n    }\n    int head'
            ' = 0;\n    while (head < context->queue_count) {\n        int current = co'
            'ntext->queue[head++];\n        __btrc_cycle_vertex* vertex = &context->ve'
            'rtices[current];\n        vertex->state = 1;\n        if (!vertex->visit) '
            'continue;\n        context->source = current;\n        vertex->visit(\n    '
            '        vertex->object, __btrc_abandon_snapshot_edge, context);\n    }\n}\n'
            '\nstatic void __btrc_abandon_mark_live(\n        __btrc_cycle_context* con'
            'text) {\n    __btrc_cycle_reserve_queue(context, context->vertex_count);\n'
            '    int head = 0;\n    int tail = 0;\n    for (int i = 0; i < context->ver'
            'tex_count; i++) {\n        __btrc_cycle_vertex* vertex = &context->vertic'
            'es[i];\n        __btrc_arc_header* header =\n            __btrc_arc_header'
            '_of(vertex->object);\n        int incoming = 0;\n        for (__btrc_arc_i'
            'ncoming* edge = header->incoming;\n                edge; edge = edge->nex'
            't) {\n            if (incoming == INT_MAX)\n                __btrc_cycle_f'
            'ail("partial-construction incoming overflow");\n            incoming++;\n '
            '       }\n        int root_hold = vertex->root ? 1 : 0;\n        if (root_'
            'hold && vertex->internal == INT_MAX)\n            __btrc_cycle_fail("part'
            'ial-construction root count overflow");\n        int owned = vertex->inte'
            'rnal + root_hold;\n        if (header->state != __BTRC_ARC_LIVE\n         '
            '       || incoming != header->edge_rc\n                || header->rc < ow'
            'ned\n                || header->edge_rc < vertex->internal)\n            _'
            '_btrc_cycle_fail("invalid escaping partial construction");\n        if (v'
            'ertex->root && header->edge_rc != vertex->internal)\n            __btrc_c'
            'ycle_fail("invalid escaping partial construction");\n        if (header->'
            'rc > owned) {\n            vertex->live = 1;\n            context->queue[t'
            'ail++] = i;\n        }\n    }\n    while (head < tail) {\n        int source'
            ' = context->queue[head++];\n        for (int edge = context->vertices[sou'
            'rce].first_edge;\n                edge >= 0; edge = context->edges[edge].'
            'next) {\n            int target = context->edges[edge].target;\n          '
            '  if (context->vertices[target].live) continue;\n            context->ver'
            'tices[target].live = 1;\n            context->queue[tail++] = target;\n   '
            '     }\n    }\n    for (int i = 0; i < context->vertex_count; i++) {\n     '
            '   if (context->vertices[i].root\n                && context->vertices[i]'
            '.live)\n            __btrc_cycle_fail("invalid escaping partial construct'
            'ion");\n    }\n}\n\nstatic void __btrc_abandon_reclaim(__btrc_cycle_context*'
            ' context) {\n    for (int i = 0; i < context->edge_count; i++) {\n        '
            '__btrc_cycle_edge* edge = &context->edges[i];\n        if (context->verti'
            'ces[edge->source].live) continue;\n        void* source = context->vertic'
            'es[edge->source].object;\n        void* target = context->vertices[edge->'
            'target].object;\n        if (edge->access(edge->slot_storage,\n           '
            '     target, NULL, 1) != target)\n            __btrc_cycle_fail("managed '
            'graph changed during construction abandon");\n        __btrc_arc_unregist'
            'er_incoming(target, source);\n        __btrc_arc_header* header = __btrc_'
            'arc_header_of(target);\n        if (header->rc <= 0 || header->edge_rc <='
            ' 0)\n            __btrc_cycle_fail("partial-construction edge underflow")'
            ';\n        header->rc--;\n        header->edge_rc--;\n    }\n    for (int i '
            '= 0; i < context->vertex_count; i++) {\n        __btrc_cycle_vertex* vert'
            'ex = &context->vertices[i];\n        if (!vertex->root) continue;\n       '
            ' __btrc_arc_header* root =\n            __btrc_arc_header_of(vertex->obje'
            'ct);\n        if (root->rc <= 0)\n            __btrc_cycle_fail("partial-c'
            'onstruction root underflow");\n        root->rc--;\n    }\n    for (int i ='
            ' 0; i < context->vertex_count; i++) {\n        __btrc_cycle_vertex* verte'
            'x = &context->vertices[i];\n        __btrc_arc_header* header =\n         '
            '   __btrc_arc_header_of(vertex->object);\n        if (vertex->live) {\n   '
            '         __btrc_arc_validate(vertex->object);\n            continue;\n    '
            '    }\n        if (header->rc != 0 || header->edge_rc != 0\n              '
            '  || header->incoming != NULL)\n            __btrc_cycle_fail("partial co'
            'nstruction retained a reference");\n        __btrc_forget_suspect(vertex-'
            '>object);\n    }\n    for (int i = 0; i < context->vertex_count; i++) {\n  '
            '      __btrc_cycle_vertex* vertex = &context->vertices[i];\n        if (v'
            'ertex->live) continue;\n        if (vertex->root)\n            __btrc_arc_'
            'header_of(vertex->object)->suppress_hook = 1;\n        __btrc_arc_enqueue'
            '_locked(vertex->object);\n    }\n}\n\nstatic void __btrc_arc_abandon_many(\n '
            '       void** roots, int root_count, int free_roots) {\n    if (!roots ||'
            ' root_count <= 0) return;\n    __btrc_arc_exclusive_snapshot_begin();\n   '
            ' __btrc_cycle_context* context = &__btrc_cycle_scratch;\n    __btrc_cycle'
            '_reset_context(context);\n    __btrc_abandon_snapshot(context, roots, roo'
            't_count);\n    __btrc_abandon_mark_live(context);\n    __btrc_arc_lock_raw'
            '();\n    __btrc_abandon_reclaim(context);\n    __btrc_arc_unlock_raw();\n  '
            '  __btrc_arc_exclusive_snapshot_end();\n    if (free_roots) free(roots);\n'
            '    __btrc_arc_drain_deferred(0);\n}\n\nstatic void __btrc_arc_abandon_now('
            'void* object) {\n    if (!object) return;\n    void* roots[1] = {object};\n'
            '    __btrc_arc_abandon_many(roots, 1, 0);\n}'
        ),
        depends_on=('__btrc_arc_graph_primitives', '__btrc_arc_unregister_incoming', '__btrc_forget_suspect', '__btrc_arc_exclusive_snapshot', '__btrc_arc_deferred_state', '__btrc_arc_drain'),
        required_headers=('stdlib.h',),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_abandon_callback_state',
        c_source=(
            'typedef void (*__btrc_abandon_drain_fn)(void);\nstatic _Thread_local __bt'
            'rc_abandon_drain_fn\n    __btrc_abandon_drain_callback = NULL;'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_abandon_queue_state',
        c_source=(
            'static _Thread_local void** __btrc_abandon_queue = NULL;\nstatic _Thread_'
            'local int __btrc_abandon_count = 0;\nstatic _Thread_local int __btrc_aban'
            'don_cap = 0;'
        ),
        depends_on=('__btrc_arc_abandon_callback_state',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_abandon_queue_drain',
        c_source=(
            'static void __btrc_arc_drain_pending_abandons(void) {\n    __btrc_abandon'
            '_drain_fn callback =\n        __btrc_abandon_drain_callback;\n    if (call'
            'back) callback();\n}'
        ),
        depends_on=('__btrc_arc_abandon_callback_state',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_abandon',
        c_source=(
            'static void __btrc_arc_drain_abandon_queue(void) {\n    if (__btrc_arc_to'
            'pology_depth != 0) return;\n    for (;;) {\n        __btrc_arc_lock_mutati'
            'on();\n        void** batch = __btrc_abandon_queue;\n        int count = _'
            '_btrc_abandon_count;\n        __btrc_abandon_queue = NULL;\n        __btrc'
            '_abandon_count = 0;\n        __btrc_abandon_cap = 0;\n        __btrc_aband'
            'on_drain_callback = NULL;\n        __btrc_arc_unlock_mutation();\n        '
            'if (count == 0) {\n            free(batch);\n            break;\n        }\n'
            '        __btrc_arc_abandon_many(batch, count, 1);\n    }\n}\n\nstatic void _'
            '_btrc_arc_abandon(void* object) {\n    if (!object) return;\n    if (__btr'
            'c_arc_topology_depth == 0) {\n        __btrc_arc_abandon_now(object);\n   '
            '     return;\n    }\n    __btrc_arc_lock_mutation();\n    __btrc_arc_valida'
            'te(object);\n    __btrc_arc_header* header = __btrc_arc_header_of(object)'
            ';\n    if (header->state != __BTRC_ARC_LIVE) {\n        fprintf(stderr, "b'
            'trc: invalid deferred construction abandon\\n");\n        exit(1);\n    }\n '
            '   if (__btrc_abandon_count < 0 || __btrc_abandon_cap < 0\n            ||'
            ' __btrc_abandon_count > __btrc_abandon_cap) {\n        fprintf(stderr, "b'
            'trc: invalid construction abandon capacity\\n");\n        exit(1);\n    }\n '
            '   for (int i = 0; i < __btrc_abandon_count; i++) {\n        if (__btrc_a'
            'bandon_queue[i] == object) {\n            fprintf(stderr, "btrc: duplicat'
            'e deferred construction abandon\\n");\n            exit(1);\n        }\n    '
            '}\n    if (__btrc_abandon_count == INT_MAX) {\n        fprintf(stderr, "bt'
            'rc: construction abandon queue overflow\\n");\n        exit(1);\n    }\n    '
            'if (__btrc_abandon_count >= __btrc_abandon_cap) {\n        if (__btrc_aba'
            'ndon_cap > INT_MAX / 2) {\n            fprintf(stderr, "btrc: constructio'
            'n abandon capacity overflow\\n");\n            exit(1);\n        }\n        '
            'int cap = __btrc_abandon_cap\n            ? __btrc_abandon_cap * 2 : 16;\n'
            '        if ((size_t)cap > SIZE_MAX / sizeof(void*)) {\n            fprint'
            'f(stderr, "btrc: construction abandon size overflow\\n");\n            exi'
            't(1);\n        }\n        size_t bytes = sizeof(void*) * (size_t)cap;\n    '
            '    __btrc_abandon_queue = (void**)__btrc_safe_realloc(\n            __bt'
            'rc_abandon_queue, bytes);\n        __btrc_abandon_cap = cap;\n    }\n    __'
            'btrc_abandon_queue[__btrc_abandon_count++] = object;\n    __btrc_abandon_'
            'drain_callback =\n        __btrc_arc_drain_abandon_queue;\n    __btrc_arc_'
            'topology_flush_pending = 1;\n    __btrc_arc_unlock_mutation();\n}'
        ),
        depends_on=('__btrc_arc_abandon_graph', '__btrc_arc_abandon_queue_state', '__btrc_safe_realloc', '__btrc_arc_mutation_lock', '__btrc_arc_topology_state', '__btrc_arc_topology_depth_state'),
        required_headers=('limits.h', 'stdint.h', 'stdio.h', 'stdlib.h'),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_collect_cycles_once',
        c_source=(
            'static void __btrc_cycle_snapshot_edge(\n        volatile void* slot_stor'
            'age, __btrc_arc_slot_access_fn access,\n        const __btrc_arc_type* ty'
            'pe, void* opaque) {\n    __btrc_cycle_context* context = (__btrc_cycle_co'
            'ntext*)opaque;\n    if (!slot_storage || !access) return;\n    void* objec'
            't = access(slot_storage, NULL, NULL, 0);\n    if (!object) return;\n    if'
            ' (__btrc_cycle_find_slot(context, slot_storage) >= 0) return;\n    if (co'
            'ntext->slot_cap == 0\n            || context->edge_count >= context->slot'
            '_cap / 2)\n        __btrc_cycle_grow_slots(context);\n    int target = __b'
            'trc_cycle_add_object(context, object, type);\n    if (context->vertices[t'
            'arget].internal == INT_MAX)\n        __btrc_cycle_fail("cycle incoming-ed'
            'ge overflow");\n    context->vertices[target].internal++;\n    __btrc_cycl'
            'e_vertex* target_vertex = &context->vertices[target];\n    if (target_ver'
            'tex->state == 0) {\n        __btrc_arc_header* header =\n            __btr'
            'c_arc_header_of(target_vertex->object);\n        if (header->rc > header-'
            '>edge_rc) {\n            target_vertex->state = 2;\n            target_ver'
            'tex->live = 1;\n        } else {\n            target_vertex->state = 3;\n  '
            '          __btrc_cycle_push_queue(context, target);\n        }\n    }\n    '
            'if (context->edge_count < 0 || context->edge_count == INT_MAX)\n        _'
            '_btrc_cycle_fail("cycle edge overflow");\n    __btrc_cycle_reserve_edges('
            'context, context->edge_count + 1);\n    int edge = context->edge_count++;'
            '\n    context->edges[edge] = (__btrc_cycle_edge){\n        slot_storage, a'
            'ccess, context->source, target,\n        context->vertices[context->sourc'
            'e].first_edge};\n    context->vertices[context->source].first_edge = edge'
            ';\n    size_t slot = __btrc_ptr_hash((const void*)slot_storage)\n        &'
            ' ((size_t)context->slot_cap - 1);\n    while (context->slot_marks[slot] ='
            '= context->slot_epoch)\n        slot = (slot + 1) & ((size_t)context->slo'
            't_cap - 1);\n    context->slot_marks[slot] = context->slot_epoch;\n    con'
            'text->slot_keys[slot] = slot_storage;\n    context->slot_values[slot] = e'
            'dge;\n}\nstatic void __btrc_cycle_snapshot(__btrc_cycle_context* context) '
            '{\n    int seeds = __btrc_suspect_count;\n    for (int i = 0; i < seeds; i'
            '++) {\n        void* object = __btrc_suspects[i];\n        if (!object) co'
            'ntinue;\n        __btrc_arc_validate(object);\n        __btrc_arc_header* '
            'header = __btrc_arc_header_of(object);\n        if (header->rc > header->'
            'edge_rc) continue;\n        __btrc_arc_type fallback = {\n            .vis'
            'it = __btrc_visit_table[i],\n            .destroy = __btrc_destroy_table['
            'i],\n            .hook = NULL, .guard = NULL, .raise = NULL};\n        int'
            ' root = __btrc_cycle_add_object(context, object, &fallback);\n        if '
            '(context->vertices[root].state == 0) {\n            context->vertices[roo'
            't].state = 3;\n            __btrc_cycle_push_queue(context, root);\n      '
            '  }\n    }\n    __btrc_suspect_count = 0;\n    if (__btrc_suspect_keys) {\n '
            '       size_t bytes = __btrc_cycle_capacity_bytes(\n            __btrc_su'
            'spect_key_cap, sizeof(void*),\n            "cycle suspect hash size overf'
            'low");\n        memset(__btrc_suspect_keys, 0, bytes);\n    }\n    int head'
            ' = 0;\n    while (head < context->queue_count) {\n        int scanned = co'
            'ntext->queue[head++];\n        __btrc_cycle_vertex* vertex = &context->ve'
            'rtices[scanned];\n        if (vertex->state != 3) continue;\n        __btr'
            'c_arc_validate(vertex->object);\n        __btrc_arc_header* header = __bt'
            'rc_arc_header_of(vertex->object);\n        if (header->rc > header->edge_'
            'rc) {\n            vertex->state = 2;\n            vertex->live = 1;\n     '
            '       continue;\n        }\n        vertex->state = 1;\n        vertex->li'
            've = 0;\n        if (!vertex->visit) continue;\n        context->source = '
            'scanned;\n        vertex->visit(vertex->object, __btrc_cycle_snapshot_edg'
            'e, context);\n    }\n}\nstatic void __btrc_cycle_mark_live(__btrc_cycle_con'
            'text* context) {\n    __btrc_cycle_reserve_queue(context, context->vertex'
            '_count);\n    int head = 0;\n    int tail = 0;\n    for (int i = 0; i < con'
            'text->vertex_count; i++) {\n        __btrc_cycle_vertex* vertex = &contex'
            't->vertices[i];\n        __btrc_arc_validate(vertex->object);\n        int'
            ' rc = __btrc_arc_header_of(vertex->object)->rc;\n        if (rc < vertex-'
            '>internal)\n            __btrc_cycle_fail("reference count below internal'
            ' edge count");\n        if (vertex->live || rc > vertex->internal) {\n    '
            '        vertex->live = 1;\n            context->queue[tail++] = i;\n      '
            '  }\n    }\n    while (head < tail) {\n        int source = context->queue['
            'head++];\n        for (int edge = context->vertices[source].first_edge;\n '
            '               edge >= 0; edge = context->edges[edge].next) {\n          '
            '  int target = context->edges[edge].target;\n            if (!context->ve'
            'rtices[target].live) {\n                context->vertices[target].live = '
            '1;\n                context->queue[tail++] = target;\n            }\n      '
            '  }\n    }\n    for (int i = 0; i < context->vertex_count; i++) {\n        '
            '__btrc_cycle_vertex* vertex = &context->vertices[i];\n        __btrc_arc_'
            'header* header =\n            __btrc_arc_header_of(vertex->object);\n     '
            '   if (!vertex->live) {\n            header->live_witness = NULL;\n       '
            ' } else if (header->rc == header->edge_rc\n                && !header->li'
            've_witness) {\n            /* Preserve a concrete owner; self is only the'
            ' fallback proof. */\n            header->live_witness = vertex->object;\n '
            '       }\n    }\n}\nstatic void __btrc_cycle_reclaim(__btrc_cycle_context* '
            'context) {\n    for (int i = 0; i < context->edge_count; i++) {\n        _'
            '_btrc_cycle_edge* edge = &context->edges[i];\n        if (context->vertic'
            'es[edge->source].live) continue;\n        void* target_object = context->'
            'vertices[edge->target].object;\n        if (edge->access(edge->slot_stora'
            'ge,\n                target_object, NULL, 1) != target_object)\n          '
            '  __btrc_cycle_fail("managed graph changed during cycle collection");\n  '
            '      __btrc_arc_unregister_incoming(\n            context->vertices[edge'
            '->target].object,\n            context->vertices[edge->source].object);\n '
            '       __btrc_arc_header* target = __btrc_arc_header_of(\n            con'
            'text->vertices[edge->target].object);\n        if (target->rc <= 0 || tar'
            'get->edge_rc <= 0)\n            __btrc_cycle_fail("managed edge count und'
            'erflow");\n        target->rc--;\n        target->edge_rc--;\n        if (t'
            'arget->rc > 0)\n            __btrc_arc_validate(context->vertices[edge->t'
            'arget].object);\n    }\n    for (int i = 0; i < context->vertex_count; i++'
            ') {\n        __btrc_cycle_vertex* vertex = &context->vertices[i];\n       '
            ' if (vertex->live) continue;\n        __btrc_arc_header* header = __btrc_'
            'arc_header_of(vertex->object);\n        if (header->rc != 0 || header->ed'
            'ge_rc != 0)\n            __btrc_cycle_fail("dead cycle retained an owned '
            'reference");\n        if (header->incoming != NULL)\n            __btrc_cy'
            'cle_fail("dead cycle retained an incoming owner");\n        __btrc_forget'
            '_suspect(vertex->object);\n        __btrc_arc_enqueue_locked(vertex->obje'
            'ct);\n    }\n}\nstatic int __btrc_collect_cycles_once(void) {\n    __btrc_ar'
            'c_lock_raw();\n    if (__btrc_arc_shutdown) {\n        __btrc_arc_unlock_r'
            'aw();\n        fprintf(stderr, "btrc: ARC operation after shutdown\\n");\n '
            '       exit(1);\n    }\n    /* The snapshot owner resets the suspect buffe'
            'r outside the raw lock.\n     * Gate that ownership before inspecting any'
            ' suspect-buffer state. */\n    if (__btrc_collecting) {\n        __btrc_ar'
            'c_topology_flush_pending = 1;\n        __btrc_arc_unlock_raw();\n        r'
            'eturn 2;\n    }\n    if (atomic_load_explicit(\n                &__btrc_arc'
            '_snapshot_pending, memory_order_acquire)\n            || atomic_load_expl'
            'icit(\n                &__btrc_arc_snapshotting, memory_order_acquire)) {'
            '\n        __btrc_arc_topology_flush_pending = 1;\n        __btrc_arc_unloc'
            'k_raw();\n        return 2;\n    }\n    if (__btrc_suspect_count == 0) {\n  '
            '      __btrc_arc_unlock_raw();\n        return 0;\n    }\n    if (__btrc_ar'
            'c_topology_active > 0) {\n        __btrc_arc_topology_flush_pending = 1;\n'
            '        __btrc_arc_unlock_raw();\n        return 2;\n    }\n    __btrc_coll'
            'ecting = 1;\n    __btrc_arc_topology_flush_pending = 0;\n    atomic_store_'
            'explicit(\n        &__btrc_arc_snapshotting, 1, memory_order_release);\n  '
            '  __btrc_arc_unlock_raw();\n\n    __btrc_cycle_context* context = &__btrc_'
            'cycle_scratch;\n    __btrc_cycle_reset_context(context);\n    __btrc_cycle'
            '_snapshot(context);\n    __btrc_cycle_mark_live(context);\n\n    __btrc_arc'
            '_lock_raw();\n    __btrc_cycle_reclaim(context);\n    __btrc_collecting = '
            '0;\n    atomic_store_explicit(\n        &__btrc_arc_snapshotting, 0, memor'
            'y_order_release);\n    __btrc_arc_unlock_raw();\n    return 1;\n}\n'
        ),
        depends_on=('__btrc_arc_graph_primitives', '__btrc_suspect_state', '__btrc_ptr_hash', '__btrc_safe_realloc', '__btrc_arc_unregister_incoming', '__btrc_forget_suspect', '__btrc_arc_type_of', '__btrc_arc_validate', '__btrc_arc_lock_state', '__btrc_arc_snapshot_state', '__btrc_arc_snapshot_gate_state', '__btrc_arc_topology_state', '__btrc_arc_shutdown_state', '__btrc_arc_deferred_state'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_drain',
        c_source=(
            'static void __btrc_arc_drain_deferred(int force_cycles) {\n    if (__btrc'
            '_arc_draining) return;\n    if (__btrc_arc_topology_depth > 0) {\n        '
            '__btrc_arc_lock_mutation();\n        if (force_cycles || __btrc_arc_defer'
            'red_head\n                || __btrc_suspect_count > 0)\n            __btrc'
            '_arc_topology_flush_pending = 1;\n        __btrc_arc_unlock_mutation();\n '
            '       return;\n    }\n    __btrc_arc_lock_mutation();\n    int has_termina'
            'l = __btrc_arc_deferred_head != NULL;\n    if (!has_terminal && !force_cy'
            'cles) {\n        __btrc_arc_unlock_mutation();\n        return;\n    }\n    '
            'if (__btrc_arc_active_drains == INT_MAX) {\n        fprintf(stderr, "btrc'
            ': ARC drain count overflow\\n");\n        exit(1);\n    }\n    __btrc_arc_ac'
            'tive_drains++;\n    __btrc_arc_unlock_mutation();\n\n    __btrc_arc_drainin'
            'g = 1;\n    int cascade = 0;\n    char first_error[1024];\n    first_error['
            "0] = '\\0';\n    __btrc_raise_fn first_raise = NULL;\n    int has_error = 0"
            ';\n    for (;;) {\n        __btrc_arc_lock_mutation();\n        void* objec'
            't = __btrc_arc_deferred_head;\n        if (object) {\n            __btrc_a'
            'rc_header* header = __btrc_arc_header_of(object);\n            if (header'
            '->state != __BTRC_ARC_QUEUED) {\n                fprintf(stderr, "btrc: i'
            'nvalid deferred ARC state\\n");\n                exit(1);\n            }\n  '
            '          __btrc_arc_deferred_head = header->deferred_next;\n            '
            'if (!__btrc_arc_deferred_head)\n                __btrc_arc_deferred_tail '
            '= NULL;\n            header->deferred_next = NULL;\n            int suppre'
            'ss_hook = header->suppress_hook;\n            header->suppress_hook = 0;\n'
            '            header->state = __BTRC_ARC_DESTROYING;\n            const __b'
            'trc_arc_type* type = header->type;\n            __btrc_arc_unlock_mutatio'
            'n();\n\n            if (type->visit || type->hook) cascade = 1;\n          '
            '  if (type->hook && !suppress_hook) {\n                char error[1024];\n'
            "                error[0] = '\\0';\n                if (type->guard(type->h"
            'ook, object, error, sizeof error)\n                        && !has_error)'
            ' {\n                    memcpy(first_error, error, sizeof first_error);\n '
            '                   first_raise = type->raise;\n                    has_er'
            'ror = 1;\n                }\n            }\n            type->destroy(objec'
            't);\n            continue;\n        }\n        int pending = __btrc_suspect'
            '_count > 0;\n        if (!pending && __btrc_arc_topology_active == 0)\n   '
            '         __btrc_arc_topology_flush_pending = 0;\n        __btrc_arc_unloc'
            'k_mutation();\n        if (!(pending && (force_cycles || cascade))) break'
            ';\n        int collected = __btrc_collect_cycles_once();\n        if (coll'
            'ected == 1) continue;\n        /* Another collector owns the snapshot, or'
            ' another thread owns a\n         * topology scope.  In either case collec'
            't-once has published the\n         * global flush request.  Never wait he'
            're: the topology owner may be\n         * waiting for this thread, while '
            'an active collector will finish the\n         * handoff from its own drai'
            'n loop. */\n        break;\n    }\n    __btrc_arc_draining = 0;\n    __btrc_'
            'arc_lock_mutation();\n    if (__btrc_arc_active_drains <= 0) {\n        fp'
            'rintf(stderr, "btrc: invalid ARC drain count\\n");\n        exit(1);\n    }'
            '\n    __btrc_arc_active_drains--;\n    __btrc_arc_unlock_mutation();\n    i'
            'f (has_error) {\n        __btrc_arc_type transport = {\n            .visit'
            ' = NULL, .destroy = NULL, .hook = NULL,\n            .guard = NULL, .rais'
            'e = first_raise};\n        __btrc_arc_raise_unlocked(&transport, first_er'
            'ror);\n    }\n}'
        ),
        depends_on=('__btrc_arc_deferred_state', '__btrc_collect_cycles_once', '__btrc_arc_mutation_lock', '__btrc_arc_topology_state', '__btrc_arc_topology_depth_state', '__btrc_arc_shutdown_state', '__btrc_arc_active_drains_state'),
        required_headers=('limits.h', 'stdio.h', 'stdlib.h', 'string.h'),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_collect_cycles',
        c_source=(
            'static void __btrc_collect_cycles(void) {\n    __btrc_arc_drain_deferred('
            '1);\n}'
        ),
        depends_on=('__btrc_arc_drain',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_poll_cycles',
        c_source=(
            'static inline int __btrc_poll_cycles(void) {\n    __btrc_arc_lock_mutatio'
            'n();\n    int pending = __btrc_suspect_count >= 256;\n    __btrc_arc_unloc'
            'k_mutation();\n    if (pending) __btrc_arc_drain_deferred(1);\n    return '
            '0;\n}'
        ),
        depends_on=('__btrc_arc_drain', '__btrc_arc_mutation_lock'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_flush_cycles',
        c_source=(
            'static int __btrc_flush_cycles(void) {\n    __btrc_arc_drain_deferred(1);'
            '\n    return 0;\n}'
        ),
        depends_on=('__btrc_arc_drain',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_arc_thread_state_cleanup',
        c_source=(
            'static void __btrc_arc_thread_state_finalize(void) {\n    __btrc_arc_lock'
            '_mutation();\n    if (__btrc_tracking != 0\n            || __btrc_arc_topo'
            'logy_depth != 0\n            || __btrc_arc_draining\n            || __btrc'
            '_arc_deferred_head\n            || __btrc_arc_deferred_tail\n            |'
            '| __btrc_abandon_queue\n            || __btrc_abandon_count != 0\n        '
            '    || __btrc_abandon_drain_callback) {\n        fprintf(stderr, "btrc: A'
            'RC thread cleanup during active work\\n");\n        exit(1);\n    }\n    fre'
            'e(__btrc_destroyed);\n    __btrc_destroyed = NULL;\n    __btrc_destroyed_c'
            'ount = 0;\n    __btrc_destroyed_cap = 0;\n    free(__btrc_abandon_queue);\n'
            '    __btrc_abandon_queue = NULL;\n    __btrc_abandon_count = 0;\n    __btr'
            'c_abandon_cap = 0;\n    __btrc_abandon_drain_callback = NULL;\n    __btrc_'
            'arc_unlock_mutation();\n}\nstatic void __btrc_arc_thread_state_cleanup(voi'
            'd) {\n    __btrc_arc_drain_pending_abandons();\n    __btrc_arc_drain_defer'
            'red(1);\n    __btrc_arc_thread_state_finalize();\n}'
        ),
        depends_on=('__btrc_arc_abandon_queue_state', '__btrc_arc_abandon_queue_drain', '__btrc_arc_drain', '__btrc_arc_mutation_lock', '__btrc_arc_topology_depth_state', '__btrc_arc_deferred_state', '__btrc_destroyed_tracking', '__btrc_destroyed_capacity'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='cycles',
        name='__btrc_cycle_state_cleanup',
        c_source=(
            'static inline void __btrc_cycle_state_cleanup(void) {\n    __btrc_arc_thr'
            'ead_state_cleanup();\n    __btrc_flush_cycles();\n    __btrc_arc_lock_raw('
            ');\n    if (__btrc_arc_shutdown) {\n        __btrc_arc_unlock_raw();\n     '
            '   fprintf(stderr, "btrc: repeated ARC shutdown\\n");\n        exit(1);\n  '
            '  }\n    __btrc_arc_shutdown = 1;\n    if (__btrc_arc_active_drains != 0\n '
            '           || __btrc_arc_active_unwinds != 0\n            || atomic_load_'
            'explicit(\n                &__btrc_arc_snapshotting, memory_order_acquire'
            ') != 0\n            || atomic_load_explicit(\n                &__btrc_arc_'
            'snapshot_pending, memory_order_acquire) != 0\n            || __btrc_colle'
            'cting != 0) {\n        fprintf(stderr, "btrc: ARC cleanup during active w'
            'ork\\n");\n        exit(1);\n    }\n    if (__btrc_arc_topology_active != 0)'
            ' {\n        fprintf(stderr, "btrc: ARC cleanup during topology mutation\\n'
            '");\n        exit(1);\n    }\n    free(__btrc_suspects);\n    free(__btrc_vi'
            'sit_table);\n    free(__btrc_destroy_table);\n    free(__btrc_suspect_keys'
            ');\n    free(__btrc_reverse_queue);\n    free(__btrc_reverse_keys);\n    fr'
            'ee(__btrc_reverse_marks);\n    free(__btrc_cycle_scratch.vertices);\n    f'
            'ree(__btrc_cycle_scratch.edges);\n    free(__btrc_cycle_scratch.queue);\n '
            '   free(__btrc_cycle_scratch.object_keys);\n    free(__btrc_cycle_scratch'
            '.object_values);\n    free(__btrc_cycle_scratch.object_marks);\n    free(_'
            '_btrc_cycle_scratch.slot_keys);\n    free(__btrc_cycle_scratch.slot_value'
            's);\n    free(__btrc_cycle_scratch.slot_marks);\n    memset(&__btrc_cycle_'
            'scratch, 0, sizeof(__btrc_cycle_scratch));\n    __btrc_suspects = NULL;\n '
            '   __btrc_visit_table = NULL;\n    __btrc_destroy_table = NULL;\n    __btr'
            'c_suspect_keys = NULL;\n    __btrc_reverse_queue = NULL;\n    __btrc_rever'
            'se_keys = NULL;\n    __btrc_reverse_marks = NULL;\n    __btrc_suspect_coun'
            't = __btrc_suspect_cap = 0;\n    __btrc_suspect_key_cap = 0;\n    __btrc_r'
            'everse_queue_cap = __btrc_reverse_key_cap = 0;\n    __btrc_reverse_count '
            '= 0;\n    __btrc_reverse_epoch = 0;\n    if (__btrc_arc_deferred_head || _'
            '_btrc_arc_deferred_tail\n            || __btrc_arc_draining) {\n        fp'
            'rintf(stderr, "btrc: ARC cleanup during active drain\\n");\n        exit(1'
            ');\n    }\n    __btrc_arc_topology_flush_pending = 0;\n    __btrc_collectin'
            'g = 0;\n    __btrc_arc_unlock_raw();\n}'
        ),
        depends_on=('__btrc_flush_cycles', '__btrc_arc_thread_state_cleanup', '__btrc_suspect_capacity', '__btrc_arc_reverse_state', '__btrc_arc_deferred_state', '__btrc_arc_drain', '__btrc_arc_mutation_lock', '__btrc_arc_lock_state', '__btrc_arc_snapshot_state', '__btrc_arc_snapshot_gate_state', '__btrc_arc_shutdown_state', '__btrc_arc_active_drains_state', '__btrc_arc_active_unwinds_state', '__btrc_arc_topology_state', '__btrc_cycle_collector_state'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='process',
        name='__btrc_descriptor_close_bound',
        c_source=(
            '#if defined(__APPLE__)\n#include <sys/sysctl.h>\n#endif\nstatic int __btrc_'
            'descriptor_close_bound(void) {\n    struct rlimit limit;\n    if (getrlimi'
            't(RLIMIT_NOFILE, &limit) != 0) return -1;\n    uintmax_t bound = (uintmax'
            '_t)limit.rlim_max;\n#if defined(__APPLE__)\n    if (bound == (uintmax_t)RL'
            'IM_INFINITY\n            || bound > (uintmax_t)1048576) {\n        int sys'
            'tem_bound = 0;\n        size_t size = sizeof(system_bound);\n        if (s'
            'ysctlbyname("kern.maxfilesperproc", &system_bound, &size,\n              '
            '  NULL, (size_t)0) != 0\n                || size != sizeof(system_bound) '
            '|| system_bound < 3)\n            return -1;\n        bound = (uintmax_t)s'
            'ystem_bound;\n    }\n#endif\n    if (bound == (uintmax_t)RLIM_INFINITY\n    '
            '        || bound < (uintmax_t)3\n            || bound > (uintmax_t)104857'
            '6)\n        return -1;\n    return (int)bound;\n}'
        ),
        depends_on=(),
        required_headers=('stdint.h', 'sys/resource.h'),
        provided_types=(),
        provided_objects=(),
        source_visible=True,
    ),
    GeneratedRuntimeHelperRow(
        category='process',
        name='__btrc_close_descriptors_from',
        c_source=(
            '#if defined(__linux__)\n#include <sys/syscall.h>\n#endif\n#if defined(__lin'
            'ux__) && defined(SYS_close_range)\nextern long syscall(long number, ...);'
            '\n#endif\nstatic int __btrc_close_descriptor_range(\n        unsigned int f'
            'irst, unsigned int last, int bound) {\n    if (first > last) return 0;\n#i'
            'f defined(__linux__) && defined(SYS_close_range)\n    if (syscall((long)S'
            'YS_close_range, first, last, 0U) == 0L) return 0;\n#endif\n    if (bound <'
            ' 3) return -1;\n    unsigned int end = last == ~0U || last >= (unsigned i'
            'nt)bound\n        ? (unsigned int)bound : last + 1U;\n    for (unsigned in'
            't descriptor = first; descriptor < end; descriptor++) {\n        int clos'
            'ed = close(descriptor);\n        /* close(2) may already have released th'
            'e descriptor when it\n         * reports EINTR. Retrying can close an unr'
            'elated descriptor that\n         * a signal handler opened in the meantim'
            'e; continuing could leak\n         * that replacement into exec. Fail clo'
            'sed instead. */\n        if (closed != 0 && errno != EBADF) return -1;\n  '
            '  }\n    return 0;\n}\nstatic int __btrc_close_descriptors_from(int bound) '
            '{\n#if defined(__FreeBSD__) || defined(__OpenBSD__) || defined(__NetBSD__'
            ') || defined(__DragonFly__)\n    closefrom(3);\n    return 0;\n#else\n    re'
            'turn __btrc_close_descriptor_range(3U, ~0U, bound);\n#endif\n}'
        ),
        depends_on=(),
        required_headers=('errno.h', 'unistd.h'),
        provided_types=(),
        provided_objects=(),
        source_visible=True,
    ),
    GeneratedRuntimeHelperRow(
        category='process',
        name='__btrc_close_descriptors_except',
        c_source=(
            'static int __btrc_close_descriptors_except(\n        int bound, int prese'
            'rved) {\n    if (preserved < 3) return -1;\n    if (__btrc_close_descripto'
            'r_range(\n            3U, (unsigned int)preserved - 1U, bound) != 0)\n    '
            '    return -1;\n    return __btrc_close_descriptor_range(\n        (unsign'
            'ed int)preserved + 1U, ~0U, bound);\n}'
        ),
        depends_on=('__btrc_close_descriptors_from',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=True,
    ),
    GeneratedRuntimeHelperRow(
        category='process',
        name='__btrc_close_descriptors_except_many',
        c_source=(
            'static int __btrc_close_descriptors_except_many(\n        int bound, cons'
            't int* preserved, int count) {\n    if (bound < 3 || count < 0 || (count '
            '> 0 && preserved == NULL)) {\n        errno = EINVAL;\n        return -1;\n'
            '    }\n    int previous = 2;\n    for (int index = 0; index < count; index'
            '++) {\n        int descriptor = preserved[index];\n        if (descriptor '
            '< 3 || descriptor >= bound\n                || descriptor <= previous) {\n'
            '            errno = EINVAL;\n            return -1;\n        }\n        pre'
            'vious = descriptor;\n    }\n    unsigned int first = 3U;\n    for (int inde'
            'x = 0; index < count; index++) {\n        int descriptor = preserved[inde'
            'x];\n        if (__btrc_close_descriptor_range(\n                first, (u'
            'nsigned int)descriptor - 1U, bound) != 0)\n            return -1;\n       '
            ' first = (unsigned int)descriptor + 1U;\n    }\n    return __btrc_close_de'
            'scriptor_range(first, ~0U, bound);\n}'
        ),
        depends_on=('__btrc_close_descriptors_from',),
        required_headers=('errno.h',),
        provided_types=(),
        provided_objects=(),
        source_visible=True,
    ),
    GeneratedRuntimeHelperRow(
        category='process',
        name='__btrc_move_descriptor_outside_stdio',
        c_source=(
            'static int __btrc_move_descriptor_outside_stdio(int* descriptor) {\n    i'
            'f (descriptor == NULL || *descriptor < 0) return -1;\n    int original = '
            '*descriptor;\n    if (original > STDERR_FILENO) return 0;\n    int flags ='
            ' fcntl(original, F_GETFD, 0);\n    if (flags < 0\n            || fcntl(ori'
            'ginal, F_SETFD, flags | FD_CLOEXEC) != 0)\n        return -1;\n    int mov'
            'ed = fcntl(original, F_DUPFD_CLOEXEC, 3);\n    if (moved < 0) return -1;\n'
            '    *descriptor = -1;\n    if (close(original) != 0) {\n        int close_'
            'error = errno;\n        /* The original may already name another descript'
            'or. Never retry\n         * or return it to a caller that would close it '
            'again. The known\n         * duplicate is CLOEXEC even if its cleanup is '
            'interrupted. */\n        int current_flags = fcntl(original, F_GETFD, 0);'
            '\n        if (current_flags >= 0)\n            (void)fcntl(original, F_SET'
            'FD, current_flags | FD_CLOEXEC);\n        (void)close(moved);\n        err'
            'no = close_error;\n        return -1;\n    }\n    *descriptor = moved;\n    '
            'return 0;\n}'
        ),
        depends_on=(),
        required_headers=('errno.h', 'fcntl.h', 'unistd.h'),
        provided_types=(),
        provided_objects=(),
        source_visible=True,
    ),
    GeneratedRuntimeHelperRow(
        category='process',
        name='__btrc_posix_spawn_cloexec',
        c_source=(
            '#if defined(__APPLE__)\n#include <spawn.h>\nstatic int __btrc_spawn_map_de'
            'scriptor(\n        posix_spawn_file_actions_t* actions, int source, int t'
            'arget,\n        int inherit_target) {\n    if (source >= 0)\n        return'
            ' posix_spawn_file_actions_adddup2(actions, source, target);\n    if (inhe'
            'rit_target)\n        return posix_spawn_file_actions_addinherit_np(action'
            's, target);\n    return 0;\n}\nstatic int __btrc_spawn_close_source(\n      '
            '  posix_spawn_file_actions_t* actions, int source,\n        int first, in'
            't second) {\n    if (source <= STDERR_FILENO || source == first || source'
            ' == second)\n        return 0;\n    return posix_spawn_file_actions_addclo'
            'se(actions, source);\n}\n#endif\nstatic pid_t __btrc_posix_spawn_cloexec(\n '
            '       const char* executable, char** argv, char** envp,\n        const c'
            'har* cwd, int stdout_source, int stderr_source,\n        int stdin_source'
            ', int combine_stderr, int inherit_stdin,\n        int inherit_stdout, int'
            ' inherit_stderr) {\n#if defined(__APPLE__) && defined(POSIX_SPAWN_CLOEXEC'
            '_DEFAULT)\n    posix_spawn_file_actions_t actions;\n    posix_spawnattr_t '
            'attributes;\n    int error = posix_spawn_file_actions_init(&actions);\n   '
            ' if (error != 0) { errno = error; return (pid_t)-1; }\n    error = posix_'
            'spawnattr_init(&attributes);\n    if (error != 0) {\n        (void)posix_s'
            'pawn_file_actions_destroy(&actions);\n        errno = error;\n        retu'
            'rn (pid_t)-1;\n    }\n    error = __btrc_spawn_map_descriptor(\n        &ac'
            'tions, stdout_source, STDOUT_FILENO, inherit_stdout);\n    if (error == 0'
            ') {\n        if (combine_stderr)\n            error = posix_spawn_file_act'
            'ions_adddup2(\n                &actions, STDOUT_FILENO, STDERR_FILENO);\n '
            '       else\n            error = __btrc_spawn_map_descriptor(\n           '
            '     &actions, stderr_source, STDERR_FILENO, inherit_stderr);\n    }\n    '
            'if (error == 0)\n        error = __btrc_spawn_map_descriptor(\n           '
            ' &actions, stdin_source, STDIN_FILENO, inherit_stdin);\n    if (error == '
            '0)\n        error = __btrc_spawn_close_source(\n            &actions, stdo'
            'ut_source, -1, -1);\n    if (error == 0)\n        error = __btrc_spawn_clo'
            'se_source(\n            &actions, stderr_source, stdout_source, -1);\n    '
            'if (error == 0)\n        error = __btrc_spawn_close_source(\n            &'
            'actions, stdin_source, stdout_source, stderr_source);\n    if (error == 0'
            " && cwd != NULL && cwd[0] != '\\0') {\n#if defined(__GNUC__)\n#pragma GCC d"
            'iagnostic push\n#pragma GCC diagnostic ignored "-Wdeprecated-declarations'
            '"\n#endif\n        error = posix_spawn_file_actions_addchdir_np(&actions, '
            'cwd);\n#if defined(__GNUC__)\n#pragma GCC diagnostic pop\n#endif\n    }\n    '
            'if (error == 0)\n        error = posix_spawnattr_setpgroup(&attributes, ('
            'pid_t)0);\n    if (error == 0)\n        error = posix_spawnattr_setflags(\n'
            '            &attributes, (short)(POSIX_SPAWN_CLOEXEC_DEFAULT\n           '
            '     | POSIX_SPAWN_SETPGROUP));\n    pid_t child = (pid_t)-1;\n    if (err'
            'or == 0)\n        error = posix_spawn(\n            &child, executable, &a'
            'ctions, &attributes, argv, envp);\n    (void)posix_spawnattr_destroy(&att'
            'ributes);\n    (void)posix_spawn_file_actions_destroy(&actions);\n    if ('
            'error != 0) { errno = error; return (pid_t)-1; }\n    return child;\n#else'
            '\n    (void)executable; (void)argv; (void)envp; (void)cwd;\n    (void)stdo'
            'ut_source; (void)stderr_source; (void)stdin_source;\n    (void)combine_st'
            'derr; (void)inherit_stdin;\n    (void)inherit_stdout; (void)inherit_stder'
            'r;\n    return (pid_t)-2;\n#endif\n}'
        ),
        depends_on=(),
        required_headers=('errno.h', 'sys/types.h', 'unistd.h'),
        provided_types=(),
        provided_objects=(),
        source_visible=True,
    ),
    GeneratedRuntimeHelperRow(
        category='process',
        name='__btrc_process_descriptors_supported',
        c_source=(
            'static int __btrc_process_descriptors_supported(void) {\n#if defined(__li'
            'nux__)\n    return 1;\n#else\n    return 0;\n#endif\n}'
        ),
        depends_on=(),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=True,
    ),
    GeneratedRuntimeHelperRow(
        category='process',
        name='__btrc_validate_executable_descriptor',
        c_source=(
            'static int __btrc_validate_executable_descriptor(int descriptor) {\n#if d'
            'efined(__linux__)\n    struct stat status;\n    if (descriptor < 0) { errn'
            'o = EBADF; return -1; }\n    if (fstat(descriptor, &status) != 0) return '
            '-1;\n    if (!S_ISREG(status.st_mode)) { errno = EACCES; return -1; }\n   '
            ' return 0;\n#else\n    (void)descriptor;\n    errno = ENOTSUP;\n    return -'
            '1;\n#endif\n}'
        ),
        depends_on=(),
        required_headers=('errno.h', 'sys/stat.h', 'unistd.h'),
        provided_types=(),
        provided_objects=(),
        source_visible=True,
    ),
    GeneratedRuntimeHelperRow(
        category='process',
        name='__btrc_validate_working_directory_descriptor',
        c_source=(
            'static int __btrc_validate_working_directory_descriptor(int descriptor) '
            '{\n#if defined(__linux__)\n    struct stat status;\n    if (descriptor < 0)'
            ' { errno = EBADF; return -1; }\n    if (fstat(descriptor, &status) != 0) '
            'return -1;\n    if (!S_ISDIR(status.st_mode)) { errno = ENOTDIR; return -'
            '1; }\n    return 0;\n#else\n    (void)descriptor;\n    errno = ENOTSUP;\n    '
            'return -1;\n#endif\n}'
        ),
        depends_on=(),
        required_headers=('errno.h', 'sys/stat.h', 'unistd.h'),
        provided_types=(),
        provided_objects=(),
        source_visible=True,
    ),
    GeneratedRuntimeHelperRow(
        category='process',
        name='__btrc_enter_working_directory_descriptor',
        c_source=(
            'static int __btrc_enter_working_directory_descriptor(int descriptor) {\n#'
            'if defined(__linux__)\n    return fchdir(descriptor);\n#else\n    (void)des'
            'criptor;\n    errno = ENOTSUP;\n    return -1;\n#endif\n}'
        ),
        depends_on=(),
        required_headers=('errno.h', 'unistd.h'),
        provided_types=(),
        provided_objects=(),
        source_visible=True,
    ),
    GeneratedRuntimeHelperRow(
        category='process',
        name='__btrc_exec_signal_guard_begin',
        c_source=(
            'static int __btrc_exec_signal_guard_begin(\n        sigset_t* previous_ma'
            'sk) {\n    if (previous_mask == NULL) { errno = EINVAL; return -1; }\n    '
            'sigset_t blocked;\n    if (sigfillset(&blocked) != 0) return -1;\n    int '
            'error = pthread_sigmask(SIG_BLOCK, &blocked, previous_mask);\n    if (err'
            'or != 0) { errno = error; return -1; }\n    return 0;\n}'
        ),
        depends_on=(),
        required_headers=('errno.h', 'pthread.h', 'signal.h'),
        provided_types=(),
        provided_objects=(),
        source_visible=True,
    ),
    GeneratedRuntimeHelperRow(
        category='process',
        name='__btrc_exec_signal_guard_parent_end',
        c_source=(
            'static int __btrc_exec_signal_guard_parent_end(\n        const sigset_t* '
            'previous_mask) {\n    if (previous_mask == NULL) { errno = EINVAL; return'
            ' -1; }\n    int error = pthread_sigmask(SIG_SETMASK, previous_mask, NULL)'
            ';\n    if (error != 0) { errno = error; return -1; }\n    return 0;\n}'
        ),
        depends_on=('__btrc_exec_signal_guard_begin',),
        required_headers=('errno.h', 'pthread.h', 'signal.h'),
        provided_types=(),
        provided_objects=(),
        source_visible=True,
    ),
    GeneratedRuntimeHelperRow(
        category='process',
        name='__btrc_exec_signal_guard_child_end',
        c_source=(
            'static int __btrc_exec_signal_guard_child_end(\n        const sigset_t* p'
            'revious_mask) {\n    if (previous_mask == NULL) { errno = EINVAL; return '
            '-1; }\n    for (int signal_number = 1; signal_number < NSIG; signal_numbe'
            'r++) {\n        struct sigaction current;\n        if (sigaction(signal_nu'
            'mber, NULL, &current) != 0) {\n            if (errno == EINVAL) continue;'
            '\n            return -1;\n        }\n        if (current.sa_handler == SIG_'
            'IGN) continue;\n        struct sigaction reset;\n        memset(&reset, 0,'
            ' sizeof(reset));\n        reset.sa_handler = SIG_DFL;\n        if (sigempt'
            'yset(&reset.sa_mask) != 0\n                || sigaction(signal_number, &r'
            'eset, NULL) != 0) {\n            if (errno == EINVAL) continue;\n         '
            '   return -1;\n        }\n    }\n    if (sigprocmask(SIG_SETMASK, previous_'
            'mask, NULL) != 0)\n        return -1;\n    return 0;\n}'
        ),
        depends_on=('__btrc_exec_signal_guard_begin',),
        required_headers=('errno.h', 'pthread.h', 'signal.h', 'string.h'),
        provided_types=(),
        provided_objects=(),
        source_visible=True,
    ),
    GeneratedRuntimeHelperRow(
        category='process',
        name='__btrc_exec_executable_descriptor',
        c_source=(
            'static int __btrc_exec_executable_descriptor(\n        int descriptor, ch'
            'ar** argv, char** envp) {\n#if defined(__linux__)\n    return fexecve(desc'
            'riptor, argv, envp);\n#else\n    (void)descriptor; (void)argv; (void)envp;'
            '\n    errno = ENOTSUP;\n    return -1;\n#endif\n}'
        ),
        depends_on=(),
        required_headers=('errno.h', 'unistd.h'),
        provided_types=(),
        provided_objects=(),
        source_visible=True,
    ),
    GeneratedRuntimeHelperRow(
        category='threads',
        name='__btrc_thread_types',
        c_source=(
            'typedef void (*__btrc_thread_result_dispose)(void*, void*);\ntypedef void'
            ' (*__btrc_thread_arg_dispose)(void*);\ntypedef struct {\n    void* (*fn)(v'
            'oid*);\n    void* arg;\n    __btrc_thread_arg_dispose dispose_arg;\n    voi'
            'd* result;\n    void* result_context;\n    __btrc_thread_result_dispose di'
            'spose_result;\n    __btrc_raise_fn raise_result;\n    __btrc_raise_fn rais'
            'e_worker;\n    int has_worker_error;\n    char worker_error[1024];\n    pth'
            'read_t handle;\n} __btrc_thread_t;'
        ),
        depends_on=('__btrc_arc_callback_types',),
        required_headers=('pthread.h',),
        provided_types=('__btrc_thread_result_dispose', '__btrc_thread_arg_dispose', '__btrc_thread_t'),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='threads',
        name='__btrc_thread_spawn',
        c_source=(
            'static int __btrc_thread_guard(\n        __btrc_thread_t* t, __btrc_hook_'
            "fn hook, void* object) {\n    char error[1024];\n    error[0] = '\\0';\n    "
            'int failed = __btrc_arc_guard_hook(\n        hook, object, error, sizeof '
            'error);\n    if (failed && !t->has_worker_error) {\n        memcpy(t->work'
            'er_error, error, sizeof t->worker_error);\n        t->has_worker_error = '
            '1;\n    }\n    return failed;\n}\n\nstatic void __btrc_thread_entry_thunk(voi'
            'd* raw) {\n    __btrc_thread_t* t = (__btrc_thread_t*)raw;\n    t->result '
            '= t->fn(t->arg);\n}\n\nstatic void __btrc_thread_arc_cleanup_thunk(void* un'
            'used) {\n    (void)unused;\n    __btrc_arc_thread_state_cleanup();\n}\n\nstat'
            'ic void* __btrc_thread_wrapper(void* raw) {\n    __btrc_thread_t* t = (__'
            'btrc_thread_t*)raw;\n    (void)__btrc_thread_guard(\n        t, __btrc_thr'
            'ead_entry_thunk, t);\n    if (t->dispose_arg)\n        (void)__btrc_thread'
            '_guard(t, t->dispose_arg, t->arg);\n    t->arg = NULL;\n    t->dispose_arg'
            ' = NULL;\n    int cleanup_failed = __btrc_thread_guard(\n        t, __btrc'
            '_thread_arc_cleanup_thunk, NULL);\n    if (cleanup_failed)\n        __btrc'
            '_arc_thread_state_finalize();\n    __btrc_try_state_cleanup();\n    return'
            ' NULL;\n}\n\nstatic __btrc_thread_t* __btrc_thread_spawn(\n        void* (*f'
            'n)(void*), void* arg,\n        __btrc_thread_arg_dispose dispose_arg,\n   '
            '     const void* result_context, size_t context_size,\n        __btrc_thr'
            'ead_result_dispose dispose_result,\n        __btrc_raise_fn raise_result)'
            ' {\n    if (!fn) { fprintf(stderr, "btrc: cannot spawn a null thread func'
            'tion\\n"); exit(1); }\n    if (dispose_arg && !arg) { fprintf(stderr, "btr'
            'c: cannot dispose a null thread argument\\n"); exit(1); }\n    if ((!resul'
            't_context) != (context_size == 0) || (result_context && !dispose_result)'
            ') { fprintf(stderr, "btrc: invalid thread result disposal context\\n"); e'
            'xit(1); }\n    if (raise_result && !dispose_result) { fprintf(stderr, "bt'
            'rc: invalid thread result raise callback\\n"); exit(1); }\n    __btrc_thre'
            'ad_t* t = (__btrc_thread_t*)__btrc_safe_realloc(\n        NULL, sizeof(__'
            'btrc_thread_t));\n    t->fn = fn;\n    t->arg = arg;\n    t->dispose_arg = '
            'dispose_arg;\n    t->result = NULL;\n    t->result_context = NULL;\n    if '
            '(context_size != 0) {\n        t->result_context = __btrc_safe_realloc(NU'
            'LL, context_size);\n        memcpy(t->result_context, result_context, con'
            'text_size);\n    }\n    t->dispose_result = dispose_result;\n    t->raise_r'
            'esult = raise_result;\n    t->raise_worker = __btrc_throw;\n    t->has_wor'
            "ker_error = 0;\n    t->worker_error[0] = '\\0';\n    int err = pthread_crea"
            'te(&t->handle, NULL, __btrc_thread_wrapper, t);\n    if (err != 0) { fpri'
            'ntf(stderr, "btrc: pthread_create failed (%d)\\n", err); free(t->result_c'
            'ontext); free(t); exit(1); }\n    return t;\n}'
        ),
        depends_on=('__btrc_thread_types', '__btrc_safe_realloc', '__btrc_try_state_cleanup', '__btrc_arc_thread_state_cleanup', '__btrc_arc_guard_hook', '__btrc_throw'),
        required_headers=('pthread.h', 'string.h'),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='threads',
        name='__btrc_thread_finish',
        c_source=(
            'static void __btrc_thread_finish(__btrc_thread_t* t) {\n    int err = pth'
            'read_join(t->handle, NULL);\n    if (err != 0) { fprintf(stderr, "btrc: p'
            'thread_join failed (%d)\\n", err); exit(1); }\n}'
        ),
        depends_on=('__btrc_thread_spawn',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='threads',
        name='__btrc_thread_destroy_handle',
        c_source=(
            'static void __btrc_thread_destroy_handle(__btrc_thread_t* t) {\n    free('
            't->result_context);\n    free(t);\n}'
        ),
        depends_on=('__btrc_thread_spawn',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='threads',
        name='__btrc_thread_box_dispose',
        c_source=(
            'static inline void __btrc_thread_box_dispose(\n        void* result, void'
            '* context) {\n    (void)context;\n    free(result);\n}'
        ),
        depends_on=('__btrc_thread_spawn',),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='threads',
        name='__btrc_thread_arc_dispose',
        c_source=(
            'static inline void __btrc_thread_arc_dispose(\n        void* result, void'
            '* context) {\n    __btrc_arc_release(\n        result, (const __btrc_arc_t'
            'ype*)context);\n    __btrc_flush_cycles();\n}'
        ),
        depends_on=('__btrc_thread_spawn', '__btrc_arc_release', '__btrc_flush_cycles'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='threads',
        name='__btrc_thread_string_dispose',
        c_source=(
            'static inline void __btrc_thread_string_dispose(\n        void* result, v'
            'oid* context) {\n    (void)context;\n    __btrc_string_release((const char'
            '*)result);\n}'
        ),
        depends_on=('__btrc_thread_spawn', '__btrc_string_release'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='threads',
        name='__btrc_thread_dispose_guarded',
        c_source=(
            'typedef struct {\n    __btrc_thread_result_dispose callback;\n    void* re'
            'sult;\n    void* context;\n} __btrc_thread_dispose_call;\nstatic void __btr'
            'c_thread_dispose_thunk(void* raw) {\n    __btrc_thread_dispose_call* call'
            ' =\n        (__btrc_thread_dispose_call*)raw;\n    call->callback(call->re'
            'sult, call->context);\n}\nstatic int __btrc_thread_dispose_guarded(\n      '
            '  __btrc_thread_result_dispose callback,\n        void* result, void* con'
            'text,\n        char* error, size_t error_capacity) {\n    __btrc_thread_di'
            'spose_call call = {callback, result, context};\n    return __btrc_arc_gua'
            'rd_hook(\n        __btrc_thread_dispose_thunk, &call, error, error_capaci'
            'ty);\n}'
        ),
        depends_on=('__btrc_thread_spawn', '__btrc_arc_guard_hook'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='threads',
        name='__btrc_thread_join',
        c_source=(
            'static void* __btrc_thread_join(__btrc_thread_t* t) {\n    if (!t) { fpri'
            'ntf(stderr, "btrc: cannot join a consumed thread handle\\n"); exit(1); }\n'
            '    __btrc_thread_finish(t);\n    if (t->has_worker_error) {\n        char'
            ' worker_error[1024];\n        char dispose_error[1024];\n        dispose_e'
            "rror[0] = '\\0';\n        memcpy(worker_error, t->worker_error, sizeof wor"
            'ker_error);\n        __btrc_raise_fn raise = t->raise_worker;\n        if '
            '(t->dispose_result)\n            (void)__btrc_thread_dispose_guarded(\n   '
            '             t->dispose_result, t->result, t->result_context,\n          '
            '      dispose_error, sizeof dispose_error);\n        __btrc_thread_destro'
            'y_handle(t);\n        __btrc_raise_captured(raise, worker_error);\n    }\n '
            '   void* result = t->result;\n    __btrc_thread_destroy_handle(t);\n    re'
            'turn result;\n}'
        ),
        depends_on=('__btrc_thread_finish', '__btrc_thread_destroy_handle', '__btrc_thread_dispose_guarded', '__btrc_raise_captured'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='threads',
        name='__btrc_thread_free',
        c_source=(
            'static void __btrc_thread_free(void* raw) {\n    __btrc_thread_t* t = (__'
            'btrc_thread_t*)raw;\n    if (!t) return;\n    __btrc_thread_finish(t);\n   '
            " char error[1024];\n    error[0] = '\\0';\n    char dispose_error[1024];\n  "
            "  dispose_error[0] = '\\0';\n    int has_error = t->has_worker_error;\n    "
            '__btrc_raise_fn raise = t->raise_worker;\n    if (has_error)\n        memc'
            'py(error, t->worker_error, sizeof error);\n    int has_dispose_error = t-'
            '>dispose_result\n        && __btrc_thread_dispose_guarded(\n            t-'
            '>dispose_result, t->result, t->result_context,\n            dispose_error'
            ', sizeof dispose_error);\n    if (!has_error && has_dispose_error) {\n    '
            '    memcpy(error, dispose_error, sizeof error);\n        raise = t->raise'
            '_result;\n        has_error = 1;\n    }\n    __btrc_thread_destroy_handle(t'
            ');\n    if (has_error) __btrc_raise_captured(raise, error);\n}'
        ),
        depends_on=('__btrc_thread_finish', '__btrc_thread_destroy_handle', '__btrc_thread_dispose_guarded', '__btrc_raise_captured'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='threads',
        name='__btrc_mutex_val_types',
        c_source=(
            'typedef void* (*__btrc_mutex_value_access)(const void*);\ntypedef void (*'
            '__btrc_mutex_value_callback)(\n    const void*, __btrc_mutex_value_access'
            ', void*, void*);\ntypedef void (*__btrc_mutex_finalize_callback)(void*);\n'
            'typedef struct {\n    __btrc_arc_header arc;\n    pthread_mutex_t lock;\n  '
            '  void* value;\n    size_t size;\n    __btrc_mutex_value_access access;\n  '
            '  __btrc_arc_slot_access_fn slot_access;\n    void* context;\n    __btrc_m'
            'utex_value_callback retain;\n    __btrc_mutex_value_callback release;\n   '
            ' __btrc_mutex_finalize_callback finalize;\n    __btrc_raise_fn raise;\n} _'
            '_btrc_mutex_val_t;'
        ),
        depends_on=('__btrc_arc_callback_types',),
        required_headers=('pthread.h',),
        provided_types=('__btrc_mutex_value_access', '__btrc_mutex_value_callback', '__btrc_mutex_finalize_callback', '__btrc_mutex_val_t'),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='threads',
        name='__btrc_mutex_value_callback_guard',
        c_source=(
            'typedef struct {\n    __btrc_mutex_value_callback callback;\n    const voi'
            'd* storage;\n    __btrc_mutex_value_access access;\n    void* context;\n   '
            ' void* owner;\n} __btrc_mutex_value_call;\nstatic void __btrc_mutex_value_'
            'callback_thunk(void* raw) {\n    __btrc_mutex_value_call* call = (__btrc_'
            'mutex_value_call*)raw;\n    call->callback(\n        call->storage, call->'
            'access, call->context, call->owner);\n}\nstatic int __btrc_mutex_value_cal'
            'lback_guard(\n        __btrc_mutex_value_callback callback,\n        const'
            ' void* storage, __btrc_mutex_value_access access,\n        void* context,'
            ' void* owner,\n        char* error, size_t error_capacity) {\n    __btrc_m'
            'utex_value_call call = {\n        callback, storage, access, context, own'
            'er};\n    return __btrc_arc_guard_hook(\n        __btrc_mutex_value_callba'
            'ck_thunk,\n        &call, error, error_capacity);\n}'
        ),
        depends_on=('__btrc_mutex_val_types', '__btrc_arc_guard_hook'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='threads',
        name='__btrc_mutex_finalize_callback_guard',
        c_source=(
            'typedef struct {\n    __btrc_mutex_finalize_callback callback;\n    void* '
            'context;\n} __btrc_mutex_finalize_call;\nstatic void __btrc_mutex_finalize'
            '_callback_thunk(void* raw) {\n    __btrc_mutex_finalize_call* call =\n    '
            '    (__btrc_mutex_finalize_call*)raw;\n    call->callback(call->context);'
            '\n}\nstatic int __btrc_mutex_finalize_callback_guard(\n        __btrc_mutex'
            '_finalize_callback callback, void* context,\n        char* error, size_t '
            'error_capacity) {\n    __btrc_mutex_finalize_call call = {callback, conte'
            'xt};\n    return __btrc_arc_guard_hook(\n        __btrc_mutex_finalize_cal'
            'lback_thunk,\n        &call, error, error_capacity);\n}'
        ),
        depends_on=('__btrc_mutex_val_types', '__btrc_arc_guard_hook'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='threads',
        name='__btrc_mutex_val_create',
        c_source=(
            'static __btrc_mutex_val_t* __btrc_mutex_val_create(\n        void* initia'
            'l, size_t size,\n        __btrc_mutex_value_access access,\n        __btrc'
            '_arc_slot_access_fn slot_access,\n        const void* context, size_t con'
            'text_size,\n        __btrc_mutex_value_callback retain,\n        __btrc_mu'
            'tex_value_callback release,\n        __btrc_mutex_finalize_callback final'
            'ize,\n        __btrc_raise_fn raise) {\n    if (!initial || size == 0) {\n '
            '       fprintf(stderr, "btrc: Mutex requires an initial value\\n");\n     '
            '   exit(1);\n    }\n    if ((!retain) != (!release) || (!access) != (!reta'
            'in)\n            || (slot_access && !retain) || (finalize && !release)\n  '
            '          || (raise && !release)\n            || ((!context) != (context_'
            'size == 0))) {\n        fprintf(stderr, "btrc: invalid Mutex ownership me'
            'tadata\\n");\n        free(initial);\n        exit(1);\n    }\n    __btrc_mut'
            'ex_val_t* m = (__btrc_mutex_val_t*)__btrc_safe_realloc(\n        NULL, si'
            'zeof(__btrc_mutex_val_t));\n    memset(m, 0, sizeof(*m));\n    int err = p'
            'thread_mutex_init(&m->lock, NULL);\n    if (err != 0) {\n        fprintf(s'
            'tderr, "btrc: mutex init failed (%d)\\n", err);\n        free(initial);\n  '
            '      free(m);\n        exit(1);\n    }\n    m->value = initial;\n    m->siz'
            'e = size;\n    m->access = access;\n    m->slot_access = slot_access;\n    '
            'if (context_size != 0) {\n        m->context = __btrc_safe_realloc(NULL, '
            'context_size);\n        memcpy(m->context, context, context_size);\n    }\n'
            '    m->retain = retain;\n    m->release = release;\n    m->finalize = fina'
            'lize;\n    m->raise = raise;\n    m->arc.rc = 1;\n    m->arc.edge_rc = 0;\n '
            '   m->arc.type = &__btrc_mutex_arc_descriptor;\n    m->arc.state = __BTRC'
            '_ARC_LIVE;\n    if (m->retain) {\n        char error[1024];\n        error['
            "0] = '\\0';\n        if (__btrc_mutex_value_callback_guard(\n              "
            '  m->retain, m->value, m->access, m->context,\n                m, error, '
            'sizeof error)) {\n            __btrc_raise_fn saved_raise = m->raise;\n   '
            '         (void)pthread_mutex_destroy(&m->lock);\n            free(m->cont'
            'ext);\n            free(initial);\n            free(m);\n            __btrc'
            '_raise_captured(saved_raise, error);\n        }\n    }\n    return m;\n}'
        ),
        depends_on=('__btrc_mutex_arc_type', '__btrc_mutex_value_callback_guard', '__btrc_raise_captured', '__btrc_safe_realloc'),
        required_headers=('string.h',),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='threads',
        name='__btrc_mutex_arc_retain',
        c_source=(
            'static void __btrc_mutex_arc_retain(\n        const void* storage, __btrc'
            '_mutex_value_access access,\n        void* context, void* owner) {\n    (v'
            'oid)context;\n    if (owner)\n        (void)__btrc_arc_retain_edge(access('
            'storage), owner);\n    else\n        (void)__btrc_arc_retain(access(storag'
            'e));\n}'
        ),
        depends_on=('__btrc_mutex_val_types', '__btrc_arc_retain', '__btrc_arc_retain_edge'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='threads',
        name='__btrc_mutex_arc_release',
        c_source=(
            'static void __btrc_mutex_arc_release(\n        const void* storage, __btr'
            'c_mutex_value_access access,\n        void* context, void* owner) {\n    v'
            'oid* object = access(storage);\n    if (owner) {\n        (void)__btrc_arc'
            '_unlink_edge(object, owner);\n        (void)__btrc_arc_release_edge(\n    '
            '        object, (const __btrc_arc_type*)context, NULL);\n    } else {\n   '
            '     (void)__btrc_arc_release(\n            object, (const __btrc_arc_typ'
            'e*)context);\n    }\n}'
        ),
        depends_on=('__btrc_mutex_val_types', '__btrc_arc_release', '__btrc_arc_release_edge', '__btrc_arc_unlink_edge'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='threads',
        name='__btrc_mutex_arc_finalize',
        c_source=(
            'static void __btrc_mutex_arc_finalize(void* context) {\n    (void)context'
            ';\n    (void)__btrc_flush_cycles();\n}'
        ),
        depends_on=('__btrc_mutex_val_types', '__btrc_flush_cycles'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='threads',
        name='__btrc_mutex_string_retain',
        c_source=(
            'static void __btrc_mutex_string_retain(\n        const void* storage, __b'
            'trc_mutex_value_access access,\n        void* context, void* owner) {\n   '
            ' (void)context;\n    (void)owner;\n    (void)__btrc_string_retain((const c'
            'har*)access(storage));\n}'
        ),
        depends_on=('__btrc_mutex_val_types', '__btrc_string_retain'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='threads',
        name='__btrc_mutex_string_release',
        c_source=(
            'static void __btrc_mutex_string_release(\n        const void* storage, __'
            'btrc_mutex_value_access access,\n        void* context, void* owner) {\n  '
            '  (void)context;\n    (void)owner;\n    __btrc_string_release((const char*'
            ')access(storage));\n}'
        ),
        depends_on=('__btrc_mutex_val_types', '__btrc_string_release'),
        required_headers=(),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='threads',
        name='__btrc_mutex_arc_type',
        c_source=(
            'static void __btrc_mutex_arc_visit(\n        void* object, __btrc_field_v'
            'isit_fn fn, void* context) {\n    __btrc_mutex_val_t* m = (__btrc_mutex_v'
            'al_t*)object;\n    if (!m || !fn) return;\n    int err = pthread_mutex_loc'
            'k(&m->lock);\n    if (err != 0) {\n        fprintf(stderr, "btrc: mutex lo'
            'ck failed (%d)\\n", err);\n        exit(1);\n    }\n    if (m->value && m->s'
            'lot_access)\n        fn((volatile void*)m->value, m->slot_access,\n       '
            '     (const __btrc_arc_type*)m->context, context);\n    err = pthread_mut'
            'ex_unlock(&m->lock);\n    if (err != 0) {\n        fprintf(stderr, "btrc: '
            'mutex unlock failed (%d)\\n", err);\n        exit(1);\n    }\n}\nstatic void '
            '__btrc_mutex_arc_destroy(void* object) {\n    __btrc_mutex_val_t* m = (__'
            'btrc_mutex_val_t*)object;\n    if (!m) return;\n    void* topology = m->sl'
            'ot_access\n        ? __btrc_arc_topology_begin() : NULL;\n    int err = pt'
            'hread_mutex_lock(&m->lock);\n    if (err != 0) {\n        fprintf(stderr, '
            '"btrc: mutex lock failed (%d)\\n", err);\n        exit(1);\n    }\n    void*'
            ' old = m->value;\n    m->value = NULL;\n    err = pthread_mutex_unlock(&m-'
            '>lock);\n    if (err != 0) {\n        fprintf(stderr, "btrc: mutex unlock '
            'failed (%d)\\n", err);\n        exit(1);\n    }\n    err = pthread_mutex_des'
            'troy(&m->lock);\n    if (err != 0) {\n        fprintf(stderr, "btrc: mutex'
            ' destroy failed (%d)\\n", err);\n        exit(1);\n    }\n    if (m->release'
            ' && old)\n        m->release(old, m->access, m->context, m);\n    if (topo'
            'logy)\n        (void)__btrc_arc_topology_leave(topology);\n    __btrc_mark'
            '_destroyed(m);\n    free(old);\n    free(m->context);\n    free(m);\n}\nstati'
            'c const __btrc_arc_type __btrc_mutex_arc_descriptor = {\n    __btrc_mutex'
            '_arc_visit,\n    __btrc_mutex_arc_destroy,\n    NULL, NULL, __btrc_throw\n}'
            ';'
        ),
        depends_on=('__btrc_mutex_val_types', '__btrc_arc_topology_begin', '__btrc_arc_topology_leave', '__btrc_mark_destroyed', '__btrc_throw'),
        required_headers=('stdio.h', 'stdlib.h'),
        provided_types=(),
        provided_objects=('__btrc_mutex_arc_descriptor',),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='threads',
        name='__btrc_mutex_val_get',
        c_source=(
            'static void* __btrc_mutex_val_get(__btrc_mutex_val_t* m) {\n    if (!m) {'
            '\n        fprintf(stderr, "btrc: cannot get a null Mutex\\n");\n        exi'
            't(1);\n    }\n    void* copy = __btrc_safe_realloc(NULL, m->size);\n    voi'
            'd* topology = m->slot_access\n        ? __btrc_arc_topology_begin() : NUL'
            'L;\n    int err = pthread_mutex_lock(&m->lock);\n    if (err != 0) {\n     '
            '   fprintf(stderr, "btrc: mutex lock failed (%d)\\n", err);\n        free('
            'copy);\n        exit(1);\n    }\n    memcpy(copy, m->value, m->size);\n    c'
            "har first_error[1024];\n    first_error[0] = '\\0';\n    int retain_failed "
            '= m->retain\n        && __btrc_mutex_value_callback_guard(\n            m-'
            '>retain, copy, m->access, m->context,\n            NULL, first_error, siz'
            'eof first_error);\n    int has_error = retain_failed;\n    __btrc_raise_fn'
            ' saved_raise = m->raise;\n    err = pthread_mutex_unlock(&m->lock);\n    i'
            'f (err != 0) {\n        fprintf(stderr, "btrc: mutex unlock failed (%d)\\n'
            '", err);\n        free(copy);\n        exit(1);\n    }\n    int should_flush'
            ' = topology\n        && __btrc_arc_topology_leave(topology);\n    if (shou'
            'ld_flush && m->finalize) {\n        char finalize_error[1024];\n        fi'
            "nalize_error[0] = '\\0';\n        int finalize_failed = __btrc_mutex_final"
            'ize_callback_guard(\n            m->finalize, m->context,\n            fin'
            'alize_error, sizeof finalize_error);\n        if (finalize_failed && !has'
            '_error) {\n            memcpy(first_error, finalize_error, sizeof first_e'
            'rror);\n            has_error = 1;\n        }\n    }\n    if (has_error) {\n '
            '       if (m->release && !retain_failed) {\n            char rollback_err'
            "or[1024];\n            rollback_error[0] = '\\0';\n            (void)__btrc"
            '_mutex_value_callback_guard(\n                m->release, copy, m->access'
            ', m->context,\n                NULL, rollback_error, sizeof rollback_erro'
            'r);\n        }\n        free(copy);\n        __btrc_raise_captured(saved_ra'
            'ise, first_error);\n    }\n    return copy;\n}'
        ),
        depends_on=('__btrc_mutex_value_callback_guard', '__btrc_mutex_finalize_callback_guard', '__btrc_arc_topology_begin', '__btrc_arc_topology_leave', '__btrc_raise_captured', '__btrc_safe_realloc'),
        required_headers=('string.h',),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='threads',
        name='__btrc_mutex_val_set',
        c_source=(
            'static void __btrc_mutex_val_set(\n        __btrc_mutex_val_t* m, void* v'
            'al) {\n    if (!m || !val) {\n        fprintf(stderr, "btrc: cannot set a '
            'null Mutex\\n");\n        free(val);\n        exit(1);\n    }\n    void* topo'
            'logy = m->slot_access\n        ? __btrc_arc_topology_begin() : NULL;\n    '
            'int err = pthread_mutex_lock(&m->lock);\n    if (err != 0) {\n        fpri'
            'ntf(stderr, "btrc: mutex lock failed (%d)\\n", err);\n        free(val);\n '
            "       exit(1);\n    }\n    char first_error[1024];\n    first_error[0] = '"
            "\\0';\n    int has_error = m->retain\n        && __btrc_mutex_value_callbac"
            'k_guard(\n            m->retain, val, m->access, m->context, m,\n         '
            '   first_error, sizeof first_error);\n    void* old = NULL;\n    if (!has_'
            'error) {\n        old = m->value;\n        m->value = val;\n    }\n    err ='
            ' pthread_mutex_unlock(&m->lock);\n    if (err != 0) {\n        fprintf(std'
            'err, "btrc: mutex unlock failed (%d)\\n", err);\n        exit(1);\n    }\n  '
            '  if (!has_error && m->release)\n        has_error = __btrc_mutex_value_c'
            'allback_guard(\n            m->release, old, m->access, m->context, m,\n  '
            '          first_error, sizeof first_error);\n    int should_flush = topol'
            'ogy\n        && __btrc_arc_topology_leave(topology);\n    if (should_flush'
            ' && m->finalize) {\n        char finalize_error[1024];\n        finalize_e'
            "rror[0] = '\\0';\n        int finalize_failed = __btrc_mutex_finalize_call"
            'back_guard(\n            m->finalize, m->context,\n            finalize_er'
            'ror, sizeof finalize_error);\n        if (finalize_failed && !has_error) '
            '{\n            memcpy(first_error, finalize_error, sizeof first_error);\n '
            '           has_error = 1;\n        }\n    }\n    __btrc_raise_fn saved_rais'
            'e = m->raise;\n    free(old ? old : val);\n    if (has_error)\n        __bt'
            'rc_raise_captured(saved_raise, first_error);\n}'
        ),
        depends_on=('__btrc_mutex_value_callback_guard', '__btrc_mutex_finalize_callback_guard', '__btrc_arc_topology_begin', '__btrc_arc_topology_leave', '__btrc_raise_captured'),
        required_headers=('string.h',),
        provided_types=(),
        provided_objects=(),
        source_visible=False,
    ),
    GeneratedRuntimeHelperRow(
        category='process',
        name='__btrc_controlling_terminal_descriptor',
        c_source=(
            'static int __btrc_controlling_terminal_descriptor(void) {\n    int candid'
            'ates[3];\n    candidates[0] = STDIN_FILENO;\n    candidates[1] = STDOUT_FI'
            'LENO;\n    candidates[2] = STDERR_FILENO;\n    for (size_t i = (size_t)0; '
            'i < sizeof(candidates) / sizeof(candidates[0]); i++) {\n        if (tcget'
            'pgrp(candidates[i]) >= (pid_t)0)\n            return candidates[i];\n    }'
            '\n    errno = ENOTTY;\n    return -1;\n}'
        ),
        depends_on=(),
        required_headers=('errno.h', 'stddef.h', 'unistd.h'),
        provided_types=(),
        provided_objects=(),
        source_visible=True,
    ),
    GeneratedRuntimeHelperRow(
        category='process',
        name='__btrc_terminal_foreground_group',
        c_source=(
            'static pid_t __btrc_terminal_foreground_group(int descriptor) {\n    if ('
            'descriptor < 0) { errno = EBADF; return (pid_t)-1; }\n    return tcgetpgr'
            'p(descriptor);\n}'
        ),
        depends_on=(),
        required_headers=('errno.h', 'unistd.h'),
        provided_types=(),
        provided_objects=(),
        source_visible=True,
    ),
    GeneratedRuntimeHelperRow(
        category='process',
        name='__btrc_terminal_adopt_foreground',
        c_source=(
            '/* tcsetpgrp from a background process group raises SIGTTOU at the calle'
            'r, so\n * the disposition is suppressed across the handoff and restored a'
            'fterwards.\n * Only async-signal-safe calls are used: the child branch ru'
            'ns this after fork\n * and before execve. */\nstatic int __btrc_terminal_a'
            'dopt_foreground(int descriptor, pid_t group) {\n    struct sigaction igno'
            'red;\n    struct sigaction previous;\n    int result;\n    int saved;\n    i'
            'f (descriptor < 0 || group <= (pid_t)0) { errno = EINVAL; return -1; }\n '
            '   memset(&ignored, 0, sizeof(ignored));\n    ignored.sa_handler = SIG_IG'
            'N;\n    if (sigemptyset(&ignored.sa_mask) != 0) return -1;\n    if (sigact'
            'ion(SIGTTOU, &ignored, &previous) != 0) return -1;\n    result = tcsetpgr'
            'p(descriptor, group);\n    saved = errno;\n    if (sigaction(SIGTTOU, &pre'
            'vious, NULL) != 0) return -1;\n    errno = saved;\n    return result;\n}'
        ),
        depends_on=(),
        required_headers=('errno.h', 'signal.h', 'string.h', 'unistd.h'),
        provided_types=(),
        provided_objects=(),
        source_visible=True,
    ),
)

C_RUNTIME_CALLS: tuple[str, ...] = (
    'abort',
    'calloc',
    'ceil',
    'clock_gettime',
    'exit',
    'fabs',
    'floor',
    'fmod',
    'fprintf',
    'free',
    'isalpha',
    'isdigit',
    'isspace',
    'longjmp',
    'malloc',
    'memcmp',
    'memcpy',
    'memmove',
    'memset',
    'nanosleep',
    'pow',
    'printf',
    'qsort',
    'realloc',
    'round',
    'setjmp',
    'sin',
    'snprintf',
    'sqrt',
    'strchr',
    'strcmp',
    'strcpy',
    'strlen',
    'strncmp',
    'strncpy',
    'strstr',
    'strtod',
    'strtof',
    'tolower',
    'toupper',
)

C_RUNTIME_OBJECTS: tuple[str, ...] = (
    'errno',
    'stderr',
    'stdin',
    'stdout',
)

C_RUNTIME_TYPES: tuple[str, ...] = (
    'bool',
    'int16_t',
    'int32_t',
    'int64_t',
    'int8_t',
    'intptr_t',
    'max_align_t',
    'ptrdiff_t',
    'size_t',
    'uint16_t',
    'uint32_t',
    'uint64_t',
    'uint8_t',
    'uintptr_t',
)

C_RUNTIME_LITERALS: tuple[str, ...] = (
    'CHAR_BIT',
    'CHAR_MAX',
    'CHAR_MIN',
    'INT_MAX',
    'INT_MIN',
    'LLONG_MAX',
    'LLONG_MIN',
    'LONG_MAX',
    'LONG_MIN',
    'NULL',
    'SCHAR_MAX',
    'SCHAR_MIN',
    'SHRT_MAX',
    'SHRT_MIN',
    'SIZE_MAX',
    'UCHAR_MAX',
    'UINT_MAX',
    'ULLONG_MAX',
    'ULONG_MAX',
    'USHRT_MAX',
    'false',
    'true',
)

RUNTIME_CALL_FEATURES: tuple[tuple[str, str], ...] = (
    ('btrc_gpu_', 'BTRC_RT_NEEDS_GPU'),
    ('btrc_gui_', 'BTRC_RT_NEEDS_GUI'),
    ('btrc_tray_', 'BTRC_RT_NEEDS_TRAY'),
    ('pthread_', 'BTRC_RT_NEEDS_PTHREAD'),
)

HEADER_FEATURES: tuple[tuple[str, str], ...] = (
    ('pthread.h', 'BTRC_RT_NEEDS_PTHREAD'),
    ('setjmp.h', 'BTRC_RT_NEEDS_SETJMP'),
)

RUNTIME_HEADER = (
    '/* btrc_rt.h — the single retargeting seam for --freestanding btrc outpu'
    't.\n *\n * Generated btrc code in --freestanding mode includes ONLY this h'
    'eader. It is\n * the one place an embedder maps the btrc runtime onto the'
    ' target environment.\n *\n *   Hosted (default):      builds against the C'
    ' standard library, unchanged.\n *   Freestanding target:   compile with -'
    'ffreestanding -fno-builtin and\n *                          -DBTRC_FREEST'
    'ANDING, optionally name\n *                          BTRC_RT_PLATFORM_HEA'
    'DER, and provide reached APIs.\n *\n * The pure btrc subset (integer/float'
    '/struct code, no strings/collections/\n * try-catch) references NONE of t'
    'hese symbols, so its translation unit is fully\n * self-contained and nee'
    'ds nothing from this header beyond the base types.\n */\n#ifndef BTRC_RT_H'
    '\n#define BTRC_RT_H\n\n/* Feature-test macros must precede every hosted sys'
    'tem header: even stdint.h\n * may include the platform feature dispatcher'
    '. */\n#ifndef BTRC_FREESTANDING\n#ifndef _DEFAULT_SOURCE\n#define _DEFAULT_'
    'SOURCE\n#endif\n#ifndef _DARWIN_C_SOURCE\n#define _DARWIN_C_SOURCE\n#endif\n#'
    'endif\n\n/* --- Foundational types (needed by even the pure subset) ------'
    '------------ */\n#include <stddef.h>   /* size_t, NULL — freestanding-con'
    'forming per C11 7.19 */\n#include <stdint.h>   /* intN_t        — freesta'
    'nding-conforming per C11 7.20 */\n#include <stdbool.h>  /* bool/true/fals'
    'e — a macro header, no libc symbols    */\n#include <stdatomic.h> /* proc'
    'ess-wide managed-value registries                */\n#include <limits.h> '
    '  /* implementation-width integer bounds used by helpers   */\n#include <'
    'float.h>    /* floating-point bounds; also freestanding-conforming    */'
    '\n\n#ifndef BTRC_FREESTANDING\n/* ========================================='
    '================================ *\n *  HOSTED DEFAULT — map the runtime '
    'onto the C standard library.            *\n * ==========================='
    '============================================== */\n#include <stdio.h>    '
    '/* printf, fprintf, snprintf, stderr            */\n#include <stdlib.h>  '
    ' /* malloc, calloc, realloc, free, abort, exit   */\n#include <string.h> '
    '  /* mem*, str*                                   */\n#include <ctype.h> '
    '   /* isspace, isdigit, isalpha, tolower, toupper  */\n#include <math.h> '
    '    /* sqrt, sin, cos, pow, floor, ceil, round, ... */\n#include <setjmp.'
    'h>   /* setjmp, longjmp  (btrc try/catch)            */\n#ifdef BTRC_RT_N'
    'EEDS_PTHREAD\n#include <pthread.h>  /* Thread<T>, Mutex<T>, spawn        '
    '            */\n#endif\n#ifdef BTRC_RT_NEEDS_GPU\n#ifndef BTRC_RT_GPU_HEADE'
    'R\n#define BTRC_RT_GPU_HEADER <btrc_gpu.h>\n#endif\n#include BTRC_RT_GPU_HE'
    'ADER\n#endif\n#ifdef BTRC_RT_NEEDS_GUI\n#ifndef BTRC_RT_GUI_HEADER\n#define '
    'BTRC_RT_GUI_HEADER <btrc_gui.h>\n#endif\n#ifndef BTRC_RT_GUI_FONT_HEADER\n#'
    'define BTRC_RT_GUI_FONT_HEADER <btrc_gui_font.h>\n#endif\n#ifndef BTRC_RT_'
    'GUI_WINDOW_HEADER\n#define BTRC_RT_GUI_WINDOW_HEADER <btrc_gui_window.h>\n'
    '#endif\n#include BTRC_RT_GUI_HEADER\n#include BTRC_RT_GUI_FONT_HEADER\n#inc'
    'lude BTRC_RT_GUI_WINDOW_HEADER\n#endif\n#ifdef BTRC_RT_NEEDS_TRAY\n#ifndef '
    'BTRC_RT_TRAY_HEADER\n#define BTRC_RT_TRAY_HEADER <btrc_tray.h>\n#endif\n#in'
    'clude BTRC_RT_TRAY_HEADER\n#endif\n\n#else\n/* ============================='
    '============================================ *\n *  FREESTANDING TARGET —'
    ' you provide every symbol below.                    *\n *                '
    '                                                           *\n *  This is'
    ' the core external surface of the btrc runtime. Optional stdlib    *\n * '
    ' modules (filesystem, sockets, native UI, etc.) come through the platfor'
    'm *\n *  header hook below. Anything unreachable can remain unimplemented'
    '.        *\n * =========================================================='
    '=============== */\n\n/* One target-owned umbrella header may provide POSI'
    'X/native types, constants,\n * macros, and declarations used by the selec'
    'ted stdlib modules. */\n#ifdef BTRC_RT_PLATFORM_HEADER\n#include BTRC_RT_P'
    'LATFORM_HEADER\n#endif\n\n/* -- Memory ------------------------------------'
    '-------------------------- *\n *  malloc / calloc / realloc / free\n *  ke'
    'rnel:  kmalloc(n, GFP_KERNEL) / kcalloc / krealloc / kfree\n *  Note: mal'
    'loc must provide max-align storage; calloc must zero it.         */\nvoid'
    ' *malloc(size_t);\nvoid *calloc(size_t, size_t);\nvoid *realloc(void *, si'
    'ze_t);\nvoid  free(void *);\n\n/* -- Formatted output ---------------------'
    '------------------------------- *\n *  print/println -> printf; f-strings'
    ' & number->string -> snprintf;\n *  uncaught-error & assert messages -> f'
    'printf(stderr, ...).\n *  kernel:  printf->printk; fprintf(stderr,...)->p'
    'r_err(...);\n *           snprintf is provided by the kernel as-is.      '
    '                 */\nint printf(const char *, ...);\nint snprintf(char *, '
    'size_t, const char *, ...);\nint fprintf(void *, const char *, ...);   /*'
    ' stream arg is opaque here */\nextern void *stderr;                      '
    ' /* unused if you remap fprintf */\n\n/* -- Memory & string ops (kernel pr'
    'ovides all of these by the same name) - */\nvoid  *memcpy(void *, const v'
    'oid *, size_t);\nvoid  *memmove(void *, const void *, size_t);\nvoid  *mem'
    'set(void *, int, size_t);\nint    memcmp(const void *, const void *, size'
    '_t);\nsize_t strlen(const char *);\nint    strcmp(const char *, const char'
    ' *);\nint    strncmp(const char *, const char *, size_t);\nchar  *strcpy(c'
    'har *, const char *);\nchar  *strncpy(char *, const char *, size_t);\nchar'
    '  *strstr(const char *, const char *);\nchar  *strchr(const char *, int);'
    '\nfloat  strtof(const char *, char **);\ndouble strtod(const char *, char '
    '**);\n\n/* -- Character classification (kernel: linux/ctype.h) -----------'
    '--------- */\nint isspace(int);\nint isdigit(int);\nint isalpha(int);\nint t'
    'olower(int);\nint toupper(int);\n\n/* -- Abnormal termination -------------'
    '----------------------------------- *\n *  Uncaught btrc errors call exit'
    '()/abort().\n *  kernel:  route to BUG()/panic() or a controlled module-u'
    'nload path.      */\n_Noreturn void abort(void);\n_Noreturn void exit(int)'
    ';\n\n/* -- Floating-point math (only if the program uses the Math module) '
    '------ *\n *  kernel: no libm — supply your own or avoid floating point i'
    'n-kernel.     */\ndouble sqrt(double);\ndouble pow(double, double);\ndouble'
    ' sin(double);\ndouble cos(double);\ndouble floor(double);\ndouble ceil(doub'
    'le);\ndouble round(double);\ndouble fmod(double, double);\ndouble fabs(doub'
    'le);\n\n/* -- Non-local control flow (only if the program uses try/catch) '
    '--------- *\n *  jmp_buf is target-specific and cannot be guessed portabl'
    'y. Name a shim\n *  that owns its type plus setjmp/longjmp declarations a'
    'nd implementation.  */\n#ifdef BTRC_RT_NEEDS_SETJMP\n#ifndef BTRC_RT_SETJM'
    'P_HEADER\n#error "try/catch freestanding builds require BTRC_RT_SETJMP_HE'
    'ADER"\n#endif\n#include BTRC_RT_SETJMP_HEADER\n#endif\n\n/* -- Threads (Threa'
    'd<T>/Mutex<T>) ---------------------------------------- *\n *  Backed by '
    'pthreads. A freestanding program using threads must name a\n *  compatibl'
    'e shim header, for example:\n *    -DBTRC_RT_PTHREAD_HEADER=\'"my_pthread_'
    'shim.h"\'\n *  The shim owns pthread_t/pthread_mutex_t and every pthread_*'
    ' declaration.  */\n#ifdef BTRC_RT_NEEDS_PTHREAD\n#ifndef BTRC_RT_PTHREAD_H'
    'EADER\n#error "threaded freestanding builds require BTRC_RT_PTHREAD_HEADE'
    'R"\n#endif\n#include BTRC_RT_PTHREAD_HEADER\n#endif\n\n/* -- Optional native '
    'runtimes -------------------------------------------- *\n *  Native GPU/G'
    'UI/tray APIs are target-owned. Name one shim header for each\n *  feature'
    ' reached by the program; the shim declares the complete C ABI.    */\n#if'
    'def BTRC_RT_NEEDS_GPU\n#ifndef BTRC_RT_GPU_HEADER\n#error "GPU freestandin'
    'g builds require BTRC_RT_GPU_HEADER"\n#endif\n#include BTRC_RT_GPU_HEADER\n'
    '#endif\n#ifdef BTRC_RT_NEEDS_GUI\n#ifndef BTRC_RT_GUI_HEADER\n#error "GUI f'
    'reestanding builds require BTRC_RT_GUI_HEADER"\n#endif\n#include BTRC_RT_G'
    'UI_HEADER\n#endif\n#ifdef BTRC_RT_NEEDS_TRAY\n#ifndef BTRC_RT_TRAY_HEADER\n#'
    'error "tray freestanding builds require BTRC_RT_TRAY_HEADER"\n#endif\n#inc'
    'lude BTRC_RT_TRAY_HEADER\n#endif\n\n#ifdef BTRC_FREESTANDING_IMPL\n/* ======'
    '================================================== *\n * REFERENCE RUNTIM'
    'E — a self-contained core implementation with no libc.   *\n * Define BTR'
    'C_FREESTANDING_IMPL in exactly one translation unit.            *\n * Rep'
    'lace BTRC_RT_PUTS/BTRC_RT_TRAP and the bump allocator for real targets. '
    '*\n * Floating formatted-output precision is intentionally bounded to 18 '
    'digits. *\n * Try/catch and threads intentionally require target-provided'
    ' shims.         *\n * ==================================================='
    '====================== */\n#include <stdarg.h>   /* freestanding-conformi'
    'ng per C11 7.16 */\n\nvoid *memset(void *dest, int value, size_t count) {\n'
    '    unsigned char *out = dest;\n    while (count-- > 0U) *out++ = (unsign'
    'ed char)value;\n    return dest;\n}\n\nvoid *memcpy(void *dest, const void *'
    'source, size_t count) {\n    unsigned char *out = dest;\n    const unsigne'
    'd char *in = source;\n    while (count-- > 0U) *out++ = *in++;\n    return'
    ' dest;\n}\n\nvoid *memmove(void *dest, const void *source, size_t count) {\n'
    '    unsigned char *out = dest;\n    const unsigned char *in = source;\n   '
    ' uintptr_t out_address = (uintptr_t)dest;\n    uintptr_t in_address = (ui'
    'ntptr_t)source;\n    if (out_address <= in_address || out_address - in_ad'
    'dress >= count) {\n        while (count-- > 0U) *out++ = *in++;\n    } els'
    'e {\n        out += count;\n        in += count;\n        while (count-- > '
    '0U) *--out = *--in;\n    }\n    return dest;\n}\n\nint memcmp(const void *lef'
    't, const void *right, size_t count) {\n    const unsigned char *a = left;'
    '\n    const unsigned char *b = right;\n    while (count-- > 0U) {\n        '
    'if (*a != *b) return (int)*a - (int)*b;\n        a++;\n        b++;\n    }\n'
    '    return 0;\n}\n\n#ifndef BTRC_RT_ARENA_BYTES\n#define BTRC_RT_ARENA_BYTES'
    ' (1u << 22)\n#endif\n#define BTRC_RT_ALIGNMENT ((size_t)_Alignof(max_align'
    '_t))\n#define BTRC_RT_HEADER_BYTES \\\n    ((sizeof(size_t) + BTRC_RT_ALIGN'
    'MENT - 1U) / BTRC_RT_ALIGNMENT * BTRC_RT_ALIGNMENT)\nstatic union {\n    m'
    'ax_align_t alignment;\n    unsigned char bytes[BTRC_RT_ARENA_BYTES];\n} __'
    'btrc_arena;\nstatic size_t __btrc_arena_offset = 0U;\n\nvoid *malloc(size_t'
    ' size) {\n    if (size > SIZE_MAX - (BTRC_RT_ALIGNMENT - 1U)) return (voi'
    'd *)0;\n    size_t aligned = (size + BTRC_RT_ALIGNMENT - 1U)\n        / BT'
    'RC_RT_ALIGNMENT * BTRC_RT_ALIGNMENT;\n    if (aligned > SIZE_MAX - BTRC_R'
    'T_HEADER_BYTES) return (void *)0;\n    size_t total = BTRC_RT_HEADER_BYTE'
    'S + aligned;\n    if (total > sizeof __btrc_arena.bytes - __btrc_arena_of'
    'fset) return (void *)0;\n    unsigned char *block = __btrc_arena.bytes + '
    '__btrc_arena_offset;\n    __btrc_arena_offset += total;\n    memcpy(block,'
    ' &size, sizeof size);\n    return block + BTRC_RT_HEADER_BYTES;\n}\n\nvoid f'
    'ree(void *pointer) { (void)pointer; }\n\nvoid *calloc(size_t count, size_t'
    ' size) {\n    if (size != 0U && count > SIZE_MAX / size) return (void *)0'
    ';\n    size_t total = count * size;\n    void *result = malloc(total);\n   '
    ' if (result) memset(result, 0, total);\n    return result;\n}\n\nvoid *reall'
    'oc(void *pointer, size_t size) {\n    if (!pointer) return malloc(size);\n'
    '    size_t old_size = 0U;\n    memcpy(&old_size, (unsigned char *)pointer'
    ' - BTRC_RT_HEADER_BYTES, sizeof old_size);\n    void *result = malloc(siz'
    'e);\n    if (result) memcpy(result, pointer, old_size < size ? old_size :'
    ' size);\n    return result;\n}\n\nsize_t strlen(const char *value) {\n    con'
    'st char *end = value;\n    while (*end) end++;\n    return (size_t)(end - '
    'value);\n}\n\nint strcmp(const char *left, const char *right) {\n    while ('
    '*left && *left == *right) { left++; right++; }\n    return (int)(unsigned'
    ' char)*left - (int)(unsigned char)*right;\n}\n\nint strncmp(const char *lef'
    't, const char *right, size_t count) {\n    while (count > 0U && *left && '
    '*left == *right) { left++; right++; count--; }\n    return count ? (int)('
    'unsigned char)*left - (int)(unsigned char)*right : 0;\n}\n\nchar *strcpy(ch'
    'ar *dest, const char *source) {\n    char *result = dest;\n    while ((*de'
    "st++ = *source++) != '\\0') {}\n    return result;\n}\n\nchar *strncpy(char *"
    'dest, const char *source, size_t count) {\n    size_t index = 0U;\n    whi'
    "le (index < count && source[index] != '\\0') {\n        dest[index] = sour"
    'ce[index];\n        index++;\n    }\n    while (index < count) dest[index++'
    "] = '\\0';\n    return dest;\n}\n\nchar *strchr(const char *value, int needle"
    ') {\n    do {\n        if (*value == (char)needle) return (char *)value;\n '
    "   } while (*value++ != '\\0');\n    return (char *)0;\n}\n\nchar *strstr(con"
    'st char *haystack, const char *needle) {\n    if (!*needle) return (char '
    '*)haystack;\n    for (; *haystack; haystack++) {\n        const char *left'
    ' = haystack;\n        const char *right = needle;\n        while (*left &&'
    ' *right && *left == *right) { left++; right++; }\n        if (!*right) re'
    'turn (char *)haystack;\n    }\n    return (char *)0;\n}\n\nint isspace(int va'
    "lue) {\n    return value == ' ' || value == '\\t' || value == '\\n'\n       "
    " || value == '\\r' || value == '\\v' || value == '\\f';\n}\nint isdigit(int v"
    "alue) { return value >= '0' && value <= '9'; }\nint isalpha(int value) {\n"
    "    return (value >= 'a' && value <= 'z') || (value >= 'A' && value <= '"
    "Z');\n}\nint tolower(int value) { return value >= 'A' && value <= 'Z' ? va"
    "lue + 32 : value; }\nint toupper(int value) { return value >= 'a' && valu"
    "e <= 'z' ? value - 32 : value; }\n\nstatic long double __btrc_rt_parse_rea"
    'l(const char *text, char **end_pointer) {\n    const char *start = text;\n'
    '    while (isspace((unsigned char)*text)) text++;\n    bool negative = fa'
    "lse;\n    if (*text == '-' || *text == '+') { negative = *text == '-'; te"
    'xt++; }\n    long double value = 0.0L;\n    bool any = false;\n    while (i'
    'sdigit((unsigned char)*text)) {\n        unsigned int digit = (unsigned i'
    "nt)(*text++ - '0');\n        any = true;\n        value = value > (LDBL_MA"
    'X - (long double)digit) / 10.0L\n            ? LDBL_MAX : value * 10.0L +'
    " (long double)digit;\n    }\n    if (*text == '.') {\n        const char *f"
    'raction_start = text++;\n        long double scale = 0.1L;\n        while '
    '(isdigit((unsigned char)*text)) {\n            unsigned int digit = (unsi'
    "gned int)(*text++ - '0');\n            any = true;\n            if (value "
    '< LDBL_MAX) value += (long double)digit * scale;\n            scale /= 10'
    '.0L;\n        }\n        if (!any) text = fraction_start;\n    }\n    if (an'
    "y && (*text == 'e' || *text == 'E')) {\n        const char *exponent_star"
    't = text++;\n        bool exponent_negative = false;\n        if (*text =='
    " '-' || *text == '+') {\n            exponent_negative = *text == '-';\n  "
    '          text++;\n        }\n        int exponent = 0;\n        bool expon'
    'ent_any = false;\n        while (isdigit((unsigned char)*text)) {\n       '
    '     exponent_any = true;\n            if (exponent <= 999) exponent = ex'
    "ponent * 10 + (*text - '0');\n            else exponent = 10000;\n        "
    '    text++;\n        }\n        if (!exponent_any) text = exponent_start;\n'
    '        else if (exponent_negative) while (exponent-- > 0 && value != 0.'
    '0L) value /= 10.0L;\n        else while (exponent-- > 0 && value < LDBL_M'
    'AX) {\n            value = value > LDBL_MAX / 10.0L ? LDBL_MAX : value * '
    '10.0L;\n        }\n    }\n    if (end_pointer) *end_pointer = (char *)(any '
    '? text : start);\n    if (!any) return 0.0L;\n    return negative ? -value'
    ' : value;\n}\n\nfloat strtof(const char *text, char **end_pointer) {\n    re'
    'turn (float)__btrc_rt_parse_real(text, end_pointer);\n}\ndouble strtod(con'
    'st char *text, char **end_pointer) {\n    return (double)__btrc_rt_parse_'
    'real(text, end_pointer);\n}\n\n#ifndef BTRC_RT_PUTS\nvoid __btrc_rt_puts(con'
    'st char *text, size_t length) { (void)text; (void)length; }\n#define BTRC'
    '_RT_PUTS __btrc_rt_puts\n#endif\n#ifndef BTRC_RT_TRAP\n_Noreturn void __btr'
    'c_rt_trap(void) { for (;;) {} }\n#define BTRC_RT_TRAP __btrc_rt_trap\n#end'
    'if\n_Noreturn void abort(void) { BTRC_RT_TRAP(); for (;;) {} }\n_Noreturn '
    'void exit(int code) { (void)code; BTRC_RT_TRAP(); for (;;) {} }\nvoid *st'
    'derr = (void *)0;\n\ntypedef struct {\n    char *out;\n    size_t cap;\n    s'
    'ize_t pos;\n} __btrc_rt_sink;\n\nstatic void __btrc_rt_put(__btrc_rt_sink *'
    'sink, char value) {\n    if (sink->out && sink->pos + 1U < sink->cap) sin'
    'k->out[sink->pos] = value;\n    sink->pos++;\n}\n\nstatic void __btrc_rt_pad'
    '(__btrc_rt_sink *sink, char value, int count) {\n    while (count-- > 0) '
    '__btrc_rt_put(sink, value);\n}\n\nstatic int __btrc_rt_digits(\n        char'
    ' *reversed, uintmax_t value, unsigned int base, bool upper) {\n    const '
    'char *alphabet = upper\n        ? "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"\n'
    '        : "0123456789abcdefghijklmnopqrstuvwxyz";\n    int length = 0;\n  '
    '  do {\n        reversed[length++] = alphabet[value % base];\n        valu'
    'e /= base;\n    } while (value != 0U);\n    return length;\n}\n\nstatic void '
    '__btrc_rt_emit_integer(\n        __btrc_rt_sink *sink, uintmax_t value, b'
    'ool negative,\n        unsigned int base, bool upper, bool alternate, int'
    ' width,\n        int precision, bool zero, bool left, bool plus, bool spa'
    'ce) {\n    char reversed[sizeof(uintmax_t) * CHAR_BIT + 1U];\n    int digi'
    'ts = value == 0U && precision == 0\n        ? 0 : __btrc_rt_digits(revers'
    "ed, value, base, upper);\n    char sign = negative ? '-' : plus ? '+' : s"
    'pace ? \' \' : \'\\0\';\n    const char *prefix = "";\n    int prefix_length = '
    'sign ? 1 : 0;\n    if (alternate && value != 0U && base == 16U) {\n       '
    ' prefix = upper ? "0X" : "0x";\n        prefix_length += 2;\n    } else if'
    " (alternate && base == 8U && (digits == 0 || reversed[digits - 1] != '0'"
    ')) {\n        prefix = "0";\n        prefix_length += 1;\n    }\n    int lea'
    'ding_zeroes = precision > digits ? precision - digits : 0;\n    int paddi'
    'ng = width - prefix_length - leading_zeroes - digits;\n    if (!left && ('
    "!zero || precision >= 0)) __btrc_rt_pad(sink, ' ', padding);\n    if (sig"
    'n) __btrc_rt_put(sink, sign);\n    while (*prefix) __btrc_rt_put(sink, *p'
    "refix++);\n    if (!left && zero && precision < 0) __btrc_rt_pad(sink, '0"
    "', padding);\n    __btrc_rt_pad(sink, '0', leading_zeroes);\n    while (di"
    'gits-- > 0) __btrc_rt_put(sink, reversed[digits]);\n    if (left) __btrc_'
    "rt_pad(sink, ' ', padding);\n}\n\n\nstatic int __btrc_rt_normalize(long doub"
    'le *value) {\n    int exponent = 0;\n    if (*value == 0.0L) return 0;\n   '
    ' while (*value >= 10.0L) { *value /= 10.0L; exponent++; }\n    while (*va'
    'lue < 1.0L) { *value *= 10.0L; exponent--; }\n    return exponent;\n}\n\nsta'
    'tic int __btrc_rt_next_digit(long double *value) {\n    int digit = (int)'
    '*value;\n    if (digit < 0) digit = 0;\n    if (digit > 9) digit = 9;\n    '
    '*value = (*value - (long double)digit) * 10.0L;\n    if (*value < 0.0L) *'
    'value = 0.0L;\n    return digit;\n}\n\nstatic void __btrc_rt_emit_exponent(\n'
    '        __btrc_rt_sink *sink, int exponent, bool upper) {\n    char rever'
    "sed[16];\n    int length;\n    __btrc_rt_put(sink, upper ? 'E' : 'e');\n   "
    " if (exponent < 0) { __btrc_rt_put(sink, '-'); exponent = -exponent; }\n "
    "   else __btrc_rt_put(sink, '+');\n    length = __btrc_rt_digits(reversed"
    ', (uintmax_t)exponent, 10U, false);\n    if (length < 2) __btrc_rt_put(si'
    "nk, '0');\n    while (length-- > 0) __btrc_rt_put(sink, reversed[length])"
    ';\n}\n\nstatic void __btrc_rt_emit_fixed_body(\n        __btrc_rt_sink *sink'
    ', long double value, int precision) {\n    long double rounding = 0.5L;\n '
    '   for (int i = 0; i < precision; ++i) rounding /= 10.0L;\n    long doubl'
    'e rounded = value + rounding;\n    if (rounded != 0.0L && rounded + round'
    'ed == rounded) rounded = value;\n    value = rounded;\n    int exponent = '
    '__btrc_rt_normalize(&value);\n    if (rounded == 0.0L || exponent < 0) {\n'
    "        __btrc_rt_put(sink, '0');\n    } else {\n        for (int place = "
    "exponent; place >= 0; --place)\n            __btrc_rt_put(sink, (char)('0"
    "' + __btrc_rt_next_digit(&value)));\n    }\n    if (precision <= 0) return"
    ";\n    __btrc_rt_put(sink, '.');\n    for (int place = -1; place >= -preci"
    'sion; --place) {\n        int digit = place > exponent || rounded == 0.0L'
    '\n            ? 0 : __btrc_rt_next_digit(&value);\n        __btrc_rt_put(s'
    "ink, (char)('0' + digit));\n    }\n}\n\nstatic int __btrc_rt_significant_dig"
    'its(\n        long double *value, int count, unsigned char *digits) {\n   '
    ' if (*value == 0.0L) {\n        for (int i = 0; i < count; ++i) digits[i]'
    ' = 0U;\n        return 0;\n    }\n    int exponent = __btrc_rt_normalize(va'
    'lue);\n    long double rounding = 0.5L;\n    for (int i = 1; i < count; ++'
    'i) rounding /= 10.0L;\n    *value += rounding;\n    if (*value >= 10.0L) {'
    ' *value /= 10.0L; exponent++; }\n    for (int i = 0; i < count; ++i)\n    '
    '    digits[i] = (unsigned char)__btrc_rt_next_digit(value);\n    return e'
    'xponent;\n}\n\nstatic void __btrc_rt_emit_scientific_body(\n        __btrc_r'
    't_sink *sink, long double value, int precision, bool upper) {\n    unsign'
    'ed char digits[20];\n    int count = precision + 1;\n    int exponent = __'
    'btrc_rt_significant_digits(&value, count, digits);\n    __btrc_rt_put(sin'
    "k, (char)('0' + digits[0]));\n    if (precision > 0) {\n        __btrc_rt_"
    "put(sink, '.');\n        for (int i = 1; i < count; ++i)\n            __bt"
    "rc_rt_put(sink, (char)('0' + digits[i]));\n    }\n    __btrc_rt_emit_expon"
    'ent(sink, exponent, upper);\n}\n\nstatic void __btrc_rt_emit_general_body(\n'
    '        __btrc_rt_sink *sink, long double value, int precision,\n        '
    'bool upper, bool alternate) {\n    unsigned char digits[18];\n    int expo'
    'nent = __btrc_rt_significant_digits(&value, precision, digits);\n    int '
    'last = precision - 1;\n    if (!alternate) while (last >= 0 && digits[las'
    "t] == 0) last--;\n    if (last < 0) { __btrc_rt_put(sink, '0'); return; }"
    '\n    if (exponent < -4 || exponent >= precision) {\n        __btrc_rt_put'
    "(sink, (char)('0' + digits[0]));\n        if (last > 0 || alternate) {\n  "
    "          __btrc_rt_put(sink, '.');\n            for (int i = 1; i <= las"
    "t; ++i)\n                __btrc_rt_put(sink, (char)('0' + digits[i]));\n  "
    '      }\n        __btrc_rt_emit_exponent(sink, exponent, upper);\n        '
    "return;\n    }\n    if (exponent < 0) {\n        __btrc_rt_put(sink, '0');\n"
    "        __btrc_rt_put(sink, '.');\n        for (int place = -1; place > e"
    "xponent; --place) __btrc_rt_put(sink, '0');\n        for (int i = 0; i <="
    " last; ++i)\n            __btrc_rt_put(sink, (char)('0' + digits[i]));\n  "
    '      return;\n    }\n    for (int place = 0; place <= exponent; ++place) '
    '{\n        int digit = place < precision ? digits[place] : 0;\n        __b'
    "trc_rt_put(sink, (char)('0' + digit));\n    }\n    if (last > exponent || "
    "alternate) {\n        __btrc_rt_put(sink, '.');\n        for (int i = expo"
    "nent + 1; i <= last; ++i)\n            __btrc_rt_put(sink, (char)('0' + d"
    'igits[i]));\n    }\n}\n\nstatic void __btrc_rt_emit_real_body(\n        __btr'
    'c_rt_sink *sink, long double value, char spec,\n        int precision, bo'
    "ol alternate) {\n    bool upper = spec == 'F' || spec == 'E' || spec == '"
    "G';\n    char lower = upper ? (char)(spec + ('a' - 'A')) : spec;\n    if ("
    'value != value) {\n        const char *word = upper ? "NAN" : "nan";\n    '
    '    while (*word) __btrc_rt_put(sink, *word++);\n    } else if (value != '
    '0.0L && value + value == value) {\n        const char *word = upper ? "IN'
    'F" : "inf";\n        while (*word) __btrc_rt_put(sink, *word++);\n    } el'
    "se if (lower == 'f') {\n        __btrc_rt_emit_fixed_body(sink, value, pr"
    "ecision);\n    } else if (lower == 'e') {\n        __btrc_rt_emit_scientif"
    'ic_body(sink, value, precision, upper);\n    } else {\n        __btrc_rt_e'
    'mit_general_body(sink, value, precision, upper, alternate);\n    }\n}\n\nsta'
    'tic void __btrc_rt_emit_real(\n        __btrc_rt_sink *sink, long double '
    'value, char spec, int width,\n        int precision, bool zero, bool left'
    ', bool plus, bool space,\n        bool alternate) {\n    bool negative = v'
    'alue < 0.0L;\n    if (negative) value = -value;\n    char sign = negative '
    "? '-' : plus ? '+' : space ? ' ' : '\\0';\n    __btrc_rt_sink count = {0};"
    '\n    __btrc_rt_emit_real_body(&count, value, spec, precision, alternate)'
    ';\n    int padding = width - (int)count.pos - (sign ? 1 : 0);\n    if (!le'
    "ft && !zero) __btrc_rt_pad(sink, ' ', padding);\n    if (sign) __btrc_rt_"
    "put(sink, sign);\n    if (!left && zero) __btrc_rt_pad(sink, '0', padding"
    ');\n    __btrc_rt_emit_real_body(sink, value, spec, precision, alternate)'
    ";\n    if (left) __btrc_rt_pad(sink, ' ', padding);\n}\n\nstatic size_t __bt"
    'rc_fmt(char *out, size_t cap, const char *fmt, va_list ap) {\n    __btrc_'
    "rt_sink sink = {out, cap, 0U};\n    while (*fmt) {\n        if (*fmt != '%"
    "') { __btrc_rt_put(&sink, *fmt++); continue; }\n        fmt++;\n        bo"
    'ol left = false, plus = false, space = false, alternate = false, zero = '
    'false;\n        bool flags = true;\n        while (flags) {\n            sw'
    "itch (*fmt) {\n            case '-': left = true; fmt++; break;\n         "
    "   case '+': plus = true; fmt++; break;\n            case ' ': space = tr"
    "ue; fmt++; break;\n            case '#': alternate = true; fmt++; break;\n"
    "            case '0': zero = true; fmt++; break;\n            default: fl"
    'ags = false; break;\n            }\n        }\n        int width = 0;\n     '
    "   if (*fmt == '*') {\n            width = va_arg(ap, int);\n            f"
    'mt++;\n            if (width < 0) {\n                left = true;\n        '
    '        width = width == INT_MIN ? INT_MAX : -width;\n            }\n     '
    "   }\n        else while (*fmt >= '0' && *fmt <= '9') {\n            if (w"
    "idth <= (INT_MAX - 9) / 10) width = width * 10 + (*fmt - '0');\n         "
    "   fmt++;\n        }\n        int precision = -1;\n        if (*fmt == '.')"
    " {\n            fmt++; precision = 0;\n            if (*fmt == '*') { prec"
    "ision = va_arg(ap, int); fmt++; }\n            else while (*fmt >= '0' &&"
    " *fmt <= '9') {\n                if (precision <= (INT_MAX - 9) / 10) pre"
    "cision = precision * 10 + (*fmt - '0');\n                fmt++;\n         "
    '   }\n            if (precision < 0) precision = -1;\n        }\n        in'
    "t length = 0;\n        if (*fmt == 'h') { fmt++; length = *fmt == 'h' ? ("
    "fmt++, -2) : -1; }\n        else if (*fmt == 'l') { fmt++; length = *fmt "
    "== 'l' ? (fmt++, 2) : 1; }\n        else if (*fmt == 'j') { fmt++; length"
    " = 3; }\n        else if (*fmt == 'z') { fmt++; length = 4; }\n        els"
    "e if (*fmt == 't') { fmt++; length = 5; }\n        else if (*fmt == 'L') "
    '{ fmt++; length = 6; }\n        char spec = *fmt;\n        if (!spec) brea'
    "k;\n        fmt++;\n        if (spec == 'd' || spec == 'i') {\n            "
    'intmax_t signed_value = length == 1 ? (intmax_t)va_arg(ap, long)\n       '
    '         : length == 2 ? (intmax_t)va_arg(ap, long long)\n               '
    ' : length == 3 ? va_arg(ap, intmax_t)\n                : length == 4 || l'
    'ength == 5 ? (intmax_t)va_arg(ap, ptrdiff_t)\n                : (intmax_t'
    ')va_arg(ap, int);\n            bool negative = signed_value < 0;\n        '
    '    uintmax_t magnitude = negative\n                ? (uintmax_t)(-(signe'
    'd_value + 1)) + 1U : (uintmax_t)signed_value;\n            __btrc_rt_emit'
    '_integer(&sink, magnitude, negative, 10U, false,\n                false, '
    "width, precision, zero, left, plus, space);\n        } else if (spec == '"
    "u' || spec == 'o' || spec == 'x' || spec == 'X') {\n            uintmax_t"
    ' value = length == 1 ? (uintmax_t)va_arg(ap, unsigned long)\n            '
    '    : length == 2 ? (uintmax_t)va_arg(ap, unsigned long long)\n          '
    '      : length == 3 ? va_arg(ap, uintmax_t)\n                : length == '
    '4 ? (uintmax_t)va_arg(ap, size_t)\n                : length == 5 ? (uintm'
    'ax_t)va_arg(ap, uintptr_t)\n                : (uintmax_t)va_arg(ap, unsig'
    "ned int);\n            unsigned int base = spec == 'o' ? 8U : (spec == 'x"
    "' || spec == 'X' ? 16U : 10U);\n            __btrc_rt_emit_integer(&sink,"
    " value, false, base, spec == 'X',\n                alternate, width, prec"
    "ision, zero, left, false, false);\n        } else if (spec == 'f' || spec"
    " == 'F' || spec == 'e' || spec == 'E'\n                || spec == 'g' || "
    "spec == 'G') {\n            long double value = length == 6 ? va_arg(ap, "
    'long double)\n                                            : (long double)'
    'va_arg(ap, double);\n            int real_precision = precision < 0 ? 6 :'
    " precision;\n            if ((spec == 'g' || spec == 'G') && real_precisi"
    'on == 0) real_precision = 1;\n            if (real_precision > 18) real_p'
    'recision = 18;\n            __btrc_rt_emit_real(&sink, value, spec, width'
    ', real_precision,\n                zero, left, plus, space, alternate);\n '
    "       } else if (spec == 'c') {\n            int padding = width - 1;\n  "
    "          if (!left) __btrc_rt_pad(&sink, ' ', padding);\n            __b"
    'trc_rt_put(&sink, (char)va_arg(ap, int));\n            if (left) __btrc_r'
    "t_pad(&sink, ' ', padding);\n        } else if (spec == 's') {\n          "
    '  const char *value = va_arg(ap, const char *);\n            if (!value) '
    'value = "(null)";\n            size_t length_value = strlen(value);\n     '
    '       if (precision >= 0 && length_value > (size_t)precision) length_va'
    'lue = (size_t)precision;\n            int padding = length_value < (size_'
    't)width ? width - (int)length_value : 0;\n            if (!left) __btrc_r'
    "t_pad(&sink, ' ', padding);\n            for (size_t i = 0; i < length_va"
    'lue; ++i) __btrc_rt_put(&sink, value[i]);\n            if (left) __btrc_r'
    "t_pad(&sink, ' ', padding);\n        } else if (spec == 'p') {\n          "
    '  uintptr_t value = (uintptr_t)va_arg(ap, void *);\n            __btrc_rt'
    '_emit_integer(&sink, (uintmax_t)value, false, 16U, false,\n              '
    '  true, width, precision, zero, left, false, false);\n        } else if ('
    "spec == '%') {\n            __btrc_rt_put(&sink, '%');\n        } else {\n "
    "           __btrc_rt_put(&sink, '%');\n            __btrc_rt_put(&sink, s"
    'pec);\n        }\n    }\n    if (out && cap) out[sink.pos < cap ? sink.pos '
    ": cap - 1U] = '\\0';\n    return sink.pos;\n}\n\nint snprintf(char *out, size"
    '_t cap, const char *format, ...) {\n    va_list args;\n    va_start(args, '
    'format);\n    size_t length = __btrc_fmt(out, cap, format, args);\n    va_'
    'end(args);\n    return length > (size_t)INT_MAX ? -1 : (int)length;\n}\nsta'
    'tic int __btrc_rt_vprint(const char *format, va_list args) {\n    va_list'
    ' count_args;\n    va_copy(count_args, args);\n    size_t length = __btrc_f'
    'mt((char *)0, 0U, format, count_args);\n    va_end(count_args);\n    if (l'
    'ength > (size_t)INT_MAX || length == SIZE_MAX) return -1;\n    char *buff'
    'er = malloc(length + 1U);\n    if (!buffer) return -1;\n    (void)__btrc_f'
    'mt(buffer, length + 1U, format, args);\n    BTRC_RT_PUTS(buffer, length);'
    '\n    free(buffer);\n    return (int)length;\n}\nint printf(const char *form'
    'at, ...) {\n    va_list args;\n    va_start(args, format);\n    int result '
    '= __btrc_rt_vprint(format, args);\n    va_end(args);\n    return result;\n}'
    '\nint fprintf(void *stream, const char *format, ...) {\n    (void)stream;\n'
    '    va_list args;\n    va_start(args, format);\n    int result = __btrc_rt'
    '_vprint(format, args);\n    va_end(args);\n    return result;\n}\n\n#endif /*'
    ' BTRC_FREESTANDING_IMPL */\n\n#endif /* BTRC_FREESTANDING */\n\n#endif /* BT'
    'RC_RT_H */\n'
)
