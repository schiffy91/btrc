# CoreAudio cleanup status diagnostic

This private diagnostic starts at `6f1b81d9`; its original macOS audio provider
bytes also match `5be08004`. The e772 Player replay returned status 9 from
provider cleanup three times and retained a failed setup through output-only
fallback. The native operation and raw OSStatus are not yet known.

The existing status mapper prints each nonzero input once, in decimal and
hexadecimal, then executes its original mapping unchanged. The session-resource
close owner labels unsuccessful unit, aggregate, aggregate-configuration,
input and output cleanup using the statuses already returned by the original
calls. Both input/output results are observed before their existing priority
returns. No additional native calls, retries, state transitions or cleanup
ordering changes are introduced; this is not a proposed production repair.

Removing only the diagnostic lines recovers the original provider byte for
byte. Formatting is checked before freezing. No compiler or native execution
has been performed. A reference-only replay must use this exact stdlib delta;
the historical self-host binary must not be treated as containing it. All
original failure, pending and indeterminate outcomes remain unchanged. This
packet and diagnostic product ancestry are excluded from product integration.
