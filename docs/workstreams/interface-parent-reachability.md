# Inherited stdlib interface signatures survive reachability pruning

Source repair: `808592c9735bd012fbde0dfd000ac8a72911de97`.
Fixture-only checkpoint: `72be5947`. Base: `ab494fad`, containing frozen
integration candidate `71a22734` plus status documentation. Main is unchanged.

## Product failure and ownership

Actual Linux Grid04 qualification failed all four plain/sanitized, reference/
self-hosted rows before executing native behavior. Generated signatures inherited
from `IApplication` named types such as `IButton`, `IStack` and `IGPUView` whose
declarations had been pruned. Current integration source `71a22734` reproduces
the same failure with the pinned Linux reader/provider environment.

Both `StdlibReachability` owners collected class parents and interfaces but
omitted `InterfaceDecl.parent`. Generic child traversal intentionally does not
traverse scalar names. The analyzer's inherited method signatures therefore
outlived the declarations they referenced. The repair adds that one dependency
edge in each compiler; the existing worklist closes it transitively. No emitter,
generated-source, interface contract or retain-everything fallback changes.

## Regression and independent review

The closure regression reaches a three-level interface chain, return and
parameter types while proving an unrelated interface remains pruned. The paired
program uses a custom stdlib root, invokes only a leaf-specific method and still
requires inherited signature types to compile. Each frontend's emitted C is
compiled with C11, pedantic errors and warnings as errors at `-O2`; the executable
must return success from the leaf method's actual result.

The fixture-only tree produces **3 failures, 8 passes**: one closure failure and
one strict-C failure per frontend. The repaired reference path produces **10
passes**, with only the self-host case deliberately deselected pending rebuild.
Ruff, Python/BTRC formatting and diff checks pass. Independent source review by
`performance_review` found no blocker, no coverage weakening and matching paired
ownership. That review is source evidence, not native qualification.

Evidence root: `~/.cache/btrc/plan-consolidation-2026-10-07/interface-parent-reachability/`.
`baseline.log`/`baseline.xml` preserve the fixture-only result;
`reference-green.log`/`reference-green.xml` preserve the reference result.
The original Linux failure remains in
`linux-provider-native-2202-grid47/rows/grid-green/`, and current-source diagnosis
in that evidence root's `diagnostic-current/`.

## Linux source-matched qualification

The fresh `808592c9` compiler build passes on native Linux ARM64 with GCC 15.2
at `-O2`. Binary SHA-256:
`1739f6b16838694fa52297379f431777238ed8a01ec24577fc51ca7d9b07c505`.
The immutable image, native reader and shell are unchanged from the first
attempt. The existing Linux LP64 target-row equality check and paired functional
baseline pass. All **11 compiler regression rows pass with zero skips** (3.207
seconds), including reference/self-hosted strict-C compilation and execution.

The same binary then runs all **four Grid04 native rows successfully**, zero
skips (129.72 seconds). Both compilers, plain and ASan/UBSan, execute actual
rendering, rejected-child pixel/identity preservation and ownership assertions.
The original four strict-C failures remain retained, with no assertion weakened.

Evidence is under `linux-provider-native-2202-grid47/repaired-808592c9/`:
`compiler-build.json`, `native-elf.json`, `admission-sequence.json` and per-row
logs/XML. Exact source inventories identify each original provider revision and
the reviewed compiler/current caller-tooling overlay. Original source archives
and compiler binary are untouched. The host remains Apple M1 Max, 8P+2E, 64 GiB,
macOS 27.0; execution is in its actual Linux AArch64 guest. This is not native
x86-64, macOS or physical-device evidence.

## Remaining acceptance

Genuine Grid fixture-only negative controls and the remaining 96 reconstructed
provider cases still need execution. Full final-tree bootstrap, strict C11,
normal test matrix and hosted gates remain required before main integration.
No compiler performance improvement or complete platform qualification is claimed.
