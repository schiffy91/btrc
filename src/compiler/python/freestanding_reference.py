"""Allocator, libc primitives, and numeric parser for the reference runtime."""

from __future__ import annotations

from .freestanding_formatter import REFERENCE_FORMATTER

REFERENCE_RUNTIME = (
    r"""/* ======================================================== *
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
void __btrc_rt_trap(void) { for (;;) {} }
#define BTRC_RT_TRAP __btrc_rt_trap
#endif
void abort(void) { BTRC_RT_TRAP(); }
void exit(int code) { (void)code; BTRC_RT_TRAP(); }
void *stderr = (void *)0;
"""
    + REFERENCE_FORMATTER
    + r"""
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
"""
)

__all__ = ["REFERENCE_RUNTIME"]
