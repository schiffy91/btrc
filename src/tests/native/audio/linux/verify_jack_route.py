"""Check signed output from LinuxPluginRoute against an independent, running JACK server."""

import argparse
import ctypes
import os
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def recorder():
    jack = ctypes.CDLL("libjack.so.0")
    pointer, uint, text = ctypes.c_void_p, ctypes.c_uint, ctypes.c_char_p

    def bind(name, result, *arguments):
        function = getattr(jack, name)
        function.restype = result
        function.argtypes = arguments
        return function

    status = uint()
    open_client = bind("jack_client_open", pointer, text, uint, ctypes.POINTER(uint))
    client = open_client(f"btrc_audio_probe_{os.getpid()}".encode(), 1, ctypes.byref(status))
    if not client:
        raise RuntimeError(f"Could not connect to the configured JACK server (status {status.value})")
    try:
        register = bind("jack_port_register", pointer, pointer, text, text, ctypes.c_ulong, ctypes.c_ulong)
        left, right = (register(client, name, b"32 bit float mono audio", 1, 0) for name in (b"left", b"right"))
        assert left and right
        get_buffer = bind("jack_port_get_buffer", ctypes.POINTER(ctypes.c_float), pointer, uint)
        get_name = bind("jack_port_name", text, pointer)
        counts = [0, 0]
        callback_type = ctypes.CFUNCTYPE(ctypes.c_int, uint, pointer)

        @callback_type
        def receive(frames, _context):
            left_samples, right_samples = get_buffer(left, frames), get_buffer(right, frames)
            for index in range(frames):
                if left_samples[index] == 0.25 and right_samples[index] == -0.5:
                    counts[0] += 1
                elif left_samples[index] != 0.0 or right_samples[index] != 0.0:
                    counts[1] += 1
            return 0

        set_process = bind("jack_set_process_callback", ctypes.c_int, pointer, callback_type, pointer)
        assert set_process(client, receive, None) == 0
        assert bind("jack_activate", ctypes.c_int, pointer)(client) == 0
        yield (get_name(left).decode(), get_name(right).decode()), counts
    finally:
        assert bind("jack_client_close", ctypes.c_int, pointer)(client) == 0


def verify(plain, linked, adapter, before=None):
    with tempfile.TemporaryDirectory() as directory, recorder() as (ports, counts):
        config = Path(directory) / "asound.conf"
        config.write_text(
            'pcm.!default { type null hint { show on description "Independent default" } }\n'
            f'pcm.jack {{ type jack playback_ports {{ 0 "{ports[0]}" 1 "{ports[1]}" }} '
            'capture_ports { 0 system:capture_1 1 system:capture_2 } hint { show on description "JACK" } }\n'
        )
        environment = {
            **os.environ,
            "ALSA_CONFIG_PATH": str(config),
            "PULSE_SERVER": "unix:/missing",
            "BTRC_PCM_ID": "jack",
        }
        environment.pop("LD_PRELOAD", None)
        cases = []
        if before:
            cases.append(("previous automatic fallback", before, environment, 0))
        cases.extend(
            [
                ("standalone", plain, environment, 3),
                ("launcher adapter", plain, {**environment, "LD_PRELOAD": str(adapter.resolve())}, 0),
                ("linked adapter", linked, environment, 0),
            ]
        )
        for name, client, env, expected in cases:
            counts[:] = [0, 0]
            result = subprocess.run([client], env=env, capture_output=True, text=True, timeout=30)
            assert result.returncode == expected, (name, result.stdout, result.stderr)
            matching, incorrect = counts
            assert incorrect == 0
            if expected == 0:
                assert matching >= 256 and "PASS: configured device jack" in result.stdout
            else:
                assert matching == 0 and "PCM unavailable" in result.stdout
            print(f"{name}: verified {matching} matching stereo frames, exit {result.returncode}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plain", required=True, type=Path)
    parser.add_argument("--linked", required=True, type=Path)
    parser.add_argument("--adapter", required=True, type=Path)
    parser.add_argument("--before", type=Path)
    args = parser.parse_args()
    verify(args.plain, args.linked, args.adapter, args.before)
