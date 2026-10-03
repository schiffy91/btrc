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
| Byte-identical C of every corpus program listed in `src/tests/fixtures/c_output_parity/identical.txt` | `src/tests/btrc/test_c_output_parity.py` |
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

### Callable const layers

A function passed to a callable parameter keeps its declared const layers in
both compilers. `btrcc` used to flatten typedefs in each signature component
before comparing them, which puts a slot const (`Handle const*` with
`Handle = struct HandleStorage*`) and a pointee const (`const HandleStorage**`)
on one shape; Python compares `declaration_const_depths`. `btrcc` now checks
every argument bound to a callable parameter layer by layer on the unflattened
types (`TypeValidator.argumentConstLayersMatch`). The gap surfaced when
native tag aliases made `const struct HandleStorage**` name the imported record
(`test_native_linux_call_shapes.py::test_callback_slot_const_is_not_pointee_const`);
it already applied to the untagged spelling. Python also applies the rule to
assignments and initializers of callable type; `btrcc` checks call arguments.

### Call arity wording

Both compilers refuse a call with the wrong number of arguments, but word it
differently: Python reports the expected range (`'f()' expects at least 2
argument(s) but got 1`, or `at most`), and `btrcc` names the first missing
parameter (`'f()' missing required argument 'b'`) and reports only the first
such call. Found while proving whole-function variadic shapes
(`test_native_linux_call_shapes.py` pins the refusal, not the text); it applies
to every function, not only native imports.

## Remaining differences in emitted C

`python3 -m src.tests.c_output_parity survey --btrcc <btrcc>` transpiles every
corpus program through both compilers, normalizing only the absolute checkout
path, and prints the byte-identical count and a first-difference histogram;
`--module-units` also compares every emitted module unit, and the *user
declarations* view drops the runtime catalog's helper text, which both
compilers copy verbatim. `--write-manifest` records the identical set in
`src/tests/fixtures/c_output_parity/identical.txt`, and
`src/tests/btrc/test_c_output_parity.py` requires every listed program to
stay byte-identical. Regenerate the manifest whenever a program joins the set.

On 2026-10-02 (`stage4/c-output-parity`) the survey measured:

| View | Before the lane (`7e7e128`) | After |
| --- | --- | --- |
| Whole programs byte-identical | 224 of 972 | 776 of 977 |
| User declarations identical | 226 of 972 | 776 of 977 |
| Module units identical | 770 of 3830 | 2542 of 3845 |
| Programs with every module unit identical | 138 of 972 | 496 of 977 |

The converged families are described in the lane's commits: runtime-helper
order, header placement, typed-declaration pruning, prototype order,
per-function temporary numbering, first-use adapter numbering, the physical
storage model for stores and updates, managed slot transactions,
call-boundary cleanup guards, f-strings through the call boundary, lifted
lambda and spawn-wrapper placement, enum placement, iterable ownership,
static linkage, throw-operand protection and the `@gpu` fallback's catalog
bounds check.

The 201 programs that still differ, by the family of their first differing
line:

| Family | Python | `btrcc` | Programs |
| --- | --- | --- | --- |
| Temporary allocation order | the same lowering numbers some temporaries in a different order (e.g. call operands before storage receivers) | | 51 |
| Generic-instance and type-declaration order | instance views in its discovery order | instance views in a different discovery order | 47 |
| Explicit releases in public collection methods | flushes cycle roots at each release of a cyclable value | polls at each release and flushes once at the method's end (`installReleaseBearingBoundary`) | 37 |
| Operand staging | stages every operand of an ordered expression | skips operands it proves inert (receivers, `bool` formats, some field projections), and lowers property stores through `__btrc_property_value` | 29 |
| Runtime-helper selection | a few helpers (`__btrc_string_retain`, `__btrc_interface_try_methods`, `__btrc_arc_release_acyclic`) materialized in different programs | | 16 |
| Other | function-pointer typedef order (7), `<stdatomic.h>` selection (3), prototypes (2), switch lowering, span and VLA hoists, a shadowing catch binding's numbering | | 21 |

None changes observable behaviour; the corpus, the C11 matrix and the
bootstrap run on both compilers' output. The collection-release batching is
deliberately left in `btrcc`: flushing per release inside a collection loop
over cyclable values could make large self-host collections quadratic, so it
needs a measured decision before either compiler moves.

Until a program is listed in the manifest, a test may require identical
**behaviour** of the two compilers' output, or identical text of a narrow
fragment it names (the WGSL modules, a diagnostic), but not identical
translation units.

## Nullable-to-non-nullable stores

Both compilers warn, from the same flow, where a value that may be null is
stored into a non-nullable class, interface or `string` reference:

```
warning: Possibly-null value stored in non-nullable <context> of type 'T' — check for null first
```

The context is `variable 'n'` (a typed local or global's initializer),
`assignment target` (`=` to a local or a field), `return value`,
`argument <i> of '<callee>'`, `field 'C.f'` (a field default) or
`parameter 'p'` (a parameter default). A value may be null when it is the
`null` literal, has a nullable type `T?`, is a `?:` with such an arm, or is an
`a ?? b` whose fallback `b` may be null. The warning is silenced where the flow
proves the value non-null (a guard, an early `return`, `throw` or
non-returning call, a store of a non-null value) and in unreachable code.

An argument is checked against the parameter of the callee the call resolves
to by the same rule in both compilers: by name to a top-level function with a
body or a non-generic class's constructor, as a static `C.m()`, or through the
receiver's type to a class, interface or generic-instance method, whose class
type parameters take the instance's arguments. A positional argument only; a
parameter typed by the method's own type parameter has no known target.

Access paths include a class's static fields (`C.f`), which, like globals, any
call can change, so `if (C.f == null) { ... return ...; } return C.f;` is
proven. Code after `self.field.m()` is unreachable when every implementation
of `m` in the field's declared class (and its subclasses) never returns.

A prototype of the warning reported 94 sites in the self-hosted compiler on
2026-10-01, before non-returning calls were understood; this rule reported
187 in the compiler's self-host transpile (21 of them in the generated
`Node` list accessors, which the static-field paths now prove), 28 more in the
stdlib and 135 in the corpus (2026-10-02). Every site in the compiler, the stdlib and the examples is now
proven or rewritten, so both self-host transpiles and the bootstrap stay
warning-free; the corpus programs that store `null` on purpose to exercise
the runtime's null handling keep their warning in `expected/<Stem>.warnings`.
