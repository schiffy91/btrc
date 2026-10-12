# CoreAudio cleanup for disappeared aggregate devices

A failed aggregate-audio setup retained resources whose later cleanup queried
an aggregate that had already been destroyed. CoreAudio returned BadObject
(`!obj`), which the provider classified as a generic failure. The existing
missing-identity cleanup path therefore never ran, and Player's original
complete-shutdown assertion failed even after its playback journey completed.

The provider now maps the SDK's `kAudioHardwareBadObjectError` to the existing
`AUDIO_DEVICE_NOT_FOUND` outcome, alongside BadDevice. The Audio package selects
the SDK constant explicitly. `CoreAudioDeviceConfiguration.close` already clears
a missing object's pending restoration without writing to it. Cleanup order,
retry policy, all other status mappings and fatal unknown-disposal behavior are
unchanged. In particular, UnknownProperty (`who?`) is not remapped.

## Qualification

The test-only `e15b6944` adds scenario 14 to the existing ResourceFaults provider
and invokes the existing replaced-identity assertion. All four original
reference/self-host and plain/sanitized resource cells compiled and executed,
then failed the intended close-success/no-extra-writes assertion. There were no
setup errors or skips. Independent audit `58e77bd9` retains that RED result.

Candidate `d5430626` passes all 20 original CoreAudio SDK-fault cells: five
fixtures through both frontends, plain and sanitized. The self-hosted compiler
was freshly built from that exact tree. The original 240-second compile and
30-second native limits, fault cases and fatal-disposal controls are retained.
Result `64ad8214` and independent audit `a008421f` record zero failures, errors
or skips, unchanged source/tools, and no remaining process groups. Full hosted acceptance remains required.

The causal Player replay uses original product `10ed2b66`, the historical
reference compiler baseline `6f1b81d9`, and exactly the provider condition plus
its native binding. It passes the original real-ready mute 37→0→37 sequence,
both playing and paused part switches, all five captures, native exit zero and
the original final close state COMPLETE. Result `a6b58d04` and independent audit
`9ee94698` verify all seven process groups closed and private inputs unchanged.
This proves the repair against the retained failing journey; it does not claim
current-compiler/self-host Player, Linux, physical-device or full MVP acceptance.

## Retained failures and remaining work

The raw-status diagnostic `907c2378` records the aggregate-configuration failure
and three BadObject results. Its diagnostic logging is excluded from the repair.
The first fixed-Player attempt failed before native execution because the SDK
constant was not selected; result `e5f40992` and audit `11d3d709` remain intact.
The first 20-cell recipe stopped before build/tests on an audit-state spelling
mismatch; result `ff1d096c` and audit `c9333d7c` remain intact. Its corrected
recipe normalizes the audit-state spelling while preserving result/hash checks.

The current-compiler Player journey through both frontends, queued-action
cancellation, Linux qualification, full final gates and integration remain open.
The branch's last commit is the required native-binding `fragment:`; generated
files are untouched. Evidence is retained in the corresponding immutable
`~/.cache/btrc/plan-consolidation-2026-10-07/` attempt directories.
