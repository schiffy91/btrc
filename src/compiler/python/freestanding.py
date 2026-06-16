"""Reference runtime seam for ``--freestanding`` output.

In freestanding mode the emitter funnels every hosted-libc dependency through a
single ``#include "btrc_rt.h"``. This module holds the reference copy of that
header, which the CLI drops next to the generated ``.c``.

The header serves two audiences from one file:

* **Hosted toolchain (default):** it maps every runtime symbol onto the C
  standard library, so freestanding output compiles and runs unchanged on a
  normal ``gcc``/``clang`` — useful for testing the transpiled code before it
  ever reaches the target.
* **Freestanding target (``-DBTRC_FREESTANDING``):** the ``#else`` branch
  enumerates the COMPLETE set of external symbols the btrc runtime can
  reference and shows where to map each one (the Linux-kernel mappings are
  given as examples). This is the single file an embedder edits.

The symbol list is derived from the libc identifiers actually emitted by the IR
generator and the runtime helpers; keep it in sync if either grows.
"""

from __future__ import annotations

RUNTIME_HEADER = r"""/* btrc_rt.h — the single retargeting seam for --freestanding btrc output.
 *
 * Generated btrc code in --freestanding mode includes ONLY this header. It is
 * the one place an embedder maps the btrc runtime onto the target environment.
 *
 *   Hosted (default):      builds against the C standard library, unchanged.
 *   Freestanding target:   compile with -DBTRC_FREESTANDING and provide the
 *                          symbols listed in the #else branch below.
 *
 * The pure btrc subset (integer/float/struct code, no strings/collections/
 * try-catch) references NONE of these symbols, so its translation unit is fully
 * self-contained and needs nothing from this header beyond the base types.
 */
#ifndef BTRC_RT_H
#define BTRC_RT_H

/* --- Foundational types (needed by even the pure subset) ------------------ */
#include <stddef.h>   /* size_t, NULL — freestanding-conforming per C11 7.19 */
#include <stdint.h>   /* intN_t        — freestanding-conforming per C11 7.20 */
#include <stdbool.h>  /* bool/true/false — a macro header, no libc symbols    */

#ifndef BTRC_FREESTANDING
/* ========================================================================= *
 *  HOSTED DEFAULT — map the runtime onto the C standard library.            *
 * ========================================================================= */
#define _DEFAULT_SOURCE
#define _DARWIN_C_SOURCE
#include <stdio.h>    /* printf, fprintf, snprintf, stderr            */
#include <stdlib.h>   /* malloc, calloc, realloc, free, abort, exit   */
#include <string.h>   /* mem*, str*                                   */
#include <ctype.h>    /* isspace, isdigit, isalpha, tolower, toupper  */
#include <math.h>     /* sqrt, sin, cos, pow, floor, ceil, round, ... */
#include <setjmp.h>   /* setjmp, longjmp  (btrc try/catch)            */

#else
/* ========================================================================= *
 *  FREESTANDING TARGET — you provide every symbol below.                    *
 *                                                                           *
 *  This is the COMPLETE external surface of the btrc runtime. Map each to   *
 *  your environment; the Linux-kernel equivalent is shown for reference.    *
 *  Anything your program never uses can be left unmapped (the linker only   *
 *  pulls what is reached). Map with macros or real definitions — your call. *
 * ========================================================================= */

/* -- Memory -------------------------------------------------------------- *
 *  malloc / calloc / realloc / free
 *  kernel:  kmalloc(n, GFP_KERNEL) / kcalloc / krealloc / kfree
 *  Note: btrc assumes malloc returns zeroable, 8-byte-aligned blocks.       */
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

/* -- Character classification (kernel: linux/ctype.h) -------------------- */
int isspace(int);
int isdigit(int);
int isalpha(int);
int tolower(int);
int toupper(int);

/* -- Abnormal termination ------------------------------------------------ *
 *  Uncaught btrc errors call exit()/abort().
 *  kernel:  route to BUG()/panic() or a controlled module-unload path.      */
void abort(void);
void exit(int);

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
 *  There is no setjmp/longjmp in the Linux kernel. To use btrc try/catch in
 *  a freestanding target, provide an implementation or avoid try/catch.     */
typedef long jmp_buf[16];
int  setjmp(jmp_buf);
void longjmp(jmp_buf, int);

/* -- Threads (Thread<T>/Mutex<T>) ---------------------------------------- *
 *  Backed by pthreads; not available freestanding. Programs using threads
 *  must include a pthread-compatible shim (e.g. kthread wrappers).          */

#ifdef BTRC_FREESTANDING_IMPL
/* ========================================================================= *
 *  REFERENCE RUNTIME — a self-contained implementation of the symbols above *
 *  so a single-TU btrc program (integer/string/collection subset) links     *
 *  with NO libc. Define BTRC_FREESTANDING_IMPL in exactly one TU.           *
 *                                                                           *
 *  All output goes through one hook, __btrc_rt_puts; replace it for your     *
 *  target (kernel: printk). Memory comes from a fixed bump arena (free is a  *
 *  no-op) — swap in kmalloc/kfree for real use. printf/snprintf cover        *
 *  integers, strings, and %f floats. NOT provided: setjmp/longjmp            *
 *  (try/catch) and threads.                                                  *
 * ========================================================================= */
#include <stdarg.h>   /* freestanding-conforming per C11 7.16 */

#ifndef BTRC_RT_ARENA_BYTES
#define BTRC_RT_ARENA_BYTES (1u << 22)   /* 4 MiB */
#endif
static unsigned char __btrc_arena[BTRC_RT_ARENA_BYTES];
static size_t __btrc_arena_off = 0;

void *memset(void *d, int c, size_t n) { unsigned char *D = d; while (n--) *D++ = (unsigned char)c; return d; }
void *memcpy(void *d, const void *s, size_t n) { unsigned char *D = d; const unsigned char *S = s; while (n--) *D++ = *S++; return d; }
void *memmove(void *d, const void *s, size_t n) { unsigned char *D = d; const unsigned char *S = s; if (D < S) while (n--) *D++ = *S++; else { D += n; S += n; while (n--) *--D = *--S; } return d; }
int memcmp(const void *a, const void *b, size_t n) { const unsigned char *A = a, *B = b; while (n--) { if (*A != *B) return *A - *B; A++; B++; } return 0; }

void *malloc(size_t n) { n = (n + 15u) & ~(size_t)15u; if (__btrc_arena_off + n > sizeof __btrc_arena) return (void *)0; void *p = &__btrc_arena[__btrc_arena_off]; __btrc_arena_off += n; return p; }
void free(void *p) { (void)p; }
void *calloc(size_t a, size_t b) { size_t n = a * b; void *p = malloc(n); if (p) memset(p, 0, n); return p; }
void *realloc(void *p, size_t n) { void *q = malloc(n); if (q && p) memcpy(q, p, n); return q; }

size_t strlen(const char *s) { const char *p = s; while (*p) p++; return (size_t)(p - s); }
int strcmp(const char *a, const char *b) { while (*a && *a == *b) { a++; b++; } return (unsigned char)*a - (unsigned char)*b; }
int strncmp(const char *a, const char *b, size_t n) { while (n && *a && *a == *b) { a++; b++; n--; } return n ? (unsigned char)*a - (unsigned char)*b : 0; }
char *strcpy(char *d, const char *s) { char *r = d; while ((*d++ = *s++)) {} return r; }
char *strncpy(char *d, const char *s, size_t n) { char *r = d; while (n && (*d++ = *s++)) n--; while (n--) *d++ = 0; return r; }
char *strchr(const char *s, int c) { for (; *s; s++) if (*s == (char)c) return (char *)s; return c ? (char *)0 : (char *)s; }
char *strstr(const char *h, const char *n) { if (!*n) return (char *)h; for (; *h; h++) { const char *a = h, *b = n; while (*a && *b && *a == *b) { a++; b++; } if (!*b) return (char *)h; } return (char *)0; }

int isspace(int c) { return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\v' || c == '\f'; }
int isdigit(int c) { return c >= '0' && c <= '9'; }
int isalpha(int c) { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z'); }
int tolower(int c) { return (c >= 'A' && c <= 'Z') ? c + 32 : c; }
int toupper(int c) { return (c >= 'a' && c <= 'z') ? c - 32 : c; }

#ifndef BTRC_RT_PUTS
void __btrc_rt_puts(const char *s, size_t n) { (void)s; (void)n; }  /* replace with printk */
#define BTRC_RT_PUTS __btrc_rt_puts
#endif
#ifndef BTRC_RT_TRAP
void __btrc_rt_trap(void) { for (;;) {} }   /* replace with BUG()/panic() */
#define BTRC_RT_TRAP __btrc_rt_trap
#endif
void abort(void) { BTRC_RT_TRAP(); }
void exit(int code) { (void)code; BTRC_RT_TRAP(); }
void *stderr = (void *)0;

/* Minimal integer/string formatter: %d %i %u %x %X %c %s %% with field width
 * and 0-padding. No floating point (add a float path if your program prints
 * floats). Shared by snprintf/printf/fprintf. */
static size_t __btrc_fmt(char *out, size_t cap, const char *fmt, va_list ap) {
    size_t pos = 0;
#define BTRC_PUT(ch) do { if (pos + 1 < cap) out[pos] = (char)(ch); pos++; } while (0)
    for (; *fmt; fmt++) {
        if (*fmt != '%') { BTRC_PUT(*fmt); continue; }
        fmt++;
        int zero = 0, width = 0, prec = -1;
        if (*fmt == '0') { zero = 1; fmt++; }
        while (*fmt >= '0' && *fmt <= '9') { width = width * 10 + (*fmt - '0'); fmt++; }
        if (*fmt == '.') { fmt++; prec = 0; while (*fmt >= '0' && *fmt <= '9') { prec = prec * 10 + (*fmt - '0'); fmt++; } }
        char buf[32]; int bl = 0, neg = 0;
        switch (*fmt) {
        case 'f': case 'F': case 'g': case 'G': {
            double dv = va_arg(ap, double);
            int fp = (prec < 0) ? 6 : (prec > 18 ? 18 : prec);
            if (dv != dv) { BTRC_PUT('n'); BTRC_PUT('a'); BTRC_PUT('n'); continue; }
            int fneg = (dv < 0); if (fneg) dv = -dv;
            if (dv != 0 && dv + dv == dv) { if (fneg) BTRC_PUT('-'); BTRC_PUT('i'); BTRC_PUT('n'); BTRC_PUT('f'); continue; }
            if (fneg) BTRC_PUT('-');
            double scale = 1; for (int i = 0; i < fp; i++) scale *= 10;
            unsigned long long ip = (unsigned long long)dv;
            unsigned long long fr = (unsigned long long)((dv - (double)ip) * scale + 0.5);
            if (scale >= 1 && fr >= (unsigned long long)scale) { ip += 1; fr -= (unsigned long long)scale; }
            char ib[24]; int ibl = 0; unsigned long long t = ip; do { ib[ibl++] = "0123456789"[t % 10]; t /= 10; } while (t);
            while (ibl) BTRC_PUT(ib[--ibl]);
            if (fp > 0) {
                BTRC_PUT('.');
                char fb[24]; int fbl = 0; unsigned long long f = fr; do { fb[fbl++] = "0123456789"[f % 10]; f /= 10; } while (f);
                for (int i = fbl; i < fp; i++) BTRC_PUT('0');
                while (fbl) BTRC_PUT(fb[--fbl]);
            }
            continue;
        }
        case 'd': case 'i': { int iv = va_arg(ap, int); unsigned long u; if (iv < 0) { neg = 1; u = (unsigned long)(-(long)iv); } else u = (unsigned long)iv; do { buf[bl++] = "0123456789"[u % 10]; u /= 10; } while (u); if (neg) buf[bl++] = '-'; break; }
        case 'u': { unsigned long u = va_arg(ap, unsigned int); do { buf[bl++] = "0123456789"[u % 10]; u /= 10; } while (u); break; }
        case 'x': case 'X': { unsigned long u = va_arg(ap, unsigned int); const char *d = (*fmt == 'x') ? "0123456789abcdef" : "0123456789ABCDEF"; do { buf[bl++] = d[u % 16]; u /= 16; } while (u); break; }
        case 'c': BTRC_PUT((char)va_arg(ap, int)); continue;
        case 's': { const char *s = va_arg(ap, const char *); if (!s) s = "(null)"; while (*s) BTRC_PUT(*s++); continue; }
        case '%': BTRC_PUT('%'); continue;
        case 0: goto done;
        default: BTRC_PUT('%'); BTRC_PUT(*fmt); continue;
        }
        for (int p = bl; p < width; p++) BTRC_PUT(zero ? '0' : ' ');
        while (bl) BTRC_PUT(buf[--bl]);
    }
done:
    if (cap) out[pos < cap ? pos : cap - 1] = 0;
#undef BTRC_PUT
    return pos;
}
int snprintf(char *out, size_t cap, const char *fmt, ...) { va_list ap; va_start(ap, fmt); size_t n = __btrc_fmt(out, cap, fmt, ap); va_end(ap); return (int)n; }
int printf(const char *fmt, ...) { char b[1024]; va_list ap; va_start(ap, fmt); size_t n = __btrc_fmt(b, sizeof b, fmt, ap); va_end(ap); BTRC_RT_PUTS(b, n < sizeof b ? n : sizeof b - 1); return (int)n; }
int fprintf(void *stream, const char *fmt, ...) { (void)stream; char b[1024]; va_list ap; va_start(ap, fmt); size_t n = __btrc_fmt(b, sizeof b, fmt, ap); va_end(ap); BTRC_RT_PUTS(b, n < sizeof b ? n : sizeof b - 1); return (int)n; }
#endif /* BTRC_FREESTANDING_IMPL */

#endif /* BTRC_FREESTANDING */

#endif /* BTRC_RT_H */
"""
