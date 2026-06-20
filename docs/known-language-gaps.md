# Known language gaps

These are language features the grammar/spec permits (or the docs imply) but the
**reference Python compiler does not yet correctly lower** — so they fail on
*both* the reference and the self-hosted (btrcc) compiler. They were surfaced by
the exhaustive test-coverage sweep (a swarm that enumerated every feature in the
grammar/ASDL/README and tried to write a passing test for each). No test exists
for these yet, because a test cannot pass until the compiler is fixed; each is a
concrete, reproducible fix opportunity.

| # | Feature | Symptom | Where |
|---|---------|---------|-------|
| 1 | `typedef` aliases (`typedef int MyInt;`) | parsed into a TypedefDecl but never lowered/emitted; use site references an undeclared C type | no TypedefDecl handler in `ir/gen/` |
| 2 | `static` on a **local** variable | the storage qualifier is dropped; the local does not persist across calls | statement lowering |
| 3 | Class-type C-style cast (`(Animal)dog`) | drops the pointer level (`(Animal)x` instead of `(Animal*)x`) → gcc error | cast lowering |
| 4 | `long long`.toString() | uses the `int` formatter (`__btrc_intToString`), truncating 64-bit values (`long` is fine) | type-dispatched toString |
| 5 | Rich enum as a param / return / class field / collection element | the tagged-union struct is emitted *after* a forward decl that references it by value → "unknown type" (rich enums kept local to a function work) | emit ordering |
| 6 | Compound assignment on a class (`obj += other`) | not routed through the `__add__`/`__sub__`/... overload; emits raw `obj += other` on struct pointers → gcc error | `_lower_assign` in `ir/gen/fields.py` |
| 7 | Nullable class element in a generic collection (`Vector<Box?>`) | `push` doesn't retain a nullable element; the temp's auto-release frees it → use-after-free | generic-collection ARC |
| 8 | `unsigned long long`, `long long int`, `long long double` base types | parser rejects them though the `base_type` grammar rule permits them (`unsigned long`, `long long`, `long int`, `short int` all work) | parser type parsing |
| 9 | Multi-dimensional fixed arrays (`int grid[2][3]`) | only a single `[N]` name suffix is accepted | parser var-decl |
| 10 | Capturing block-body IIFE (`((int k) => { return k + n; })(4)` capturing `n`) | the inline call site omits the closure env arg → "too few arguments" | lambda-capture call lowering |
| 11 | A **capturing** lambda stored in a bare `__fn_ptr` and called through it (`__fn_ptr<bool,int> p = over; p(1)`) | `__fn_ptr` is a plain C function pointer with no env slot, so the call passes no env and reads garbage where the captured value should be (only "worked" under compilers whose stack garbage happened to read right; gcc 15 returns wrong results). A capturing lambda needs a closure object, not a bare pointer. Either the analyzer should reject the assignment or the language needs a distinct closure type. | `__fn_ptr` typing / lambda-to-fn-ptr lowering |

The self-hosted compiler mirrors the reference, so fixing each in
`src/compiler/python/` and then in `src/compiler/btrc/` (and adding the test the
sweep already drafted) closes the gap on both. Everything the compilers *do*
support is covered by the corpus and passes on both compilers.
