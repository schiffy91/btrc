# Disappeared CoreAudio object reproduction

The existing resource fault provider gains scenario 14: its property read
returns the SDK constant `kAudioHardwareBadObjectError`. The existing
`replaced` case runs with that response after successful configuration and
requires successful cleanup without another property write. Its original
reset, identity-replacement and all other scenario assertions remain unchanged.

The SDK distinguishes an invalid AudioObject ID (`!obj`) from BadDevice. The
current status mapper recognizes only BadDevice as not found. This fixture
isolates the missing-object cleanup contract without changing production
mapping, native ownership, flags, providers or test driver selections.

Only the two insertion lines are executable changes. Formatting and source
preservation are checked; no compiler or native execution has occurred. The
original four reference/self-host and plain/sanitized resource rows must run
under their existing bounds. No behavioral RED is claimed yet, and this test
alone cannot identify the real Player shutdown OSStatus. Raw-status diagnostic
evidence remains a separate prerequisite for that causal claim.
