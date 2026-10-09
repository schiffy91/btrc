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

## Source-matched native qualification

On 2026-10-08 the parent allocated the serial Mac native lane. The source stayed
clean at `c3f709f709ac4e7825a6db5726f37a4b7a40284c` throughout the following runs,
holding the external `gate` and `btrcc-build` locks and checking at least 80 GB
free before each stage. Host: **Apple M1 Max, 8P+2E, 64 GiB, macOS 27.0**.

Evidence is retained under the directory above, in `c3f709f7/`:

- `build-result.json`: strict-import reference emission of `cli/MacOSMain.btrc`
  and strict C11 `-O2` native build passed with the retained Nix Clang 21.1.8,
  matching the established baseline toolchain. The pinned shell is
  `/nix/store/vn9csyrcz5gk24y9402kpxcwa6wkkngv-nix-shell-env`; the receipt records
  its digest, actual compiler path/hash, reader and SDK environment, exact
  commands and exit statuses. Native binary SHA-256:
  `5b5bd238a8313750d95834782a6a7c883e2ce975919422fb6fccf4f38878655f`.
- `qualification-result.json`, `paired.xml` and `paired.log`: **18 passed,
  zero skipped in 14.90 s**, selecting the exact nine parameterized rows through
  each frontend with `BTRC_TEST_BTRCC` pinned to that binary. Class and method
  use reordering in release and debug changes only `Use`, lowers one group and
  matches a fresh clean build. Changed demand invalidates the template; the
  dependency, tuple and span guards also pass. These rows inspect compiler
  output and counters; they are not elapsed-time performance measurements.
- `dependency-native-result.json`: the retained by-value dependency program's
  five C units from each frontend additionally compiled and linked with Clang
  21.1.8, `-std=c11 -pedantic-errors -Wall -Wextra -Werror -O0`, then executed
  successfully. Both programs check the expected value of 9 and return zero;
  emitted source hashes, native binary hashes and diagnostics are retained.

## Full frozen-boundary recapture

The unchanged existing generator ran explicitly as
`python3 -m tools.compiler_codegen.main boundary-capture --candidate build/verification/compiler-boundaries/g12-c3f709f7`.
This executes all producers, including observed behavior, rather than the
compatibility-skipping capture used by an ordinary boundary check. It built its
own source-matched `LexMain`, `ParseMain` and `BtrccMain` tools serially; it did
not substitute the MacOSMain test binary. Their hashes are in
`boundaries/result.json`.

`boundaries/original/` retains the entire original fixture tree, including the
manifest and both baseline and accepted artifacts. `boundaries/candidate/`,
`delta.json` and `diffs/` retain all **311** newly captured records and compare
against each record's effective accepted bytes, or baseline when unamended.

- **307 records are byte-identical:** all 287 portable records and all 20
  observed status/stdout/stderr channels.
- The only four differences are observation metadata: actual C tool identity
  and version digests, Python 3.14.6 versus 3.13.13, and Darwin 27.0.0 versus
  25.6.0. Flags, arguments and controlled environment remain unchanged.
- All **34 parity equalities** hold. All 32 status channels match, including
  the eight expected diagnostic failures and the twelve successful observed
  source/compile/run statuses. No failed producer was accepted as a pass.
- The existing boundary checker passes **287** portable records and explicitly
  leaves the 24 host-incompatible observed channels unchecked. The separate
  force-observed capture executed those producers successfully; this is not a
  claim that the checker accepted all 311 historical host observations.

The current frozen source fixtures have no generic specializations, so this
ordering change requires no portable expectation update. No manifest, accepted
artifact, baseline or frozen design reference was changed. Independent review
by performance_review recomputed the complete inventory and effective hashes,
confirmed all statuses and equalities, and verified the retained original tree
still equals the tracked fixture tree. No actionable blocker was found.

Full exact-tree gates, including bootstrap and the full C11 matrix, remain
pending. This bounded result closes the specialization-order reuse defect; it
does not close all G12 groundwork or Stage 9's analysis/journal counter, and no
benchmark improvement is claimed.
