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
  defines the core ABI and one platform-header hook for POSIX/native extensions.
  This is the single file an embedder edits.

The symbol list is derived from the libc identifiers actually emitted by the IR
generator and the runtime helpers; keep it in sync if either grows.
"""

from __future__ import annotations

from .freestanding_reference import REFERENCE_RUNTIME

RUNTIME_HEADER = (
    r"""/* btrc_rt.h — the single retargeting seam for --freestanding btrc output.
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
"""
    + REFERENCE_RUNTIME
    + r"""
#endif /* BTRC_FREESTANDING_IMPL */

#endif /* BTRC_FREESTANDING */

#endif /* BTRC_RT_H */
"""
)
