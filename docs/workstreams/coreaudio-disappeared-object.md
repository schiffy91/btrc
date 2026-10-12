# Disappeared CoreAudio object reproduction

The existing resource fault provider gains scenario 14: its property read
returns the SDK constant `kAudioHardwareBadObjectError`. The existing
`replaced` case runs with that response after successful configuration and
requires successful cleanup without another property write. Its original
reset, identity-replacement and all other scenario assertions remain unchanged.

The SDK distinguishes an invalid AudioObject ID (`!obj`) from BadDevice. The
baseline `5be08004` status mapper recognizes only BadDevice as not found. This fixture
isolates the missing-object cleanup contract without changing production
mapping, native ownership, flags, providers or test driver selections.

In the test-only reproduction, only the two insertion lines are executable changes. Formatting and source
preservation are checked; no compiler or native execution has occurred. The
original four reference/self-host and plain/sanitized resource rows must run
under their existing bounds. No behavioral RED is claimed yet, and this test
alone cannot identify the real Player shutdown OSStatus. Raw-status diagnostic
evidence remains a separate prerequisite for that causal claim.

## Minimal candidate

The production candidate maps `kAudioHardwareBadObjectError` alongside
`kAudioHardwareBadDeviceError` to the existing `AUDIO_DEVICE_NOT_FOUND` result.
The SDK describes BadObject as an ID that does not map to an AudioObject.
`CoreAudioDeviceConfiguration.close` already owns the terminal missing-identity
case and avoids restoring properties on that object; this change allows that
existing behavior to handle the SDK's distinct invalid-object status.

Only this mapper condition changes. Cleanup order, retry behavior, all other
status mappings and every fixture byte remain unchanged. The test-only
`e15b6944` ref and raw-status diagnostic ref remain separate and intact. Source
preservation and formatting are checked; no behavioral baseline/candidate run
or Player root-cause proof is claimed. Native qualification must preserve the
original four paired plain/sanitized resource rows and all fault scenarios.
