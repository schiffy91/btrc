# Realtime

Realtime clip playback, practice audio and the clocks that map between them.
Import each module by its own path; the group deliberately has **no facade
module**. Unlike `Library.Audio`, there is no platform choice to hide
behind one entry point: every module here is portable, and each is a separate
contract a consumer takes on only when it needs it. A facade would only re-export
these modules and widen every importer's visibility to all of them.

| Module | Owns |
| --- | --- |
| `Library.Realtime.RealtimeClock` | Immutable frame-rate, speed and clock-mapping values. |
| `Library.Realtime.RealtimeClipPractice` | Practice configuration, telemetry and captured-input values. |
| `Library.Realtime.RealtimeClipTransport` | The clip transport contract (`IRealtimeClipTransport`) and its preallocated implementation. |

## Threads and barriers

The control thread owns clips, transports and every managed value. A transport
lends its realtime callback through `realtimeProgram()` (a whole program for an
audio provider) or `renderer()` (a plain-data handle a composing `@realtime`
program passes to `RealtimeClipTransport.render`). Either loan ends at
`suspend()`, which is the transport's drain barrier: it closes callback
admission, waits for any render already inside, and only then returns
`REALTIME_CLIP_TRANSPORT_OK`. A render attempted after that writes silence and
touches no clip state. Stop invoking the transport before `close()`, which
frees the callback context.

A composing program, such as a player that mixes the transport with other
sources, renders the transport into scratch storage it owns and mixes from
there. It suspends the transport after its own provider has drained, so no
callback can still hold the handle when `close()` runs.

The clock snapshot is a sequence lock whose payload words are published with
release stores and read with acquire loads, so a reader either sees one
complete snapshot or retries.

## Package-private runtime

`RealtimeClipTransportRuntime.btrc` and `RealtimeClipPracticeRuntime.btrc` hold
the transport's callback mechanics: the plain-data context, its queues, and the
render loop. They are not exported, so a consumer outside this package cannot
import them or name their `Btrc*` context layout; `RealtimeClipTransport.btrc`
imports them by module path. A composing program uses `renderer()` and
`RealtimeClipTransport.render`, and drains with `suspend()`, as described above.
