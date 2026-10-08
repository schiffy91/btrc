# G12 / SB-29 canonical specialization order

Owner: Codex execution_review, assigned under PLAN D29 on 2026-10-08.
Branch: `codex/compiler-canonical-instance-order`.
Base: `cd48ca3eb27f443c74355adad6e96ce1e0c09633` (compiler production matches dff538ef).
The quiet-classification branch at afda125e and plan-status branch at 404a5a6b remain preserved.

Owned paths:

- `src/compiler/python/ir/lowering/generics.py`
- `src/compiler/python/ir/lowering/translation_unit.py`
- `src/compiler/python/application/modules.py`
- `src/compiler/btrc/ir/lowering/Generics.btrc`
- `src/compiler/btrc/ir/lowering/Declarations.btrc`
- `src/compiler/btrc/pipeline/ModuleUnits.btrc`
- Targeted specialization/dependency regression tests in `src/tests/python/test_module_unit_staleness.py` and `src/tests/python/test_module_units.py`.
- This report.

## Contract and scope

The approved `docs/design/stage-b-reuse-keys.md` G12 contract requires canonical specialization emission, keeping shared declarations dependency-safe. This bounded slice addresses SB-29: exchanging two existing instance uses must not change the template unit merely by changing discovery order. Analysis and demand replay stay in their existing order; canonical views belong to lowering. Emission and cache identity must agree. Removing order from a key without canonical emission is not a fix.

This does not implement the full consulted-fact cache, tuple-order groundwork, analysis journal or Stage 9 analysis counters. No speedup or benchmark acceptance is claimed. The frozen design reference is untouched. Any necessary boundary recapture uses existing generation and explicit review, retaining the original records as evidence.

## Baseline

Retained `~/.cache/btrc/plan-consolidation-2026-10-07/combined-dff538ef/suite.xml` records passing paired instance-order, tuple/span staleness, simple private-edit reuse and self-hosted validation replay tests. The current instance-order regression requires all three groups to relower; it proves conservative correctness, not the desired precise reuse. Both simple private-edit tests already prove one lowered source group.

Initial disk check: 79,509,892 KiB available (about 81.4 GB). Source and lightweight checks only while the parent owns the Mac native lane. No self-host build/native test or publication is authorized for this checkpoint.

## Qualification

The Python specialization owner returns class and method views sorted by their
existing injective emitted symbols. The self-hosted owner supplies the same
canonical instance views to its plans, generic forward declarations and module
identity. Both generic forward loops use canonical order. Analysis demand lists
are untouched. Shared-declaration order and the other program facts remain in
the keys; this slice does not remove their conservative invalidation.

Evidence directory:
`~/.cache/btrc/plan-consolidation-2026-10-07/canonical-instance-order/`.

- Preserved fixture checkpoint `902c5621`; the preceding checkpoint used an
  unsupported explicit generic-call syntax in the new method fixture. That
  fixture mistake was corrected to ordinary inferred calls, not counted as a
  compiler regression.
- `red-reference-r2.xml` / `.log`: all four reference class/method × release/debug
  rows fail on the original production source because the unchanged template
  unit's bytes change. The cold, edit and fresh-clean builds otherwise complete.
- `green-reference.xml` / `.log`: the same four rows pass with exactly one
  changed unit (`Use`) and one lowered group (4 passed, 4.56 s).
- Changed class demand and reverse-lexical by-value dependency guards pass in
  `guard-reference.xml`; a method guard initially substituted `double` for a
  literal that already inferred `double`, so that fixture did not change the
  demand set. The corrected guard removes that instance and passes in
  `guard-reference-r2.xml` (1 passed, 1.16 s). All failed attempts are retained.
- The guards require changed demand to update the template unit and conservatively
  lower all three groups; `ABox<ZRecord>` must retain its template unit across
  reordered uses, with the by-value `ZRecord` definition before `ABox` despite
  their reversed lexical names. This is emitted-source dependency evidence,
  not yet a native C execution result.
- Ruff check, Python formatting, BTRC formatting and `git diff --check` pass.
- Final source-frozen reference selection, `focused-reference.xml` / `.log`:
  **9 passed in 9.82 s**, covering the seven new/strengthened ordering and
  dependency rows plus the existing conservative tuple and span order guards.
  Every selection used its full parameterized reference node ID.

The first attempted reference selection used `-k ...python`, which also matched
the module path and admitted the self-host fixture after four reference failures.
The owned pytest PID 61225 and reference-emission child PID 61255 were terminated
before native C compilation. Session 89442 ended 143; `red-python.log` is an
incomplete attempt, not a baseline. Subsequent reference admission explicitly
selected `--compilers=python`, then used full parameterized node IDs. No new
self-host binary was built by that attempt.

Independent source review by performance_review is complete with no actionable
blocker. It checked canonical view/forward/key wiring, unchanged analyzer order,
changed-demand invalidation and the by-value dependency fixture; the reviewer
ran no tests or builds.

Paired self-host/native execution, recapture of **every frozen boundary record**
through the existing generator as G12 requires, and final exact-tree gates remain
pending. Canonical ordering changes clean output once; boundary expectations
must be reviewed, never hand-edited to conceal a failure. No timing here is a
performance result, and Stage 9's full analysis/journal counter remains open.
