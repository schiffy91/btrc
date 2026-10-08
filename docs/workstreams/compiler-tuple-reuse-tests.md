# SB-28 tuple reuse fixtures

## Ownership and source

D29 assignment owns only `src/tests/python/test_module_unit_staleness.py` and
this report. Branch `codex/compiler-tuple-reuse-tests` starts at
`56d548c49ca027c9698c8546acdaf4df918630bd`. The separate token-lifetime branch
`codex/compiler-token-current` remains at
`fb6145b97945f8e9ee105a79d85290453122108b`.

No compiler, runtime, cache identity, generated source, or baseline changes.

## Outcomes asserted

The existing SB-D7 fixture adds `(double, int)` to Lib even though Use already
contains it. Canonical tuple ordering should make this discovery-order edit
lower only Lib. The strengthened test preserves source line count, covers
release and debug, requires exactly Lib's unit bytes to change, and retains
the existing complete incremental-versus-clean unit/diagnostic comparison.
The original function name remains stable for existing qualification selectors.

A separate case introduces the genuinely new `(int, int)` shape. Its element
type names already occur in the program, avoiding an unrelated mentioned-name
change. The fixture requires the concrete struct definition to be absent before
and present after the edit, exactly Lib's C bytes to change, and the current
conservative three-group lowering count. This does not claim per-unit shared
answer validation exists.

Both cases link and execute the retained cold and incremental C units through
the existing corpus multi-unit runner, with strict C11/pedantic/warning flags.
Exact golden output is `PASS 6` for the original program and discovery-order
edit, and `PASS 13` for the genuinely new shape. The new field is read in the
returned result. The test does not retranspile for its native assertion or
execute only the final clean build's files.

## Validation status and commands

Prepared source only while the integrator's compiler build owns the native
lane. No test, compiler, native build, or measurement was run for this packet.
The expected one-group result remains pending the integrator's current-source
paired qualification. No speed or memory improvement is claimed.

After source review and lane allocation, use the current-source qualified
binary through `BTRC_TEST_BTRCC` in the retained qualified environment:

```sh
python3 -m pytest -q --compilers=python,btrc \
  src/tests/python/test_module_unit_staleness.py::test_a_new_tuple_shape_in_one_body_keeps_other_units_exact \
  src/tests/python/test_module_unit_staleness.py::test_a_genuinely_new_tuple_shape_preserves_conservative_invalidation
```

Expected collection: eight rows (two cases, two build modes, two frontends),
with no skips. Each row retains the clean-build comparison and executes cold
and incremental units separately. Broader staleness, boundary and final-tree
qualification remain integrator-owned. A failure of the new counter or exact
unit assertions must be investigated, not relaxed to pass.

## First native qualification

At test source `45dfa41f`, the entire module completed 52 cases: 48 passed
and four failed. All four failures were the existing-shape fixture's newly
added strict native compile: its inserted tuple variable was unused. Both
compilers already passed the one-group counter, exact unaffected units and
incremental-versus-clean comparison. All four genuinely new-shape cases passed,
including strict native execution and conservative three-group invalidation.

The fixture now obtains the same integer from `flag._1` when creating `pair`.
This consumes the inserted tuple while preserving source line count, discovery
order, expected output and every assertion. The original failed result is
retained in `tuple-canonical-order/45dfa41f-reuse/`; the four affected rows need
a separate replay. No compiler change or warning suppression was added.

The first correction at `1f9d670b` exposed a separate conservative guard:
reading the previously declaration-only name `flag` adds a whole-program
mentioned identifier and invalidates all three groups. Both frontends kept
exact incremental output; all four counter expectations failed at three.
Independent tracing located this in the retained reachability `plan.names`
inputs, not tuple ordering. The discovery-order fixture now uses the local
name `left`, already referenced in `Use`, so its edit changes neither the
shape inventory nor the program's mentioned-name set. It still reads the
inserted tuple, keeps the same source lines and requires one lowered group,
unchanged other units, exact clean output and strict native execution.
The separate invalidation guard remains unchanged. Both failed attempts are retained.

The isolated existing-shape fixture at `dcf8ba88` passes all four paired
release/debug native rows (16.907 s): one lowered group, only Lib changed,
incremental equals clean, and both cold/edited executables print `PASS 6`.
The genuinely new `(int,int)` fixture also uses the already-mentioned local
name `left`; its conservative three-group result must depend on the changed
shape inventory rather than accidentally also adding a mentioned identifier.
Its four affected rows are replayed separately with output 6 then 13 unchanged.
