"""Real preprocessing receipt capture, replay, and content/search invalidation."""

import hashlib
import json
import os
import shlex
import subprocess
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def preprocessing():
    reader = os.environ.get("BTRC_NATIVE_HEADER_READER")
    driver = os.environ.get("BTRC_NATIVE_PROVIDER_CC")
    if not reader or not driver:
        pytest.skip("build native reader and configure its native compiler provider")
    with tempfile.TemporaryDirectory(prefix=".btrc-preprocess-", dir=Path.home()) as temporary:
        root = Path(temporary)
        source = root / "source"
        source.mkdir()
        (source / "early").mkdir()
        (source / "late").mkdir()
        main = source / "main.c"
        main.write_text(
            '#include "value.h"\n#if __has_include("optional.h")\n#include "optional.h"\n#endif\nint answer = VALUE;\n'
        )
        (source / "late/value.h").write_text("#define VALUE 42 /* AAA */\n")
        capture = root / "normal"
        capture.mkdir()
        environment = {**os.environ, "SOURCE_DATE_EPOCH": "1"}
        paths = {
            "preprocessed": capture / "source.i",
            "dependencies": capture / "source.d",
            "headers": capture / "headers.txt",
        }

        def command(extra=()):
            return [
                driver,
                "-std=c11",
                "-pedantic-errors",
                "-Iearly",
                "-Ilate",
                str(main),
                *extra,
                "-E",
                "-MD",
                "-MF",
                str(paths["dependencies"]),
                "-MT",
                "btrc-object",
                "-Xclang",
                "-header-include-file",
                "-Xclang",
                str(paths["headers"]),
                "-Xclang",
                "-fshow-skipped-includes",
                "-o",
                str(paths["preprocessed"]),
            ]

        def expanded(extra=()):
            result = subprocess.run(
                [*command(extra), "-###"], cwd=source, env=environment, capture_output=True, text=True, timeout=30
            )
            assert result.returncode == 0, result.stderr
            jobs = [shlex.split(line.strip()) for line in result.stderr.splitlines() if line.lstrip().startswith('"')]
            assert len(jobs) == 1 and jobs[0][1] == "-cc1", jobs
            return jobs[0]

        def normal(extra=()):
            for path in paths.values():
                path.unlink(missing_ok=True)
            result = subprocess.run(command(extra), cwd=source, env=environment, capture_output=True, timeout=30)
            assert result.returncode == 0, result.stderr
            return {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}, result.stderr

        def run(arguments=None, changes=None, payload=None):
            request = {
                "schema": "btrc.native-preprocess.v1",
                "cache_directory": str(root / "cache"),
                "drivers": [driver],
                "units": [{"id": "main", "cc1": expanded() if arguments is None else arguments}],
            }
            result = subprocess.run(
                [reader, "--native-preprocess=-"],
                input=json.dumps(request if payload is None else payload),
                cwd=source,
                env={**environment, **(changes or {})},
                capture_output=True,
                text=True,
                timeout=60,
            )
            assert result.returncode == 0, result.stderr
            assert not result.stderr
            response = json.loads(result.stdout)
            assert response["schema"] == request["schema"]
            assert response["launcher"] == reader and response["eligible_launcher"]
            return response

        def receipt(arguments=None):
            response = run(arguments)
            assert response["contexts"] and all(context["eligible"] for context in response["contexts"]), response
            assert len(response["units"]) == 1, response
            unit = response["units"][0]
            assert unit["id"] == "main" and unit["eligible"], unit
            streams = {}
            for name, info in unit["response"].items():
                data = Path(info["path"]).read_bytes()
                assert len(data) == info["bytes"] and hashlib.sha256(data).hexdigest() == info["sha256"]
                streams[name] = data
            return unit, json.loads(streams["stdout"]), streams["stderr"]

        yield root, source, main, expanded, normal, run, receipt


def test_receipt_matches_real_preprocessing_and_reuses_it(preprocessing):
    root, source, _, _, normal, _, receipt = preprocessing
    hashes, errors = normal()
    first, output, diagnostics = receipt()
    assert not first["cache_hit"]
    assert all(output[name] == digest for name, digest in hashes.items())
    assert diagnostics == errors
    assert output["buffers"]
    assert any((source / path).resolve() == source / "late/value.h" for path, _ in output["buffers"])
    second, reused, repeated_errors = receipt()
    assert second["cache_hit"] and reused == output and repeated_errors == errors
    assert not list((root / "cache/workers").iterdir())


def test_failed_receipt_publication_returns_no_descriptors(preprocessing):
    root, _, _, expanded, normal, run, receipt = preprocessing
    hashes, errors = normal()
    request = {
        "schema": "btrc.native-preprocess.v1",
        "cache_directory": str(root / "cache"),
        "drivers": [os.environ["BTRC_NATIVE_PROVIDER_CC"]],
        "capture": False,
        "units": [{"id": "main", "cc1": expanded()}],
    }
    prepared = run(payload=request)["units"][0]
    destination = root / "cache" / (prepared["identity_sha256"] + ".receipt")
    destination.mkdir(mode=0o700)
    failed = run()["units"][0]
    assert not failed["eligible"] and not failed["cache_hit"]
    assert failed["reason"] == "receipt-not-published" and "response" not in failed
    assert destination.is_dir() and not list((root / "cache/workers").iterdir())
    destination.rmdir()
    first, output, diagnostics = receipt()
    assert not first["cache_hit"] and diagnostics == errors
    assert all(output[name] == digest for name, digest in hashes.items())
    assert receipt()[0]["cache_hit"]


def test_concurrent_captures_return_complete_owned_responses(preprocessing):
    from concurrent.futures import ThreadPoolExecutor

    root, _, _, _, normal, _, receipt = preprocessing
    hashes, errors = normal()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: receipt(), range(4)))
    for _, output, diagnostics in results:
        assert diagnostics == errors
        assert all(output[name] == digest for name, digest in hashes.items())
        assert output == results[0][1]
    assert receipt()[0]["cache_hit"]
    assert not list((root / "cache/workers").iterdir())


@pytest.mark.parametrize("change", ["content", "comment", "source-comment", "shadow", "negative", "delete", "symlink"])
def test_changed_inputs_cannot_reuse_a_receipt(preprocessing, change):
    _, source, main, _, normal, run, receipt = preprocessing
    header = source / "late/value.h"
    if change == "symlink":
        header.rename(source / "late/first.h")
        (source / "late/second.h").write_text("#define VALUE 43\n")
        header.symlink_to("first.h")
    normal()
    _, before, _ = receipt()
    assert receipt()[0]["cache_hit"]
    if change in {"content", "comment", "source-comment"}:
        path = main if change == "source-comment" else header
        stat = path.stat()
        data = path.read_bytes()
        if change == "content":
            data = data.replace(b"42", b"43")
        elif change == "comment":
            data = data.replace(b"AAA", b"BBB")
        else:
            data += b"/* comment */\n"
        path.write_bytes(data)
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    elif change == "shadow":
        (source / "early/value.h").write_text("#define VALUE 43\n")
    elif change == "negative":
        (source / "optional.h").write_text("int optional;\n")
    elif change == "delete":
        header.unlink()
        unit = run()["units"][0]
        assert not unit["eligible"] and not unit["cache_hit"]
        return
    else:
        header.unlink()
        header.symlink_to("second.h")
    hashes, _ = normal()
    unit, after, _ = receipt()
    assert not unit["cache_hit"]
    assert all(after[name] == digest for name, digest in hashes.items())
    assert after != before
    if change == "comment":
        assert after["preprocessed"] == before["preprocessed"]
        assert after["buffers"] != before["buffers"]
    assert receipt()[0]["cache_hit"]


@pytest.mark.parametrize("macro", ["__DATE__", "__TIME__", "__TIMESTAMP__"])
def test_volatile_preprocessing_is_not_reusable(preprocessing, macro):
    root, _, main, _, _, run, _ = preprocessing
    main.write_text(f"const char *stamp = {macro};\n")
    unit = run()["units"][0]
    assert not unit["eligible"] and unit["reason"] == "preprocessing-not-reusable"
    assert not list((root / "cache").glob("*.receipt"))
    assert not list((root / "cache/workers").iterdir())


@pytest.mark.parametrize("corruption", ["receipt", "stdout", "stderr"])
def test_corrupt_receipts_and_blobs_recompute(preprocessing, corruption):
    root, _, _, _, normal, _, receipt = preprocessing
    normal()
    first, output, errors = receipt()
    assert receipt()[0]["cache_hit"]
    path = (
        next((root / "cache").glob("*.receipt"))
        if corruption == "receipt"
        else Path(first["response"][corruption]["path"])
    )
    path.write_bytes(b"corrupt")
    result, fresh, diagnostics = receipt()
    assert not result["cache_hit"] and fresh == output and diagnostics == errors
    assert receipt()[0]["cache_hit"]


def test_diagnostics_and_feature_policy_match_the_compiler(preprocessing):
    _, _, main, _, normal, _, receipt = preprocessing
    main.write_text(
        '#pragma message("diagnostic fixture")\n#if __has_extension(cxx_fixed_enum)\n#error wrong diagnostic policy\n#endif\nint value;\n'
    )
    hashes, errors = normal()
    assert b"diagnostic fixture" in errors
    first, output, diagnostics = receipt()
    assert not first["cache_hit"] and diagnostics == errors
    assert all(output[name] == digest for name, digest in hashes.items())
    assert receipt()[2] == errors


def test_unbound_compiler_cannot_execute_or_reuse(preprocessing):
    root, _, _, expanded, _, run, _ = preprocessing
    arguments = expanded()
    arguments[0] = "/usr/bin/clang"
    unit = run(arguments)["units"][0]
    assert not unit["eligible"] and unit["reason"] == "unsupported-preprocessing-inputs"
    assert not list((root / "cache").glob("*.receipt"))


def test_unsupported_side_outputs_are_not_written(preprocessing):
    root, _, _, expanded, _, run, _ = preprocessing
    destination = root / "stats.json"
    destination.write_text("caller-owned")
    unit = run([*expanded(), "-stats-file=" + str(destination)])["units"][0]
    assert not unit["eligible"] and not unit["cache_hit"]
    assert destination.read_text() == "caller-owned"


def test_environment_change_invalidates_the_context(preprocessing):
    _, _, _, _, normal, run, receipt = preprocessing
    normal()
    receipt()
    assert receipt()[0]["cache_hit"]
    changed = run(changes={"BTRC_RECEIPT_CONTEXT": "changed"})
    assert all(context["eligible"] for context in changed["contexts"]) and not changed["units"][0]["cache_hit"]


def test_capture_destinations_do_not_change_identity_or_write_caller_files(preprocessing):
    root, _, _, expanded, normal, _, receipt = preprocessing
    normal()
    first, output, _ = receipt()
    arguments = expanded()
    caller = root / "caller-output"
    caller.write_text("caller-owned")
    for option in ["-o", "-dependency-file", "-header-include-file"]:
        arguments[arguments.index(option) + 1] = str(caller)
    second, reused, _ = receipt(arguments)
    assert second["cache_hit"] and reused == output
    assert second["identity_sha256"] == first["identity_sha256"]
    assert caller.read_text() == "caller-owned"


def test_options_change_the_receipt_identity(preprocessing):
    _, _, _, expanded, normal, _, receipt = preprocessing
    normal()
    first, _, _ = receipt()
    second, _, _ = receipt(expanded(["-DCHANGED=1"]))
    assert not second["cache_hit"]
    assert second["identity_sha256"] != first["identity_sha256"]


@pytest.mark.parametrize("option", ["-help", "-version", "-fmodules", "-load"])
def test_unsupported_actions_decline_without_execution(preprocessing, option):
    root, _, _, expanded, _, run, _ = preprocessing
    arguments = [*expanded(), option]
    if option == "-load":
        arguments.append(str(root / "not-a-plugin.dylib"))
    unit = run(arguments)["units"][0]
    assert not unit["eligible"] and unit["reason"] == "unsupported-preprocessing-inputs"


def test_session_retains_unit_order_and_shares_validated_inputs(preprocessing):
    root, _, _, expanded, normal, run, _ = preprocessing
    normal()
    request = {
        "schema": "btrc.native-preprocess.v1",
        "cache_directory": str(root / "cache"),
        "drivers": [os.environ["BTRC_NATIVE_PROVIDER_CC"]],
        "units": [{"id": identity, "cc1": expanded()} for identity in ["first", "second"]],
    }
    first = run(payload=request)
    assert [unit["id"] for unit in first["units"]] == ["first", "second"]
    assert all(unit["eligible"] for unit in first["units"])
    assert [unit["cache_hit"] for unit in first["units"]] == [False, True]
    assert all(unit["cache_hit"] for unit in run(payload=request)["units"])


def test_interrupted_clang_temporary_output_is_collected(preprocessing):
    import contextlib
    import signal
    import time

    root, source, main, expanded, normal, run, receipt = preprocessing
    normal()
    receipt()
    retained = {path: path.read_bytes() for path in (root / "cache").glob("*.receipt")}
    main.write_bytes(b"int repeated;\n" * 2_000_000)
    request = {
        "schema": "btrc.native-preprocess.v1",
        "cache_directory": str(root / "cache"),
        "drivers": [os.environ["BTRC_NATIVE_PROVIDER_CC"]],
        "units": [{"id": "main", "cc1": expanded()}],
    }
    process = subprocess.Popen(
        [os.environ["BTRC_NATIVE_HEADER_READER"], "--native-preprocess=-"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=source,
        env={**os.environ, "SOURCE_DATE_EPOCH": "1"},
    )
    temporary = None
    try:
        process.stdin.write(json.dumps(request).encode())
        process.stdin.close()
        deadline = time.monotonic() + 30
        while process.poll() is None and time.monotonic() < deadline:
            with contextlib.suppress(FileNotFoundError):
                temporary = next((root / "cache/workers").glob("*/preprocessed-*.tmp"), None)
            if temporary is not None:
                process.send_signal(signal.SIGSTOP)
                assert temporary.is_file(), "the stopped worker must own a live Clang temporary output"
                break
            time.sleep(0.001)
        assert temporary is not None, "did not observe the actual Clang temporary output"
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=30)
        process.stdout.close()
        process.stderr.close()
    assert temporary.is_file()
    arguments = expanded()
    arguments[0] = "/usr/bin/clang"
    assert not run(arguments)["units"][0]["eligible"]
    assert not list((root / "cache/workers").iterdir())
    assert all(path.read_bytes() == data for path, data in retained.items())


def test_physical_header_identity_survives_a_normalized_name_collision(preprocessing):
    _, source, main, _, normal, _, receipt = preprocessing
    actual = source / "late/back\\slash.h"
    actual.write_text("#define VALUE 42 /* AAA */\n")
    (source / "late/back").mkdir()
    decoy = source / "late/back/slash.h"
    decoy.write_text("#define VALUE 42 /* AAA */\n")
    main.write_text('#include "back\\slash.h"\nint answer = VALUE;\n')
    normal()
    _, before, _ = receipt()
    assert receipt()[0]["cache_hit"]
    stat = actual.stat()
    actual.write_text("#define VALUE 42 /* BBB */\n")
    os.utime(actual, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    normal()
    unit, after, _ = receipt()
    assert not unit["cache_hit"]
    assert before["preprocessed"] == after["preprocessed"]
    assert before["buffers"] != after["buffers"]
    assert decoy.read_text() == "#define VALUE 42 /* AAA */\n"


def test_actual_cxx_driver_binds_its_own_compiler_image(preprocessing):
    root, source, main, _, _, run, _ = preprocessing
    driver = os.environ.get("BTRC_NATIVE_PROVIDER_CXX")
    if not driver:
        pytest.skip("configure the C++ compiler provider")
    main.write_text("template <typename T> struct Box { T value; }; Box<int> answer{42};\n")
    directory = root / "cxx"
    directory.mkdir()
    output = directory / "source.i"
    command = [
        driver,
        "-x",
        "c++",
        "-std=c++17",
        str(main),
        "-E",
        "-MD",
        "-MF",
        str(directory / "source.d"),
        "-MT",
        "btrc-object",
        "-Xclang",
        "-header-include-file",
        "-Xclang",
        str(directory / "headers.txt"),
        "-Xclang",
        "-fshow-skipped-includes",
        "-o",
        str(output),
    ]
    environment = {**os.environ, "SOURCE_DATE_EPOCH": "1"}
    normal = subprocess.run(command, cwd=source, env=environment, capture_output=True, timeout=30)
    assert normal.returncode == 0, normal.stderr
    expanded = subprocess.run(
        [*command, "-###"], cwd=source, env=environment, capture_output=True, text=True, timeout=30
    )
    assert expanded.returncode == 0, expanded.stderr
    jobs = [shlex.split(line.strip()) for line in expanded.stderr.splitlines() if line.lstrip().startswith('"')]
    assert len(jobs) == 1 and jobs[0][1] == "-cc1"
    request = {
        "schema": "btrc.native-preprocess.v1",
        "cache_directory": str(root / "cache"),
        "drivers": [driver],
        "units": [{"id": "cxx", "cc1": jobs[0]}],
    }
    for expected_hit in [False, True]:
        response = run(payload=request)
        assert len(response["contexts"]) == 1 and response["contexts"][0]["eligible"]
        assert response["contexts"][0]["compiler"] == str(Path(jobs[0][0]).resolve())
        unit = response["units"][0]
        assert unit["eligible"] and unit["cache_hit"] == expected_hit
        summary = json.loads(Path(unit["response"]["stdout"]["path"]).read_bytes())
        assert summary["preprocessed"] == hashlib.sha256(output.read_bytes()).hexdigest()
        assert Path(unit["response"]["stderr"]["path"]).read_bytes() == normal.stderr


def test_unrelated_directory_entries_do_not_repeat_preprocessing(preprocessing):
    _, source, _, _, normal, _, receipt = preprocessing
    normal()
    first, output, _ = receipt()
    assert not first["cache_hit"]
    (source / "unrelated-build-output").write_text("not a source input\n")
    second, reused, _ = receipt()
    assert second["cache_hit"] and reused == output


@pytest.mark.parametrize("change", ["permissions", "identity"])
def test_directory_identity_and_permissions_remain_dependencies(preprocessing, change):
    _, source, _, _, normal, _, receipt = preprocessing
    normal()
    receipt()
    assert receipt()[0]["cache_hit"]
    directory = source / "late"
    if change == "permissions":
        directory.chmod(0o700 if directory.stat().st_mode & 0o077 else 0o750)
    else:
        directory.rename(source / "old-late")
        directory.mkdir()
        # Keep the actual header's inode, bytes and timestamp; only the
        # directory binding changes.
        os.link(source / "old-late/value.h", directory / "value.h")
    assert not receipt()[0]["cache_hit"]


def test_prepare_only_miss_defers_preprocessing_to_a_worker(preprocessing):
    root, _, main, expanded, _, run, receipt = preprocessing
    main.write_text("#error preparation must not execute preprocessing\n")
    request = {
        "schema": "btrc.native-preprocess.v1",
        "cache_directory": str(root / "cache"),
        "drivers": [os.environ["BTRC_NATIVE_PROVIDER_CC"]],
        "capture": False,
        "units": [{"id": "main", "cc1": expanded()}],
    }
    unit = run(payload=request)["units"][0]
    assert unit["eligible"] and not unit["cache_hit"] and unit["reason"] == "receipt-miss"
    assert "response" not in unit and not list((root / "cache").glob("*.receipt"))
    main.write_text("int value;\n")
    receipt()
    unit = run(payload=request)["units"][0]
    assert unit["cache_hit"] and "response" in unit


@pytest.mark.parametrize("size", [65535, 65536, 65537, 131073])
def test_platform_digest_matches_current_bytes_across_update_boundaries(preprocessing, size):
    _, source, _, _, normal, _, receipt = preprocessing
    header = source / "late/value.h"
    prefix, suffix = b"#define VALUE 42\n/*", b"*/\n"
    contents = prefix + b"x" * (size - len(prefix) - len(suffix)) + suffix
    assert len(contents) == size
    header.write_bytes(contents)
    hashes, _ = normal()
    _, output, _ = receipt()
    assert all(output[name] == digest for name, digest in hashes.items())
    matched = [digest for path, digest in output["buffers"] if (source / path).resolve() == header]
    assert matched == [hashlib.sha256(contents).hexdigest()]
    assert receipt()[0]["cache_hit"]
