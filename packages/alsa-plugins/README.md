# Configured ALSA and JACK devices on Linux

This package opens user-configured ALSA PCMs through the installed
`libasound.so.2`, including JACK-only routes. It needs no ALSA development
headers. Keep using `Library.Audio` for kernel PCM, native PulseAudio
and PipeWire sessions.

## Link the adapter into an application

Add a relative path to the package in the application's `btrc.toml`.

```toml
[dependencies]
alsa = { path = "packages/alsa-plugins" }
```

Import `alsa.AlsaPlugins` and call `AlsaPlugins.createDevice()`.
The returned provider uses the ordinary `Library.Audio.AudioDevice` API,
including existing saved device IDs. `AlsaPlugins.available()` reports
whether the installed Linux ALSA runtime can be opened. On the other
supported targets, device creation uses the normal system provider.

## Deploy an adapter for an existing application

Applications built with the Linux PCM provider ABI can select the same
adapter at launch without a change to their source. Build the first-party
shared object once for the application's target architecture from a BTRC checkout.

```sh
cc -O2 -std=c11 -fPIC -shared -I src/stdlib/Audio/PcmPlugin \
  packages/alsa-plugins/Linux/Backend.c \
  -Wl,-soname,libbtrc-alsa-plugins.so.1 -o libbtrc-alsa-plugins.so.1
```

Distribute the shared object alongside the application. Its launcher can then
set `LD_PRELOAD` to the adapter's absolute path for that process.

```sh
LD_PRELOAD=/opt/my-app/lib/libbtrc-alsa-plugins.so.1 /opt/my-app/bin/my-app
```

This deployment requires a dynamic ELF loader that permits preloading.
For statically linked or secure-execution applications, link the package
into the executable. A rebuilt standalone executable distributed without
the adapter can reach its first-party audio devices. Its saved devices
that require an ALSA plugin become available when the adapter and the
original plugin runtime are present. Binaries built with the older automatic
fallback keep the implementation they shipped with.

## Check the installed plugin and a JACK server

The public file-route test checks the standalone executable, the linked
package, and a launcher-deployed adapter through each compiler.

```sh
python -m pytest -q src/tests/python/test_alsa_plugin_adapter.py --basetemp=/tmp/btrc-pcm-clients
```

With a separate JACK server running, use the same clients to send samples
to an independent recorder. The recorder checks the signs of both channels.
Set `JACK_DEFAULT_SERVER` when testing a named server; `ALSA_PLUGIN_DIR`
can select the directory containing the installed ALSA JACK plugin.

```sh
clients=/tmp/btrc-pcm-clients/plugin-client0
python src/tests/native/audio/linux/verify_jack_route.py \
  --plain "$clients/standalone/Program" --linked "$clients/linked/Program" \
  --adapter "$clients/libbtrc-alsa-plugins.so.1"
```

Repeat with `plugin-client1` for the other compiler. The optional `--before`
argument accepts the same public probe built against the older automatic
fallback and verifies its samples through the same recorder.
