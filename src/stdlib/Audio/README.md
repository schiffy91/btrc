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

macOS is the only current device implementation in scope. Future Linux/Windows
providers belong under sibling `Linux/` and `Windows/` packages and implement
the same negotiated-format and drain contracts. Do not add fake-success stubs.
