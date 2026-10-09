# Retain setjmp flow only for safety consumers

Status: source candidate, not runtime-qualified. Base is `6f1b81d9`.

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

Source review is clear. Python AST and Ruff checks pass. The new cases have not
yet run; their old-source comparison is a missing API, not a behavioral RED.
Fresh self-host compilation, generated ownership inspection, focused semantics,
exact current-product output parity and the final combined gate matrix remain
required. Per-function flow construction remains; the change removes retention,
not analysis work. No measured memory or instruction saving is claimed.
