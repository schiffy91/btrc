# Current compiler token-lifetime candidate

## Claim and status

Integrator assignment under D29, 2026-10-08. Branch
`codex/compiler-token-current` starts at exact baseline
`56d548c49ca027c9698c8546acdaf4df918630bd` in the existing `http-contract`
clone. Own only `src/compiler/btrc/pipeline/Pipeline.btrc`, this report and the
corresponding `WORKSTREAMS.md` claim row. The Windows branch remains at
`110a514c5f91bc6c647f84f944f80ff8eae3fecc`; the historical token branch remains
at `d6309c7ca4e71c92415851359a50223e1cfdba48` (implementation `69ca0f17`).
The separate Linux UI2 branch remains frozen at `44a6f04a`.

Reapply only the reviewed lexical lexer/parser/token ownership change from
`69ca0f17eb95aaf5213e93d9b134c6e15a30d3b9`. No stale report/claim merge, Python
pipeline change, runtime change, generated edit, ownership escape or benchmark
baseline adjustment is authorized. Python owns its existing reference lifetime
and remains unchanged by design. Preserve the exact AST strings, diagnostics,
phase marks and downstream ownership.

Status: source preparation only. No current candidate build, test, emitted-C
inspection, sanitizer qualification, benchmark, PR or CI run has occurred.
Baseline qualification is parent-owned and incomplete. A lexical scope change
is a mechanism hypothesis, not proof of peak-memory or instruction improvement.
