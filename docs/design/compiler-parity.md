# Compiler parity

The Python reference compiler and the self-hosted `btrcc` must accept the same
programs, reject the same programs with the same first diagnostic, and build
programs that behave the same. This note records what is held equal, how, and
which differences remain in the C the two compilers emit.

## What is held equal

| Property | Checked by |
| --- | --- |
| Acceptance and the first diagnostic (message, line, column) of ordinary programs | `src/tests/btrc/test_analyzer_parity_battery.py` |
| Acceptance, first diagnostic and byte-identical WGSL of `@gpu` programs | `src/tests/btrc/test_gpu_diagnostics_parity.py` |
| Runtime behaviour of every corpus program | the unified corpus runner, through both compilers |
| Runtime behaviour of every SDK-free example | `src/tests/python/test_examples.py` |
| Recorded outcome of every C-compatibility probe | `src/tests/btrc/test_c_compatibility_inventory.py` |

A divergence found anywhere is fixed in both compilers in one commit, and its
minimal program joins one of the batteries above.

### Resolved in the Stage 4 analyzer-parity lane

- **Floating literals in `@gpu` kernels.** A floating literal is `double` in
  host code in both compilers, as in C. Inside a kernel there is no `double`:
  a `var` binding takes the kernel's f32 domain, so `var s = 0.5;` is a
  `float` in the WGSL, in the CPU fallback and in both analyzers. Python used
  to infer `double` and reject the kernel.
- **Bitwise operators on two `bool`s** (`&`, `|`, `^`) yield `bool` in both
  compilers, as the GPU analyzers already did; arithmetic on `bool` is
  rejected in both.
- **`new` of a non-class** (`new int()`, `new S()` for a struct) is rejected in
  both. Python used to accept it and emit a call to a nonexistent `int_new()`.
- **Class members require an access specifier** in both parsers. `btrcc` used
  to accept `class C { int x; }`.
- **Wording**: `??` on non-references, operators on unsupported operands
  (`Operator '<<' ...`), indexing a scalar, calling a non-callable value,
  duplicate and conflicting top-level declarations, unresolved identifiers,
  and assignment type mismatches (now reported before the opaque-borrow rule).
- **f-string interpolation positions.** Both compilers report a diagnostic in
  an interpolated expression at its real line and column; both used to
  report it at the start of the file.
- **Trigraph spelling in emitted C.** Both C emitters escape a `?` that
  follows another inside literal text, so `"a??'b"` stays three characters
  under a strict C11 compiler instead of becoming `a^b`.
- **Duplicate includes.** A source `#include` of a header the compiler
  already includes is emitted once by both compilers (`btrcc` always
  deduplicated; Python repeated it).

## Remaining differences in emitted C

The two compilers' C is not byte-identical, so `test_examples.py` and the
corpus compare behaviour, not text. A survey of 414 corpus programs (`basics`,
`classes`, `collections`, `memory` and the `Fstring*` strings) on
2026-10-01 found 82 byte-identical and the rest differing only in the
families below. None changes observable behaviour; each is a rewrite of a
lowering owner in one compiler, not a local fix, so they are recorded rather
than converged here.

| Family | Python | `btrcc` | Scope |
| --- | --- | --- | --- |
| Call-boundary temporaries | `__btrc_call_operand_N`, `__btrc_call_result_N` | `__btrc_operand_N`, `__btrc_boundary_result_N` | most programs that pass a managed value to a call |
| Released-operand cleanup | unconditional `__btrc_string_release(x)` | `x` declared `= NULL`, released under `x != NULL ? ... : (void)0` | the same call boundaries |
| Store temporaries | `__btrc_slot_new_N`, `__btrc_slot_old_N` | `__btrc_store_value_N`, `__btrc_store_current_N` | managed stores |
| Indexed stores | index captured in `int __btrc_storage_index_N`, then `a[i] = v` | address captured in `T volatile* __btrc_lvalue_N`, then `*p = v` | every indexed assignment, including the `@gpu` CPU fallback |
| Promoted ternary branches | `__btrc_promoted_branch_N` | `__btrc_promoted_N` | `??` and ternaries over managed values |
| `bool` in `print` | `printf("%d", (int)b)` | `printf("%d", b)` | printing a `bool` |
| `@gpu` fallback index check | `__btrc_gpu_index_check` | `__btrc_gpu_checked_index` | CPU fallback bodies |
| Runtime-helper selection | `__btrc_arc_release_acyclic` materialized in fewer units | materialized wherever an acyclic release could be reached | ARC programs |
| Header order | `<setjmp.h>` before `<stdatomic.h>` | `<stdatomic.h>` before `<setjmp.h>` | programs needing both (2 of 414) |

Converging these means choosing one lowering per family and moving the other
compiler's owner to it, with the corpus and the C11 matrix proving each step.
Until then a test may require identical **behaviour** of the two compilers'
output, or identical text of a narrow fragment it names (the WGSL modules, a
diagnostic), but not identical translation units.

## Deferred: nullable-to-non-nullable stores

`N n = make();`, where `make()` returns `N?`, is accepted silently by both
compilers. The consistent rule would be the existing nullable-access one: a
path-sensitive **warning**, silenced where the flow proves the value non-null.
It is not implemented yet, for three reasons measured on 2026-10-01:

1. A prototype of the warning in the Python analyzer reported 94 sites in the
   self-hosted compiler alone, before the stdlib, examples and corpus. Almost
   all are the deliberate `Node concreteX = maybeX;` narrowing written after
   `TypeValidator.fail(...)`, which exits. The flow analysis does not know
   that a call cannot return, so it cannot see these as proven.
2. Self-host builds fail on any analyzer warning, so the warning cannot land
   before every site is either rewritten or proven by a flow that understands
   non-returning calls.
3. `btrcc` has no warning channel and no nullable-flow analysis at all: the
   existing nullable-access warning is reported by the Python compiler only.

The order of work is therefore: teach the flow analysis non-returning calls
(`exit`, and functions whose every path ends in one), port the nullable flow
and a warning channel to `btrcc`, then add the store warning to both.
