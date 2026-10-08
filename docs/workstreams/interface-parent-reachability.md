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

## Remaining acceptance

A fresh source-matched Linux self-hosted compiler build is running. Its paired
regression must pass before rerunning Grid04, the genuine fixture-only negative
controls and the remaining 96 reconstructed provider cases. Private qualification
composites retain each original provider revision, overlay the reviewed compiler
and current caller tooling, and record exact source inventories; original archives
and the old compiler binary remain intact. Full final-tree bootstrap, strict C11,
normal test matrix and hosted gates remain required before main integration.
No compiler performance improvement or native Grid success is claimed here.
