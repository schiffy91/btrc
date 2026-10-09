# Retain setjmp flow only for safety consumers

Status: reference behavior qualified; self-host and performance acceptance open.
Candidate `266cadd7` is based on `6f1b81d9`.

Module-unit solving previously retained each function's complete per-node flow
through optimization and emission. The final safety pass consults those facts
only for functions containing setjmp. Every function still needs a summary,
including ordinary callees that transmit changed effects across module groups.

Both solvers now accept a fixed, copied retention-root policy. The default
retains every flow for direct callers; an explicit empty set retains none.
Production module workers and the program-unit solver select all safety
consumers, including nested calls and array bounds. All pending functions are
still analyzed, and all summaries and consulted-dependency indexes are retained.
Python callers obtain summaries independently of returned flow contexts, so a
unit with no retained flows still exports its effects. New generations create
new solvers and policies. Whole-program analysis is unchanged.

The exact source tree has a hosted baseline of 131 related passing module-unit,
invalidation and exception checks, plus eight explicitly skipped native-adapter
checks. This is baseline evidence, not candidate qualification. Added Python
cases compare recursive effect propagation against the full-flow policy and use
weak references to test actual collection of non-root facts; they also check
copied root policy, empty roots, and three safety locations. The native driver
compares default, one-root and empty-root solves across an external-effect
change. Existing `test_an_effect_changing_edit_matches_a_clean_build` covers the
non-root Lib unit exporting changed effects through actual module compilation,
and must run through both frontends with worker/inline parity coverage.

Source review, Python AST/Ruff and BTR formatting checks pass. The original
compiler passes the production effect-changing edit baseline. Candidate `266cadd7` passes
the same edit and all six new Python cases, zero failures/errors/skips. These prove
actual collection of non-root facts and recursive summary propagation, while the
ordinary Lib unit still exports changed effects. The old-source API comparison
is not a behavioral RED. Independent audit confirms all eight groups reaped and
absent with exact source/tool/log closure. Result SHA-256:
`6dea8c023904bb7e0269b9f24318b7675d84652b92439039c5b89a048b49d02e`.

Fresh self-host compilation, both-frontend native driver execution, generated
ownership inspection, worker/continuation coverage, current-product output
parity and the final combined gate matrix remain required. Per-function flow construction remains; the change removes retention,
not analysis work. No measured memory or instruction saving is claimed.
