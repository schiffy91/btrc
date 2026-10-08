# G12 / SB-29 canonical specialization order

Owner: Codex execution_review, assigned under PLAN D29 on 2026-10-08.
Branch: `codex/compiler-canonical-instance-order`.
Base: `cd48ca3eb27f443c74355adad6e96ce1e0c09633` (compiler production matches dff538ef).
The quiet-classification branch at afda125e and plan-status branch at 404a5a6b remain preserved.

Owned paths:

- `src/compiler/python/ir/lowering/generics.py`
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

Implementation, red/green regression evidence, independent review and exact-tree qualification are pending.
