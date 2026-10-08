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

## Focused qualification

The first CatalogMain counterfactual unexpectedly passed on unchanged3974:
its plain C include supplied no native binding metadata, so it never exercised
header pruning. That result remains retained as an invalid-regression result
(`module-emission-once/counterfactual/result.json`, SHA prefix6143e8f4); no
candidate tests or build followed it. The next attempt successfully transpiled
the actual CoreFoundation binding but failed its bare-header assertion: the
native reader preserves the resolved absolute header path. That failed receipt
is retained at `module-emission-once-r2/counterfactual/result.json`, SHA-256
`e0d26c7fe3a8a0be94ce22d661869d6f043142c9187075eb110e0d305d017e60`.
Fixture-only `660ac18d` checks that resolved identity. Production remains
identical to `72357bac`.

Fresh R3 qualification now passes. The unchanged `3974d47b` compiler, with only
the corrected test overlaid, fails the intended traversal assertion: both
observed source functions are formatted twice instead of once. Compilation
reaches successful transpilation and header-selection assertions before that
failure; the old control does not reach the following native C build/run.
The candidate passes all 18 reference checks (six new and 12 existing), including
one traversal and the strict native build/run. The original MacOSMain build
with Nix Clang 21.1.8 at `-O2` succeeds within its unchanged 1800-second bound.
The fresh self-hosted binary then passes the original 18 paired checks.
Both test sets have zero failures, errors or skips and exact collected/JUnit
identity agreement. Independent review verifies source/tool closure and all
42 recorded process groups reaped and absent.

Evidence under `module-emission-once-r3/`:

| Receipt | SHA-256 |
|---|---|
| `counterfactual/result.json` | `2327cf60538dd5cf9431fcb251eb5ea650f4bc2adc4803ca1fe5f04442b90dc5` |
| `reference/result.json` | `f5bc22e9b3d6b77278274a2d2cb2fa64dd4c8c114f3b1fdb014ea66e4e382ee8` |
| `candidate-build/result.json` | `edb08b87c2b22a07589ea6afafc4c0fd2367dd6e82e62fd30ffd859a2280cbcc` |
| `paired/result.json` | `052063121c3f1553208f9076d0da158399de5301abcf658c982bda2c8efd13d3` |

The tested source is `660ac18dbc618c03f43525efda91fc6548c78e85`; its binary has
SHA-256 `181e0d52ebe87396427155304f4bdd42b9f685e718aff06bbee352e8943f6625`.

The regression's non-macOS skip is already classified by the existing
`native-reader-macos-only` manifest rule for this module, with hosted macOS as
the counterpart. No manifest, denominator, marker or provider requirement is
weakened. The other new cases cover independent release/debug layouts, reused
emitter state, final IR validation, freestanding prologues, macro-only header
demand and unknown headers.

## Qualification still required

Exact current-product parity across all 423 generated C/header files is next.
Preserve the original workload and 240-second compile bound. The focused native
and paired checks do not replace that product proof or the full final matrix.

The immutable snapshot adds a tuple/vector copy to ordinary emission. Net wall,
instruction and peak-memory effects remain unmeasured and may be unfavorable.
Quiet paired product measurements and the complete final matrix are required
before integration or any performance acceptance claim. The overall PLAN.md
compiler speed/memory and platform/MVP goals remain open.
