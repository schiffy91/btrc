# CX-UIA-21: approved UI2 interface implementation

Owned paths are the interface, facade, completion-hook, portable fixture and
catalog paths in `docs/design/ui-contracts/ui2-approved.md` (Landing), as listed
in the draft PR. Provider implementations remain in the stacked CX-UIA-22/23
packets and land atomically with this interface.

The integrator extended this packet's ownership to
`src/tests/python/test_ui0_catalog.py` for the isolated amendment/source fixture
repair discovered by the UI2 qualification gate.

Base: `87dd60d7`. Implement the approved record; do not restart its design review.
No compiler prerequisite blocks the approved interface. The interface by itself
does not qualify the existing platform providers.

Acceptance: exact approved source surface, portable E-case fixtures, completion
hook contract/regression, formatting and catalog validation. Combined macOS/Linux
provider and repository acceptance remains mandatory before main landing.
No implementation or test pass is claimed by this claim commit.

## Implementation checkpoint (2026-10-07)

The approved 53 new operations and owning values are implemented in the portable
interfaces and GUI facade. Existing signatures retain their catalog identities;
comments record changed UI2 behavior. The facade wraps host attachment lifetime
so completed detach closes its application and clears its slot. Scope admission
precedes native attachment publication. Native provider implementations are
untouched and must stack before any interface landing on main.

The completion hook uses a bounded nonthrowing native function pointer with a
borrowed raw context and a ready-level bool. Queue synchronization covers terminal
publication, draining, late registration and retirement. Cancellation seals
admission and reports pending until the native wake returns. Review found that
old registrations could regress from COMPLETE to PENDING while a replacement
held the queue mutex; cancellation status is now sticky, with explicit retry for
RETRYABLE_FAILURE. The real-worker regression includes that interleaving, late
subscription, partial drain, duplicate subscription rejection and executor close.
The hook never transfers managed completions to workers.

Portable test modules cover shared assertions for E01–E04, E29, E31, E35, E39,
E40 and E46, the two-axis scroll contract and the injected host-suspension
journey. Their README enumerates the additional real native probes, faults,
timing, resource and hardware rows needed from the provider packets. These
fixtures alone do not qualify an E-case or platform.

### Checks actually performed

- Parsed the interface, facade and hook sources with the current reference parser.
- Canonical formatter write/check on the changed BTRC files and portable fixtures.
- `python3 -m tools.qualification.ui_catalog check`: passed; frozen operation
  slots remain 1,620, cases 470 and family cells 300. Pending operations are
  70 IDs / 700 slots. No missing or undeclared catalog slots.
- Invoked `verify_surface(sources())` and
  `test_surface_counts_explain_the_frozen_release_delta()` directly from
  `src.tests.python.test_ui0_catalog` with the qualified Python environment:
  passed after correcting the amendment's `long long treeRevision()` spelling.
- `git diff --check`: passed.

These are static checks. No transpilation, native execution, sanitizer, full
pytest or provider result is claimed. System Python lacks pytest, so the direct
source/count checks used the parent's qualified Python 3.14.6 environment.

### Scheduled validation

The integrator selects source-matched compilers and runs from a clone outside
Drive under the gate lock, with the qualified dev environment and native SDK
configuration:

```sh
python3 -m pytest -q src/tests/python/test_background_jobs_runtime.py::test_completion_ready_subscription src/tests/python/test_background_jobs_runtime.py::test_completion_ready_explicit_retry --compilers=both
python3 -m pytest -q src/tests/python/test_background_jobs_runtime.py --compilers=both
python3 -m pytest -q src/tests/python/test_ui0_catalog.py
python3 -m tools.qualification.ui_catalog check
```

The first command collects eight cases: two regressions, both compilers and plain/sanitized variants. Existing
BackgroundJobs conformance and failure-recovery checks cover the changed queue
path. CX-UIA-22/23 must admit the portable GUI fixture modules through their real
native drivers and complete the approved plain/sanitized E-case matrix. This
interface branch deliberately cannot qualify unimplemented providers by itself.

### Integrator fragments

Catalog operation shards and `amendments/cx-uia-21.toml` are a separate final
`fragment:` commit. It adds 53 pending IDs, records all cells as missing/unavailable,
and annotates the 51 changed IDs without erasing prior evidence. Prior evidence
covers old semantics, not the expanded UI2 contract.

Apply these additional hunks at CL-UIA-14, without changing frozen IDs:

1. Add `"ControlEvents"` to `src/stdlib/GUI/btrc.toml`'s package exports.
2. Add `"UI2"` to E01–E04 links in `cases/E01-E24.toml` and E42/E46 links
   in `cases/E25-E47.toml`. Add the completion-ready regression to E04.
3. Extend E42 owner text with UI2 (`UI1/UI2/UI5/UI9`) and E46 with UI2
   (`UI1/UI2/UI3/UI5/UI7`), including their native-ui-parity.md rows.
4. No `surface/GUIModules.toml` exists at this base. Its owner must account for
   the 15 `ControlEvents` symbols as family/UI2, plus classify the facade's
   package-private `GUIHostAttachment` lifecycle adapter. Do not claim strict
   surface coverage from the catalog check above.
5. Regenerate exports/lock/symbol/catalog artifacts in the integrator's derived
   commit. This branch never hand-edits generated files.

### Pilot time categories

- Inspection began before the first source edit; no reliable start timestamp was
  captured, so no elapsed inspection estimate is claimed.
- First implementation artifact: 2026-10-07T16:21:52Z. Hook artifact:
  16:23:44Z; catalog artifact: 16:26:27Z (retained scratch-file timestamps).
- Implementation and review/rework overlapped. The independent completion-hook
  reviewer identified sticky cancellation and explicit-retry requirements;
  both were incorporated before source freeze.
- Local static checks ran during implementation. No heavy build or native gate
  ran in this lane; the main session owned the host queue. Native qualification
  is pending, not idle time retrospectively counted as completed testing.
- No source recovery or environment rebuild was needed for this interface packet.

Source freeze: 2026-10-07T16:43:25.270020+00:00; native qualification remains pending.


### Explicit native retry regression follow-up

The final hook reviewer confirmed the sticky COMPLETE and RETRYABLE_FAILURE
source fixes, then identified missing deterministic error-path coverage. The
parent authorized extending the existing test-only NativeThreadFaults header,
control enum and C interceptor. `CompletionReadyRetry.btrc` now injects EINVAL
on exactly one trylock call; three polls must keep RETRYABLE_FAILURE without
calling native retirement, while explicit cancel retries and completes. Later
cancel/poll calls must keep COMPLETE without another trylock. The corresponding
pytest case uses the real worker executor and existing native-binding package,
with both frontends and plain/sanitized variants. No production source or
runtime hook was changed by this follow-up. Native execution remains pending.

The unpushed pre-reorder branch tip is retained by the local recovery tag
`archive/cx-uia-21-before-retry-reorder`; the catalog fragment remains the final
commit after the new test commit. The tag is local and was not pushed.

### Parent qualification and catalog fixture repair

The parent-owned gate 49797 qualified source `06a4806f`: all 26 BackgroundJobs
native cases passed, including both frontends and plain/sanitized completion
subscription and explicit-retry regressions (377.04 seconds). Evidence is under
`~/.cache/btrc/plan-consolidation-2026-10-07/subagent-delivery/ui2/06a4806f/`:
`background-jobs.xml`, `catalog.xml`, and `qualify.log`.

The catalog run passed 113 cases and failed one in 30.36 seconds. The failed
test paired live expanded GUI sources with a temporary catalog that omitted all
per-packet amendments. Its isolated setup now copies those amendments and proves
the unmodified source baseline before exercising its synthetic inheritance,
nullable/default, signature-change and removal mutations. The sparse fixtures
used by other catalog tests and the real source/count/denominator gates remain
unchanged. This follow-up changes only that test and this report; production,
compiler and native regression sources remain identical to the qualified tree.
After integrator review, the full catalog file passed all 114 tests in 30.732
seconds, with no failures, errors or skips (`catalog-fixture-repair.xml` in the
same evidence directory). `tools.qualification.ui_catalog check` passed with the
unchanged frozen/pending counts above. Ruff 0.15.14 lint and format checks on the
changed test, plus `git diff --check`, passed. Qualified Python has no Ruff
module, so those checks used the installed Nix Ruff binary directly. No native
rerun is needed for this test/report-only delta.

This is qualification/rework time, following the earlier source freeze, rather
than new provider implementation. The parent owns the measured test durations;
no local heavy run was performed by this packet agent.
