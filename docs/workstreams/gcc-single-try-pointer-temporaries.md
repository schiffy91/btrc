# Generated pointer temporaries in single try regions

Packet: `codex/gcc-single-try-pointer-temps-3974`; base `3974d47b`.
Owner: execution_review; integrator authorized the paired compiler repair.

Owned paths:

- `src/compiler/python/ir/lowering/exceptions.py`
- `src/compiler/btrc/ir/optimization/setjmp/Safety.btrc`
- `src/tests/python/test_exception_codegen_contracts.py`
- `src/tests/control_flow/SingleTryPointerOperands.btrc`
- `src/tests/control_flow/expected/SingleTryPointerOperands.stdout`
- `docs/workstreams/gcc-single-try-pointer-temporaries.md`

The existing setjmp safety planners own this GCC coalescing correction. No emitter,
grammar, runtime, generated-source, flags or product workaround changes are claimed.
Original Linux failure and local paired GCC compile-only baseline are retained.
Reference and fresh selfhost repair qualification are recorded below. Combined
gates and real hosted product continuation remain pending.

## Failure and correction

Actual Linux GCC15.2 compilation of AgentSurfaceProcessAcceptance reports four
compiler-generated `int*` temporaries as clobbered: one stabilized call operand
and three indexed-storage receivers. The exact original class reproduces the
same four diagnostics with both immutable3974 frontends and native Darwin GCC15.2
at both `-O2` and `-O3`, each ordinary exit1. No process-spawning program was run.

The existing planner already protects generated return storage and nested-try
locals from GCC register-pseudo coalescing. Extend it to generated pointer
storage inside a single try/handler region using the existing declaration-identity
pointer facts. Scalars, source bindings, arrays, static/extern objects and
address-taken objects retain their existing rules. Outside-region behavior is
unchanged, including the existing requirement for generated values already
visible across setjmp. Pointer objects are qualified; pointees are unchanged.

## Evidence and limits

The final focused baseline has **2 failed contracts, 0 errors/skips**. The exact
private reference-owner overlay has **36 passes, 0 errors/skips**, including all
existing contracts and strict GCC O2/O3 compile/run of normal8/throw10/finally
semantics. The exact authentic class then emits without diagnostics and its C
compiles cleanly at both O2/O3 with the unchanged strict GCC15 flags.

Two earlier draft test runs are retained: one expected an already-visible
generated binding to remain plain despite existing policy; another assumed a
constant argument required operand stabilization. The final fixture checks the
existing visible-binding rule and uses a later argument call to exercise actual
left-to-right stabilization. No production fix changed to accommodate those
fixture corrections. Runtime assertions and strict flags remain intact.

Evidence: `/private/tmp/btrc-audit-repair/gcc-single-try-clobber/`:

- `results/baseline1/`: exact original paired compile-only four-warning proof.
- `results/reference1/` and `reference2/`: preserved fixture diagnostics.
- `results/reference3/`: final baseline, full reference contracts and authentic
  clean GCC compilation, with exact source/tool/command/exit/cleanup receipts.
- `AgentAcceptanceClobber.btrc`: original standalone class input SHA256
  `097527c21c31b58154d985c3de2ff58f92f25c2782c54239e866430291861d94`.

Ruff lint/format, BTRC formatting and whitespace checks pass. Independent paired
source review found no owner/parity/region-scope blocker. This is reference
qualification. Fresh selfhost qualification is recorded below; full combined gates,
Linux product acceptance and performance outcomes are not claimed.

## Fresh selfhost proof

The exact `f75c737b` source builds successfully through the retained native macOS
entry recipe with the original authenticated3974 development shell, Clang21.1.8
and Python interpreter. No bootstrap or full matrix was substituted for this
bounded build. Binary SHA256:
`60639d608d3e09bec4dcdfaf76d3575cdeb135b04d2102858cf15a9f089efbf3`.

That fresh compiler emits the unchanged authentic097 process class without
diagnostics. Strict GCC15 `-O2` and `-O3` both compile its C cleanly; the authentic
process-spawning program is never linked or run. The original corpus driver then
executes `SingleTryPointerOperands` through both Python and selfhost frontends at
both optimization levels: **4 passes, 0 skips/errors**, with exact frontend/node
identities. Normal8/throw10/finally assertions and the PASS golden are unchanged.

Build receipt:
`~/.cache/btrc/plan-consolidation-2026-10-07/gcc-single-try-pointer-f75c737b/result.json`
(SHA256 `c73f5ffbf0d3be307cfc2a1600f0fb1dcbe10f54d4604c8fc65b3f71054ca526`).
Proof receipt: `results/selfhost1/result.json` under the evidence root above
(SHA256 `c105c5f023320ba1878d5af68bdd6d06a5d01d40261f0f6fce33d1ab269f80c2`).
The canonical source inventory is authenticated against the completed build;
source/tools/interpreter/binary/script checks close unchanged and every owned
process group is absent. Independent final source/test and qualifier reviews
found no remaining blocker. The packet is bounded compiler qualification, not
final-tree harmonization or actual hosted Linux product acceptance.
