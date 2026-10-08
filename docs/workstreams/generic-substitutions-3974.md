# Demand-only generic substitutions

Base: `3974d47bc87851b1ac19b8d2b4bd5022f2d94676`.
Branch: `codex/generic-substitutions-3974`.
Owner: performance agent under the integrator's D29 assignment.

Generic lowering plans eagerly constructed substitution maps even when their
consumers needed only instance/declaration metadata. The two actual map readers
are the class and method tuple scanners. Plans now retain only their metadata;
the existing GenericLowerer constructs a fresh map at each tuple-scan use.
Class bindings and class-then-method override order are unchanged. Canonical
instance/dependency ordering, analyzer replay, cache keys and the Python
immutable substitution model are unchanged.

Owned production paths are `src/compiler/btrc/ir/lowering/Generics.btrc` and
`src/compiler/btrc/ir/lowering/Declarations.btrc`. The integrator independently
reviewed outside-tree patch `86958ff18b8d16757094c1cdb76b77aac222ff2a524fe946031aaad562d8b384`
before branch creation. A recursive compiler/tools inventory found no other
plan-substitution consumers. The initial claim is committed separately.
Token `71352c50`, audio `0089e96c`, and the finish-reply proposal remain separate.

## Verification and missing evidence

On 2026-10-08, the unchanged repository BTRC formatter's `check` command passes
for both changed files with qualified Python3.14.6; `git diff --check` passes.
Free space at stage admission is81.50GB. No compiler transpilation, native
build, test, guest, measurement or publication has run for this candidate.
Source review is not allocation or performance evidence.

The private attribution draft lives outside the checkout at
`/private/tmp/btrc-audit-repair/generic-substitutions-3974/`. It observes real
Map<string,Node> allocations inside actual plan-building functions in exact
scratch generated C, with source/hash/anchor guards. Baseline must exercise
nonempty plans and allocate their substitution maps; candidate must construct
the same plans without those allocations. Tuple substitution construction and
full emitted C remain required. The observer is not production instrumentation
and must not be used as a performance binary.

Next qualification uses a fresh candidate compiler: paired generic/tuple
corpus, generic-method and shadowing semantics, G12 instance-order and tuple
invalidation guards, worker-count/cache equivalence, full boundary311 review,
and applicable strict-C/ownership/bootstrap gates. Then compare uninstrumented
baseline/candidate with the original alternating Linux peak checks and unchanged
allowances. Exact current CompileStdlibHeavy overage is96KiB; no saving or
threshold recovery is claimed. Mac D9 and final1.5GiB/current-product acceptance
remain separate.
