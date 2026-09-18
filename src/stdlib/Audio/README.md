# Audio

Portable device discovery/negotiation/lifecycle lives in `AudioDevice.btrc`;
callback contracts and routing live in `RealtimeAudio.btrc` and
`RealtimeAudioRouter.btrc`. Import them as `Library.Audio.AudioDevice`, etc.

`MacOS/CoreAudioDevice.btrc` implements `AudioDeviceProvider` using the real
CoreAudio SDK declared by `MacOS/Hardware.h`. Select it only at the application
composition boundary; application policy and processors consume portable types.
Its native binding/framework requirements are declared in the stdlib manifest.

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
(`src/tests/native/core_audio_device/CallbackInstallation.c`) exercises silent
output across repeated installation/start/stop cycles, including stop before
the first start and repeated stop. This qualifies the ordering on the tested
native backend; it does not infer an asynchronous entry barrier from a status
code. The fault suite separately proves no callback publication on preparation
failure and recovery after callback-installation failure.

`Linux/AlsaDevice.btrc` implements the same provider over ALSA. Inventory
enumerates PCM hints, keeps the shared server entry points (`default`,
`pipewire`, `pulse`, `jack`) and per-card `sysdefault`/`hw`/`plughw` names,
probes each direction for channel, rate and period ranges, and reports
`default` as both defaults. A session opens interleaved float capture and
playback handles configured to the requested period with two periods of
buffer, then runs a worker thread that reads one capture period, calls the
realtime program on the selected channels and writes one playback period in
lock step; xruns are recovered in place and reported as discontinuities, and
the worker asks for `SCHED_FIFO` when the system allows it. `suspend()` stops
admission and signals the worker, `drain()` joins it, `close()` releases the
handles. Windows remains unimplemented; do not add fake-success stubs.
