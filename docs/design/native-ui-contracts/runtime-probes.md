# P6 runtime counter and trace pre-draft

Status: draft under D27, not approved

Packet: **CX-UIB-05**. Source baseline:
`f4317455de1e567d4d6290139e5ba28fbada7d0c`.
This proposes a single counter/trace contract for UI9 and P6. CX-UIB-37 builds
the portable probe owner, CX-UIB-38/39 add desktop/mobile providers, and
CL-UIB-13 owns any analyzer/interop requests. The plan is not implemented or
measured by this document. [UI9 GPU](ui9-gpu.md) specifies its presentation,
capture, artwork and shaping consumers.

## Source of metric truth

The runtime acceptance table in [platform-parity P6](../platform-parity.md#p6--numeric-build-and-runtime-acceptance)
defines **11 rows**, all mapped below. The fixed workload is **10,000 songs /
1,000 albums**, named artwork assets and a pinned chart/audio fixture; a larger
existing product fixture or stricter budget remains binding. Import/scanning
is separate from a pre-indexed launch. Build/compiler P6 metrics remain with
the build measurement tools; this is the runtime probe surface.

| P6 runtime row | Proposed metric ids and measurement boundaries | Required acceptance |
|---|---|---|
| Pre-indexed cold launch to interactive Library | `runtime.launch.interactive`: process-launch marker to first presented Library that accepts a test interaction; record indexing state and checkpoint/restore work. | p95 ≤3 s desktop / ≤4 s mobile, **20 launches**. |
| Local catalog search/filter to visible result | `runtime.search.visible`, `runtime.search.debounce`: triggering native input → committed visible result, and debounce start → expiry separately. Generation must identify the displayed query result. | p95 ≤100 ms **after separately reported debounce**, ≥100 action samples. |
| Visible navigation/button response | `runtime.navigation.visible`: native input → presented destination/response; explicitly pending I/O interval recorded, never silently removed. | p95 ≤100 ms, ≥100 samples. |
| Library scroll and Player at 60 Hz | `runtime.frame.interval`, `runtime.frame.missed`, `runtime.frame.longestStall`: actual presentation sequence and expected display opportunities. | **10 min**, p95 ≤16.7 ms, p99 ≤33.3 ms; missed presents and longest stall reported. |
| Steady product working set | `runtime.memory.aggregate` plus CPU/native/GPU components and measurement coverage. | ≤512 MiB desktop / ≤384 MiB mobile; native/GPU accounted separately and included without double counting. |
| Repeated lifecycle ownership | `runtime.lifecycle.liveHandles`, `.liveRegistrations`, `.memoryGrowth`: before warmup/after settle per cycle, plus acquired/released counts. | **100** open/close/route-change/recreate cycles; zero leaked live handles/callback owners; settled growth ≤5% after warmup. |
| Controlled audio soak | `runtime.audio.xruns`, `.dropouts`: native/provider counter deltas and attributed cause during controlled UI/audio workload. | **30 min**, zero app-induced xruns/dropouts; **2 h physical release soak** separate. |
| Realtime callback execution | `runtime.audio.callbackPeriodPercent`: callback exit−entry divided by the **negotiated current buffer period**, not requested settings. | p99 ≤50%, p99.9 ≤75%; zero forbidden allocation/blocking paths. |
| Wired instrument round-trip latency | `runtime.audio.wiredRoundTrip`: physical loopback/input-output observations with sample rate, actual buffers, interface and method. | p95 ≤20 ms Windows/iOS; ≤30 ms Android. Mac/Linux retain their applicable product/reference goals. |
| Ordinary graceful close/drain | `runtime.close.drain`: authorized close starts → final owned callbacks/resources drained. Prompt/save decision latency is a separate component. | p95 ≤2 s; zero late callback use-after-free; terminal failure explicit. |
| Pause/resume/permission/route recovery | `runtime.recovery.duration` and `.crash`, `.duplicatePlayback`, `.lostDurableState`: lifecycle request/notification → usable recovery, with cause/route generation. | **100 scripted cycles**, zero crashes, duplicate playback or lost durable state; report recovery duration separately. |

The loopback row consumes an external physical measurement; no software counter
can manufacture it from callback duration. Bluetooth and emulator audio are
separate experiments. A missing endpoint, unsupported provider or absent
hardware remains missing/unavailable evidence rather than a zero-latency sample.

UI9/UI6 add diagnostics under the same owner, not another instrumentation stack:

| Metric ids | Meaning and minimum reporting |
|---|---|
| `ui.input.received`, `.delivered`, `.modelUpdated`, `.presented` | Correlated monotonic timestamps per action/window/generation, with debounce and I/O separately attributed (E32). |
| `ui.frame.invalidations`, `.layoutPasses`, `.paintPasses`, `.presentationAttempts` | Counts distinguish requested work from compositor redisplay; known non-presentable idle has 0 presentation attempts for 60 s (E42). |
| `ui.idle.cpuPercent`, `.wakeups` | CPU as percent of one core over 60 s, ≤1% in static idle; record assistive technology on/off and excluded active animations. |
| `ui.artwork.bytes`, `.decodeJobs`, `.trimDuration` | Decoded/staging/native/GPU/retiring categories, distinct allocations, peak/live bytes, ≤2 jobs, 128/64 MiB desktop/mobile, trim ≤1 s for eligible unused entries (E36). |
| `ui.collection.cells`, `.pinnedCells`, `.rebinds`, `.visibleCapacity` | Native owners ≤3× maximum visible viewport capacity for the run +≤2 explicit editor/focus pins; report after viewport shrink. Unchanged presentation has 0 rebinds. |
| `ui.presentation.retry`, `.failure`, `.restoreDuration` | ≤10 attempts/s, 5 s failure deadline, 1 s post-readiness recovery; scope and device generation (E43). |
| `ui.capture.duration`, `.bytes`, `.outcome` | Subtree/frame identity and bounded preparation/composition; offscreen capture is not an actual presentation timestamp (E38). |
| `ui.owner.acquire`, `.release`, `.pendingCleanup`, `.lateCallback` | Stable resource/registration identity and generation, executor affinity, terminal cleanup counts; never infer release from a dropped managed reference. |

## One bounded probe owner

Proposed **RuntimeProbe** owns preallocated per-producer counter banks and trace
rings. Instrumentation sites use fixed numeric metric/event ids and preassigned
owner/generation ids. Strings, stack traces, JSON, filesystem writes and ledger
serialization happen on an ordinary reporting worker after collection.

```btrc
// Illustrative proposed operations; exact value/annotation shape is reviewed.
bool recordEvent(ProbeEvent event);
void addCounter(int counterId, long long delta);
ProbeSnapshot snapshot();
ProbeExportResult exportSnapshot(ProbeSnapshot snapshot);
```

`ProbeEvent` has event id, raw timestamp/clock id, producer sequence, owner,
generation, correlation id and fixed numeric payload fields. Names and metadata
are registered before the measured interval. No dynamic callback, reference
counted payload or arbitrary logging function is accepted at a realtime site.
The hot path is fixed-capacity, bounded and allocation-free. This is a proof
obligation for CX-UIB-37, not an assumption that an `@realtime` label makes it so.

Each callback producer writes its own single-producer ring and counters. Publish
only fully written entries with the approved atomic ordering; the reporting
consumer cannot read partially written records. Cross-producer aggregation
happens off the callback. Validate native atomic lock-freedom and timestamp
cost per target; fall back to an explicitly unavailable realtime trace when a
bounded safe path cannot be proven. Never use a mutex, blocking queue, wait,
allocation or ring growth to rescue full-buffer logging.

On capacity exhaustion increment a preallocated overflow counter and return
false immediately. Event sequence gaps, overflow and counter saturation are
exported. They invalidate affected completeness/percentile claims; dropping the
slowest samples cannot improve a result. Size rings from the declared workload
before collection and record capacity/high-water marks. Collector shutdown
seals producers, drains admitted entries, snapshots final counters and only then
releases buffers. A late callback hits the owner generation barrier, not freed
probe storage.

Probe initialization, snapshot copying, sorting, quantile computation and export
never occur in audio/display/native callback context. The final implementation
must prove both positive instrumentation and negative fixtures that attempt
allocation/blocking. If the analyzer cannot express the counter/clock primitive
or prove its transitive hot path, file **REQUEST(CL-UIB-13)**; do not bypass the
realtime analyzer or hand-edit compiler/runtime code.

## Clocks, endpoints and sampling

Use a process monotonic domain for derived durations, with native/audio/display
domains recorded separately. Calibrate mappings with paired samples, units,
offset, drift and uncertainty. Record recalibration after resume/device or route
change. Audio frame positions map via negotiated sample rate and route generation;
they are not interchangeable with wall clock. Native display timestamps name
their semantic endpoint (predicted tick, GPU completion, compositor present).

Input latency records receipt, enqueue, delivery, model update, render submit
and observed actual presentation. Debounce has its own start/end markers.
Do not double subtract overlapping I/O/debounce or compare unrelated clocks.
If actual presentation is unavailable, export a separately named submission
proxy plus unavailable presentation evidence, never a passed visible-response
row. A screenshot/readback proves content but not physical presentation time.

Keep raw samples in run order, including warmup markers and explicit failed
attempts. Predeclare warmup, sampling interval and qualifying phase. Search and
navigation use ≥100 actions; launch uses 20 fresh processes; frame data spans
10 min; lifecycle/recovery uses 100 cycles; audio soak spans 30 min. Record
callback sample count at the actual negotiated cadence, and verify that it
supports p99.9. Never silently remove spikes, retries or failed launches.

Probe overhead is measured on/off with the same workload and exported as
diagnostic overhead, not subtracted to invent a faster observed response.
The report preserves distributions and longest stalls, not only percentiles.
Correlation distinguishes two windows/scenes and overlapping requests; stale
results cannot attach to a newer query or the wrong iPad scene.

## Memory and resource accounting

Sample OS process residency and explicit allocator/native/GPU counters together.
Record provider method, sampling interval, coverage and shared/unified-memory
behavior. Process RSS already includes many native CPU allocations: show their
breakdown without adding those same bytes to RSS again. Add distinct GPU or
other residency not already represented, with the overlap rule stated. If the
provider cannot bound toolkit-private or GPU residency, mark aggregate coverage
incomplete; explicit allocation counters alone cannot certify the working set.

Resource keys distinguish allocation identity from aliases. A GPU object remains
live and its bytes charged until actual retirement; a pending close or dropped
managed reference is not release. Record temporary readback/decode copies,
cache entries and reservations separately from backing allocations so reserved
bytes are not accidentally counted twice. Artwork is a subset of product memory,
not an extra 128/64 MiB allowance. Trim timing stops when eligible unused
resources are reusable, with pinned/in-flight exclusions reported explicitly.

For lifecycle growth compare a stable warm baseline with settled samples after
equivalent cycles; record the formula and absolute bytes. Do not reset the
baseline each cycle. A zero/unknown baseline makes the percentage unavailable,
not zero growth. Reconcile live handle/registration totals with acquire/release
events; native toolkit objects outside the explicit counters require separate
observation or a declared coverage gap.

## Ledger export contract

Export one measurement per scenario slot through the existing
[ledger schema](../../../tools/qualification/schema.py), schema
`btrc.qualification.ledger/1`. A record has subject kind `scenario`, proposed
metric id, platform, frontend and a variant separating stand-in/device/build
configurations. UI operation/case inventory slots remain separate. Multiple
metrics need separate scenario ids because a slot holds one measurement;
otherwise later rows would overwrite earlier measurements during ledger merge.
The frozen scenario inventory is a future reviewed release, not changed here.

`measurement.metric`, `unit`, `samples` (run order), `failures`,
`minimum_samples`, same-length `components` and `budgets` use the existing
fields. Budget statistics are `median`, `p95`, `p99`, `p99.9` or `max`; `max=0`
can express zero leaks/xruns. Counts are interval deltas/end-of-cycle samples,
not cumulative counters silently presented as independent observations.
Non-scalar traces and string event metadata live in the artifact named by
`evidence.artifact`, not unknown ledger keys. Components share the parent unit;
different units use another record/artifact.

This **unmeasured schema example** declares launch admission only. Empty samples
and absent evidence deliberately make no passed claim:

```toml
schema = "btrc.qualification.ledger/1"

[[records]]
subject = { kind = "scenario", id = "runtime.launch.interactive", platform = "linux", frontend = "reference", variant = "diagnostic" }
measurement = { metric = "launch-to-interactive", unit = "s", samples = [], failures = 0, minimum_samples = 20, budgets = [{ statistic = "p95", limit = 3.0 }] }
```

Exporter validates every record with `LedgerDocument`/`LedgerRecord` before
publication. Passed scenario evidence requires samples, no failures, enough
samples, budgets met and provenance naming runner, btrc revision, frontend,
build mode, OS build, device class, CPU and memory; selfhost additionally needs
C compiler and compiler digest. Include btrsmith revision, target/SDK, scale,
thermal/power and device id where applicable. Clock calibration, toolkit/font
versions, probe capacity and artifact checksums go in the linked raw artifact
when the current strict provenance schema has no field for them.

Do not publish `passed` for overflowed/incomplete traces, missing endpoints or
unaccounted memory. A measured budget miss retains samples/failures and an
explicit non-passed outcome. Missing measurements remain declared unrecorded
or unavailable with a reason and genuine covered-by runner, never invented
zero samples. `recorded_at` is offset-bearing ISO 8601; wall time identifies a
run but does not supply durations. iPad uses `platform=ios` and
`provenance.device_class`, with a distinct scenario variant when needed to
prevent one device class overwriting another run's slot.

## Validation and review obligations

CX-UIB-37/38/39 must demonstrate bounded producer cost, full-buffer behavior,
sequence/counter integrity, clock discontinuity detection, two-scene correlation,
shutdown races and no serialization in callbacks. Synthetic traces validate the
export schema/quantile calculation but cannot qualify a runtime metric. Tests
must reject missing actual-present endpoints, mismatched units, stale generation,
counter overflow and false passed records with missing provenance or failed
budgets. Every P6 runtime row above must remain declared even on an unavailable
host.

Physical instrument loopback, thermal/device measurements and the two-hour
release soak stay in owner sessions. Hosted/simulator trials label their
stand-in scope and never satisfy wired physical latency. CL-UIB-02 reviews the
UI9 contract; CL-UIB-13 resolves realtime primitive/proof needs. No runtime,
compiler, ledger-schema or generated file is modified by this pre-draft.
