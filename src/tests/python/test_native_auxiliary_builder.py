"""Build and inspect real companion/consumer pairs through both frontends."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.process_limits import TOOL_TIMEOUT
from tools.daemon_supervisor import SupervisorImage
from tools.native_plan import NativePlanBuilder, NativePlanError, NativePlanReader

REPO = Path(__file__).resolve().parents[3]


def run(command, **kwargs):
    kwargs.setdefault("timeout", TOOL_TIMEOUT)
    kwargs["env"] = {**os.environ, "BTRC_HOME": str(REPO / "src")}
    return subprocess.run(command, **kwargs)


@pytest.fixture(params=["reference", "selfhost"])
def frontend(request):
    return (
        (sys.executable, "-m", "src.compiler.python.main")
        if request.param == "reference"
        else (str(request.getfixturevalue("immutable_btrcc")),)
    )


@pytest.fixture(params=["windows-x86_64", "windows-aarch64"])
def consumer(frontend, request, tmp_path):
    source = tmp_path / "Main.btrc"
    leaf = tmp_path / "Leaf.btrc"
    leaf.write_text('int main() { puts("supervisor leaf"); return 0; }\n')
    (tmp_path / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "Pair"\n'
        '[[native.auxiliary-executables]]\npath = "Leaf.btrc"\n'
        'kind = "windows-daemon-supervisor"\nprotocol = 1\nos = ["windows"]\n'
        'requires = ["__btrc_windows_supervisor_image_verify"]\n'
    )
    source.write_text(
        "int main() {\n"
        "  __btrc_windows_image_owner* image = NULL;\n"
        "  __btrc_windows_launch_error_t error;\n"
        "  if (__btrc_windows_supervisor_image_verify(&image, &error) != 0) { return 1; }\n"
        "  if (__btrc_windows_supervisor_image_close(&image, &error) != 0) { return 2; }\n"
        '  puts("companion metadata PASS"); return 0;\n}\n'
    )
    generated, plan = tmp_path / "program.c", tmp_path / "plan.json"
    result = run(
        [
            *frontend,
            str(source),
            "--target",
            request.param,
            "--no-cache",
            "-o",
            str(generated),
            "--emit-link-plan",
            str(plan),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return frontend, request.param, leaf, generated, plan


def test_builds_final_bytes_and_required_metadata_as_a_pair(consumer, tmp_path):
    frontend, label, _, generated, plan = consumer
    output = tmp_path / "éditeur.exe"
    report = NativePlanBuilder(runner=run).build(
        plan_path=plan, generated_c=generated, output=output, frontend=frontend, optimization=0, jobs=1
    )
    companion = output.with_name(output.name + ".btrc-supervisor.exe")
    assert output.is_file() and companion.is_file()
    digest = hashlib.sha256(companion.read_bytes()).digest()
    assert digest in output.read_bytes()
    assert companion.name.encode("utf-8") + b"\0" in output.read_bytes()
    assert report.auxiliary["sha256"] == digest.hex()
    assert report.auxiliary["abi"] == label
    assert report.auxiliary["dependent_load_flags"] == 0x800
    assert report.auxiliary["frontend"] == list(frontend)
    assert report.adapter_units == 1
    assert not list(tmp_path.glob(".btrc-supervisor-*"))
    native_arch = "aarch64" if platform.machine().lower() in {"arm64", "aarch64"} else "x86_64"
    if sys.platform == "win32" and label == f"windows-{native_arch}":
        result = run([str(output)], capture_output=True, text=True)
        assert result.returncode == 0 and result.stdout.strip() == "companion metadata PASS", result.stderr


def test_reader_binds_source_and_requires_explicit_frontend(consumer, tmp_path):
    _, _, leaf, generated, plan = consumer
    assert NativePlanReader().read(plan).auxiliary.path == leaf
    with pytest.raises(NativePlanError, match="consumer frontend"):
        NativePlanBuilder(runner=run).build(plan_path=plan, generated_c=generated, output=tmp_path / "program.exe")
    leaf.write_text("int main() { return 2; }\n")
    with pytest.raises(NativePlanError, match="source changed"):
        NativePlanReader().read(plan)


def test_finalization_precedes_hash_and_failed_build_preserves_pair(consumer, tmp_path):
    frontend, _, _, generated, plan = consumer
    output = tmp_path / "signed.exe"
    companion = output.with_name(output.name + ".btrc-supervisor.exe")
    seen = []

    def finalize(path):
        seen.append(path.name)
        # A deterministic post-link trailer stands in for a signing owner's
        # final bytes. This tests ordering, not Authenticode validity.
        with path.open("ab") as stream:
            stream.write(b"finalized image bytes")

    builder = NativePlanBuilder(runner=run)
    report = builder.build(
        plan_path=plan,
        generated_c=generated,
        output=output,
        frontend=frontend,
        finalize_image=finalize,
        optimization=0,
        jobs=1,
    )
    assert seen == [companion.name, output.name]
    assert report.auxiliary["sha256"] == hashlib.sha256(companion.read_bytes()).hexdigest()
    before = (output.read_bytes(), companion.read_bytes())

    def fail_consumer(path):
        if path.name == output.name:
            raise ValueError("consumer signing failed")

    with pytest.raises(NativePlanError, match="consumer signing failed"):
        builder.build(
            plan_path=plan,
            generated_c=generated,
            output=output,
            frontend=frontend,
            finalize_image=fail_consumer,
            optimization=0,
            jobs=1,
        )
    assert (output.read_bytes(), companion.read_bytes()) == before


def test_rejects_recursive_companion_before_publication(consumer, tmp_path):
    frontend, _, leaf, generated, plan = consumer
    leaf.write_text("int main() { return __btrc_windows_supervisor_image_verify(NULL, NULL); }\n")
    document = json.loads(plan.read_text())
    document["auxiliary-executables"][0]["sha256"] = hashlib.sha256(leaf.read_bytes()).hexdigest()
    plan.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")
    output = tmp_path / "recursive.exe"
    with pytest.raises(NativePlanError, match="recursive auxiliary"):
        NativePlanBuilder(runner=run).build(
            plan_path=plan, generated_c=generated, output=output, frontend=frontend, optimization=0, jobs=1
        )
    assert not output.exists() and not output.with_name(output.name + ".btrc-supervisor.exe").exists()


def test_supervisor_policy_refuses_missing_configuration_and_wrong_abi(tmp_path):
    from tools.native_plan import TARGET_ROWS_BY_LABEL, TargetToolchain

    source = tmp_path / "plain.c"
    source.write_text("int main(void) { return 0; }\n")
    toolchain = TargetToolchain(TARGET_ROWS_BY_LABEL["windows-x86_64"])
    output = tmp_path / "plain.exe"
    result = run(
        [*toolchain.drivers["cc"], *toolchain.arguments, str(source), "-o", str(output)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    with pytest.raises(ValueError, match="loader configuration"):
        SupervisorImage(output, "x86_64").qualify()
    with pytest.raises(ValueError, match="ABI"):
        SupervisorImage(output, "aarch64")


def test_pair_reuses_objects_and_rebuilds_changed_leaf(consumer, tmp_path):
    frontend, _, leaf, generated, plan = consumer
    output = tmp_path / "cached.exe"
    options = dict(
        plan_path=plan,
        generated_c=generated,
        output=output,
        frontend=frontend,
        optimization=0,
        jobs=1,
        object_cache=tmp_path / "objects",
    )
    builder = NativePlanBuilder(runner=run)
    first = builder.build(**options)
    second = builder.build(**options)
    # A linker timestamp may change the final PE digest. Only its metadata
    # adapter then needs recompilation; every unchanged source object is reused.
    assert all(unit.cache_status == "hit" for unit in second.units[:-1]), second.as_dict()
    assert second.auxiliary["build"]["compiled_units"] == 0, second.auxiliary
    if first.auxiliary["sha256"] == second.auxiliary["sha256"]:
        assert second.as_dict()["compiled_units"] == 0
    assert bytes.fromhex(second.auxiliary["sha256"]) in output.read_bytes()
    leaf.write_text('int main() { puts("changed companion"); return 0; }\n')
    # The source digest must be renewed by the consumer frontend first.
    document = json.loads(plan.read_text())
    command = [
        *frontend,
        str(tmp_path / "Main.btrc"),
        "--target",
        document["target"]["label"],
        "-o",
        str(generated),
        "--emit-link-plan",
        str(plan),
    ]
    completed = run(command, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    third = builder.build(**options)
    assert third.auxiliary["sha256"] != first.auxiliary["sha256"]
    assert third.auxiliary["build"]["compiled_units"] > 0
    assert third.as_dict()["compiled_units"] > 0
    assert bytes.fromhex(third.auxiliary["sha256"]) in output.read_bytes()


def test_changed_leaf_after_metadata_is_refused(consumer, tmp_path):
    frontend, _, _, generated, plan = consumer
    output = tmp_path / "changed.exe"
    companion = output.with_name(output.name + ".btrc-supervisor.exe")
    output.write_bytes(b"previous consumer")
    companion.write_bytes(b"previous companion")
    leaf = None

    def finalize(path):
        nonlocal leaf
        if path.name == companion.name:
            leaf = path
        else:
            with leaf.open("ab") as stream:
                stream.write(b"changed after metadata")

    with pytest.raises(NativePlanError, match="changed before publication"):
        NativePlanBuilder(runner=run).build(
            plan_path=plan,
            generated_c=generated,
            output=output,
            frontend=frontend,
            finalize_image=finalize,
            optimization=0,
            jobs=1,
        )
    assert output.read_bytes() == b"previous consumer"
    assert companion.read_bytes() == b"previous companion"


def test_failed_second_publication_restores_previous_pair(consumer, tmp_path, monkeypatch):
    frontend, _, _, generated, plan = consumer
    output = tmp_path / "rollback.exe"
    companion = output.with_name(output.name + ".btrc-supervisor.exe")
    output.write_bytes(b"previous consumer")
    companion.write_bytes(b"previous companion")
    replace = os.replace
    injected = False

    def fail_consumer(source, destination):
        nonlocal injected
        if Path(destination) == output and Path(source).name.endswith(".publish.new-1"):
            assert companion.read_bytes() != b"previous companion"
            injected = True
            raise OSError("injected consumer publication failure")
        return replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_consumer)
    with pytest.raises(OSError, match="injected consumer publication failure"):
        NativePlanBuilder(runner=run).build(
            plan_path=plan, generated_c=generated, output=output, frontend=frontend, optimization=0, jobs=1
        )
    assert injected
    assert output.read_bytes() == b"previous consumer"
    assert companion.read_bytes() == b"previous companion"


def test_pe_policy_refuses_modified_loader_and_import_data(consumer, tmp_path):
    frontend, label, _, generated, plan = consumer
    output = tmp_path / "policy.exe"
    NativePlanBuilder(runner=run).build(
        plan_path=plan, generated_c=generated, output=output, frontend=frontend, optimization=0, jobs=1
    )
    companion = output.with_name(output.name + ".btrc-supervisor.exe")
    architecture = "aarch64" if label.endswith("aarch64") else "x86_64"
    image = SupervisorImage(companion, architecture)
    config = image.offset(*image.directory(10))
    imports = image.offset(*image.directory(1))
    name_rva = image.integer(imports + 12, 4)
    name = image.offset(name_rva, 1)
    cases = [
        (config + 78, b"\x01\x08", "only System32"),
        (image.directories + 13 * 8, b"\x01\0\0\0", "delay-loaded"),
        (name, b"evil.dll\0", "non-system DLL"),
        (config, b"\x01\0\0\0", "invalid size"),
    ]
    for offset, replacement, message in cases:
        data = bytearray(image.data)
        data[offset : offset + len(replacement)] = replacement
        modified = tmp_path / "modified.exe"
        modified.write_bytes(data)
        with pytest.raises(ValueError, match=message):
            SupervisorImage(modified, architecture).qualify()


def test_cli_builds_the_pair_with_the_selected_frontend(consumer, tmp_path):
    frontend, _, _, generated, plan = consumer
    output, report = tmp_path / "cli.exe", tmp_path / "cli-report.json"
    completed = run(
        [
            sys.executable,
            "-m",
            "tools.native_plan",
            "--plan",
            str(plan),
            "--generated-c",
            str(generated),
            "--output",
            str(output),
            "--optimization",
            "0",
            "--jobs",
            "1",
            "--frontend-command",
            shlex.join(frontend),
            "--report-json",
            str(report),
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    evidence = json.loads(report.read_text())["auxiliary"]
    assert evidence["frontend"] == list(frontend)
    assert hashlib.sha256(Path(evidence["path"]).read_bytes()).hexdigest() == evidence["sha256"]
    assert bytes.fromhex(evidence["sha256"]) in output.read_bytes()
