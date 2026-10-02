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
| Analyzer warnings (message, file, line, column and rendering) of probe programs, and that a warning never changes the exit status | `src/tests/btrc/test_warning_parity_battery.py` |
| Analyzer warnings of every corpus program, held to `expected/<Stem>.warnings` in both compilers | the unified corpus runner |
| No analyzer warning in any SDK-free example, or in the compiler compiling itself | `src/tests/python/test_examples.py`, `src/tests/btrc/test_bootstrap.py` |

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
- **Empty collection literals.** An empty `[]` or `{}`, bare or as either
  branch of a ternary, takes its type from the target (declared local, field
  default, assignment, return, call argument) in both compilers. Python used
  to reject the return and argument positions and most ternaries; `btrcc`
  lowered ternary branches as `Vector<int>`; both lowered a `{}` ternary
  branch to `NULL`.
- **Duplicate includes.** A source `#include` of a header the compiler
  already includes is emitted once by both compilers (`btrcc` always
  deduplicated; Python repeated it).

### Nullable flow and the warning channel

Both compilers report the nullable-access warning (`Non-optional access '.f'
on nullable type 'T?'`) from the same path-sensitive flow, and print every
warning the same way: `warning: <message>`, then the file (the input as named
on the command line, any other source by its absolute path), line and column,
and the source line with a caret. A warning never changes the exit status.
`btrcc` renders its warnings once analysis succeeds; a compile that fails
prints only its first error, as it always has.

The flow tracks stable access paths (a local, a parameter, `self` or a global,
followed by field names) known to be non-null. A null comparison refines the
branch it guards, `&&`, `||` and `?:` refine their right operands and arms, a
store of a value known to be non-null refines its target, and a call, a store
or an escaped address drops the facts it could change. A loop body is analysed
once, from the facts that survive its back edge.

A call can be known never to return: a hosted function listed in
`hosted_abi.toml`'s `noreturn` set (`exit`, `abort`, `_Exit`, `quick_exit`,
`longjmp`, `pthread_exit`), or a source function or method every path of whose
body ends in a `throw` or in such a call. The second set is the least fixed
point over a syntactic call graph: `f()` names a top-level function, `C.m()` a
static method of class `C`, and `self.m()` every implementation a subclass can
dispatch to; a local binding of the same name shadows the callee. Code after a
return, a throw or such a call is unreachable and reports nothing, and a
branch that never completes adds no facts to the code after it, so
`if (x == null) { TypeValidator.fail(...); }` proves `x` afterwards. btrc has
no `_Noreturn` marker of its own; `_Noreturn` stays a reserved C spelling.

In `btrcc` the flow is `NullableFlow`, beside `ControlFlowValidator`, and
module-unit validation records carry each body's warnings, so a replayed
record reports what live validation did.

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
and a warning channel to `btrcc`, then add the store warning to both. The
first two are done (see "Nullable flow and the warning channel" above); the
store warning remains.
