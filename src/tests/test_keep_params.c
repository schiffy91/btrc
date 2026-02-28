#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <stdint.h>
#include <ctype.h>
#include <math.h>
#include <assert.h>
#include <time.h>
#include <assert.h>

static inline void* __btrc_safe_realloc(void* ptr, size_t size) {
    void* result = realloc(ptr, size);
    if (!result && size > 0) { fprintf(stderr, "btrc: out of memory (realloc %zu bytes)\n", size); exit(1); }
    return result;
}

static inline int __btrc_div_int(int a, int b) {
    if (b == 0) { fprintf(stderr, "Division by zero\n"); exit(1); }
    return a / b;
}

static inline double __btrc_div_double(double a, double b) {
    if (b == 0.0) { fprintf(stderr, "Division by zero\n"); exit(1); }
    return a / b;
}

static inline int __btrc_mod_int(int a, int b) {
    if (b == 0) { fprintf(stderr, "Modulo by zero\n"); exit(1); }
    return a % b;
}

static inline unsigned int __btrc_hash_str(const char* s) {
    unsigned int h = 5381;
    while (*s) { h = ((h << 5) + h) + (unsigned char)*s++; }
    return h;
}

typedef struct Console Console;
typedef struct DateTime DateTime;
typedef struct Timer Timer;
typedef struct Error Error;
typedef struct ValueError ValueError;
typedef struct IOError IOError;
typedef struct TypeError TypeError;
typedef struct IndexError IndexError;
typedef struct KeyError KeyError;
typedef struct File File;
typedef struct Path Path;
typedef struct Math Math;
typedef struct Random Random;
typedef struct Strings Strings;
typedef struct Obj Obj;
typedef struct Holder Holder;
typedef struct btrc_Vector_string btrc_Vector_string;
typedef struct btrc_Vector_int btrc_Vector_int;
typedef struct btrc_Vector_float btrc_Vector_float;
void Console_log(char* msg);
void Console_error(char* msg);
void Console_write(char* msg);
void Console_writeLine(char* msg);
DateTime* DateTime_now();
void DateTime_display(DateTime* self);
char* DateTime_format(DateTime* self);
char* DateTime_dateString(DateTime* self);
char* DateTime_timeString(DateTime* self);
void Timer_start(Timer* self);
void Timer_stop(Timer* self);
float Timer_elapsed(Timer* self);
void Timer_reset(Timer* self);
char* Error_toString(Error* self);
bool File_ok(File* self);
char* File_read(File* self);
char* File_readLine(File* self);
btrc_Vector_string* File_readLines(File* self);
void File_setHandle(File* self, FILE* h);
void File_write(File* self, char* text);
void File_writeLine(File* self, char* text);
void File_close(File* self);
bool File_eof(File* self);
void File_flush(File* self);
bool Path_exists(char* path);
char* Path_readAll(char* path);
void Path_writeAll(char* path, char* content);
float Math_PI();
float Math_E();
float Math_TAU();
float Math_INF();
int Math_abs(int x);
float Math_fabs(float x);
int Math_max(int a, int b);
int Math_min(int a, int b);
float Math_fmax(float a, float b);
float Math_fmin(float a, float b);
int Math_clamp(int x, int lo, int hi);
float Math_power(float base, int exp);
float Math_sqrt(float x);
int Math_factorial(int n);
int Math_gcd(int a, int b);
int Math_lcm(int a, int b);
int Math_fibonacci(int n);
bool Math_isPrime(int n);
bool Math_isEven(int n);
bool Math_isOdd(int n);
int Math_sum(btrc_Vector_int* items);
float Math_fsum(btrc_Vector_float* items);
float Math_sin(float x);
float Math_cos(float x);
float Math_tan(float x);
float Math_asin(float x);
float Math_acos(float x);
float Math_atan(float x);
float Math_atan2(float y, float x);
float Math_ceil(float x);
float Math_floor(float x);
int Math_round(float x);
int Math_truncate(float x);
float Math_log(float x);
float Math_log10(float x);
float Math_log2(float x);
float Math_exp(float x);
float Math_toRadians(float degrees);
float Math_toDegrees(float radians);
float Math_fclamp(float val, float lo, float hi);
int Math_sign(int x);
float Math_fsign(float x);
void Random_seed(Random* self, int s);
void Random_seedTime(Random* self);
int Random_randint(Random* self, int lo, int hi);
float Random_random(Random* self);
float Random_uniform(Random* self, float lo, float hi);
int Random_choice(Random* self, btrc_Vector_int* items);
void Random_shuffle(Random* self, btrc_Vector_int* items);
char* Strings_repeat(char* s, int count);
char* Strings_join(btrc_Vector_string* items, char* sep);
char* Strings_replace(char* s, char* old, char* replacement);
bool Strings_isDigit(char c);
bool Strings_isAlpha(char c);
bool Strings_isAlnum(char c);
bool Strings_isSpace(char c);
int Strings_toInt(char* s);
float Strings_toFloat(char* s);
int Strings_count(char* s, char* sub);
int Strings_find(char* s, char* sub, int start);
int Strings_rfind(char* s, char* sub);
char* Strings_capitalize(char* s);
char* Strings_title(char* s);
char* Strings_swapCase(char* s);
char* Strings_padLeft(char* s, int width, char fill);
char* Strings_padRight(char* s, int width, char fill);
char* Strings_center(char* s, int width, char fill);
char* Strings_lstrip(char* s);
char* Strings_rstrip(char* s);
char* Strings_fromInt(int n);
char* Strings_fromFloat(float f);
bool Strings_isDigitStr(char* s);
bool Strings_isAlphaStr(char* s);
bool Strings_isBlank(char* s);
void Holder_store(Holder* self, Obj* o);
typedef bool (*__btrc_fn_bool_string)(char*);
typedef void (*__btrc_fn_void_string)(char*);
typedef char* (*__btrc_fn_string_string)(char*);
typedef char* (*__btrc_fn_string_string_string)(char*, char*);
typedef bool (*__btrc_fn_bool_int)(int);
typedef void (*__btrc_fn_void_int)(int);
typedef int (*__btrc_fn_int_int)(int);
typedef int (*__btrc_fn_int_int_int)(int, int);
typedef bool (*__btrc_fn_bool_float)(float);
typedef void (*__btrc_fn_void_float)(float);
typedef float (*__btrc_fn_float_float)(float);
typedef float (*__btrc_fn_float_float_float)(float, float);

struct btrc_Vector_string {
    int __rc;
    char** data;
    int len;
    int cap;
};

struct btrc_Vector_int {
    int __rc;
    int* data;
    int len;
    int cap;
};

struct btrc_Vector_float {
    int __rc;
    float* data;
    int len;
    int cap;
};

struct Console {
    int __rc;
};

struct DateTime {
    int __rc;
    int year;
    int month;
    int day;
    int hour;
    int minute;
    int second;
};

struct Timer {
    int __rc;
    clock_t start_time;
    clock_t end_time;
    bool running;
};

struct Error {
    int __rc;
    char* message;
    int code;
};

struct ValueError {
    int __rc;
    char* message;
    int code;
};

struct IOError {
    int __rc;
    char* message;
    int code;
};

struct TypeError {
    int __rc;
    char* message;
    int code;
};

struct IndexError {
    int __rc;
    char* message;
    int code;
};

struct KeyError {
    int __rc;
    char* message;
    int code;
};

struct File {
    int __rc;
    FILE* handle;
    char* path;
    char* mode;
    bool is_open;
};

struct Path {
    int __rc;
};

struct Math {
    int __rc;
};

struct Random {
    int __rc;
    bool seeded;
};

struct Strings {
    int __rc;
};

struct Obj {
    int __rc;
    int id;
};

struct Holder {
    int __rc;
    Obj* stored;
};

/* Type-dependent comparison/hashing macros for generic collections.
 * Uses __builtin_choose_expr — unselected branch is NOT evaluated.
 * Cast chain (void*)(intptr_t) avoids float-to-pointer hard errors. */
#define __btrc_eq(a, b) __builtin_choose_expr( \
    __builtin_types_compatible_p(__typeof__(a), char*), \
    strcmp((const char*)(void*)(intptr_t)(a), (const char*)(void*)(intptr_t)(b)) == 0, \
    (a) == (b))
#define __btrc_lt(a, b) __builtin_choose_expr( \
    __builtin_types_compatible_p(__typeof__(a), char*), \
    strcmp((const char*)(void*)(intptr_t)(a), (const char*)(void*)(intptr_t)(b)) < 0, \
    (a) < (b))
#define __btrc_gt(a, b) __builtin_choose_expr( \
    __builtin_types_compatible_p(__typeof__(a), char*), \
    strcmp((const char*)(void*)(intptr_t)(a), (const char*)(void*)(intptr_t)(b)) > 0, \
    (a) > (b))
#define __btrc_hash(k) __builtin_choose_expr( \
    __builtin_types_compatible_p(__typeof__(k), char*), \
    __btrc_hash_str((const char*)(void*)(intptr_t)(k)), \
    (unsigned int)(intptr_t)(k))

static void btrc_Vector_string_init(btrc_Vector_string* self);
static btrc_Vector_string* btrc_Vector_string_new(void);
static void btrc_Vector_string_destroy(btrc_Vector_string* self);
static void btrc_Vector_string_push(btrc_Vector_string* self, char* val);
static char* btrc_Vector_string_pop(btrc_Vector_string* self);
static char* btrc_Vector_string_get(btrc_Vector_string* self, int i);
static void btrc_Vector_string_set(btrc_Vector_string* self, int i, char* val);
static void btrc_Vector_string_free(btrc_Vector_string* self);
static void btrc_Vector_string_remove(btrc_Vector_string* self, int idx);
static void btrc_Vector_string_reverse(btrc_Vector_string* self);
static btrc_Vector_string* btrc_Vector_string_reversed(btrc_Vector_string* self);
static void btrc_Vector_string_swap(btrc_Vector_string* self, int i, int j);
static void btrc_Vector_string_clear(btrc_Vector_string* self);
static void btrc_Vector_string_fill(btrc_Vector_string* self, char* val);
static int btrc_Vector_string_size(btrc_Vector_string* self);
static bool btrc_Vector_string_isEmpty(btrc_Vector_string* self);
static char* btrc_Vector_string_first(btrc_Vector_string* self);
static char* btrc_Vector_string_last(btrc_Vector_string* self);
static btrc_Vector_string* btrc_Vector_string_slice(btrc_Vector_string* self, int start, int end);
static btrc_Vector_string* btrc_Vector_string_take(btrc_Vector_string* self, int n);
static btrc_Vector_string* btrc_Vector_string_drop(btrc_Vector_string* self, int n);
static void btrc_Vector_string_extend(btrc_Vector_string* self, btrc_Vector_string* other);
static void btrc_Vector_string_insert(btrc_Vector_string* self, int idx, char* val);
static bool btrc_Vector_string_contains(btrc_Vector_string* self, char* val);
static int btrc_Vector_string_indexOf(btrc_Vector_string* self, char* val);
static int btrc_Vector_string_lastIndexOf(btrc_Vector_string* self, char* val);
static int btrc_Vector_string_count(btrc_Vector_string* self, char* val);
static void btrc_Vector_string_removeAll(btrc_Vector_string* self, char* val);
static btrc_Vector_string* btrc_Vector_string_distinct(btrc_Vector_string* self);
static void btrc_Vector_string_sort(btrc_Vector_string* self);
static btrc_Vector_string* btrc_Vector_string_sorted(btrc_Vector_string* self);
static char* btrc_Vector_string_min(btrc_Vector_string* self);
static char* btrc_Vector_string_max(btrc_Vector_string* self);
static char* btrc_Vector_string_sum(btrc_Vector_string* self);
static char* btrc_Vector_string_join(btrc_Vector_string* self, char* sep);
static char* btrc_Vector_string_joinToString(btrc_Vector_string* self, char* sep);
static btrc_Vector_string* btrc_Vector_string_filter(btrc_Vector_string* self, __btrc_fn_bool_string pred);
static int btrc_Vector_string_findIndex(btrc_Vector_string* self, __btrc_fn_bool_string pred);
static void btrc_Vector_string_forEach(btrc_Vector_string* self, __btrc_fn_void_string fn);
static btrc_Vector_string* btrc_Vector_string_map(btrc_Vector_string* self, __btrc_fn_string_string fn);
static bool btrc_Vector_string_any(btrc_Vector_string* self, __btrc_fn_bool_string pred);
static bool btrc_Vector_string_all(btrc_Vector_string* self, __btrc_fn_bool_string pred);
static char* btrc_Vector_string_reduce(btrc_Vector_string* self, char* init, __btrc_fn_string_string_string fn);
static btrc_Vector_string* btrc_Vector_string_copy(btrc_Vector_string* self);
static void btrc_Vector_string_removeAt(btrc_Vector_string* self, int idx);
static int btrc_Vector_string_iterLen(btrc_Vector_string* self);
static char* btrc_Vector_string_iterGet(btrc_Vector_string* self, int i);

static void btrc_Vector_string_init(btrc_Vector_string* self) {
    self->__rc = 1;
    self->data = NULL;
    self->len = 0;
    self->cap = 0;
}
static btrc_Vector_string* btrc_Vector_string_new(void) {
    btrc_Vector_string* self = (btrc_Vector_string*)malloc(sizeof(btrc_Vector_string));
    memset(self, 0, sizeof(btrc_Vector_string));
    btrc_Vector_string_init(self);
    return self;
}
static void btrc_Vector_string_destroy(btrc_Vector_string* self) {
    free(self);
}
static void btrc_Vector_string_push(btrc_Vector_string* self, char* val) {
    if ((self->len >= self->cap)) {
        self->cap = ((self->cap == 0) ? 4 : (self->cap * 2));
        self->data = (char**)__btrc_safe_realloc(self->data, (sizeof(char*) * self->cap));
    }
    self->data[self->len] = val;
    (self->len++);
}
static char* btrc_Vector_string_pop(btrc_Vector_string* self) {
    if ((self->len <= 0)) {
        fprintf(stderr, "Vector pop from empty list\n");
        exit(1);
    }
    (self->len--);
    return self->data[self->len];
}
static char* btrc_Vector_string_get(btrc_Vector_string* self, int i) {
    if (((i < 0) || (i >= self->len))) {
        fprintf(stderr, "Vector index out of bounds: %d (len=%d)\n", i, self->len);
        exit(1);
    }
    return self->data[i];
}
static void btrc_Vector_string_set(btrc_Vector_string* self, int i, char* val) {
    if (((i < 0) || (i >= self->len))) {
        fprintf(stderr, "Vector index out of bounds: %d (len=%d)\n", i, self->len);
        exit(1);
    }
    self->data[i] = val;
}
static void btrc_Vector_string_free(btrc_Vector_string* self) {
    free(self->data);
    self->data = NULL;
    self->len = 0;
    self->cap = 0;
}
static void btrc_Vector_string_remove(btrc_Vector_string* self, int idx) {
    if (((idx < 0) || (idx >= self->len))) {
        fprintf(stderr, "Vector remove index out of bounds: %d (len=%d)\n", idx, self->len);
        exit(1);
    }
    for (int i = idx; (i < (self->len - 1)); (i++)) {
        self->data[i] = self->data[(i + 1)];
    }
    (self->len--);
}
static void btrc_Vector_string_reverse(btrc_Vector_string* self) {
    for (int i = 0; (i < (self->len / 2)); (i++)) {
        char* tmp = self->data[i];
        self->data[i] = self->data[((self->len - 1) - i)];
        self->data[((self->len - 1) - i)] = tmp;
    }
}
static btrc_Vector_string* btrc_Vector_string_reversed(btrc_Vector_string* self) {
    btrc_Vector_string* result = btrc_Vector_string_new();
    for (int i = (self->len - 1); (i >= 0); (i--)) {
        btrc_Vector_string_push(result, self->data[i]);
    }
    return result;
}
static void btrc_Vector_string_swap(btrc_Vector_string* self, int i, int j) {
    if (((((i < 0) || (i >= self->len)) || (j < 0)) || (j >= self->len))) {
        fprintf(stderr, "Vector swap index out of bounds\n");
        exit(1);
    }
    char* tmp = self->data[i];
    self->data[i] = self->data[j];
    self->data[j] = tmp;
}
static void btrc_Vector_string_clear(btrc_Vector_string* self) {
    self->len = 0;
}
static void btrc_Vector_string_fill(btrc_Vector_string* self, char* val) {
    for (int i = 0; (i < self->len); (i++)) {
        self->data[i] = val;
    }
}
static int btrc_Vector_string_size(btrc_Vector_string* self) {
    return self->len;
}
static bool btrc_Vector_string_isEmpty(btrc_Vector_string* self) {
    return (self->len == 0);
}
static char* btrc_Vector_string_first(btrc_Vector_string* self) {
    if ((self->len == 0)) {
        fprintf(stderr, "Vector.first() called on empty list\n");
        exit(1);
    }
    return self->data[0];
}
static char* btrc_Vector_string_last(btrc_Vector_string* self) {
    if ((self->len == 0)) {
        fprintf(stderr, "Vector.last() called on empty list\n");
        exit(1);
    }
    return self->data[(self->len - 1)];
}
static btrc_Vector_string* btrc_Vector_string_slice(btrc_Vector_string* self, int start, int end) {
    if ((start < 0)) {
        start = (self->len + start);
    }
    if ((end < 0)) {
        end = (self->len + end);
    }
    if ((start < 0)) {
        start = 0;
    }
    if ((end > self->len)) {
        end = self->len;
    }
    btrc_Vector_string* result = btrc_Vector_string_new();
    for (int i = start; (i < end); (i++)) {
        btrc_Vector_string_push(result, self->data[i]);
    }
    return result;
}
static btrc_Vector_string* btrc_Vector_string_take(btrc_Vector_string* self, int n) {
    if ((n > self->len)) {
        n = self->len;
    }
    if ((n < 0)) {
        n = 0;
    }
    return btrc_Vector_string_slice(self, 0, n);
}
static btrc_Vector_string* btrc_Vector_string_drop(btrc_Vector_string* self, int n) {
    if ((n > self->len)) {
        n = self->len;
    }
    if ((n < 0)) {
        n = 0;
    }
    return btrc_Vector_string_slice(self, n, self->len);
}
static void btrc_Vector_string_extend(btrc_Vector_string* self, btrc_Vector_string* other) {
    for (int i = 0; (i < other->len); (i++)) {
        btrc_Vector_string_push(self, other->data[i]);
    }
}
static void btrc_Vector_string_insert(btrc_Vector_string* self, int idx, char* val) {
    if (((idx < 0) || (idx > self->len))) {
        fprintf(stderr, "Vector insert index out of bounds: %d (size %d)\n", idx, self->len);
        exit(1);
    }
    if ((self->len >= self->cap)) {
        self->cap = ((self->cap == 0) ? 4 : (self->cap * 2));
        self->data = (char**)__btrc_safe_realloc(self->data, (sizeof(char*) * self->cap));
    }
    for (int i = self->len; (i > idx); (i--)) {
        self->data[i] = self->data[(i - 1)];
    }
    self->data[idx] = val;
    (self->len++);
}
static bool btrc_Vector_string_contains(btrc_Vector_string* self, char* val) {
    for (int i = 0; (i < self->len); (i++)) {
        if (__btrc_eq(self->data[i], val)) {
            return true;
        }
    }
    return false;
}
static int btrc_Vector_string_indexOf(btrc_Vector_string* self, char* val) {
    for (int i = 0; (i < self->len); (i++)) {
        if (__btrc_eq(self->data[i], val)) {
            return i;
        }
    }
    return (-1);
}
static int btrc_Vector_string_lastIndexOf(btrc_Vector_string* self, char* val) {
    for (int i = (self->len - 1); (i >= 0); (i--)) {
        if (__btrc_eq(self->data[i], val)) {
            return i;
        }
    }
    return (-1);
}
static int btrc_Vector_string_count(btrc_Vector_string* self, char* val) {
    int c = 0;
    for (int i = 0; (i < self->len); (i++)) {
        if (__btrc_eq(self->data[i], val)) {
            (c++);
        }
    }
    return c;
}
static void btrc_Vector_string_removeAll(btrc_Vector_string* self, char* val) {
    int j = 0;
    for (int i = 0; (i < self->len); (i++)) {
        if ((!__btrc_eq(self->data[i], val))) {
            self->data[j] = self->data[i];
            (j++);
        }
    }
    self->len = j;
}
static btrc_Vector_string* btrc_Vector_string_distinct(btrc_Vector_string* self) {
    btrc_Vector_string* result = btrc_Vector_string_new();
    for (int i = 0; (i < self->len); (i++)) {
        if ((!btrc_Vector_string_contains(result, self->data[i]))) {
            btrc_Vector_string_push(result, self->data[i]);
        }
    }
    return result;
}
static void btrc_Vector_string_sort(btrc_Vector_string* self) {
    for (int i = 1; (i < self->len); (i++)) {
        char* key = self->data[i];
        int j = (i - 1);
        while (((j >= 0) && __btrc_lt(key, self->data[j]))) {
            self->data[(j + 1)] = self->data[j];
            j = (j - 1);
        }
        self->data[(j + 1)] = key;
    }
}
static btrc_Vector_string* btrc_Vector_string_sorted(btrc_Vector_string* self) {
    btrc_Vector_string* result = btrc_Vector_string_new();
    for (int i = 0; (i < self->len); (i++)) {
        btrc_Vector_string_push(result, self->data[i]);
    }
    btrc_Vector_string_sort(result);
    return result;
}
static char* btrc_Vector_string_min(btrc_Vector_string* self) {
    if ((self->len <= 0)) {
        fprintf(stderr, "Vector min on empty list\n");
        exit(1);
    }
    char* m = self->data[0];
    for (int i = 1; (i < self->len); (i++)) {
        if (__btrc_lt(self->data[i], m)) {
            m = self->data[i];
        }
    }
    return m;
}
static char* btrc_Vector_string_max(btrc_Vector_string* self) {
    if ((self->len <= 0)) {
        fprintf(stderr, "Vector max on empty list\n");
        exit(1);
    }
    char* m = self->data[0];
    for (int i = 1; (i < self->len); (i++)) {
        if (__btrc_gt(self->data[i], m)) {
            m = self->data[i];
        }
    }
    return m;
}
static char* btrc_Vector_string_join(btrc_Vector_string* self, char* sep) {
    int total = 0;
    int sep_len = (int)strlen(sep);
    for (int i = 0; (i < self->len); (i++)) {
        total = (total + (int)strlen(self->data[i]));
        if ((i < (self->len - 1))) {
            total = (total + sep_len);
        }
    }
    char* result = (char*)malloc((total + 1));
    int pos = 0;
    for (int i = 0; (i < self->len); (i++)) {
        int slen = (int)strlen(self->data[i]);
        memcpy((result + pos), self->data[i], slen);
        pos = (pos + slen);
        if ((i < (self->len - 1))) {
            memcpy((result + pos), sep, sep_len);
            pos = (pos + sep_len);
        }
    }
    result[pos] = '\0';
    return result;
}
static char* btrc_Vector_string_joinToString(btrc_Vector_string* self, char* sep) {
    return btrc_Vector_string_join(self, sep);
}
static btrc_Vector_string* btrc_Vector_string_filter(btrc_Vector_string* self, __btrc_fn_bool_string pred) {
    btrc_Vector_string* result = btrc_Vector_string_new();
    for (int i = 0; (i < self->len); (i++)) {
        if (pred(self->data[i])) {
            btrc_Vector_string_push(result, self->data[i]);
        }
    }
    return result;
}
static int btrc_Vector_string_findIndex(btrc_Vector_string* self, __btrc_fn_bool_string pred) {
    for (int i = 0; (i < self->len); (i++)) {
        if (pred(self->data[i])) {
            return i;
        }
    }
    return (-1);
}
static void btrc_Vector_string_forEach(btrc_Vector_string* self, __btrc_fn_void_string fn) {
    for (int i = 0; (i < self->len); (i++)) {
        fn(self->data[i]);
    }
}
static btrc_Vector_string* btrc_Vector_string_map(btrc_Vector_string* self, __btrc_fn_string_string fn) {
    btrc_Vector_string* result = btrc_Vector_string_new();
    for (int i = 0; (i < self->len); (i++)) {
        btrc_Vector_string_push(result, fn(self->data[i]));
    }
    return result;
}
static bool btrc_Vector_string_any(btrc_Vector_string* self, __btrc_fn_bool_string pred) {
    for (int i = 0; (i < self->len); (i++)) {
        if (pred(self->data[i])) {
            return true;
        }
    }
    return false;
}
static bool btrc_Vector_string_all(btrc_Vector_string* self, __btrc_fn_bool_string pred) {
    for (int i = 0; (i < self->len); (i++)) {
        if ((!pred(self->data[i]))) {
            return false;
        }
    }
    return true;
}
static char* btrc_Vector_string_reduce(btrc_Vector_string* self, char* init, __btrc_fn_string_string_string fn) {
    char* acc = init;
    for (int i = 0; (i < self->len); (i++)) {
        acc = fn(acc, self->data[i]);
    }
    return acc;
}
static btrc_Vector_string* btrc_Vector_string_copy(btrc_Vector_string* self) {
    btrc_Vector_string* result = btrc_Vector_string_new();
    for (int i = 0; (i < self->len); (i++)) {
        btrc_Vector_string_push(result, self->data[i]);
    }
    return result;
}
static void btrc_Vector_string_removeAt(btrc_Vector_string* self, int idx) {
    btrc_Vector_string_remove(self, idx);
}
static int btrc_Vector_string_iterLen(btrc_Vector_string* self) {
    return self->len;
}
static char* btrc_Vector_string_iterGet(btrc_Vector_string* self, int i) {
    return self->data[i];
}

static void btrc_Vector_int_init(btrc_Vector_int* self);
static btrc_Vector_int* btrc_Vector_int_new(void);
static void btrc_Vector_int_destroy(btrc_Vector_int* self);
static void btrc_Vector_int_push(btrc_Vector_int* self, int val);
static int btrc_Vector_int_pop(btrc_Vector_int* self);
static int btrc_Vector_int_get(btrc_Vector_int* self, int i);
static void btrc_Vector_int_set(btrc_Vector_int* self, int i, int val);
static void btrc_Vector_int_free(btrc_Vector_int* self);
static void btrc_Vector_int_remove(btrc_Vector_int* self, int idx);
static void btrc_Vector_int_reverse(btrc_Vector_int* self);
static btrc_Vector_int* btrc_Vector_int_reversed(btrc_Vector_int* self);
static void btrc_Vector_int_swap(btrc_Vector_int* self, int i, int j);
static void btrc_Vector_int_clear(btrc_Vector_int* self);
static void btrc_Vector_int_fill(btrc_Vector_int* self, int val);
static int btrc_Vector_int_size(btrc_Vector_int* self);
static bool btrc_Vector_int_isEmpty(btrc_Vector_int* self);
static int btrc_Vector_int_first(btrc_Vector_int* self);
static int btrc_Vector_int_last(btrc_Vector_int* self);
static btrc_Vector_int* btrc_Vector_int_slice(btrc_Vector_int* self, int start, int end);
static btrc_Vector_int* btrc_Vector_int_take(btrc_Vector_int* self, int n);
static btrc_Vector_int* btrc_Vector_int_drop(btrc_Vector_int* self, int n);
static void btrc_Vector_int_extend(btrc_Vector_int* self, btrc_Vector_int* other);
static void btrc_Vector_int_insert(btrc_Vector_int* self, int idx, int val);
static bool btrc_Vector_int_contains(btrc_Vector_int* self, int val);
static int btrc_Vector_int_indexOf(btrc_Vector_int* self, int val);
static int btrc_Vector_int_lastIndexOf(btrc_Vector_int* self, int val);
static int btrc_Vector_int_count(btrc_Vector_int* self, int val);
static void btrc_Vector_int_removeAll(btrc_Vector_int* self, int val);
static btrc_Vector_int* btrc_Vector_int_distinct(btrc_Vector_int* self);
static void btrc_Vector_int_sort(btrc_Vector_int* self);
static btrc_Vector_int* btrc_Vector_int_sorted(btrc_Vector_int* self);
static int btrc_Vector_int_min(btrc_Vector_int* self);
static int btrc_Vector_int_max(btrc_Vector_int* self);
static int btrc_Vector_int_sum(btrc_Vector_int* self);
static char* btrc_Vector_int_join(btrc_Vector_int* self, char* sep);
static char* btrc_Vector_int_joinToString(btrc_Vector_int* self, char* sep);
static btrc_Vector_int* btrc_Vector_int_filter(btrc_Vector_int* self, __btrc_fn_bool_int pred);
static int btrc_Vector_int_findIndex(btrc_Vector_int* self, __btrc_fn_bool_int pred);
static void btrc_Vector_int_forEach(btrc_Vector_int* self, __btrc_fn_void_int fn);
static btrc_Vector_int* btrc_Vector_int_map(btrc_Vector_int* self, __btrc_fn_int_int fn);
static bool btrc_Vector_int_any(btrc_Vector_int* self, __btrc_fn_bool_int pred);
static bool btrc_Vector_int_all(btrc_Vector_int* self, __btrc_fn_bool_int pred);
static int btrc_Vector_int_reduce(btrc_Vector_int* self, int init, __btrc_fn_int_int_int fn);
static btrc_Vector_int* btrc_Vector_int_copy(btrc_Vector_int* self);
static void btrc_Vector_int_removeAt(btrc_Vector_int* self, int idx);
static int btrc_Vector_int_iterLen(btrc_Vector_int* self);
static int btrc_Vector_int_iterGet(btrc_Vector_int* self, int i);

static void btrc_Vector_int_init(btrc_Vector_int* self) {
    self->__rc = 1;
    self->data = NULL;
    self->len = 0;
    self->cap = 0;
}
static btrc_Vector_int* btrc_Vector_int_new(void) {
    btrc_Vector_int* self = (btrc_Vector_int*)malloc(sizeof(btrc_Vector_int));
    memset(self, 0, sizeof(btrc_Vector_int));
    btrc_Vector_int_init(self);
    return self;
}
static void btrc_Vector_int_destroy(btrc_Vector_int* self) {
    free(self);
}
static void btrc_Vector_int_push(btrc_Vector_int* self, int val) {
    if ((self->len >= self->cap)) {
        self->cap = ((self->cap == 0) ? 4 : (self->cap * 2));
        self->data = (int*)__btrc_safe_realloc(self->data, (sizeof(int) * self->cap));
    }
    self->data[self->len] = val;
    (self->len++);
}
static int btrc_Vector_int_pop(btrc_Vector_int* self) {
    if ((self->len <= 0)) {
        fprintf(stderr, "Vector pop from empty list\n");
        exit(1);
    }
    (self->len--);
    return self->data[self->len];
}
static int btrc_Vector_int_get(btrc_Vector_int* self, int i) {
    if (((i < 0) || (i >= self->len))) {
        fprintf(stderr, "Vector index out of bounds: %d (len=%d)\n", i, self->len);
        exit(1);
    }
    return self->data[i];
}
static void btrc_Vector_int_set(btrc_Vector_int* self, int i, int val) {
    if (((i < 0) || (i >= self->len))) {
        fprintf(stderr, "Vector index out of bounds: %d (len=%d)\n", i, self->len);
        exit(1);
    }
    self->data[i] = val;
}
static void btrc_Vector_int_free(btrc_Vector_int* self) {
    free(self->data);
    self->data = NULL;
    self->len = 0;
    self->cap = 0;
}
static void btrc_Vector_int_remove(btrc_Vector_int* self, int idx) {
    if (((idx < 0) || (idx >= self->len))) {
        fprintf(stderr, "Vector remove index out of bounds: %d (len=%d)\n", idx, self->len);
        exit(1);
    }
    for (int i = idx; (i < (self->len - 1)); (i++)) {
        self->data[i] = self->data[(i + 1)];
    }
    (self->len--);
}
static void btrc_Vector_int_reverse(btrc_Vector_int* self) {
    for (int i = 0; (i < (self->len / 2)); (i++)) {
        int tmp = self->data[i];
        self->data[i] = self->data[((self->len - 1) - i)];
        self->data[((self->len - 1) - i)] = tmp;
    }
}
static btrc_Vector_int* btrc_Vector_int_reversed(btrc_Vector_int* self) {
    btrc_Vector_int* result = btrc_Vector_int_new();
    for (int i = (self->len - 1); (i >= 0); (i--)) {
        btrc_Vector_int_push(result, self->data[i]);
    }
    return result;
}
static void btrc_Vector_int_swap(btrc_Vector_int* self, int i, int j) {
    if (((((i < 0) || (i >= self->len)) || (j < 0)) || (j >= self->len))) {
        fprintf(stderr, "Vector swap index out of bounds\n");
        exit(1);
    }
    int tmp = self->data[i];
    self->data[i] = self->data[j];
    self->data[j] = tmp;
}
static void btrc_Vector_int_clear(btrc_Vector_int* self) {
    self->len = 0;
}
static void btrc_Vector_int_fill(btrc_Vector_int* self, int val) {
    for (int i = 0; (i < self->len); (i++)) {
        self->data[i] = val;
    }
}
static int btrc_Vector_int_size(btrc_Vector_int* self) {
    return self->len;
}
static bool btrc_Vector_int_isEmpty(btrc_Vector_int* self) {
    return (self->len == 0);
}
static int btrc_Vector_int_first(btrc_Vector_int* self) {
    if ((self->len == 0)) {
        fprintf(stderr, "Vector.first() called on empty list\n");
        exit(1);
    }
    return self->data[0];
}
static int btrc_Vector_int_last(btrc_Vector_int* self) {
    if ((self->len == 0)) {
        fprintf(stderr, "Vector.last() called on empty list\n");
        exit(1);
    }
    return self->data[(self->len - 1)];
}
static btrc_Vector_int* btrc_Vector_int_slice(btrc_Vector_int* self, int start, int end) {
    if ((start < 0)) {
        start = (self->len + start);
    }
    if ((end < 0)) {
        end = (self->len + end);
    }
    if ((start < 0)) {
        start = 0;
    }
    if ((end > self->len)) {
        end = self->len;
    }
    btrc_Vector_int* result = btrc_Vector_int_new();
    for (int i = start; (i < end); (i++)) {
        btrc_Vector_int_push(result, self->data[i]);
    }
    return result;
}
static btrc_Vector_int* btrc_Vector_int_take(btrc_Vector_int* self, int n) {
    if ((n > self->len)) {
        n = self->len;
    }
    if ((n < 0)) {
        n = 0;
    }
    return btrc_Vector_int_slice(self, 0, n);
}
static btrc_Vector_int* btrc_Vector_int_drop(btrc_Vector_int* self, int n) {
    if ((n > self->len)) {
        n = self->len;
    }
    if ((n < 0)) {
        n = 0;
    }
    return btrc_Vector_int_slice(self, n, self->len);
}
static void btrc_Vector_int_extend(btrc_Vector_int* self, btrc_Vector_int* other) {
    for (int i = 0; (i < other->len); (i++)) {
        btrc_Vector_int_push(self, other->data[i]);
    }
}
static void btrc_Vector_int_insert(btrc_Vector_int* self, int idx, int val) {
    if (((idx < 0) || (idx > self->len))) {
        fprintf(stderr, "Vector insert index out of bounds: %d (size %d)\n", idx, self->len);
        exit(1);
    }
    if ((self->len >= self->cap)) {
        self->cap = ((self->cap == 0) ? 4 : (self->cap * 2));
        self->data = (int*)__btrc_safe_realloc(self->data, (sizeof(int) * self->cap));
    }
    for (int i = self->len; (i > idx); (i--)) {
        self->data[i] = self->data[(i - 1)];
    }
    self->data[idx] = val;
    (self->len++);
}
static bool btrc_Vector_int_contains(btrc_Vector_int* self, int val) {
    for (int i = 0; (i < self->len); (i++)) {
        if (__btrc_eq(self->data[i], val)) {
            return true;
        }
    }
    return false;
}
static int btrc_Vector_int_indexOf(btrc_Vector_int* self, int val) {
    for (int i = 0; (i < self->len); (i++)) {
        if (__btrc_eq(self->data[i], val)) {
            return i;
        }
    }
    return (-1);
}
static int btrc_Vector_int_lastIndexOf(btrc_Vector_int* self, int val) {
    for (int i = (self->len - 1); (i >= 0); (i--)) {
        if (__btrc_eq(self->data[i], val)) {
            return i;
        }
    }
    return (-1);
}
static int btrc_Vector_int_count(btrc_Vector_int* self, int val) {
    int c = 0;
    for (int i = 0; (i < self->len); (i++)) {
        if (__btrc_eq(self->data[i], val)) {
            (c++);
        }
    }
    return c;
}
static void btrc_Vector_int_removeAll(btrc_Vector_int* self, int val) {
    int j = 0;
    for (int i = 0; (i < self->len); (i++)) {
        if ((!__btrc_eq(self->data[i], val))) {
            self->data[j] = self->data[i];
            (j++);
        }
    }
    self->len = j;
}
static btrc_Vector_int* btrc_Vector_int_distinct(btrc_Vector_int* self) {
    btrc_Vector_int* result = btrc_Vector_int_new();
    for (int i = 0; (i < self->len); (i++)) {
        if ((!btrc_Vector_int_contains(result, self->data[i]))) {
            btrc_Vector_int_push(result, self->data[i]);
        }
    }
    return result;
}
static void btrc_Vector_int_sort(btrc_Vector_int* self) {
    for (int i = 1; (i < self->len); (i++)) {
        int key = self->data[i];
        int j = (i - 1);
        while (((j >= 0) && __btrc_lt(key, self->data[j]))) {
            self->data[(j + 1)] = self->data[j];
            j = (j - 1);
        }
        self->data[(j + 1)] = key;
    }
}
static btrc_Vector_int* btrc_Vector_int_sorted(btrc_Vector_int* self) {
    btrc_Vector_int* result = btrc_Vector_int_new();
    for (int i = 0; (i < self->len); (i++)) {
        btrc_Vector_int_push(result, self->data[i]);
    }
    btrc_Vector_int_sort(result);
    return result;
}
static int btrc_Vector_int_min(btrc_Vector_int* self) {
    if ((self->len <= 0)) {
        fprintf(stderr, "Vector min on empty list\n");
        exit(1);
    }
    int m = self->data[0];
    for (int i = 1; (i < self->len); (i++)) {
        if (__btrc_lt(self->data[i], m)) {
            m = self->data[i];
        }
    }
    return m;
}
static int btrc_Vector_int_max(btrc_Vector_int* self) {
    if ((self->len <= 0)) {
        fprintf(stderr, "Vector max on empty list\n");
        exit(1);
    }
    int m = self->data[0];
    for (int i = 1; (i < self->len); (i++)) {
        if (__btrc_gt(self->data[i], m)) {
            m = self->data[i];
        }
    }
    return m;
}
static int btrc_Vector_int_sum(btrc_Vector_int* self) {
    int s = (int)0;
    for (int i = 0; (i < self->len); (i++)) {
        s = (s + self->data[i]);
    }
    return s;
}
static btrc_Vector_int* btrc_Vector_int_filter(btrc_Vector_int* self, __btrc_fn_bool_int pred) {
    btrc_Vector_int* result = btrc_Vector_int_new();
    for (int i = 0; (i < self->len); (i++)) {
        if (pred(self->data[i])) {
            btrc_Vector_int_push(result, self->data[i]);
        }
    }
    return result;
}
static int btrc_Vector_int_findIndex(btrc_Vector_int* self, __btrc_fn_bool_int pred) {
    for (int i = 0; (i < self->len); (i++)) {
        if (pred(self->data[i])) {
            return i;
        }
    }
    return (-1);
}
static void btrc_Vector_int_forEach(btrc_Vector_int* self, __btrc_fn_void_int fn) {
    for (int i = 0; (i < self->len); (i++)) {
        fn(self->data[i]);
    }
}
static btrc_Vector_int* btrc_Vector_int_map(btrc_Vector_int* self, __btrc_fn_int_int fn) {
    btrc_Vector_int* result = btrc_Vector_int_new();
    for (int i = 0; (i < self->len); (i++)) {
        btrc_Vector_int_push(result, fn(self->data[i]));
    }
    return result;
}
static bool btrc_Vector_int_any(btrc_Vector_int* self, __btrc_fn_bool_int pred) {
    for (int i = 0; (i < self->len); (i++)) {
        if (pred(self->data[i])) {
            return true;
        }
    }
    return false;
}
static bool btrc_Vector_int_all(btrc_Vector_int* self, __btrc_fn_bool_int pred) {
    for (int i = 0; (i < self->len); (i++)) {
        if ((!pred(self->data[i]))) {
            return false;
        }
    }
    return true;
}
static int btrc_Vector_int_reduce(btrc_Vector_int* self, int init, __btrc_fn_int_int_int fn) {
    int acc = init;
    for (int i = 0; (i < self->len); (i++)) {
        acc = fn(acc, self->data[i]);
    }
    return acc;
}
static btrc_Vector_int* btrc_Vector_int_copy(btrc_Vector_int* self) {
    btrc_Vector_int* result = btrc_Vector_int_new();
    for (int i = 0; (i < self->len); (i++)) {
        btrc_Vector_int_push(result, self->data[i]);
    }
    return result;
}
static void btrc_Vector_int_removeAt(btrc_Vector_int* self, int idx) {
    btrc_Vector_int_remove(self, idx);
}
static int btrc_Vector_int_iterLen(btrc_Vector_int* self) {
    return self->len;
}
static int btrc_Vector_int_iterGet(btrc_Vector_int* self, int i) {
    return self->data[i];
}

static void btrc_Vector_float_init(btrc_Vector_float* self);
static btrc_Vector_float* btrc_Vector_float_new(void);
static void btrc_Vector_float_destroy(btrc_Vector_float* self);
static void btrc_Vector_float_push(btrc_Vector_float* self, float val);
static float btrc_Vector_float_pop(btrc_Vector_float* self);
static float btrc_Vector_float_get(btrc_Vector_float* self, int i);
static void btrc_Vector_float_set(btrc_Vector_float* self, int i, float val);
static void btrc_Vector_float_free(btrc_Vector_float* self);
static void btrc_Vector_float_remove(btrc_Vector_float* self, int idx);
static void btrc_Vector_float_reverse(btrc_Vector_float* self);
static btrc_Vector_float* btrc_Vector_float_reversed(btrc_Vector_float* self);
static void btrc_Vector_float_swap(btrc_Vector_float* self, int i, int j);
static void btrc_Vector_float_clear(btrc_Vector_float* self);
static void btrc_Vector_float_fill(btrc_Vector_float* self, float val);
static int btrc_Vector_float_size(btrc_Vector_float* self);
static bool btrc_Vector_float_isEmpty(btrc_Vector_float* self);
static float btrc_Vector_float_first(btrc_Vector_float* self);
static float btrc_Vector_float_last(btrc_Vector_float* self);
static btrc_Vector_float* btrc_Vector_float_slice(btrc_Vector_float* self, int start, int end);
static btrc_Vector_float* btrc_Vector_float_take(btrc_Vector_float* self, int n);
static btrc_Vector_float* btrc_Vector_float_drop(btrc_Vector_float* self, int n);
static void btrc_Vector_float_extend(btrc_Vector_float* self, btrc_Vector_float* other);
static void btrc_Vector_float_insert(btrc_Vector_float* self, int idx, float val);
static bool btrc_Vector_float_contains(btrc_Vector_float* self, float val);
static int btrc_Vector_float_indexOf(btrc_Vector_float* self, float val);
static int btrc_Vector_float_lastIndexOf(btrc_Vector_float* self, float val);
static int btrc_Vector_float_count(btrc_Vector_float* self, float val);
static void btrc_Vector_float_removeAll(btrc_Vector_float* self, float val);
static btrc_Vector_float* btrc_Vector_float_distinct(btrc_Vector_float* self);
static void btrc_Vector_float_sort(btrc_Vector_float* self);
static btrc_Vector_float* btrc_Vector_float_sorted(btrc_Vector_float* self);
static float btrc_Vector_float_min(btrc_Vector_float* self);
static float btrc_Vector_float_max(btrc_Vector_float* self);
static float btrc_Vector_float_sum(btrc_Vector_float* self);
static char* btrc_Vector_float_join(btrc_Vector_float* self, char* sep);
static char* btrc_Vector_float_joinToString(btrc_Vector_float* self, char* sep);
static btrc_Vector_float* btrc_Vector_float_filter(btrc_Vector_float* self, __btrc_fn_bool_float pred);
static int btrc_Vector_float_findIndex(btrc_Vector_float* self, __btrc_fn_bool_float pred);
static void btrc_Vector_float_forEach(btrc_Vector_float* self, __btrc_fn_void_float fn);
static btrc_Vector_float* btrc_Vector_float_map(btrc_Vector_float* self, __btrc_fn_float_float fn);
static bool btrc_Vector_float_any(btrc_Vector_float* self, __btrc_fn_bool_float pred);
static bool btrc_Vector_float_all(btrc_Vector_float* self, __btrc_fn_bool_float pred);
static float btrc_Vector_float_reduce(btrc_Vector_float* self, float init, __btrc_fn_float_float_float fn);
static btrc_Vector_float* btrc_Vector_float_copy(btrc_Vector_float* self);
static void btrc_Vector_float_removeAt(btrc_Vector_float* self, int idx);
static int btrc_Vector_float_iterLen(btrc_Vector_float* self);
static float btrc_Vector_float_iterGet(btrc_Vector_float* self, int i);

static void btrc_Vector_float_init(btrc_Vector_float* self) {
    self->__rc = 1;
    self->data = NULL;
    self->len = 0;
    self->cap = 0;
}
static btrc_Vector_float* btrc_Vector_float_new(void) {
    btrc_Vector_float* self = (btrc_Vector_float*)malloc(sizeof(btrc_Vector_float));
    memset(self, 0, sizeof(btrc_Vector_float));
    btrc_Vector_float_init(self);
    return self;
}
static void btrc_Vector_float_destroy(btrc_Vector_float* self) {
    free(self);
}
static void btrc_Vector_float_push(btrc_Vector_float* self, float val) {
    if ((self->len >= self->cap)) {
        self->cap = ((self->cap == 0) ? 4 : (self->cap * 2));
        self->data = (float*)__btrc_safe_realloc(self->data, (sizeof(float) * self->cap));
    }
    self->data[self->len] = val;
    (self->len++);
}
static float btrc_Vector_float_pop(btrc_Vector_float* self) {
    if ((self->len <= 0)) {
        fprintf(stderr, "Vector pop from empty list\n");
        exit(1);
    }
    (self->len--);
    return self->data[self->len];
}
static float btrc_Vector_float_get(btrc_Vector_float* self, int i) {
    if (((i < 0) || (i >= self->len))) {
        fprintf(stderr, "Vector index out of bounds: %d (len=%d)\n", i, self->len);
        exit(1);
    }
    return self->data[i];
}
static void btrc_Vector_float_set(btrc_Vector_float* self, int i, float val) {
    if (((i < 0) || (i >= self->len))) {
        fprintf(stderr, "Vector index out of bounds: %d (len=%d)\n", i, self->len);
        exit(1);
    }
    self->data[i] = val;
}
static void btrc_Vector_float_free(btrc_Vector_float* self) {
    free(self->data);
    self->data = NULL;
    self->len = 0;
    self->cap = 0;
}
static void btrc_Vector_float_remove(btrc_Vector_float* self, int idx) {
    if (((idx < 0) || (idx >= self->len))) {
        fprintf(stderr, "Vector remove index out of bounds: %d (len=%d)\n", idx, self->len);
        exit(1);
    }
    for (int i = idx; (i < (self->len - 1)); (i++)) {
        self->data[i] = self->data[(i + 1)];
    }
    (self->len--);
}
static void btrc_Vector_float_reverse(btrc_Vector_float* self) {
    for (int i = 0; (i < (self->len / 2)); (i++)) {
        float tmp = self->data[i];
        self->data[i] = self->data[((self->len - 1) - i)];
        self->data[((self->len - 1) - i)] = tmp;
    }
}
static btrc_Vector_float* btrc_Vector_float_reversed(btrc_Vector_float* self) {
    btrc_Vector_float* result = btrc_Vector_float_new();
    for (int i = (self->len - 1); (i >= 0); (i--)) {
        btrc_Vector_float_push(result, self->data[i]);
    }
    return result;
}
static void btrc_Vector_float_swap(btrc_Vector_float* self, int i, int j) {
    if (((((i < 0) || (i >= self->len)) || (j < 0)) || (j >= self->len))) {
        fprintf(stderr, "Vector swap index out of bounds\n");
        exit(1);
    }
    float tmp = self->data[i];
    self->data[i] = self->data[j];
    self->data[j] = tmp;
}
static void btrc_Vector_float_clear(btrc_Vector_float* self) {
    self->len = 0;
}
static void btrc_Vector_float_fill(btrc_Vector_float* self, float val) {
    for (int i = 0; (i < self->len); (i++)) {
        self->data[i] = val;
    }
}
static int btrc_Vector_float_size(btrc_Vector_float* self) {
    return self->len;
}
static bool btrc_Vector_float_isEmpty(btrc_Vector_float* self) {
    return (self->len == 0);
}
static float btrc_Vector_float_first(btrc_Vector_float* self) {
    if ((self->len == 0)) {
        fprintf(stderr, "Vector.first() called on empty list\n");
        exit(1);
    }
    return self->data[0];
}
static float btrc_Vector_float_last(btrc_Vector_float* self) {
    if ((self->len == 0)) {
        fprintf(stderr, "Vector.last() called on empty list\n");
        exit(1);
    }
    return self->data[(self->len - 1)];
}
static btrc_Vector_float* btrc_Vector_float_slice(btrc_Vector_float* self, int start, int end) {
    if ((start < 0)) {
        start = (self->len + start);
    }
    if ((end < 0)) {
        end = (self->len + end);
    }
    if ((start < 0)) {
        start = 0;
    }
    if ((end > self->len)) {
        end = self->len;
    }
    btrc_Vector_float* result = btrc_Vector_float_new();
    for (int i = start; (i < end); (i++)) {
        btrc_Vector_float_push(result, self->data[i]);
    }
    return result;
}
static btrc_Vector_float* btrc_Vector_float_take(btrc_Vector_float* self, int n) {
    if ((n > self->len)) {
        n = self->len;
    }
    if ((n < 0)) {
        n = 0;
    }
    return btrc_Vector_float_slice(self, 0, n);
}
static btrc_Vector_float* btrc_Vector_float_drop(btrc_Vector_float* self, int n) {
    if ((n > self->len)) {
        n = self->len;
    }
    if ((n < 0)) {
        n = 0;
    }
    return btrc_Vector_float_slice(self, n, self->len);
}
static void btrc_Vector_float_extend(btrc_Vector_float* self, btrc_Vector_float* other) {
    for (int i = 0; (i < other->len); (i++)) {
        btrc_Vector_float_push(self, other->data[i]);
    }
}
static void btrc_Vector_float_insert(btrc_Vector_float* self, int idx, float val) {
    if (((idx < 0) || (idx > self->len))) {
        fprintf(stderr, "Vector insert index out of bounds: %d (size %d)\n", idx, self->len);
        exit(1);
    }
    if ((self->len >= self->cap)) {
        self->cap = ((self->cap == 0) ? 4 : (self->cap * 2));
        self->data = (float*)__btrc_safe_realloc(self->data, (sizeof(float) * self->cap));
    }
    for (int i = self->len; (i > idx); (i--)) {
        self->data[i] = self->data[(i - 1)];
    }
    self->data[idx] = val;
    (self->len++);
}
static bool btrc_Vector_float_contains(btrc_Vector_float* self, float val) {
    for (int i = 0; (i < self->len); (i++)) {
        if (__btrc_eq(self->data[i], val)) {
            return true;
        }
    }
    return false;
}
static int btrc_Vector_float_indexOf(btrc_Vector_float* self, float val) {
    for (int i = 0; (i < self->len); (i++)) {
        if (__btrc_eq(self->data[i], val)) {
            return i;
        }
    }
    return (-1);
}
static int btrc_Vector_float_lastIndexOf(btrc_Vector_float* self, float val) {
    for (int i = (self->len - 1); (i >= 0); (i--)) {
        if (__btrc_eq(self->data[i], val)) {
            return i;
        }
    }
    return (-1);
}
static int btrc_Vector_float_count(btrc_Vector_float* self, float val) {
    int c = 0;
    for (int i = 0; (i < self->len); (i++)) {
        if (__btrc_eq(self->data[i], val)) {
            (c++);
        }
    }
    return c;
}
static void btrc_Vector_float_removeAll(btrc_Vector_float* self, float val) {
    int j = 0;
    for (int i = 0; (i < self->len); (i++)) {
        if ((!__btrc_eq(self->data[i], val))) {
            self->data[j] = self->data[i];
            (j++);
        }
    }
    self->len = j;
}
static btrc_Vector_float* btrc_Vector_float_distinct(btrc_Vector_float* self) {
    btrc_Vector_float* result = btrc_Vector_float_new();
    for (int i = 0; (i < self->len); (i++)) {
        if ((!btrc_Vector_float_contains(result, self->data[i]))) {
            btrc_Vector_float_push(result, self->data[i]);
        }
    }
    return result;
}
static void btrc_Vector_float_sort(btrc_Vector_float* self) {
    for (int i = 1; (i < self->len); (i++)) {
        float key = self->data[i];
        int j = (i - 1);
        while (((j >= 0) && __btrc_lt(key, self->data[j]))) {
            self->data[(j + 1)] = self->data[j];
            j = (j - 1);
        }
        self->data[(j + 1)] = key;
    }
}
static btrc_Vector_float* btrc_Vector_float_sorted(btrc_Vector_float* self) {
    btrc_Vector_float* result = btrc_Vector_float_new();
    for (int i = 0; (i < self->len); (i++)) {
        btrc_Vector_float_push(result, self->data[i]);
    }
    btrc_Vector_float_sort(result);
    return result;
}
static float btrc_Vector_float_min(btrc_Vector_float* self) {
    if ((self->len <= 0)) {
        fprintf(stderr, "Vector min on empty list\n");
        exit(1);
    }
    float m = self->data[0];
    for (int i = 1; (i < self->len); (i++)) {
        if (__btrc_lt(self->data[i], m)) {
            m = self->data[i];
        }
    }
    return m;
}
static float btrc_Vector_float_max(btrc_Vector_float* self) {
    if ((self->len <= 0)) {
        fprintf(stderr, "Vector max on empty list\n");
        exit(1);
    }
    float m = self->data[0];
    for (int i = 1; (i < self->len); (i++)) {
        if (__btrc_gt(self->data[i], m)) {
            m = self->data[i];
        }
    }
    return m;
}
static float btrc_Vector_float_sum(btrc_Vector_float* self) {
    float s = (float)0;
    for (int i = 0; (i < self->len); (i++)) {
        s = (s + self->data[i]);
    }
    return s;
}
static btrc_Vector_float* btrc_Vector_float_filter(btrc_Vector_float* self, __btrc_fn_bool_float pred) {
    btrc_Vector_float* result = btrc_Vector_float_new();
    for (int i = 0; (i < self->len); (i++)) {
        if (pred(self->data[i])) {
            btrc_Vector_float_push(result, self->data[i]);
        }
    }
    return result;
}
static int btrc_Vector_float_findIndex(btrc_Vector_float* self, __btrc_fn_bool_float pred) {
    for (int i = 0; (i < self->len); (i++)) {
        if (pred(self->data[i])) {
            return i;
        }
    }
    return (-1);
}
static void btrc_Vector_float_forEach(btrc_Vector_float* self, __btrc_fn_void_float fn) {
    for (int i = 0; (i < self->len); (i++)) {
        fn(self->data[i]);
    }
}
static btrc_Vector_float* btrc_Vector_float_map(btrc_Vector_float* self, __btrc_fn_float_float fn) {
    btrc_Vector_float* result = btrc_Vector_float_new();
    for (int i = 0; (i < self->len); (i++)) {
        btrc_Vector_float_push(result, fn(self->data[i]));
    }
    return result;
}
static bool btrc_Vector_float_any(btrc_Vector_float* self, __btrc_fn_bool_float pred) {
    for (int i = 0; (i < self->len); (i++)) {
        if (pred(self->data[i])) {
            return true;
        }
    }
    return false;
}
static bool btrc_Vector_float_all(btrc_Vector_float* self, __btrc_fn_bool_float pred) {
    for (int i = 0; (i < self->len); (i++)) {
        if ((!pred(self->data[i]))) {
            return false;
        }
    }
    return true;
}
static float btrc_Vector_float_reduce(btrc_Vector_float* self, float init, __btrc_fn_float_float_float fn) {
    float acc = init;
    for (int i = 0; (i < self->len); (i++)) {
        acc = fn(acc, self->data[i]);
    }
    return acc;
}
static btrc_Vector_float* btrc_Vector_float_copy(btrc_Vector_float* self) {
    btrc_Vector_float* result = btrc_Vector_float_new();
    for (int i = 0; (i < self->len); (i++)) {
        btrc_Vector_float_push(result, self->data[i]);
    }
    return result;
}
static void btrc_Vector_float_removeAt(btrc_Vector_float* self, int idx) {
    btrc_Vector_float_remove(self, idx);
}
static int btrc_Vector_float_iterLen(btrc_Vector_float* self) {
    return self->len;
}
static float btrc_Vector_float_iterGet(btrc_Vector_float* self, int i) {
    return self->data[i];
}

static int alive = 0;

void Console_init(Console* self) {
    self->__rc = 1;
}

Console* Console_new(void) {
    Console* self = ((Console*)malloc(sizeof(Console)));
    memset(self, 0, sizeof(Console));
    Console_init(self);
    return self;
}

void Console_destroy(Console* self) {
    free(self);
}

void Console_log(char* msg) {
    printf("%s\n", msg);
}

void Console_error(char* msg) {
    fprintf(stderr, "%s\n", msg);
}

void Console_write(char* msg) {
    printf("%s", msg);
}

void Console_writeLine(char* msg) {
    printf("%s\n", msg);
}

void DateTime_init(DateTime* self, int year, int month, int day, int hour, int minute, int second) {
    self->__rc = 1;
    (self->year = year);
    (self->month = month);
    (self->day = day);
    (self->hour = hour);
    (self->minute = minute);
    (self->second = second);
}

DateTime* DateTime_new(int year, int month, int day, int hour, int minute, int second) {
    DateTime* self = ((DateTime*)malloc(sizeof(DateTime)));
    memset(self, 0, sizeof(DateTime));
    DateTime_init(self, year, month, day, hour, minute, second);
    return self;
}

void DateTime_destroy(DateTime* self) {
    free(self);
}

DateTime* DateTime_now(void) {
    time_t t = time(NULL);
    struct tm* tm = localtime((&t));
    return DateTime_new((tm->tm_year + 1900), (tm->tm_mon + 1), tm->tm_mday, tm->tm_hour, tm->tm_min, tm->tm_sec);
}

void DateTime_display(DateTime* self) {
    printf("%04d-%02d-%02d %02d:%02d:%02d", self->year, self->month, self->day, self->hour, self->minute, self->second);
}

char* DateTime_format(DateTime* self) {
    char buf[64];
    snprintf(buf, 64, "%04d-%02d-%02d %02d:%02d:%02d", self->year, self->month, self->day, self->hour, self->minute, self->second);
    return strdup(buf);
}

char* DateTime_dateString(DateTime* self) {
    char buf[32];
    snprintf(buf, 32, "%04d-%02d-%02d", self->year, self->month, self->day);
    return strdup(buf);
}

char* DateTime_timeString(DateTime* self) {
    char buf[32];
    snprintf(buf, 32, "%02d:%02d:%02d", self->hour, self->minute, self->second);
    return strdup(buf);
}

void Timer_init(Timer* self) {
    self->__rc = 1;
    (self->start_time = 0);
    (self->end_time = 0);
    (self->running = false);
}

Timer* Timer_new(void) {
    Timer* self = ((Timer*)malloc(sizeof(Timer)));
    memset(self, 0, sizeof(Timer));
    Timer_init(self);
    return self;
}

void Timer_destroy(Timer* self) {
    free(self);
}

void Timer_start(Timer* self) {
    (self->start_time = clock());
    (self->running = true);
}

void Timer_stop(Timer* self) {
    (self->end_time = clock());
    (self->running = false);
}

float Timer_elapsed(Timer* self) {
    clock_t end = (self->running ? clock() : self->end_time);
    return __btrc_div_double(((float)(end - self->start_time)), ((float)CLOCKS_PER_SEC));
}

void Timer_reset(Timer* self) {
    (self->start_time = 0);
    (self->end_time = 0);
    (self->running = false);
}

void Error_init(Error* self, char* message, int code) {
    self->__rc = 1;
    (self->message = message);
    (self->code = code);
}

Error* Error_new(char* message, int code) {
    Error* self = ((Error*)malloc(sizeof(Error)));
    memset(self, 0, sizeof(Error));
    Error_init(self, message, code);
    return self;
}

void Error_destroy(Error* self) {
    free(self);
}

char* Error_toString(Error* self) {
    return self->message;
}

void ValueError_init(ValueError* self, char* message) {
    self->__rc = 1;
    (self->message = message);
    (self->code = 1);
}

ValueError* ValueError_new(char* message) {
    ValueError* self = ((ValueError*)malloc(sizeof(ValueError)));
    memset(self, 0, sizeof(ValueError));
    ValueError_init(self, message);
    return self;
}

void ValueError_destroy(ValueError* self) {
    free(self);
}

char* ValueError_toString(ValueError* self) {
    return Error_toString(((Error*)self));
}

void IOError_init(IOError* self, char* message) {
    self->__rc = 1;
    (self->message = message);
    (self->code = 2);
}

IOError* IOError_new(char* message) {
    IOError* self = ((IOError*)malloc(sizeof(IOError)));
    memset(self, 0, sizeof(IOError));
    IOError_init(self, message);
    return self;
}

void IOError_destroy(IOError* self) {
    free(self);
}

char* IOError_toString(IOError* self) {
    return Error_toString(((Error*)self));
}

void TypeError_init(TypeError* self, char* message) {
    self->__rc = 1;
    (self->message = message);
    (self->code = 3);
}

TypeError* TypeError_new(char* message) {
    TypeError* self = ((TypeError*)malloc(sizeof(TypeError)));
    memset(self, 0, sizeof(TypeError));
    TypeError_init(self, message);
    return self;
}

void TypeError_destroy(TypeError* self) {
    free(self);
}

char* TypeError_toString(TypeError* self) {
    return Error_toString(((Error*)self));
}

void IndexError_init(IndexError* self, char* message) {
    self->__rc = 1;
    (self->message = message);
    (self->code = 4);
}

IndexError* IndexError_new(char* message) {
    IndexError* self = ((IndexError*)malloc(sizeof(IndexError)));
    memset(self, 0, sizeof(IndexError));
    IndexError_init(self, message);
    return self;
}

void IndexError_destroy(IndexError* self) {
    free(self);
}

char* IndexError_toString(IndexError* self) {
    return Error_toString(((Error*)self));
}

void KeyError_init(KeyError* self, char* message) {
    self->__rc = 1;
    (self->message = message);
    (self->code = 5);
}

KeyError* KeyError_new(char* message) {
    KeyError* self = ((KeyError*)malloc(sizeof(KeyError)));
    memset(self, 0, sizeof(KeyError));
    KeyError_init(self, message);
    return self;
}

void KeyError_destroy(KeyError* self) {
    free(self);
}

char* KeyError_toString(KeyError* self) {
    return Error_toString(((Error*)self));
}

void File_init(File* self, char* path, char* mode) {
    self->__rc = 1;
    (self->path = path);
    (self->mode = mode);
    (self->handle = fopen(path, mode));
    (self->is_open = (self->handle != NULL));
}

File* File_new(char* path, char* mode) {
    File* self = ((File*)malloc(sizeof(File)));
    memset(self, 0, sizeof(File));
    File_init(self, path, mode);
    return self;
}

void File_destroy(File* self) {
    File_close(self);
    free(self);
}

bool File_ok(File* self) {
    return self->is_open;
}

char* File_read(File* self) {
    if ((!self->is_open)) {
        return "";
    }
    fseek(self->handle, 0, SEEK_END);
    long size = ftell(self->handle);
    fseek(self->handle, 0, SEEK_SET);
    char* buf = ((char*)malloc((size + 1)));
    fread(buf, 1, size, self->handle);
    (buf[size] = '\0');
    return buf;
}

char* File_readLine(File* self) {
    if ((!self->is_open)) {
        return "";
    }
    char buf[4096];
    if ((fgets(buf, 4096, self->handle) != NULL)) {
        int len = ((int)strlen(buf));
        if (((len > 0) && (buf[(len - 1)] == '\n'))) {
            (buf[(len - 1)] = '\0');
        }
        return strdup(buf);
    }
    return "";
}

btrc_Vector_string* File_readLines(File* self) {
    btrc_Vector_string* lines = btrc_Vector_string_new();
    if ((!self->is_open)) {
        return lines;
    }
    char buf[4096];
    while ((fgets(buf, 4096, self->handle) != NULL)) {
        int len = ((int)strlen(buf));
        if (((len > 0) && (buf[(len - 1)] == '\n'))) {
            (buf[(len - 1)] = '\0');
        }
        btrc_Vector_string_push(lines, strdup(buf));
    }
    return lines;
}

void File_setHandle(File* self, FILE* h) {
    (self->handle = h);
    (self->is_open = true);
}

void File_write(File* self, char* text) {
    if ((!self->is_open)) {
        return;
    }
    fputs(text, self->handle);
}

void File_writeLine(File* self, char* text) {
    if ((!self->is_open)) {
        return;
    }
    fputs(text, self->handle);
    fputc('\n', self->handle);
}

void File_close(File* self) {
    if (self->is_open) {
        if ((((int)strlen(self->path)) > 0)) {
            fclose(self->handle);
        }
        (self->is_open = false);
    }
}

bool File_eof(File* self) {
    if ((!self->is_open)) {
        return true;
    }
    return (feof(self->handle) != 0);
}

void File_flush(File* self) {
    if (self->is_open) {
        fflush(self->handle);
    }
}

void Path_init(Path* self) {
    self->__rc = 1;
}

Path* Path_new(void) {
    Path* self = ((Path*)malloc(sizeof(Path)));
    memset(self, 0, sizeof(Path));
    Path_init(self);
    return self;
}

void Path_destroy(Path* self) {
    free(self);
}

bool Path_exists(char* path) {
    FILE* f = fopen(path, "r");
    if ((f != NULL)) {
        fclose(f);
        return true;
    }
    return false;
}

char* Path_readAll(char* path) {
    File* f = File_new(path, "r");
    if ((!File_ok(f))) {
        return "";
    }
    char* content = File_read(f);
    File_close(f);
    return content;
}

void Path_writeAll(char* path, char* content) {
    File* f = File_new(path, "w");
    if ((!File_ok(f))) {
        return;
    }
    File_write(f, content);
    File_close(f);
}

void Math_init(Math* self) {
    self->__rc = 1;
}

Math* Math_new(void) {
    Math* self = ((Math*)malloc(sizeof(Math)));
    memset(self, 0, sizeof(Math));
    Math_init(self);
    return self;
}

void Math_destroy(Math* self) {
    free(self);
}

float Math_PI(void) {
    return 3.14159265358979323846f;
}

float Math_E(void) {
    return 2.71828182845904523536f;
}

float Math_TAU(void) {
    return 6.28318530717958647692f;
}

float Math_INF(void) {
    float zero = 0.0f;
    return __btrc_div_double(1.0f, zero);
}

int Math_abs(int x) {
    if ((x < 0)) {
        return (-x);
    }
    return x;
}

float Math_fabs(float x) {
    if ((x < 0.0f)) {
        return (-x);
    }
    return x;
}

int Math_max(int a, int b) {
    if ((a > b)) {
        return a;
    }
    return b;
}

int Math_min(int a, int b) {
    if ((a < b)) {
        return a;
    }
    return b;
}

float Math_fmax(float a, float b) {
    if ((a > b)) {
        return a;
    }
    return b;
}

float Math_fmin(float a, float b) {
    if ((a < b)) {
        return a;
    }
    return b;
}

int Math_clamp(int x, int lo, int hi) {
    if ((x < lo)) {
        return lo;
    }
    if ((x > hi)) {
        return hi;
    }
    return x;
}

float Math_power(float base, int exp) {
    float result = 1.0f;
    bool negative = false;
    if ((exp < 0)) {
        (negative = true);
        (exp = (-exp));
    }
    for (int i = 0; i < exp; i++) {
        (result = (result * base));
    }
    if (negative) {
        return __btrc_div_double(1.0f, result);
    }
    return result;
}

float Math_sqrt(float x) {
    return sqrt(x);
}

int Math_factorial(int n) {
    if ((n <= 1)) {
        return 1;
    }
    return (n * Math_factorial((n - 1)));
}

int Math_gcd(int a, int b) {
    while ((b != 0)) {
        int temp = b;
        (b = __btrc_mod_int(a, b));
        (a = temp);
    }
    return a;
}

int Math_lcm(int a, int b) {
    return __btrc_div_int(Math_abs((a * b)), Math_gcd(a, b));
}

int Math_fibonacci(int n) {
    if ((n <= 0)) {
        return 0;
    }
    if ((n == 1)) {
        return 1;
    }
    int a = 0;
    int b = 1;
    for (int i = 2; i < (n + 1); i++) {
        int temp = (a + b);
        (a = b);
        (b = temp);
    }
    return b;
}

bool Math_isPrime(int n) {
    if ((n < 2)) {
        return false;
    }
    if ((n < 4)) {
        return true;
    }
    if ((__btrc_mod_int(n, 2) == 0)) {
        return false;
    }
    int i = 3;
    while (((i * i) <= n)) {
        if ((__btrc_mod_int(n, i) == 0)) {
            return false;
        }
        (i = (i + 2));
    }
    return true;
}

bool Math_isEven(int n) {
    return (__btrc_mod_int(n, 2) == 0);
}

bool Math_isOdd(int n) {
    return (__btrc_mod_int(n, 2) != 0);
}

int Math_sum(btrc_Vector_int* items) {
    int total = 0;
    for (int i = 0; i < items->len; i++) {
        (total = (total + btrc_Vector_int_get(items, i)));
    }
    return total;
}

float Math_fsum(btrc_Vector_float* items) {
    float total = 0.0f;
    for (int i = 0; i < items->len; i++) {
        (total = (total + btrc_Vector_float_get(items, i)));
    }
    return total;
}

float Math_sin(float x) {
    return sin(x);
}

float Math_cos(float x) {
    return cos(x);
}

float Math_tan(float x) {
    return tan(x);
}

float Math_asin(float x) {
    return asin(x);
}

float Math_acos(float x) {
    return acos(x);
}

float Math_atan(float x) {
    return atan(x);
}

float Math_atan2(float y, float x) {
    return atan2(y, x);
}

float Math_ceil(float x) {
    return ceil(x);
}

float Math_floor(float x) {
    return floor(x);
}

int Math_round(float x) {
    return ((int)round(x));
}

int Math_truncate(float x) {
    return ((int)trunc(x));
}

float Math_log(float x) {
    return log(x);
}

float Math_log10(float x) {
    return log10(x);
}

float Math_log2(float x) {
    return log2(x);
}

float Math_exp(float x) {
    return exp(x);
}

float Math_toRadians(float degrees) {
    return __btrc_div_double((degrees * 3.14159265358979323846f), 180.0f);
}

float Math_toDegrees(float radians) {
    return __btrc_div_double((radians * 180.0f), 3.14159265358979323846f);
}

float Math_fclamp(float val, float lo, float hi) {
    if ((val < lo)) {
        return lo;
    }
    if ((val > hi)) {
        return hi;
    }
    return val;
}

int Math_sign(int x) {
    if ((x > 0)) {
        return 1;
    }
    if ((x < 0)) {
        return (-1);
    }
    return 0;
}

float Math_fsign(float x) {
    if ((x > 0.0f)) {
        return 1.0f;
    }
    if ((x < 0.0f)) {
        return (-1.0f);
    }
    return 0.0f;
}

void Random_init(Random* self) {
    self->__rc = 1;
    (self->seeded = false);
}

Random* Random_new(void) {
    Random* self = ((Random*)malloc(sizeof(Random)));
    memset(self, 0, sizeof(Random));
    Random_init(self);
    return self;
}

void Random_destroy(Random* self) {
    free(self);
}

void Random_seed(Random* self, int s) {
    srand(s);
    (self->seeded = true);
}

void Random_seedTime(Random* self) {
    srand(((unsigned int)time(NULL)));
    (self->seeded = true);
}

int Random_randint(Random* self, int lo, int hi) {
    if ((!self->seeded)) {
        Random_seedTime(self);
    }
    return (lo + (rand() % ((hi - lo) + 1)));
}

float Random_random(Random* self) {
    if ((!self->seeded)) {
        Random_seedTime(self);
    }
    return __btrc_div_double(((float)rand()), ((float)RAND_MAX));
}

float Random_uniform(Random* self, float lo, float hi) {
    return (lo + (Random_random(self) * (hi - lo)));
}

int Random_choice(Random* self, btrc_Vector_int* items) {
    int idx = Random_randint(self, 0, (items->len - 1));
    return btrc_Vector_int_get(items, idx);
}

void Random_shuffle(Random* self, btrc_Vector_int* items) {
    for (int i = (items->len - 1); i < 0; i++) {
        int j = Random_randint(self, 0, i);
        int tmp = btrc_Vector_int_get(items, i);
        btrc_Vector_int_set(items, i, btrc_Vector_int_get(items, j));
        btrc_Vector_int_set(items, j, tmp);
    }
}

void Strings_init(Strings* self) {
    self->__rc = 1;
}

Strings* Strings_new(void) {
    Strings* self = ((Strings*)malloc(sizeof(Strings)));
    memset(self, 0, sizeof(Strings));
    Strings_init(self);
    return self;
}

void Strings_destroy(Strings* self) {
    free(self);
}

char* Strings_repeat(char* s, int count) {
    int slen = ((int)strlen(s));
    int total = (slen * count);
    char* result = ((char*)malloc((total + 1)));
    for (int i = 0; i < count; i++) {
        memcpy((result + (i * slen)), s, slen);
    }
    (result[total] = '\0');
    return result;
}

char* Strings_join(btrc_Vector_string* items, char* sep) {
    if ((items->len == 0)) {
        return strdup("");
    }
    int seplen = ((int)strlen(sep));
    int total = 0;
    for (int i = 0; i < items->len; i++) {
        (total = (total + ((int)strlen(btrc_Vector_string_get(items, i)))));
    }
    (total = (total + (seplen * (items->len - 1))));
    char* result = ((char*)malloc((total + 1)));
    int pos = 0;
    int first_len = ((int)strlen(btrc_Vector_string_get(items, 0)));
    memcpy(result, btrc_Vector_string_get(items, 0), first_len);
    (pos = first_len);
    for (int i = 1; i < items->len; i++) {
        memcpy((result + pos), sep, seplen);
        (pos = (pos + seplen));
        int item_len = ((int)strlen(btrc_Vector_string_get(items, i)));
        memcpy((result + pos), btrc_Vector_string_get(items, i), item_len);
        (pos = (pos + item_len));
    }
    (result[pos] = '\0');
    return result;
}

char* Strings_replace(char* s, char* old, char* replacement) {
    int slen = ((int)strlen(s));
    int oldlen = ((int)strlen(old));
    int replen = ((int)strlen(replacement));
    int cap = ((slen * 2) + 1);
    char* result = ((char*)malloc(cap));
    int rlen = 0;
    int i = 0;
    while ((i < slen)) {
        if ((((i + oldlen) <= slen) && (strncmp((s + i), old, oldlen) == 0))) {
            while (((rlen + replen) >= cap)) {
                (cap = (cap * 2));
                (result = ((char*)realloc(result, cap)));
            }
            memcpy((result + rlen), replacement, replen);
            (rlen = (rlen + replen));
            (i = (i + oldlen));
        } else {
            if (((rlen + 1) >= cap)) {
                (cap = (cap * 2));
                (result = ((char*)realloc(result, cap)));
            }
            (result[rlen] = s[i]);
            (rlen++);
            (i++);
        }
    }
    (result[rlen] = '\0');
    return result;
}

bool Strings_isDigit(char c) {
    return ((c >= '0') && (c <= '9'));
}

bool Strings_isAlpha(char c) {
    return (((c >= 'a') && (c <= 'z')) || ((c >= 'A') && (c <= 'Z')));
}

bool Strings_isAlnum(char c) {
    return (Strings_isAlpha(c) || Strings_isDigit(c));
}

bool Strings_isSpace(char c) {
    return ((((c == ' ') || (c == '\t')) || (c == '\n')) || (c == '\r'));
}

int Strings_toInt(char* s) {
    return atoi(s);
}

float Strings_toFloat(char* s) {
    return ((float)atof(s));
}

int Strings_count(char* s, char* sub) {
    int slen = ((int)strlen(s));
    int sublen = ((int)strlen(sub));
    if ((sublen == 0)) {
        return 0;
    }
    int n = 0;
    int i = 0;
    while (((i + sublen) <= slen)) {
        if ((strncmp((s + i), sub, sublen) == 0)) {
            (n++);
            (i = (i + sublen));
        } else {
            (i++);
        }
    }
    return n;
}

int Strings_find(char* s, char* sub, int start) {
    int slen = ((int)strlen(s));
    int sublen = ((int)strlen(sub));
    if ((start < 0)) {
        (start = 0);
    }
    if ((sublen == 0)) {
        return start;
    }
    int i = start;
    while (((i + sublen) <= slen)) {
        if ((strncmp((s + i), sub, sublen) == 0)) {
            return i;
        }
        (i++);
    }
    return (-1);
}

int Strings_rfind(char* s, char* sub) {
    int slen = ((int)strlen(s));
    int sublen = ((int)strlen(sub));
    if ((sublen == 0)) {
        return slen;
    }
    int i = (slen - sublen);
    while ((i >= 0)) {
        if ((strncmp((s + i), sub, sublen) == 0)) {
            return i;
        }
        (i--);
    }
    return (-1);
}

char* Strings_capitalize(char* s) {
    int slen = ((int)strlen(s));
    char* result = ((char*)malloc((slen + 1)));
    for (int i = 0; i < slen; i++) {
        (result[i] = ((char)tolower(((unsigned char)s[i]))));
    }
    if ((slen > 0)) {
        (result[0] = ((char)toupper(((unsigned char)s[0]))));
    }
    (result[slen] = '\0');
    return result;
}

char* Strings_title(char* s) {
    int slen = ((int)strlen(s));
    char* result = ((char*)malloc((slen + 1)));
    bool newWord = true;
    for (int i = 0; i < slen; i++) {
        char c = s[i];
        if (((((c == ' ') || (c == '\t')) || (c == '\n')) || (c == '\r'))) {
            (result[i] = c);
            (newWord = true);
        } else {
            if (newWord) {
                (result[i] = ((char)toupper(((unsigned char)c))));
            } else {
                (result[i] = ((char)tolower(((unsigned char)c))));
            }
            (newWord = false);
        }
    }
    (result[slen] = '\0');
    return result;
}

char* Strings_swapCase(char* s) {
    int slen = ((int)strlen(s));
    char* result = ((char*)malloc((slen + 1)));
    for (int i = 0; i < slen; i++) {
        char c = s[i];
        if (((c >= 'A') && (c <= 'Z'))) {
            (result[i] = ((char)tolower(((unsigned char)c))));
        } else if (((c >= 'a') && (c <= 'z'))) {
            (result[i] = ((char)toupper(((unsigned char)c))));
        } else {
            (result[i] = c);
        }
    }
    (result[slen] = '\0');
    return result;
}

char* Strings_padLeft(char* s, int width, char fill) {
    int slen = ((int)strlen(s));
    if ((slen >= width)) {
        return strdup(s);
    }
    int pad = (width - slen);
    char* result = ((char*)malloc((width + 1)));
    for (int i = 0; i < pad; i++) {
        (result[i] = fill);
    }
    memcpy((result + pad), s, slen);
    (result[width] = '\0');
    return result;
}

char* Strings_padRight(char* s, int width, char fill) {
    int slen = ((int)strlen(s));
    if ((slen >= width)) {
        return strdup(s);
    }
    int pad = (width - slen);
    char* result = ((char*)malloc((width + 1)));
    memcpy(result, s, slen);
    for (int i = 0; i < pad; i++) {
        (result[(slen + i)] = fill);
    }
    (result[width] = '\0');
    return result;
}

char* Strings_center(char* s, int width, char fill) {
    int slen = ((int)strlen(s));
    if ((slen >= width)) {
        return strdup(s);
    }
    int total_pad = (width - slen);
    int left_pad = __btrc_div_int(total_pad, 2);
    int right_pad = (total_pad - left_pad);
    char* result = ((char*)malloc((width + 1)));
    for (int i = 0; i < left_pad; i++) {
        (result[i] = fill);
    }
    memcpy((result + left_pad), s, slen);
    for (int i = 0; i < right_pad; i++) {
        (result[((left_pad + slen) + i)] = fill);
    }
    (result[width] = '\0');
    return result;
}

char* Strings_lstrip(char* s) {
    int slen = ((int)strlen(s));
    int start = 0;
    while (((start < slen) && ((((s[start] == ' ') || (s[start] == '\t')) || (s[start] == '\n')) || (s[start] == '\r')))) {
        (start++);
    }
    int newlen = (slen - start);
    char* result = ((char*)malloc((newlen + 1)));
    memcpy(result, (s + start), newlen);
    (result[newlen] = '\0');
    return result;
}

char* Strings_rstrip(char* s) {
    int slen = ((int)strlen(s));
    int end = slen;
    while (((end > 0) && ((((s[(end - 1)] == ' ') || (s[(end - 1)] == '\t')) || (s[(end - 1)] == '\n')) || (s[(end - 1)] == '\r')))) {
        (end--);
    }
    char* result = ((char*)malloc((end + 1)));
    memcpy(result, s, end);
    (result[end] = '\0');
    return result;
}

char* Strings_fromInt(int n) {
    char* buf = ((char*)malloc(32));
    snprintf(buf, 32, "%d", n);
    return buf;
}

char* Strings_fromFloat(float f) {
    char* buf = ((char*)malloc(64));
    snprintf(buf, 64, "%g", f);
    return buf;
}

bool Strings_isDigitStr(char* s) {
    int slen = ((int)strlen(s));
    if ((slen == 0)) {
        return false;
    }
    for (int i = 0; i < slen; i++) {
        if (((s[i] < '0') || (s[i] > '9'))) {
            return false;
        }
    }
    return true;
}

bool Strings_isAlphaStr(char* s) {
    int slen = ((int)strlen(s));
    if ((slen == 0)) {
        return false;
    }
    for (int i = 0; i < slen; i++) {
        char c = s[i];
        if ((!(((c >= 'a') && (c <= 'z')) || ((c >= 'A') && (c <= 'Z'))))) {
            return false;
        }
    }
    return true;
}

bool Strings_isBlank(char* s) {
    int slen = ((int)strlen(s));
    for (int i = 0; i < slen; i++) {
        char c = s[i];
        if (((((c != ' ') && (c != '\t')) && (c != '\n')) && (c != '\r'))) {
            return false;
        }
    }
    return true;
}

void Obj_init(Obj* self, int id) {
    self->__rc = 1;
    (self->id = id);
    (alive++);
}

Obj* Obj_new(int id) {
    Obj* self = ((Obj*)malloc(sizeof(Obj)));
    memset(self, 0, sizeof(Obj));
    Obj_init(self, id);
    return self;
}

void Obj_destroy(Obj* self) {
    (alive--);
    free(self);
}

void Holder_init(Holder* self) {
    self->__rc = 1;
    (self->stored = NULL);
}

Holder* Holder_new(void) {
    Holder* self = ((Holder*)malloc(sizeof(Holder)));
    memset(self, 0, sizeof(Holder));
    Holder_init(self);
    return self;
}

void Holder_destroy(Holder* self) {
    if ((self->stored != NULL)) {
        if (((--self->stored->__rc) <= 0)) {
            Obj_destroy(self->stored);
        }
    }
    free(self);
}

void Holder_store(Holder* self, Obj* o) {
    if ((self->stored != NULL)) {
        if (((--self->stored->__rc) <= 0)) {
            Obj_destroy(self->stored);
        }
    }
    (self->stored = o);
    (o->__rc++);
    if ((o != NULL)) {
        if (((--o->__rc) <= 0)) {
            Obj_destroy(o);
        }
    }
}

int main(void) {
    Holder* h = Holder_new();
    Obj* o = Obj_new(1);
    assert((alive == 1));
    (o->__rc++);
    Holder_store(h, o);
    assert((h->stored->id == 1));
    Holder_destroy(h);
    h = NULL;
    assert((alive == 1));
    Obj_destroy(o);
    o = NULL;
    assert((alive == 0));
    printf("%s\n", "PASS: test_keep_params");
    if ((o != NULL)) {
        if (((--o->__rc) <= 0)) {
            Obj_destroy(o);
        }
    }
    return 0;
    if ((o != NULL)) {
        if (((--o->__rc) <= 0)) {
            Obj_destroy(o);
        }
    }
}

