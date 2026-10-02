# Audio

Portable device discovery/negotiation/lifecycle lives in `AudioDevice.btrc`;
callback contracts and routing live in `RealtimeAudio.btrc` and
`RealtimeAudioRouter.btrc`. Import them as `Library.Audio.AudioDevice`, etc.

Applications open the target's device provider with `Audio.createDevice()`
(`import Library.Audio;`). The facade calls the private `AudioProvider` module,
which the `[[package.providers]]` entries in this group's `btrc.toml` select per
compilation target: `MacOS.AudioProvider` (CoreAudio, through
`MacOS/MacOSAudioDevice.btrc` and the SDK declared by `MacOS/Hardware.h`) for
`macos`, and `Linux.AudioProvider` (ALSA, through `Linux/LinuxAudioDevice.btrc` and
`Linux/Alsa.h`) for `linux`. Application policy and processors consume the
portable types and never name a platform module. Each platform's native
bindings, frameworks and pkg-config entries are declared in the same
`btrc.toml`.

Both providers share one provider shell in `AudioDevice.btrc`:
`PlatformAudioDeviceProvider` owns the session lease, the retained failed
setup and the `openDuplex` sequence, and each platform supplies only an
`IAudioDevicePlatform` (hardware inventory plus `prepare`) and a stream that
implements `IAudioSessionBackend`. `MacOSAudioDevice.open()`,
`LinuxAudioDevice.open()` and `Audio.createDevice()` all return the one
validated `AudioDeviceProviderOpenOutcome`. Interleaved channel selection and silence go through
`RealtimeAudioSamples` in `RealtimeAudio.btrc`, which composing programs can
use too.

## Device loss and stalled devices

`drain()` is the reclamation barrier and the place a stream's failure is
reported. A stream that stopped early because its device was lost or failed
has still completed the barrier: `drain()` returns that fault
(`AUDIO_DEVICE_NOT_FOUND` for a vanished device, `AUDIO_DEVICE_UNAVAILABLE` or
`AUDIO_DEVICE_PERMISSION_DENIED` for one that stopped serving the stream,
`AUDIO_DEVICE_FAILED` for exhausted resources), the session is drained, and
`close()` releases it as usual. `AUDIO_DEVICE_BUSY` from `drain()` means the
barrier did not complete within the provider's deadline; the session stays
suspended and `drain()` may be retried. Between `start()` and `drain()` a lost
device shows up only as callbacks that stop arriving.

The control thread owns provider/session lifecycle. Processors retain their
preallocated context until the provider's drain barrier; native callbacks must
not allocate, block, mutate UI or reclaim callback-owned state.

`AUDIO_DEVICE_INDETERMINATE` is terminal, not a request to retry. CoreAudio
returns it when `AudioComponentInstanceDispose` reports failure: the provider
does not use or dispose that handle again and retains its render/program
dependencies. It never reports successful close. Releasing the unfinished
provider/session remains a fatal lifetime error. Stop and uninitialize failures
retain their separate retry paths; disposal failure must not be folded into
those paths merely because its numeric status resembles a busy error.

Apple's [disposal contract](https://developer.apple.com/documentation/audiotoolbox/audiocomponentinstancedispose(_:)?language=objc)
does not establish whether a nonzero result consumed the instance. Apple's
[component implementation](https://github.com/apple/AudioUnitSDK/blob/main/src/AudioUnitSDK/ComponentBase.cpp)
can catch failures during destruction; it is not evidence that AUHAL is safely
retryable. The native tests cover both still-live and already-consumed failure
outcomes, late silent callbacks through retained storage, and no repeated SDK
entry. Ordinary unique-owner conversion and a registration-owned realtime
native lease remain separate work; managed CF property/aggregate ownership
does not qualify that AudioUnit lifetime boundary.

Preparation initializes the audio unit without publishing a render callback.
Start installs the callback immediately before starting output, so failed
initialization cannot leave a published callback. The actual HAL ordering test
(`src/tests/native/audio/CallbackInstallation.c`) exercises silent
output across repeated installation/start/stop cycles, including stop before
the first start and repeated stop. This qualifies the ordering on the tested
native backend; it does not infer an asynchronous entry barrier from a status
code. The fault suite separately proves no callback publication on preparation
failure and recovery after callback-installation failure.

`Linux/LinuxAudioDevice.btrc` implements the same provider over ALSA. Inventory
enumerates PCM hints, keeps the shared server entry points (`default`,
`pipewire`, `pulse`, `jack`) and per-card `sysdefault`/`hw`/`plughw` names,
probes each direction for channel, rate and period ranges, and reports
`default` as both defaults. A session opens interleaved float capture and
playback handles configured to the requested period with two periods of
buffer, then runs a worker thread (a `NativeWorker` from
`Library.BackgroundJobs.NativeWorker`, the same start/join owner the
background-job executor uses) that reads one capture period, calls the
realtime program on the selected channels and writes one playback period in
lock step; xruns are recovered in place and reported as discontinuities, and
the worker asks for `SCHED_FIFO` when the system allows it. Channel counts are
negotiated as at least the selection's highest channel, so a device fixed at a
larger count opens and the selection is scattered into it. The worker waits
for each period with `snd_pcm_wait` and a 100 ms timeout, re-checking the stop
request between waits, so a stalled device never holds it. A failed
`snd_pcm_recover`, prefill write or capture start latches the stream's fault
and ends the worker. `suspend()` stops admission and signals the worker;
`drain()` waits up to five seconds for the worker to leave the device
(`AUDIO_DEVICE_BUSY` otherwise), joins it and reports any latched fault;
`close()` stops and releases the handles. While a session holds a PCM, an
inventory refresh reuses that PCM's last probe instead of reopening it, so a
`hw:` device that admits one opener stays published and the generation does
not move. A failed `snd_pcm_drop` keeps the handle, so the close is
retryable; alsa-lib frees the handle whether or not `snd_pcm_close` succeeds,
so that failure is indeterminate and the stream is never touched again, the
same disposal contract the CoreAudio provider exposes. The fault suite
(`src/tests/native/audio/linux/AlsaFaults.h`, `LinuxAudioFaults.btrc`) stands
in for alsa-lib with one fake `default` PCM and drives every failure point
without hardware, including a lost device, failed prefill and capture start,
a stalled device, an overdue worker, a fixed four-channel device and an
exclusive device held by the session. The session test (`LinuxAudioSession.btrc`) needs a PCM the
real alsa-lib can open. The devcontainer has no sound card, so its image
installs `nix/asound.conf` as `/etc/asound.conf`: a null default PCM that
discards playback and captures silence. CI's Linux shards therefore run the
session on both frontends, optimized and sanitized, and a missing PCM there is
a test failure, not a skip. The null plugin does not advance on a clock, so
those runs cover the provider's ALSA calls, lifecycle and frame accounting but
not realtime pacing or xrun recovery; that still needs a real device.
Windows remains unimplemented; do not add fake-success stubs.
