"""Real native builds consuming bound preprocessing receipts and safe fallback."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import NativeGeneratedUnit, NativeLinkPlan, PackageTarget
from tools.native_plan import NativePlanBuilder


@pytest.fixture
def project(monkeypatch):
    reader = os.environ.get("BTRC_NATIVE_HEADER_READER")
    cc = os.environ.get("BTRC_NATIVE_PROVIDER_CC")
    cxx = os.environ.get("BTRC_NATIVE_PROVIDER_CXX")
    if not reader or not cc or not cxx:
        pytest.skip("configure the packaged receipt provider and its C/C++ toolchain")
    monkeypatch.setenv("BTRC_NATIVE_PREPROCESS_RECEIPTS", "1")
    with tempfile.TemporaryDirectory(prefix=".btrc-receipt-consumer-", dir=Path.home()) as temporary:
        root = Path(temporary)
        monkeypatch.chdir(root)
        header = root / "value.h"
        header.write_text("#define VALUE 2 /* AAA */\n")
        generated = root / "main.c"
        generated.write_text(
            '#include <stdio.h>\n#include "value.h"\nint answer(void);\nint main(void) { printf("%d\\n", answer() + VALUE); return 0; }\n'
        )
        plan = root / "native.json"
        payload = NativeLinkPlan(
            PackageTarget.parse(None),
            generated_units=(
                NativeGeneratedUnit("Answer", "c++", "c++17", "raii", 'extern "C" int answer(void) { return 40; }\n'),
            ),
        ).as_dict()
        plan.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")
        options = dict(
            plan_path=plan,
            generated_c=generated,
            output=root / "program",
            cc=cc,
            cxx=cxx,
            optimization=0,
            jobs=2,
            object_cache=root / "cache",
            debug_info=True,
        )
        yield root, header, options


def execute(options):
    return subprocess.check_output([str(options["output"])], text=True)


def test_real_build_reuses_receipts_objects_executable_and_debug_inputs(project):
    root, _, options = project
    builder = NativePlanBuilder()
    first = builder.build(**options)
    assert first.preprocessing_units == 2 and first.preprocessing_hits == 0
    assert all(unit.publication_status == "stored" for unit in first.units)
    assert execute(options) == "42\n"
    before = options["output"].stat()
    digest = hashlib.sha256(options["output"].read_bytes()).hexdigest()
    debug = {path: path.stat().st_mtime_ns for path in root.glob(".btrc-debug-v1-*/*")}
    assert debug
    warm = builder.build(**options)
    assert warm.preprocessing_units == warm.preprocessing_hits == 2
    assert warm.preprocessing_s > 0
    assert warm.as_dict()["compiled_units"] == 0 and warm.links == 0
    assert warm.link_cache_status == "hit"
    assert [unit.cache_key for unit in warm.units] == [unit.cache_key for unit in first.units]
    assert options["output"].stat().st_ino == before.st_ino
    assert options["output"].stat().st_mtime_ns == before.st_mtime_ns
    assert hashlib.sha256(options["output"].read_bytes()).hexdigest() == digest
    assert {path: path.stat().st_mtime_ns for path in debug} == debug
    assert execute(options) == "42\n"


@pytest.mark.parametrize("edit", ["value", "comment"])
def test_preserved_mtime_edit_changes_object_identity(project, edit):
    _, header, options = project
    builder = NativePlanBuilder()
    first = builder.build(**options)
    stat = header.stat()
    header.write_text("#define VALUE 3 /* AAA */\n" if edit == "value" else "#define VALUE 2 /* BBB */\n")
    os.utime(header, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    changed = builder.build(**options)
    assert changed.preprocessing_units == 2 and changed.preprocessing_hits == 1
    assert changed.units[0].cache_key != first.units[0].cache_key
    assert changed.units[0].cache_status != "hit"
    assert changed.units[1].cache_status == "hit"
    assert execute(options) == ("43\n" if edit == "value" else "42\n")


def test_post_compile_validation_does_not_reuse_the_initial_batch(project):
    _, header, options = project

    class ChangedDuringCompile(NativePlanBuilder):
        def _run(self, command):
            super()._run(command)
            if "-c" in command and str(options["generated_c"]) in command:
                previous = header.stat()
                header.write_text("#define VALUE 3 /* AAA */\n")
                os.utime(header, ns=(previous.st_atime_ns, previous.st_mtime_ns))

    first = ChangedDuringCompile().build(**options)
    assert first.preprocessing_units == 2
    assert first.units[0].publication_status == "inputs-changed"
    assert execute(options) == "42\n"
    changed = NativePlanBuilder().build(**options)
    assert changed.units[0].cache_status != "hit"
    assert changed.units[0].cache_key != first.units[0].cache_key
    assert execute(options) == "43\n"


@pytest.mark.parametrize(
    "fault", ["missing-helper", "malformed-response", "wrong-launcher", "wrong-compiler", "wrong-blob"]
)
def test_optional_receipt_failure_keeps_ordinary_builds_working(project, monkeypatch, fault):
    _, _, options = project
    from src.compiler.python.frontend.native_imports import NativeHeaderRead

    original = NativeHeaderRead.read

    def read(request, environment):
        encoded = original(request, environment)
        if "--native-preprocess=-" not in request.arguments:
            return encoded
        if fault == "malformed-response":
            return "{}"
        response = json.loads(encoded)
        if fault == "wrong-launcher":
            response["launcher"] = "/unexpected/reader"
        elif fault == "wrong-compiler":
            for context in response["contexts"]:
                context["compiler"] = "/unexpected/clang"
        elif fault == "wrong-blob":
            for unit in response["units"]:
                if "response" in unit:
                    unit["response"]["stdout"]["sha256"] = "0" * 64
        return json.dumps(response)

    if fault == "missing-helper":
        monkeypatch.setenv("BTRC_NATIVE_HEADER_READER", "/nix/store/missing-reader")
    else:
        monkeypatch.setattr(NativeHeaderRead, "read", read)
    report = NativePlanBuilder().build(**options)
    assert report.preprocessing_units == 0
    assert execute(options) == "42\n"
    warm = NativePlanBuilder().build(**options)
    assert warm.as_dict()["compiled_units"] == 0 and execute(options) == "42\n"


def test_native_cli_consumes_batched_receipts_for_all_units(project):
    root, _, options = project
    # More units than workers exercises bounded CLI scheduling.
    payload = json.loads(options["plan_path"].read_text())
    extras = []
    for index in range(3):
        source = root / f"part-{index}.c"
        source.write_text(f"int extra{index}(void) {{ return {index}; }}\n")
        extras.append(str(source))
    payload.update(schema=4)
    payload["emitted-units"] = extras
    options["plan_path"].write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    )
    report = root / "report.json"
    repo = Path(__file__).resolve().parents[3]
    command = [
        sys.executable,
        "-m",
        "tools.native_plan",
        "--plan",
        str(options["plan_path"]),
        "--generated-c",
        str(options["generated_c"]),
        "--output",
        str(options["output"]),
        "--cc",
        options["cc"],
        "--cxx",
        options["cxx"],
        "--optimization",
        "0",
        "--jobs",
        "2",
        "--debug-info",
        "--object-cache",
        str(options["object_cache"]),
        "--report-json",
        str(report),
    ]
    for index in range(2):
        result = subprocess.run(
            command, cwd=root, env={**os.environ, "PYTHONPATH": str(repo)}, capture_output=True, text=True, timeout=90
        )
        assert result.returncode == 0, result.stderr
        evidence = json.loads(report.read_text())
        assert evidence["preprocessing_units"] == 5
        if index:
            assert evidence["preprocessing_hits"] == 5 and evidence["compiled_units"] == evidence["links"] == 0
        assert execute(options) == "42\n"
