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
- **Freestanding target (`-ffreestanding -fno-builtin
  -DBTRC_FREESTANDING`):** the `#else` branch defines the core ABI. Optional
  OS/native modules enter through `BTRC_RT_PLATFORM_HEADER` or a typed feature
  shim, so target-specific types such as `jmp_buf` are never guessed.

The compiler derives native feature flags from live structured calls after
dead-code elimination. `BTRC_RT_NEEDS_PTHREAD`, `BTRC_RT_NEEDS_SETJMP`,
`BTRC_RT_NEEDS_GPU`, `BTRC_RT_NEEDS_GUI`, and `BTRC_RT_NEEDS_TRAY` appear before
the seam only when reached. A target supplies the corresponding
`BTRC_RT_*_HEADER`; a single `BTRC_RT_PLATFORM_HEADER` can provide additional
filesystem/socket/platform declarations.

### Reference runtime (`-DBTRC_FREESTANDING_IMPL`)

The header also ships a self-contained reference implementation: an aligned,
overflow-checked bump arena, `mem*`/`str*`/`ctype`, decimal parsing, and
`printf`/`snprintf`, with all output funneled through one hook —
`__btrc_rt_puts` (replace with `printk`). Define `BTRC_FREESTANDING_IMPL` in one
translation unit and a collection/string program links with **zero libc**:

```bash
btrcpy prog.btrc --freestanding -o prog.c
gcc -std=c11 -ffreestanding -fno-builtin -fno-stack-protector -nostdlib \
    -DBTRC_FREESTANDING -DBTRC_FREESTANDING_IMPL -c prog.c -o prog.o
nm prog.o | grep ' U '        # → empty: no external dependencies
```

The formatter handles signed/unsigned integer width modifiers (`l`, `ll`, `z`,
and the standard promoted forms), decimal/hex/octal, strings/chars, width,
precision, padding, and `%f`/`%e`/`%g` including `long double`. Not provided by
the reference runtime formatter beyond its bounded scope: floating precision is
clamped to 18 decimal digits. Also not provided (supply a target shim or avoid): `setjmp`/`longjmp`,
threads, and native GPU/GUI/tray backends.

## What makes it self-contained

Dead-code elimination is what keeps the surface small. The optimizer prunes
unreached functions, helpers, GPU kernels, external declarations, and the
transitive graph of unused enums/typedefs/function-pointer typedefs/tagged
unions/structs/forwards. Thus an unused `popen`, `forkpty`, or native backend
cannot drag its declarations or runtime feature into a freestanding unit. See
[`src/compiler/python/ir/optimizer.py`](../../src/compiler/python/ir/optimizer.py).

## Scope

The pure subset and core stdlib (strings, conversions, collections, integer
math) work with the zero-libc reference implementation. Modules that wrap OS or
native facilities require services declared by the target platform/feature
shim and are pruned when unused.
