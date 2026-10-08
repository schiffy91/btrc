# Single module-body emission

Packet: CX-HARMONIZE follow-up, `codex/module-emission-once`, based on
`3974d47bc87851b1ac19b8d2b4bd5022f2d94676`. The parent integrator owns the
reservation in WORKSTREAMS.md. PR68 stays frozen at `00e45379`; this source
change is unpublished and does not qualify or replace that candidate.

## Product objective and evidence

Reduce repeated compiler work on real module builds while preserving exact
emitted C and native behavior. The current-product stack profile identified
two complete formatting traversals when native include selection emitted a
draft and the worker immediately emitted the final unit. The profile is
attribution only; it establishes no accepted speedup or memory reduction.

Before implementation, the original compiler and reference source passed all
18 selected declaration, debug mapping, directive-order, native adapter and
module-unit checks with no skips/errors. The exact collected identities match
JUnit. Evidence is `duplicate-emission-baseline-3974-attempt-3/result.json`,
SHA-256 `486f06e71d7f3b53144825cc5148e467e6801b4b048262fd9c3662eedff55f78`.
All 17 owned process groups closed and inputs remained unchanged. Two earlier
preflight attempts stopped before testing because host tools inherited the
retained compiler shell's PATH/SDK settings; both failed receipts are retained.
Native fixture tools use their existing Apple environment selection. The
baseline version probes inheriting the Nix SDK are not Apple-Clang evidence.

## Change and invariants

Both existing emitter owners prepare an immutable, local body snapshot with
its preprocessor insertion position and formatting flags. Each draft/final
render composes fresh lines before resolving generated-source line numbers.
The snapshot retains neither an IR graph nor an emitter, and is never cached
across requests. Existing one-shot emit APIs use the same formatter.

The shared declaration owner still omits native headers before draft
validation, scans the complete rendered draft for identifiers, retains unknown
headers and preserves directive order. It returns the prepared body only when
a draft was required. The worker repeats the existing full reference verifier
or self-hosted type planner before rendering the final unit. Units with no
native include keep the original single validation and body traversal.

Root implemented the two Python owners and regression tests; performance_review
implemented the two self-hosted owners. execution_review independently cleared
the four production files and six new regression cases. Python lint/format,
BTRC format and diff whitespace checks pass.

## Qualification still required

The first CatalogMain counterfactual unexpectedly passed on unchanged3974:
its plain C include supplied no native binding metadata, so it never exercised
header pruning. That result remains retained as an invalid-regression result
(`module-emission-once/counterfactual/result.json`, SHA prefix6143e8f4); no
candidate tests or build followed it. The corrected regression uses the existing
actual CoreFoundation binding fixture, public compiler API at one worker,
registered native include selection, and strict native compile/run. It must
still demonstrate repeated formatting on the baseline and one traversal on the
candidate. Its non-macOS skip is already classified by the existing
`native-reader-macos-only` manifest rule for this module, with hosted macOS as
the counterpart. No manifest, denominator, marker or provider requirement is
weakened. The other
new cases cover independent release/debug layouts, reused emitter state, final
IR validation, freestanding prologues, macro-only header demand and unknown
headers. Run these and the original affected checks, rebuild the candidate
self-hosted compiler, then prove paired native links and exact current-product
C/header parity. Preserve the original workload and bounds.

The immutable snapshot adds a tuple/vector copy to ordinary emission. Net wall,
instruction and peak-memory effects remain unmeasured and may be unfavorable.
Quiet paired product measurements and the complete final matrix are required
before integration or any performance acceptance claim. The overall PLAN.md
compiler speed/memory and platform/MVP goals remain open.
