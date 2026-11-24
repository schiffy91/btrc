"""Qualify existing saved ALSA routes in standalone, linked and launcher deployments."""

import ctypes.util
import os
import struct
import subprocess

import pytest

from src.tests.python.linux_provider_fixtures import (
    ROOT,
    TARGET,
    build_alsa_plugin_adapter,
    build_provider_program,
    require_linux_reader,
)
from tools.qualification.dependencies import DependencyAudit


@pytest.fixture(scope="module", params=("selfhost", "python"))
def pcm_clients(request, tmp_path_factory):
    require_linux_reader()
    work = tmp_path_factory.mktemp("plugin-client")
    package = ROOT / "packages/alsa-plugins"
    library = build_alsa_plugin_adapter(work)
    source = ROOT / "src/tests/native/audio/linux/LinuxPluginRoute.btrc"
    plain = work / "standalone"
    plain.mkdir()
    core = build_provider_program(source, plain, request.param, False, request)
    linked = work / "linked"
    linked.mkdir()
    (linked / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "configured_pcm_client"\nexports = ["Main"]\n'
        f'[dependencies]\nalsa = {{ path = "{os.path.relpath(package, linked)}" }}\n'
    )
    original = source.read_text()
    factory = "Audio.createDevice()"
    assert original.count(factory) == 1
    entry = linked / "Main.btrc"
    entry.write_text("import alsa.AlsaPlugins;\n" + original.replace(factory, "AlsaPlugins.createDevice()"))
    bundled = build_provider_program(entry, linked, request.param, False, request)
    for product in (core, bundled, library):
        assert DependencyAudit().binary_problems(product, TARGET) == []
        dynamic = subprocess.check_output(["readelf", "-d", product], text=True)
        assert "libasound" not in dynamic and "libjack" not in dynamic
    return core, bundled, library


def test_saved_pcm_across_deployments(pcm_clients, tmp_path):
    if not ctypes.util.find_library("asound"):
        pytest.skip("requires the existing alsa-lib PCM plugin runtime")
    core, bundled, library = pcm_clients
    config = tmp_path / "asound.conf"
    output = tmp_path / "selected.raw"
    config.write_text(
        "defaults.namehint.showall on\n"
        'namehint.pcm.saved "plughw:CARD=SavedRoute,DEV=7|Persisted plugin route"\n'
        "pcm.plughw { @args [ CARD DEV ] @args.CARD { type string } @args.DEV { type integer } "
        "type file slave.pcm { type null } file { @func getenv vars [ BTRC_AUDIO_TEST_OUTPUT ] "
        'default "/unavailable" } format "raw" }\n'
        'pcm.!default { type null hint { show on description "Independent default" } }\n'
    )
    environment = {
        **os.environ,
        "PULSE_SERVER": "unix:/absent",
        "BTRC_PCM_ID": "plughw:CARD=SavedRoute,DEV=7",
        "ALSA_CONFIG_PATH": str(config),
        "BTRC_AUDIO_TEST_OUTPUT": str(output),
    }
    environment.pop("LD_PRELOAD", None)
    for program, deployed, expected in ((core, False, 3), (core, True, 0), (bundled, False, 0)):
        output.unlink(missing_ok=True)
        env = {**environment, **({"LD_PRELOAD": str(library)} if deployed else {})}
        result = subprocess.run([program], env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == expected, result.stderr
        if expected:
            assert result.stdout.strip() == "PCM unavailable" and not output.exists()
        else:
            assert "PASS: configured device" in result.stdout
            assert output.read_bytes().count(struct.pack("<ff", 0.25, -0.5)) >= 256
