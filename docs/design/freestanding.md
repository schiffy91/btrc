# Freestanding btrc (kernel / embedded targets)

btrc programs can target environments with **no hosted C library** — a kernel
module, firmware, a bootloader — by compiling with `--freestanding`. The
generated C then depends on a single retargetable seam instead of `<stdio.h>`
and friends.

## `--freestanding`

In this mode the compiler emits **no `<system>` includes**. Every runtime
symbol the program references (malloc, printf, mem*, str*, setjmp, …) is routed
through one header:

```c
#include "btrc_rt.h"
```

A program that references *no* runtime symbol (the pure integer/float/struct
subset) gets an empty prologue — a fully self-contained translation unit.
`btrcpy --freestanding foo.btrc -o foo.c` also writes a reference `btrc_rt.h`
next to the output.

## The seam: `btrc_rt.h`

One header, two modes:

- **Hosted (default):** maps every symbol onto the C standard library, so
  freestanding output still builds and runs on a normal toolchain — useful for
  testing transpiled code before it reaches the target.
- **Freestanding target (`-DBTRC_FREESTANDING`):** the `#else` branch enumerates
  the complete external surface of the btrc runtime and shows where to map each
  symbol (Linux-kernel equivalents in comments).

### Reference runtime (`-DBTRC_FREESTANDING_IMPL`)

The header also ships a self-contained reference implementation: a bump-arena
allocator, `mem*`/`str*`/`ctype`, and an integer/string `printf`/`snprintf`,
with all output funneled through one hook — `__btrc_rt_puts` (replace with
`printk`). Define `BTRC_FREESTANDING_IMPL` in one translation unit and a
collection/string program links with **zero libc**:

```bash
btrcpy prog.btrc --freestanding -o prog.c
gcc -std=c11 -ffreestanding -fno-builtin -fno-stack-protector -nostdlib \
    -DBTRC_FREESTANDING -DBTRC_FREESTANDING_IMPL -c prog.c -o prog.o
nm prog.o | grep ' U '        # → empty: no external dependencies
```

The formatter handles `%d`/`%u`/`%x`/`%c`/`%s`/`%%` with width and zero-padding,
and `%f`/`%.Nf` (float printing). Not provided by the reference runtime (add for
your target, or avoid): `setjmp`/`longjmp` (btrc `try/catch`) and threads
(`Thread<T>`/`Mutex<T>` need a pthread-compatible shim).

## What makes it self-contained

Dead-code elimination is what keeps the surface small. The optimizer prunes
unreached functions, unreferenced structs, and — importantly for freestanding —
**unused libc extern declarations** (the auto-composed stdlib declares `popen`,
`forkpty`, etc.; when the using code is eliminated, so is the extern, which
otherwise drags in `FILE` and other unavailable types). See
[`src/compiler/python/ir/optimizer.py`](../../src/compiler/python/ir/optimizer.py).

## Scope

The pure subset and the core stdlib (strings, collections, integer math) are
kernel-ready today. Modules that wrap OS facilities (files, processes, sockets,
regex, threads) are not freestanding — they require the corresponding target
services and are pruned when unused.
