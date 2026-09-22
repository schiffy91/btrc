"""Real tool/runtime binding before native preprocessing receipts may be reused."""

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def context():
    reader = os.environ.get("BTRC_NATIVE_HEADER_READER")
    cc = os.environ.get("BTRC_NATIVE_PROVIDER_CC")
    cxx = os.environ.get("BTRC_NATIVE_PROVIDER_CXX")
    if not reader or not cc or not cxx:
        pytest.skip("build native reader and configure its native compiler provider")
    with tempfile.TemporaryDirectory(prefix=".btrc-compiler-context-", dir=Path.home()) as temporary:
        root = Path(temporary)
        environment = dict(os.environ)
        request = {
            "schema": "btrc.native-compiler-context.v1",
            "drivers": [cc, cxx],
            "cache_directory": str(root / "cache"),
        }

        def run(payload=None, changes=None, executable=None):
            return subprocess.run(
                [executable or reader, "--native-compiler-context=-"],
                input=json.dumps(request if payload is None else payload),
                env={**environment, **(changes or {})},
                capture_output=True,
                text=True,
                timeout=30,
            )

        yield root, request, run


def response(run, *args, **kwargs):
    result = run(*args, **kwargs)
    assert result.returncode == 0, result.stderr
    assert not result.stderr
    value = json.loads(result.stdout)
    assert value["schema"] == "btrc.native-compiler-context.v1"
    return value


def test_real_configured_compilers_bind_to_the_loaded_runtime(context):
    root, request, run = context
    first = response(run)
    assert first["eligible"], first
    assert first["eligible_launcher"]
    assert first["launcher"] == os.environ["BTRC_NATIVE_HEADER_READER"]
    assert first["drivers"] == request["drivers"]
    assert first["compiler"].startswith("/nix/store/")
    assert any("libclang-cpp" in image[1] for image in first["images"])
    assert any("libLLVM" in image[1] for image in first["images"])
    encoded = json.dumps(first["identity"], separators=(",", ":"), ensure_ascii=False).encode()
    assert first["identity_sha256"] == hashlib.sha256(encoded).hexdigest()
    assert response(run) == first, "temporary capture names must not enter the context identity"
    assert not list((root / "cache" / "workers").iterdir())


def test_context_binds_the_current_environment(context):
    _, _, run = context
    first = response(run)
    changed = response(run, changes={"BTRC_CONTEXT_FIXTURE": "changed"})
    assert first["eligible"] and changed["eligible"]
    assert first["identity_sha256"] != changed["identity_sha256"]


@pytest.mark.parametrize("kind", ["wrapper", "symlink", "copied-binary", "other-compiler"])
def test_unqualified_driver_cannot_borrow_the_configured_runtime(context, kind):
    root, request, run = context
    candidate = root / "compiler"
    if kind == "wrapper":
        candidate.write_text(f'#!/bin/sh\nexec {shlex.quote(request["drivers"][0])} "$@"\n')
        candidate.chmod(0o755)
    elif kind == "symlink":
        candidate.symlink_to(request["drivers"][0])
    elif kind == "copied-binary":
        valid = response(run)
        assert valid["eligible"], valid
        shutil.copyfile(valid["compiler"], candidate)
        candidate.chmod(0o755)
    else:
        candidate = Path("/usr/bin/clang")
    refused = response(run, {**request, "drivers": [str(candidate)]})
    assert not refused["eligible"]
    assert refused["reason"] == "unqualified-driver"


@pytest.mark.parametrize(
    "variable", ["BASH_ENV", "ENV", "BASH_FUNC_fixture%%", "DYLD_LIBRARY_PATH", "DYLD_DIAGNOSTICS_FILE"]
)
def test_dynamic_shell_or_loader_configuration_refuses_admission(context, variable):
    root, _, run = context
    script = root / "environment"
    script.write_text(":\n")
    value = str(script) if variable in {"BASH_ENV", "ENV", "DYLD_DIAGNOSTICS_FILE"} else ""
    refused = response(run, changes={variable: value})
    assert not refused["eligible"]
    assert refused["reason"] == "dynamic-tool-environment"


@pytest.mark.parametrize("kind", ["file", "symlink", "public-directory"])
def test_unavailable_private_capture_storage_refuses_admission(context, kind):
    root, request, run = context
    cache = Path(request["cache_directory"])
    if kind == "file":
        cache.write_text("caller-owned")
    elif kind == "symlink":
        actual = root / "actual"
        actual.mkdir(mode=0o700)
        cache.symlink_to(actual, target_is_directory=True)
    else:
        cache.mkdir(mode=0o755)
    refused = response(run)
    assert not refused["eligible"]
    assert refused["reason"] == "capture-storage-unavailable"
    if kind == "file":
        assert cache.read_text() == "caller-owned"


@pytest.mark.parametrize(
    "change", [{"schema": "unknown"}, {"drivers": []}, {"drivers": [3]}, {"extra": True}, {"drivers": ["cc\u0000"]}]
)
def test_malformed_context_request_fails_before_observing_tools(context, change):
    _, request, run = context
    result = run({**request, **change})
    assert result.returncode == 1
    assert not result.stdout


def test_mutable_copy_of_reader_cannot_issue_a_bound_context(context):
    root, _, run = context
    reader = Path(os.environ["BTRC_NATIVE_HEADER_READER"])
    binary = reader.parent / ".btrc-native-header-wrapped"
    assert binary.is_file(), "Nix package must expose its wrapped native binary"
    copied = root / "reader"
    shutil.copyfile(binary, copied)
    copied.chmod(0o755)
    refused = response(run, executable=str(copied))
    assert not refused["eligible"] and not refused["eligible_launcher"]
    assert refused["reason"] == "unsupported-runtime"
