# Audio

Portable device discovery/negotiation/lifecycle lives in `AudioDevice.btrc`;
callback contracts and routing live in `RealtimeAudio.btrc` and
`RealtimeAudioRouter.btrc`. Import them as `Library.Audio.AudioDevice`, etc.

Applications open the target's device provider with `Audio.createDevice()`
(`import Library.Audio;`). The facade calls the private `AudioProvider` module,
which the `[[package.providers]]` entries in this group's `btrc.toml` select per
compilation target: `MacOS.AudioProvider` (CoreAudio, through
`MacOS/MacOSAudioDevice.btrc` and the SDK declared by `MacOS/Hardware.h`) for
`macos`, and `Linux.AudioProvider` (the kernel ALSA PCM interface and the Pulse native socket protocol through
`Linux/LinuxAudioDevice.btrc`) for `linux`. Application policy and processors consume the
portable types and never name a platform module. Each platform's native
bindings, include directories and frameworks are declared in the same
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

Linux reads the kernel PCM inventory from `/proc/asound/pcm` and card names from
`/proc/asound/card*/id`. Both numeric and named addresses work, for example
`hw:0,0` and `plughw:CARD=Loopback,DEV=0`. A raw `hw:` session uses native
interleaved float32. The `plughw:` and per-card `sysdefault:` entries also
convert S32_LE, S24_3LE, S24_LE and S16_LE samples to and from the public
float buffers. A device with a larger fixed channel count opens with its full
count. The worker scatters selected output channels, silences unselected
channels and gathers selected input channels. A raw `hw:` session requires
a hardware-supported sample rate and the requested period. The adapting
entries negotiate the nearest native timing when necessary. The worker
converts the rate using rational frame counts and a windowed-sinc filter,
retaining history across callbacks. The public sample rate and block size
stay as requested.

On a desktop, `default` and `pulse` connect to PulseAudio or PipeWire's
Pulse server over a Unix socket. The provider publishes `pipewire` when that
server identifies itself as PipeWire. It reads the server address from
`PULSE_SERVER` or `XDG_RUNTIME_DIR/pulse/native`, authenticates using
`PULSE_COOKIE` or the user configuration directory, and reads channel counts
and rates for the default sink and source. Without a reachable sound server,
`default` selects the first available kernel capture and playback devices.
If the desktop server exposes JACK sinks or sources with `device.api=jack`,
selecting `jack` targets those named ports independently of the default sink
and source. Explicit ALSA configuration takes precedence for the IDs it
advertises, including `default`. A self-contained file in `ALSA_CONFIG_PATH`
can route a persisted ID to a null PCM, or to a regular raw float file backed
by a null PCM. These routes support PCM aliases and pass-through `plug`
wrappers. Like the ALSA null plugin, these PCMs can process offline audio
faster than real time. `Library.Audio` itself uses only first-party kernel PCM,
PulseAudio/PipeWire, and self-contained null/raw-file routes.

Each session runs one worker, with a bounded wait for each device. Kernel
xruns prepare the device again. A suspended kernel PCM resumes when the
driver supports it. Pulse underflow and overflow notifications reach the
next realtime block as discontinuity flags. The worker asks for `SCHED_FIFO`
when the OS permits it. Admission stops at `suspend()`. After `drain()` joins
the worker, subsequent calls observe its terminal fault, if any. The drain
deadline is five seconds, after which an active worker reports
`AUDIO_DEVICE_BUSY`.

The standard Linux audio tests use a clocked Pulse native peer and a kernel
PCM ioctl fixture. To check real kernel transfer, load the kernel's
`snd-aloop` module, then run the public duplex sample round-trip.

```sh
sudo modprobe snd-aloop
BTRC_TEST_AUDIO_HARDWARE=1 python -m pytest src/tests/python/test_native_linux_providers.py -k '(linux_audio_loopback and alsa-loopback) or linux_audio_resampling' --compilers=both
```

For the real sound-server round-trip, select a test sink and its matching
monitor as that server's default source, then run the same sample test.

```sh
BTRC_TEST_PULSE_MONITOR=1 python -m pytest src/tests/python/test_native_linux_providers.py -k 'linux_audio_loopback and pulse-monitor' --compilers=both
```

Windows remains unimplemented.
