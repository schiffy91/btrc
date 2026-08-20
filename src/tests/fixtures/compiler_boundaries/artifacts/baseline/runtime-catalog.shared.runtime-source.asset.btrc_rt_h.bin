/* btrc_rt.h — the single retargeting seam for --freestanding btrc output.
 *
 * Generated btrc code in --freestanding mode includes ONLY this header. It is
 * the one place an embedder maps the btrc runtime onto the target environment.
 *
 *   Hosted (default):      builds against the C standard library, unchanged.
 *   Freestanding target:   compile with -ffreestanding -fno-builtin and
 *                          -DBTRC_FREESTANDING, optionally name
 *                          BTRC_RT_PLATFORM_HEADER, and provide reached APIs.
 *
 * The pure btrc subset (integer/float/struct code, no strings/collections/
 * try-catch) references NONE of these symbols, so its translation unit is fully
 * self-contained and needs nothing from this header beyond the base types.
 */
#ifndef BTRC_RT_H
#define BTRC_RT_H

/* Feature-test macros must precede every hosted system header: even stdint.h
 * may include the platform feature dispatcher. */
#ifndef BTRC_FREESTANDING
#ifndef _DEFAULT_SOURCE
#define _DEFAULT_SOURCE
#endif
#ifndef _DARWIN_C_SOURCE
#define _DARWIN_C_SOURCE
#endif
#endif

/* --- Foundational types (needed by even the pure subset) ------------------ */
#include <stddef.h>   /* size_t, NULL — freestanding-conforming per C11 7.19 */
#include <stdint.h>   /* intN_t        — freestanding-conforming per C11 7.20 */
#include <stdbool.h>  /* bool/true/false — a macro header, no libc symbols    */
#include <stdatomic.h> /* process-wide managed-value registries                */
#include <limits.h>   /* implementation-width integer bounds used by helpers   */
#include <float.h>    /* floating-point bounds; also freestanding-conforming    */

#ifndef BTRC_FREESTANDING
/* ========================================================================= *
 *  HOSTED DEFAULT — map the runtime onto the C standard library.            *
 * ========================================================================= */
#include <stdio.h>    /* printf, fprintf, snprintf, stderr            */
#include <stdlib.h>   /* malloc, calloc, realloc, free, abort, exit   */
#include <string.h>   /* mem*, str*                                   */
#include <ctype.h>    /* isspace, isdigit, isalpha, tolower, toupper  */
#include <math.h>     /* sqrt, sin, cos, pow, floor, ceil, round, ... */
#include <setjmp.h>   /* setjmp, longjmp  (btrc try/catch)            */
#ifdef BTRC_RT_NEEDS_PTHREAD
#include <pthread.h>  /* Thread<T>, Mutex<T>, spawn                    */
#endif
#ifdef BTRC_RT_NEEDS_GPU
#ifndef BTRC_RT_GPU_HEADER
#define BTRC_RT_GPU_HEADER <btrc_gpu.h>
#endif
#include BTRC_RT_GPU_HEADER
#endif
#ifdef BTRC_RT_NEEDS_GUI
#ifndef BTRC_RT_GUI_HEADER
#define BTRC_RT_GUI_HEADER <btrc_gui.h>
#endif
#ifndef BTRC_RT_GUI_FONT_HEADER
#define BTRC_RT_GUI_FONT_HEADER <btrc_gui_font.h>
#endif
#ifndef BTRC_RT_GUI_WINDOW_HEADER
#define BTRC_RT_GUI_WINDOW_HEADER <btrc_gui_window.h>
#endif
#include BTRC_RT_GUI_HEADER
#include BTRC_RT_GUI_FONT_HEADER
#include BTRC_RT_GUI_WINDOW_HEADER
#endif
#ifdef BTRC_RT_NEEDS_TRAY
#ifndef BTRC_RT_TRAY_HEADER
#define BTRC_RT_TRAY_HEADER <btrc_tray.h>
#endif
#include BTRC_RT_TRAY_HEADER
#endif

#else
/* ========================================================================= *
 *  FREESTANDING TARGET — you provide every symbol below.                    *
 *                                                                           *
 *  This is the core external surface of the btrc runtime. Optional stdlib    *
 *  modules (filesystem, sockets, native UI, etc.) come through the platform *
 *  header hook below. Anything unreachable can remain unimplemented.        *
 * ========================================================================= */

/* One target-owned umbrella header may provide POSIX/native types, constants,
 * macros, and declarations used by the selected stdlib modules. */
#ifdef BTRC_RT_PLATFORM_HEADER
#include BTRC_RT_PLATFORM_HEADER
#endif

/* -- Memory -------------------------------------------------------------- *
 *  malloc / calloc / realloc / free
 *  kernel:  kmalloc(n, GFP_KERNEL) / kcalloc / krealloc / kfree
 *  Note: malloc must provide max-align storage; calloc must zero it.         */
void *malloc(size_t);
void *calloc(size_t, size_t);
void *realloc(void *, size_t);
void  free(void *);

/* -- Formatted output ---------------------------------------------------- *
 *  print/println -> printf; f-strings & number->string -> snprintf;
 *  uncaught-error & assert messages -> fprintf(stderr, ...).
 *  kernel:  printf->printk; fprintf(stderr,...)->pr_err(...);
 *           snprintf is provided by the kernel as-is.                       */
int printf(const char *, ...);
int snprintf(char *, size_t, const char *, ...);
int fprintf(void *, const char *, ...);   /* stream arg is opaque here */
extern void *stderr;                       /* unused if you remap fprintf */

/* -- Memory & string ops (kernel provides all of these by the same name) - */
void  *memcpy(void *, const void *, size_t);
void  *memmove(void *, const void *, size_t);
void  *memset(void *, int, size_t);
int    memcmp(const void *, const void *, size_t);
size_t strlen(const char *);
int    strcmp(const char *, const char *);
int    strncmp(const char *, const char *, size_t);
char  *strcpy(char *, const char *);
char  *strncpy(char *, const char *, size_t);
char  *strstr(const char *, const char *);
char  *strchr(const char *, int);
float  strtof(const char *, char **);
double strtod(const char *, char **);

/* -- Character classification (kernel: linux/ctype.h) -------------------- */
int isspace(int);
int isdigit(int);
int isalpha(int);
int tolower(int);
int toupper(int);

/* -- Abnormal termination ------------------------------------------------ *
 *  Uncaught btrc errors call exit()/abort().
 *  kernel:  route to BUG()/panic() or a controlled module-unload path.      */
_Noreturn void abort(void);
_Noreturn void exit(int);

/* -- Floating-point math (only if the program uses the Math module) ------ *
 *  kernel: no libm — supply your own or avoid floating point in-kernel.     */
double sqrt(double);
double pow(double, double);
double sin(double);
double cos(double);
double floor(double);
double ceil(double);
double round(double);
double fmod(double, double);
double fabs(double);

/* -- Non-local control flow (only if the program uses try/catch) --------- *
 *  jmp_buf is target-specific and cannot be guessed portably. Name a shim
 *  that owns its type plus setjmp/longjmp declarations and implementation.  */
#ifdef BTRC_RT_NEEDS_SETJMP
#ifndef BTRC_RT_SETJMP_HEADER
#error "try/catch freestanding builds require BTRC_RT_SETJMP_HEADER"
#endif
#include BTRC_RT_SETJMP_HEADER
#endif

/* -- Threads (Thread<T>/Mutex<T>) ---------------------------------------- *
 *  Backed by pthreads. A freestanding program using threads must name a
 *  compatible shim header, for example:
 *    -DBTRC_RT_PTHREAD_HEADER='"my_pthread_shim.h"'
 *  The shim owns pthread_t/pthread_mutex_t and every pthread_* declaration.  */
#ifdef BTRC_RT_NEEDS_PTHREAD
#ifndef BTRC_RT_PTHREAD_HEADER
#error "threaded freestanding builds require BTRC_RT_PTHREAD_HEADER"
#endif
#include BTRC_RT_PTHREAD_HEADER
#endif

/* -- Optional native runtimes -------------------------------------------- *
 *  Native GPU/GUI/tray APIs are target-owned. Name one shim header for each
 *  feature reached by the program; the shim declares the complete C ABI.    */
#ifdef BTRC_RT_NEEDS_GPU
#ifndef BTRC_RT_GPU_HEADER
#error "GPU freestanding builds require BTRC_RT_GPU_HEADER"
#endif
#include BTRC_RT_GPU_HEADER
#endif
#ifdef BTRC_RT_NEEDS_GUI
#ifndef BTRC_RT_GUI_HEADER
#error "GUI freestanding builds require BTRC_RT_GUI_HEADER"
#endif
#include BTRC_RT_GUI_HEADER
#endif
#ifdef BTRC_RT_NEEDS_TRAY
#ifndef BTRC_RT_TRAY_HEADER
#error "tray freestanding builds require BTRC_RT_TRAY_HEADER"
#endif
#include BTRC_RT_TRAY_HEADER
#endif

#ifdef BTRC_FREESTANDING_IMPL
/* ======================================================== *
 * REFERENCE RUNTIME — a self-contained core implementation with no libc.   *
 * Define BTRC_FREESTANDING_IMPL in exactly one translation unit.            *
 * Replace BTRC_RT_PUTS/BTRC_RT_TRAP and the bump allocator for real targets. *
 * Floating formatted-output precision is intentionally bounded to 18 digits. *
 * Try/catch and threads intentionally require target-provided shims.         *
 * ========================================================================= */
#include <stdarg.h>   /* freestanding-conforming per C11 7.16 */

void *memset(void *dest, int value, size_t count) {
    unsigned char *out = dest;
    while (count-- > 0U) *out++ = (unsigned char)value;
    return dest;
}

void *memcpy(void *dest, const void *source, size_t count) {
    unsigned char *out = dest;
    const unsigned char *in = source;
    while (count-- > 0U) *out++ = *in++;
    return dest;
}

void *memmove(void *dest, const void *source, size_t count) {
    unsigned char *out = dest;
    const unsigned char *in = source;
    uintptr_t out_address = (uintptr_t)dest;
    uintptr_t in_address = (uintptr_t)source;
    if (out_address <= in_address || out_address - in_address >= count) {
        while (count-- > 0U) *out++ = *in++;
    } else {
        out += count;
        in += count;
        while (count-- > 0U) *--out = *--in;
    }
    return dest;
}

int memcmp(const void *left, const void *right, size_t count) {
    const unsigned char *a = left;
    const unsigned char *b = right;
    while (count-- > 0U) {
        if (*a != *b) return (int)*a - (int)*b;
        a++;
        b++;
    }
    return 0;
}

#ifndef BTRC_RT_ARENA_BYTES
#define BTRC_RT_ARENA_BYTES (1u << 22)
#endif
#define BTRC_RT_ALIGNMENT ((size_t)_Alignof(max_align_t))
#define BTRC_RT_HEADER_BYTES \
    ((sizeof(size_t) + BTRC_RT_ALIGNMENT - 1U) / BTRC_RT_ALIGNMENT * BTRC_RT_ALIGNMENT)
static union {
    max_align_t alignment;
    unsigned char bytes[BTRC_RT_ARENA_BYTES];
} __btrc_arena;
static size_t __btrc_arena_offset = 0U;

void *malloc(size_t size) {
    if (size > SIZE_MAX - (BTRC_RT_ALIGNMENT - 1U)) return (void *)0;
    size_t aligned = (size + BTRC_RT_ALIGNMENT - 1U)
        / BTRC_RT_ALIGNMENT * BTRC_RT_ALIGNMENT;
    if (aligned > SIZE_MAX - BTRC_RT_HEADER_BYTES) return (void *)0;
    size_t total = BTRC_RT_HEADER_BYTES + aligned;
    if (total > sizeof __btrc_arena.bytes - __btrc_arena_offset) return (void *)0;
    unsigned char *block = __btrc_arena.bytes + __btrc_arena_offset;
    __btrc_arena_offset += total;
    memcpy(block, &size, sizeof size);
    return block + BTRC_RT_HEADER_BYTES;
}

void free(void *pointer) { (void)pointer; }

void *calloc(size_t count, size_t size) {
    if (size != 0U && count > SIZE_MAX / size) return (void *)0;
    size_t total = count * size;
    void *result = malloc(total);
    if (result) memset(result, 0, total);
    return result;
}

void *realloc(void *pointer, size_t size) {
    if (!pointer) return malloc(size);
    size_t old_size = 0U;
    memcpy(&old_size, (unsigned char *)pointer - BTRC_RT_HEADER_BYTES, sizeof old_size);
    void *result = malloc(size);
    if (result) memcpy(result, pointer, old_size < size ? old_size : size);
    return result;
}

size_t strlen(const char *value) {
    const char *end = value;
    while (*end) end++;
    return (size_t)(end - value);
}

int strcmp(const char *left, const char *right) {
    while (*left && *left == *right) { left++; right++; }
    return (int)(unsigned char)*left - (int)(unsigned char)*right;
}

int strncmp(const char *left, const char *right, size_t count) {
    while (count > 0U && *left && *left == *right) { left++; right++; count--; }
    return count ? (int)(unsigned char)*left - (int)(unsigned char)*right : 0;
}

char *strcpy(char *dest, const char *source) {
    char *result = dest;
    while ((*dest++ = *source++) != '\0') {}
    return result;
}

char *strncpy(char *dest, const char *source, size_t count) {
    size_t index = 0U;
    while (index < count && source[index] != '\0') {
        dest[index] = source[index];
        index++;
    }
    while (index < count) dest[index++] = '\0';
    return dest;
}

char *strchr(const char *value, int needle) {
    do {
        if (*value == (char)needle) return (char *)value;
    } while (*value++ != '\0');
    return (char *)0;
}

char *strstr(const char *haystack, const char *needle) {
    if (!*needle) return (char *)haystack;
    for (; *haystack; haystack++) {
        const char *left = haystack;
        const char *right = needle;
        while (*left && *right && *left == *right) { left++; right++; }
        if (!*right) return (char *)haystack;
    }
    return (char *)0;
}

int isspace(int value) {
    return value == ' ' || value == '\t' || value == '\n'
        || value == '\r' || value == '\v' || value == '\f';
}
int isdigit(int value) { return value >= '0' && value <= '9'; }
int isalpha(int value) {
    return (value >= 'a' && value <= 'z') || (value >= 'A' && value <= 'Z');
}
int tolower(int value) { return value >= 'A' && value <= 'Z' ? value + 32 : value; }
int toupper(int value) { return value >= 'a' && value <= 'z' ? value - 32 : value; }

static long double __btrc_rt_parse_real(const char *text, char **end_pointer) {
    const char *start = text;
    while (isspace((unsigned char)*text)) text++;
    bool negative = false;
    if (*text == '-' || *text == '+') { negative = *text == '-'; text++; }
    long double value = 0.0L;
    bool any = false;
    while (isdigit((unsigned char)*text)) {
        unsigned int digit = (unsigned int)(*text++ - '0');
        any = true;
        value = value > (LDBL_MAX - (long double)digit) / 10.0L
            ? LDBL_MAX : value * 10.0L + (long double)digit;
    }
    if (*text == '.') {
        const char *fraction_start = text++;
        long double scale = 0.1L;
        while (isdigit((unsigned char)*text)) {
            unsigned int digit = (unsigned int)(*text++ - '0');
            any = true;
            if (value < LDBL_MAX) value += (long double)digit * scale;
            scale /= 10.0L;
        }
        if (!any) text = fraction_start;
    }
    if (any && (*text == 'e' || *text == 'E')) {
        const char *exponent_start = text++;
        bool exponent_negative = false;
        if (*text == '-' || *text == '+') {
            exponent_negative = *text == '-';
            text++;
        }
        int exponent = 0;
        bool exponent_any = false;
        while (isdigit((unsigned char)*text)) {
            exponent_any = true;
            if (exponent <= 999) exponent = exponent * 10 + (*text - '0');
            else exponent = 10000;
            text++;
        }
        if (!exponent_any) text = exponent_start;
        else if (exponent_negative) while (exponent-- > 0 && value != 0.0L) value /= 10.0L;
        else while (exponent-- > 0 && value < LDBL_MAX) {
            value = value > LDBL_MAX / 10.0L ? LDBL_MAX : value * 10.0L;
        }
    }
    if (end_pointer) *end_pointer = (char *)(any ? text : start);
    if (!any) return 0.0L;
    return negative ? -value : value;
}

float strtof(const char *text, char **end_pointer) {
    return (float)__btrc_rt_parse_real(text, end_pointer);
}
double strtod(const char *text, char **end_pointer) {
    return (double)__btrc_rt_parse_real(text, end_pointer);
}

#ifndef BTRC_RT_PUTS
void __btrc_rt_puts(const char *text, size_t length) { (void)text; (void)length; }
#define BTRC_RT_PUTS __btrc_rt_puts
#endif
#ifndef BTRC_RT_TRAP
_Noreturn void __btrc_rt_trap(void) { for (;;) {} }
#define BTRC_RT_TRAP __btrc_rt_trap
#endif
_Noreturn void abort(void) { BTRC_RT_TRAP(); for (;;) {} }
_Noreturn void exit(int code) { (void)code; BTRC_RT_TRAP(); for (;;) {} }
void *stderr = (void *)0;

typedef struct {
    char *out;
    size_t cap;
    size_t pos;
} __btrc_rt_sink;

static void __btrc_rt_put(__btrc_rt_sink *sink, char value) {
    if (sink->out && sink->pos + 1U < sink->cap) sink->out[sink->pos] = value;
    sink->pos++;
}

static void __btrc_rt_pad(__btrc_rt_sink *sink, char value, int count) {
    while (count-- > 0) __btrc_rt_put(sink, value);
}

static int __btrc_rt_digits(
        char *reversed, uintmax_t value, unsigned int base, bool upper) {
    const char *alphabet = upper
        ? "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        : "0123456789abcdefghijklmnopqrstuvwxyz";
    int length = 0;
    do {
        reversed[length++] = alphabet[value % base];
        value /= base;
    } while (value != 0U);
    return length;
}

static void __btrc_rt_emit_integer(
        __btrc_rt_sink *sink, uintmax_t value, bool negative,
        unsigned int base, bool upper, bool alternate, int width,
        int precision, bool zero, bool left, bool plus, bool space) {
    char reversed[sizeof(uintmax_t) * CHAR_BIT + 1U];
    int digits = value == 0U && precision == 0
        ? 0 : __btrc_rt_digits(reversed, value, base, upper);
    char sign = negative ? '-' : plus ? '+' : space ? ' ' : '\0';
    const char *prefix = "";
    int prefix_length = sign ? 1 : 0;
    if (alternate && value != 0U && base == 16U) {
        prefix = upper ? "0X" : "0x";
        prefix_length += 2;
    } else if (alternate && base == 8U && (digits == 0 || reversed[digits - 1] != '0')) {
        prefix = "0";
        prefix_length += 1;
    }
    int leading_zeroes = precision > digits ? precision - digits : 0;
    int padding = width - prefix_length - leading_zeroes - digits;
    if (!left && (!zero || precision >= 0)) __btrc_rt_pad(sink, ' ', padding);
    if (sign) __btrc_rt_put(sink, sign);
    while (*prefix) __btrc_rt_put(sink, *prefix++);
    if (!left && zero && precision < 0) __btrc_rt_pad(sink, '0', padding);
    __btrc_rt_pad(sink, '0', leading_zeroes);
    while (digits-- > 0) __btrc_rt_put(sink, reversed[digits]);
    if (left) __btrc_rt_pad(sink, ' ', padding);
}


static int __btrc_rt_normalize(long double *value) {
    int exponent = 0;
    if (*value == 0.0L) return 0;
    while (*value >= 10.0L) { *value /= 10.0L; exponent++; }
    while (*value < 1.0L) { *value *= 10.0L; exponent--; }
    return exponent;
}

static int __btrc_rt_next_digit(long double *value) {
    int digit = (int)*value;
    if (digit < 0) digit = 0;
    if (digit > 9) digit = 9;
    *value = (*value - (long double)digit) * 10.0L;
    if (*value < 0.0L) *value = 0.0L;
    return digit;
}

static void __btrc_rt_emit_exponent(
        __btrc_rt_sink *sink, int exponent, bool upper) {
    char reversed[16];
    int length;
    __btrc_rt_put(sink, upper ? 'E' : 'e');
    if (exponent < 0) { __btrc_rt_put(sink, '-'); exponent = -exponent; }
    else __btrc_rt_put(sink, '+');
    length = __btrc_rt_digits(reversed, (uintmax_t)exponent, 10U, false);
    if (length < 2) __btrc_rt_put(sink, '0');
    while (length-- > 0) __btrc_rt_put(sink, reversed[length]);
}

static void __btrc_rt_emit_fixed_body(
        __btrc_rt_sink *sink, long double value, int precision) {
    long double rounding = 0.5L;
    for (int i = 0; i < precision; ++i) rounding /= 10.0L;
    long double rounded = value + rounding;
    if (rounded != 0.0L && rounded + rounded == rounded) rounded = value;
    value = rounded;
    int exponent = __btrc_rt_normalize(&value);
    if (rounded == 0.0L || exponent < 0) {
        __btrc_rt_put(sink, '0');
    } else {
        for (int place = exponent; place >= 0; --place)
            __btrc_rt_put(sink, (char)('0' + __btrc_rt_next_digit(&value)));
    }
    if (precision <= 0) return;
    __btrc_rt_put(sink, '.');
    for (int place = -1; place >= -precision; --place) {
        int digit = place > exponent || rounded == 0.0L
            ? 0 : __btrc_rt_next_digit(&value);
        __btrc_rt_put(sink, (char)('0' + digit));
    }
}

static int __btrc_rt_significant_digits(
        long double *value, int count, unsigned char *digits) {
    if (*value == 0.0L) {
        for (int i = 0; i < count; ++i) digits[i] = 0U;
        return 0;
    }
    int exponent = __btrc_rt_normalize(value);
    long double rounding = 0.5L;
    for (int i = 1; i < count; ++i) rounding /= 10.0L;
    *value += rounding;
    if (*value >= 10.0L) { *value /= 10.0L; exponent++; }
    for (int i = 0; i < count; ++i)
        digits[i] = (unsigned char)__btrc_rt_next_digit(value);
    return exponent;
}

static void __btrc_rt_emit_scientific_body(
        __btrc_rt_sink *sink, long double value, int precision, bool upper) {
    unsigned char digits[20];
    int count = precision + 1;
    int exponent = __btrc_rt_significant_digits(&value, count, digits);
    __btrc_rt_put(sink, (char)('0' + digits[0]));
    if (precision > 0) {
        __btrc_rt_put(sink, '.');
        for (int i = 1; i < count; ++i)
            __btrc_rt_put(sink, (char)('0' + digits[i]));
    }
    __btrc_rt_emit_exponent(sink, exponent, upper);
}

static void __btrc_rt_emit_general_body(
        __btrc_rt_sink *sink, long double value, int precision,
        bool upper, bool alternate) {
    unsigned char digits[18];
    int exponent = __btrc_rt_significant_digits(&value, precision, digits);
    int last = precision - 1;
    if (!alternate) while (last >= 0 && digits[last] == 0) last--;
    if (last < 0) { __btrc_rt_put(sink, '0'); return; }
    if (exponent < -4 || exponent >= precision) {
        __btrc_rt_put(sink, (char)('0' + digits[0]));
        if (last > 0 || alternate) {
            __btrc_rt_put(sink, '.');
            for (int i = 1; i <= last; ++i)
                __btrc_rt_put(sink, (char)('0' + digits[i]));
        }
        __btrc_rt_emit_exponent(sink, exponent, upper);
        return;
    }
    if (exponent < 0) {
        __btrc_rt_put(sink, '0');
        __btrc_rt_put(sink, '.');
        for (int place = -1; place > exponent; --place) __btrc_rt_put(sink, '0');
        for (int i = 0; i <= last; ++i)
            __btrc_rt_put(sink, (char)('0' + digits[i]));
        return;
    }
    for (int place = 0; place <= exponent; ++place) {
        int digit = place < precision ? digits[place] : 0;
        __btrc_rt_put(sink, (char)('0' + digit));
    }
    if (last > exponent || alternate) {
        __btrc_rt_put(sink, '.');
        for (int i = exponent + 1; i <= last; ++i)
            __btrc_rt_put(sink, (char)('0' + digits[i]));
    }
}

static void __btrc_rt_emit_real_body(
        __btrc_rt_sink *sink, long double value, char spec,
        int precision, bool alternate) {
    bool upper = spec == 'F' || spec == 'E' || spec == 'G';
    char lower = upper ? (char)(spec + ('a' - 'A')) : spec;
    if (value != value) {
        const char *word = upper ? "NAN" : "nan";
        while (*word) __btrc_rt_put(sink, *word++);
    } else if (value != 0.0L && value + value == value) {
        const char *word = upper ? "INF" : "inf";
        while (*word) __btrc_rt_put(sink, *word++);
    } else if (lower == 'f') {
        __btrc_rt_emit_fixed_body(sink, value, precision);
    } else if (lower == 'e') {
        __btrc_rt_emit_scientific_body(sink, value, precision, upper);
    } else {
        __btrc_rt_emit_general_body(sink, value, precision, upper, alternate);
    }
}

static void __btrc_rt_emit_real(
        __btrc_rt_sink *sink, long double value, char spec, int width,
        int precision, bool zero, bool left, bool plus, bool space,
        bool alternate) {
    bool negative = value < 0.0L;
    if (negative) value = -value;
    char sign = negative ? '-' : plus ? '+' : space ? ' ' : '\0';
    __btrc_rt_sink count = {0};
    __btrc_rt_emit_real_body(&count, value, spec, precision, alternate);
    int padding = width - (int)count.pos - (sign ? 1 : 0);
    if (!left && !zero) __btrc_rt_pad(sink, ' ', padding);
    if (sign) __btrc_rt_put(sink, sign);
    if (!left && zero) __btrc_rt_pad(sink, '0', padding);
    __btrc_rt_emit_real_body(sink, value, spec, precision, alternate);
    if (left) __btrc_rt_pad(sink, ' ', padding);
}

static size_t __btrc_fmt(char *out, size_t cap, const char *fmt, va_list ap) {
    __btrc_rt_sink sink = {out, cap, 0U};
    while (*fmt) {
        if (*fmt != '%') { __btrc_rt_put(&sink, *fmt++); continue; }
        fmt++;
        bool left = false, plus = false, space = false, alternate = false, zero = false;
        bool flags = true;
        while (flags) {
            switch (*fmt) {
            case '-': left = true; fmt++; break;
            case '+': plus = true; fmt++; break;
            case ' ': space = true; fmt++; break;
            case '#': alternate = true; fmt++; break;
            case '0': zero = true; fmt++; break;
            default: flags = false; break;
            }
        }
        int width = 0;
        if (*fmt == '*') {
            width = va_arg(ap, int);
            fmt++;
            if (width < 0) {
                left = true;
                width = width == INT_MIN ? INT_MAX : -width;
            }
        }
        else while (*fmt >= '0' && *fmt <= '9') {
            if (width <= (INT_MAX - 9) / 10) width = width * 10 + (*fmt - '0');
            fmt++;
        }
        int precision = -1;
        if (*fmt == '.') {
            fmt++; precision = 0;
            if (*fmt == '*') { precision = va_arg(ap, int); fmt++; }
            else while (*fmt >= '0' && *fmt <= '9') {
                if (precision <= (INT_MAX - 9) / 10) precision = precision * 10 + (*fmt - '0');
                fmt++;
            }
            if (precision < 0) precision = -1;
        }
        int length = 0;
        if (*fmt == 'h') { fmt++; length = *fmt == 'h' ? (fmt++, -2) : -1; }
        else if (*fmt == 'l') { fmt++; length = *fmt == 'l' ? (fmt++, 2) : 1; }
        else if (*fmt == 'j') { fmt++; length = 3; }
        else if (*fmt == 'z') { fmt++; length = 4; }
        else if (*fmt == 't') { fmt++; length = 5; }
        else if (*fmt == 'L') { fmt++; length = 6; }
        char spec = *fmt;
        if (!spec) break;
        fmt++;
        if (spec == 'd' || spec == 'i') {
            intmax_t signed_value = length == 1 ? (intmax_t)va_arg(ap, long)
                : length == 2 ? (intmax_t)va_arg(ap, long long)
                : length == 3 ? va_arg(ap, intmax_t)
                : length == 4 || length == 5 ? (intmax_t)va_arg(ap, ptrdiff_t)
                : (intmax_t)va_arg(ap, int);
            bool negative = signed_value < 0;
            uintmax_t magnitude = negative
                ? (uintmax_t)(-(signed_value + 1)) + 1U : (uintmax_t)signed_value;
            __btrc_rt_emit_integer(&sink, magnitude, negative, 10U, false,
                false, width, precision, zero, left, plus, space);
        } else if (spec == 'u' || spec == 'o' || spec == 'x' || spec == 'X') {
            uintmax_t value = length == 1 ? (uintmax_t)va_arg(ap, unsigned long)
                : length == 2 ? (uintmax_t)va_arg(ap, unsigned long long)
                : length == 3 ? va_arg(ap, uintmax_t)
                : length == 4 ? (uintmax_t)va_arg(ap, size_t)
                : length == 5 ? (uintmax_t)va_arg(ap, uintptr_t)
                : (uintmax_t)va_arg(ap, unsigned int);
            unsigned int base = spec == 'o' ? 8U : (spec == 'x' || spec == 'X' ? 16U : 10U);
            __btrc_rt_emit_integer(&sink, value, false, base, spec == 'X',
                alternate, width, precision, zero, left, false, false);
        } else if (spec == 'f' || spec == 'F' || spec == 'e' || spec == 'E'
                || spec == 'g' || spec == 'G') {
            long double value = length == 6 ? va_arg(ap, long double)
                                            : (long double)va_arg(ap, double);
            int real_precision = precision < 0 ? 6 : precision;
            if ((spec == 'g' || spec == 'G') && real_precision == 0) real_precision = 1;
            if (real_precision > 18) real_precision = 18;
            __btrc_rt_emit_real(&sink, value, spec, width, real_precision,
                zero, left, plus, space, alternate);
        } else if (spec == 'c') {
            int padding = width - 1;
            if (!left) __btrc_rt_pad(&sink, ' ', padding);
            __btrc_rt_put(&sink, (char)va_arg(ap, int));
            if (left) __btrc_rt_pad(&sink, ' ', padding);
        } else if (spec == 's') {
            const char *value = va_arg(ap, const char *);
            if (!value) value = "(null)";
            size_t length_value = strlen(value);
            if (precision >= 0 && length_value > (size_t)precision) length_value = (size_t)precision;
            int padding = length_value < (size_t)width ? width - (int)length_value : 0;
            if (!left) __btrc_rt_pad(&sink, ' ', padding);
            for (size_t i = 0; i < length_value; ++i) __btrc_rt_put(&sink, value[i]);
            if (left) __btrc_rt_pad(&sink, ' ', padding);
        } else if (spec == 'p') {
            uintptr_t value = (uintptr_t)va_arg(ap, void *);
            __btrc_rt_emit_integer(&sink, (uintmax_t)value, false, 16U, false,
                true, width, precision, zero, left, false, false);
        } else if (spec == '%') {
            __btrc_rt_put(&sink, '%');
        } else {
            __btrc_rt_put(&sink, '%');
            __btrc_rt_put(&sink, spec);
        }
    }
    if (out && cap) out[sink.pos < cap ? sink.pos : cap - 1U] = '\0';
    return sink.pos;
}

int snprintf(char *out, size_t cap, const char *format, ...) {
    va_list args;
    va_start(args, format);
    size_t length = __btrc_fmt(out, cap, format, args);
    va_end(args);
    return length > (size_t)INT_MAX ? -1 : (int)length;
}
static int __btrc_rt_vprint(const char *format, va_list args) {
    va_list count_args;
    va_copy(count_args, args);
    size_t length = __btrc_fmt((char *)0, 0U, format, count_args);
    va_end(count_args);
    if (length > (size_t)INT_MAX || length == SIZE_MAX) return -1;
    char *buffer = malloc(length + 1U);
    if (!buffer) return -1;
    (void)__btrc_fmt(buffer, length + 1U, format, args);
    BTRC_RT_PUTS(buffer, length);
    free(buffer);
    return (int)length;
}
int printf(const char *format, ...) {
    va_list args;
    va_start(args, format);
    int result = __btrc_rt_vprint(format, args);
    va_end(args);
    return result;
}
int fprintf(void *stream, const char *format, ...) {
    (void)stream;
    va_list args;
    va_start(args, format);
    int result = __btrc_rt_vprint(format, args);
    va_end(args);
    return result;
}

#endif /* BTRC_FREESTANDING_IMPL */

#endif /* BTRC_FREESTANDING */

#endif /* BTRC_RT_H */
