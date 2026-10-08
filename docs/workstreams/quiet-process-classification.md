# Quiet process classification: idle infrastructure versus active work

Branch: `codex/quiet-process-classification`, based on
`dff538ef502f4a074c3019f677220810e4061225`.
The parent assigned this bounded repair on 2026-10-08. The released
`codex/plan-status-refresh` branch remains at `404a5a6b`.

Owned paths:

- `tools/runbook/quiet.py`
- `src/tests/python/test_quiet_check.py`
- This report.

## Reproduced admission problem

The parent's first strict token-lifetime diagnostic attempted the unchanged
60-second quiet window with a 180-second deadline. It admitted no measurement:
the process rules classified an idle Apple SimulatorTrampoline XPC service and
an idle bundled Codex exec-server transport as active simulator/agent work.
The failed attempt remains evidence; this packet does not relabel it successful.

Read-only process inspection confirmed the exact Apple XPC executable, no
arguments, PPID 1 and zero reported CPU. The bundled transport's argv shape was
`exec-server --remote VALUE --environment-id VALUE`, with the desktop app as its
parent and zero reported CPU. Its full process tree had no descendants. A
read-only `simctl list devices --json` returned 13 devices, all `Shutdown`.
No service was killed, no device was changed, and no system setting was edited.
The temporary mds reading above 5% was a real blocker, not a classifier defect.

## Correction and boundaries

Only the exact trusted Apple executable/arguments/launchd parent or the exact
bundled transport executable/argument grammar/desktop parent/same user can be
recognized as infrastructure. Recognition alone grants no exemption: reported
CPU must be exactly zero and every foreign descendant must be absent. Arbitrary
shell, Python, sleep, and grep work blocks even if it matches no named build
rule. Parent identity and descendant relationships use one unfiltered process
snapshot, so this runner's ancestry filtering cannot erase evidence of an
unrelated job. Ancestral transports are also checked for foreign sibling work.
Only the existing own ancestry and direct probe child exclusions apply; sharing
a wrapper does not excuse other work beneath it.

The exception applies solely to the corresponding original default
agent/simulator rule. Explicit additional or replacement process rules still
block these services. Ordinary CLI agents, lookalike paths/arguments, nonzero
service CPU, Simulator, launchd_sim, builds and guests retain their blockers.
There is no new ignore expression and no threshold/configuration change.

A separate default macOS probe reads the complete simctl devices inventory on
**every sample**. It validates the container/runtime/device schema, mandatory
name/UDID/state/availability types, and unique device identities, including
unavailable devices. Every state must be exactly `Shutdown`. Missing command,
failed command, invalid JSON/schema, duplicate identities, unknown states,
Booting and Booted all fail closed. A valid empty inventory reports zero devices;
a malformed or absent inventory does not count as an empty one.

The full 60-second window, 5-second sample interval, and existing 5% background
CPU limits are unchanged. A device becoming active resets the quiet window.
The normal macOS probe is read-only; other hosts report it as not required.

This establishes local process idleness only. A childless transport does not
prove that remote or in-process jobs are absent. The parent must retain the
explicit no-other-active-jobs scheduling barrier for the entire measurement.
A measurement wrapper that itself leaves a foreign helper beneath a recognized
transport may conservatively block; this repair does not excuse that helper.

## Verification

Qualified retained Python:
`/nix/store/35r726j0hx21698i9p7ry53l1afprc84-python3-3.14.6-env/bin/python3`.

`PYTHONDONTWRITEBYTECODE=1 BTRC_TEST_RUNNER=macos <python> -m pytest -q
src/tests/python/test_quiet_check.py
--basetemp=/private/tmp/btrc-audit-repair/quiet-classification-pytest-2`

Result: **92 passed in 0.56 s**. The earlier 89-test draft passed in 0.59 s;
independent review then found a too-broad own-wrapper subtree exception, which
was removed and covered by three additional sibling-job cases. The focused
module also retains all previous agent/build/guest and CPU threshold tests.
New tests cover exact idle services, parent identity surviving ancestry
filtering, arbitrary nested descendants and wrapper siblings, busy/disguised
services, explicit stricter rules, malformed/failed device listings, unavailable
active devices, and a Booting observation forcing a new full 60-second window.
Its existing real-probe test remains report-only, not a successful quiet round.

Ruff lint/format and `git diff --check` pass. No native builds, compiler rebuilds,
guests, benchmark samples, full matrix, publication, or performance acceptance
were performed by this packet. Before retrying the diagnostic, pin this harness
revision separately from the unchanged dff/69ca compiler source snapshots and
retain both the failed original attempt and the new probe provenance.

## Follow-up: keep host simulator lookup out of the compiler SDK

The next diagnostic attempt ended with zero samples. Its retained BTRSmith
shell exports `DEVELOPER_DIR` and `SDKROOT` for the pinned Nix Apple SDK14.4.
The simulator probe already used `/usr/bin/xcrun`; changing its executable path
would not repair this failure. In that exact shell, the absolute host executable
still inherited the SDK redirect and exited1 without finding simctl.

Only the simctl subprocess now receives a copied environment with
`DEVELOPER_DIR`, `SDKROOT` and `TOOLCHAINS` removed, allowing the host's selected
installed Xcode to supply its simulator tool. `CommandRunner.output` accepts an
optional per-command environment; all ordinary calls continue inheriting the
original environment. Neither `os.environ`, the compiler SDK settings, the
selected Xcode, nor any system configuration is changed. Command/listing/schema
failures remain blockers.

A new process-boundary regression failed against bc685ed7 because no isolated
environment reached subprocess.run. It then passed with the correction and
checks the exact absolute command, removal of all three redirect variables,
preservation of unrelated variables, unchanged parent environment, and ordinary
commands continuing to inherit their original environment. Full focused result:
**93 passed in0.56s**; Ruff lint/format and diff checks pass.

A single read-only reproduction inside the retained BTRSmith shell recorded:
unisolated absolute xcrun exit1; corrected real SimulatorProbe reports
**13 devices, all Shutdown**; all three parent environment values remain
unchanged. Evidence is retained at
`~/.cache/btrc/plan-consolidation-2026-10-07/quiet-simctl-environment/result.json`
and its adjacent probe.py. This is host-probe evidence, not a completed quiet
window or compiler measurement. The failed diagnostic remains retained.
