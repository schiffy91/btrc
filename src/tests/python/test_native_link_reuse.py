"""Actual links and executable behavior qualify Darwin link receipt reuse."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import NativeLinkPlan, PackageTarget
from tools.native_plan import NativePlanBuilder, NativePlanError

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="Darwin dependency-info link receipts")


def setup_build(tmp_path, *, cc="/usr/bin/clang", debug=True):
    source, plan = tmp_path / "main.c", tmp_path / "plan.json"
    source.write_text('#include <stdio.h>\nint main(void) { puts("first"); return 0; }\n')
    plan.write_text(
        json.dumps(NativeLinkPlan.empty(PackageTarget.parse(None)).as_dict(), sort_keys=True, separators=(",", ":"))
        + "\n"
    )
    return dict(
        plan_path=plan,
        generated_c=source,
        output=tmp_path / "program",
        cc=cc,
        object_cache=tmp_path / "cache",
        debug_info=debug,
        optimization=0,
    )


def output(options):
    return subprocess.run([options["output"]], check=True, capture_output=True, text=True, timeout=15).stdout


def identity(path):
    metadata = path.stat()
    return path.read_bytes(), metadata.st_ino, metadata.st_mtime_ns, metadata.st_mode


@pytest.mark.parametrize("debug", [False, True])
def test_unchanged_link_retains_executable_and_reports_zero_links(tmp_path, debug):
    options = setup_build(tmp_path, debug=debug)
    cold = NativePlanBuilder().build(**options)
    assert cold.link_cache_status == "stored" and cold.links == 2
    before = identity(options["output"])
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.run(command, **kwargs)

    warm = NativePlanBuilder(runner=run).build(**options)
    assert warm.link_cache_status == "hit" and warm.as_dict()["links"] == 0 and warm.link_s == 0
    assert warm.as_dict()["compiled_units"] == 0
    assert all("-dependency_info" not in command for command in calls), calls
    assert identity(options["output"]) == before
    assert output(options) == "first\n"
    options["generated_c"].touch()
    assert NativePlanBuilder().build(**options).links == 0
    assert identity(options["output"]) == before


def library_build(tmp_path, *, early_exists=True, cc="/usr/bin/clang"):
    options = setup_build(tmp_path, cc=cc)
    options["generated_c"].write_text(
        '#include <stdio.h>\nint choice(void); int main(void) { printf("%d\\n", choice()); return 0; }\n'
    )
    early, late = tmp_path / "early", tmp_path / "late"
    if early_exists:
        early.mkdir()
    late.mkdir()
    archive(late, 1, cc)
    payload = json.loads(options["plan_path"].read_text())
    payload["packages"] = [{"name": "Choice", "root": str(tmp_path), "dependencies": {}}]
    payload["pkg-config"] = [{"package": "Choice", "name": "choice"}]
    options["plan_path"].write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    config = tmp_path / "pkg-config"
    flags = shlex.join([f"-L{early}", f"-L{late}", "-lchoice"])
    config.write_text('#!/bin/sh\nif [ "$1" = --libs ]; then printf "%s\\n" ' + shlex.quote(flags) + "; fi\n")
    config.chmod(0o755)
    options["pkg_config"] = str(config)
    return options, early, late


def archive(directory, value, cc="/usr/bin/clang"):
    source, obj, library = directory / "choice.c", directory / "choice.o", directory / "libchoice.a"
    source.write_text(f"int choice(void) {{ return {value}; }}\n")
    subprocess.run([cc, "-c", str(source), "-o", str(obj)], check=True, capture_output=True, timeout=30)
    subprocess.run(["/usr/bin/ar", "rcs", str(library), str(obj)], check=True, capture_output=True, timeout=30)
    return library


@pytest.mark.parametrize("change", ["same-mtime", "earlier-library", "earlier-directory", "search-alias"])
def test_library_changes_relink_without_recompiling_sources(tmp_path, change):
    options, early, late = library_build(tmp_path, early_exists=change not in {"earlier-directory", "search-alias"})
    if change == "search-alias":
        other = tmp_path / "empty"
        other.mkdir()
        early.symlink_to(other, target_is_directory=True)
    assert NativePlanBuilder().build(**options).link_cache_status == "stored"
    assert NativePlanBuilder().build(**options).links == 0
    assert output(options) == "1\n"
    if change == "same-mtime":
        old = (late / "libchoice.a").stat()
        library = archive(late, 2)
        assert library.stat().st_size == old.st_size
        os.utime(library, ns=(old.st_atime_ns, old.st_mtime_ns))
    elif change == "search-alias":
        selected = tmp_path / "selected"
        selected.mkdir()
        archive(selected, 2)
        early.unlink()
        early.symlink_to(selected, target_is_directory=True)
    else:
        early.mkdir(exist_ok=True)
        archive(early, 2)
    changed = NativePlanBuilder().build(**options)
    assert changed.as_dict()["compiled_units"] == 0
    assert changed.links == 2 and changed.link_cache_status == "stored"
    assert output(options) == "2\n"
    assert NativePlanBuilder().build(**options).links == 0


@pytest.mark.parametrize("damage", ["missing-output", "corrupt-output", "mode", "receipt", "missing-library"])
def test_invalid_receipt_or_output_is_never_a_hit(tmp_path, damage):
    options, _early, late = library_build(tmp_path)
    NativePlanBuilder().build(**options)
    if damage == "missing-output":
        options["output"].unlink()
    elif damage == "corrupt-output":
        options["output"].write_bytes(b"damaged")
    elif damage == "mode":
        options["output"].chmod(0o600)
    elif damage == "receipt":
        next((options["object_cache"] / "links").glob("link-v1-*.json")).write_text("{}")
    else:
        (late / "libchoice.a").unlink()
        before = identity(options["output"])
        with pytest.raises(NativePlanError, match="native build command failed"):
            NativePlanBuilder().build(**options)
        assert identity(options["output"]) == before
        return
    report = NativePlanBuilder().build(**options)
    assert report.links == 2 and report.link_cache_status == "stored"
    assert output(options) == "1\n"


def test_library_mutation_during_verified_link_does_not_publish_receipt(tmp_path):
    options, _early, late = library_build(tmp_path)
    count = 0

    def run(command, **kwargs):
        nonlocal count
        result = subprocess.run(command, **kwargs)
        if "-dependency_info" in command:
            count += 1
            if count == 2:
                archive(late, 2)
        return result

    report = NativePlanBuilder(runner=run).build(**options)
    assert report.link_cache_status == "unverified-inputs" and report.links == 2
    assert not list((options["object_cache"] / "links").glob("link-v1-*.json"))
    assert output(options) == "1\n"
    assert NativePlanBuilder().build(**options).link_cache_status == "stored"
    assert output(options) == "2\n"


def test_debug_release_and_source_changes_have_separate_identity(tmp_path):
    options = setup_build(tmp_path)
    first = NativePlanBuilder().build(**options)
    assert first.link_cache_status == "stored"
    options.update(debug_info=False, optimization=2)
    release = NativePlanBuilder().build(**options)
    assert release.link_cache_status == "stored" and release.links == 2
    assert NativePlanBuilder().build(**options).links == 0
    original = options["generated_c"].stat()
    options["generated_c"].write_text(options["generated_c"].read_text().replace("first", "other"))
    os.utime(options["generated_c"], ns=(original.st_atime_ns, original.st_mtime_ns))
    assert NativePlanBuilder().build(**options).links == 2
    assert output(options) == "other\n"


def test_opaque_wrapper_bypasses_link_reuse(tmp_path):
    options = setup_build(tmp_path)
    wrapper = tmp_path / "cc"
    wrapper.write_text('#!/bin/sh\nexec /usr/bin/clang "$@"\n')
    wrapper.chmod(0o755)
    options["cc"] = str(wrapper)
    for _ in range(2):
        result = NativePlanBuilder().build(**options)
        assert result.links == 1 and result.link_cache_status == "unsupported-input"


def test_nix_toolchain_can_reuse_link(tmp_path):
    cc = os.environ.get("BTRC_TEST_NIX_CLANG") or shutil.which("clang")
    if cc is None or not Path(cc).resolve().is_relative_to("/nix/store"):
        pytest.skip("Nix Clang toolchain is unavailable")
    options = setup_build(tmp_path, cc=cc)
    assert NativePlanBuilder().build(**options).link_cache_status == "stored"
    before = identity(options["output"])
    assert NativePlanBuilder().build(**options).links == 0
    assert identity(options["output"]) == before


@pytest.mark.parametrize("shared_cache", [False, True])
def test_concurrent_configurations_cannot_reuse_each_others_executable(tmp_path, shared_cache):
    from concurrent.futures import ThreadPoolExecutor

    configurations = []
    for index in range(2):
        directory = tmp_path / str(index)
        directory.mkdir()
        options = setup_build(directory, debug=bool(index))
        options["generated_c"].write_text(f'#include <stdio.h>\nint main(void) {{ puts("{index}"); return 0; }}\n')
        options["output"] = tmp_path / "program"
        if shared_cache:
            options["object_cache"] = tmp_path / "shared-cache"
        configurations.append(options)
    with ThreadPoolExecutor(max_workers=2) as pool:
        reports = list(pool.map(lambda options: NativePlanBuilder().build(**options), configurations))
    assert all(report.link_cache_status == "stored" for report in reports)
    for index, options in enumerate(configurations):
        NativePlanBuilder().build(**options)
        assert output(options) == f"{index}\n"
        assert NativePlanBuilder().build(**options).links == 0
        assert output(options) == f"{index}\n"


def test_failed_verification_link_preserves_previous_executable(tmp_path):
    options = setup_build(tmp_path)
    NativePlanBuilder().build(**options)
    before = identity(options["output"])
    options["generated_c"].write_text(options["generated_c"].read_text().replace("first", "other"))
    links = 0

    def run(command, **kwargs):
        nonlocal links
        if "-dependency_info" in command:
            links += 1
            if links == 2:
                return subprocess.CompletedProcess(command, 1, "", "injected verification link failure")
        return subprocess.run(command, **kwargs)

    with pytest.raises(NativePlanError, match="injected verification link failure"):
        NativePlanBuilder(runner=run).build(**options)
    assert identity(options["output"]) == before
    assert output(options) == "first\n"
    assert NativePlanBuilder().build(**options).link_cache_status == "stored"
    assert output(options) == "other\n"


def test_linker_response_file_bypasses_reuse(tmp_path):
    options, _early, _late = library_build(tmp_path)
    response = tmp_path / "link-flags.txt"
    response.write_text("-dead_strip\n")
    config = Path(options["pkg_config"])
    original = config.read_text()
    # pkg-config is still the argument authority; the adapter declines reuse
    # when the linker reads an additional argument language from a file.
    config.write_text(original.replace("; fi", '; printf "%s\\n" ' + shlex.quote("-Wl,@" + str(response)) + "; fi"))
    for _ in range(2):
        report = NativePlanBuilder().build(**options)
        assert report.link_cache_status == "unsupported-input" and report.links == 1
        assert output(options) == "1\n"


def test_compiler_replacement_at_same_path_invalidates_receipt(tmp_path):
    options = setup_build(tmp_path)
    options["generated_c"].write_text('#include <stdio.h>\nint main(void) { printf("%d\\n", CHOICE); return 0; }\n')
    driver = tmp_path / "driver"
    fixture = tmp_path / "driver.c"

    # A real native forwarding executable keeps the reported Clang version
    # unchanged while its own implementation and injected compile define change.
    def compile_driver(value):
        fixture.write_text(
            "#include <stdlib.h>\n#include <unistd.h>\n"
            "int main(int argc, char **argv) { char **args=calloc((size_t)argc+2,sizeof(char*)); "
            'args[0]="/usr/bin/clang"; '
            f'args[1]="-DCHOICE={value}"; '
            "for(int i=1;i<argc;i++) args[i+1]=argv[i]; execv(args[0],args); return 127; }\n"
        )
        candidate = tmp_path / "new-driver"
        subprocess.run(
            ["/usr/bin/clang", str(fixture), "-o", str(candidate)], check=True, capture_output=True, timeout=30
        )
        candidate.replace(driver)

    compile_driver(1)
    options["cc"] = str(driver)
    assert NativePlanBuilder().build(**options).link_cache_status == "stored"
    assert NativePlanBuilder().build(**options).links == 0
    assert output(options) == "1\n"
    before = driver.stat()
    compile_driver(2)
    assert driver.stat().st_size == before.st_size
    os.utime(driver, ns=(before.st_atime_ns, before.st_mtime_ns))
    report = NativePlanBuilder().build(**options)
    assert report.as_dict()["compiled_units"] == 1 and report.links == 2
    assert output(options) == "2\n"
