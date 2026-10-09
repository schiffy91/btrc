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
from src.tests.process_limits import TOOL_TIMEOUT
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
    # A library replaced at a known path is part of the last receipt's
    # inventory, unchanged across this link, so one link qualifies. A library
    # appearing where the last link found none (directly or through a moved
    # search alias) voids that inventory.
    expected_links = 1 if change == "same-mtime" else 2
    assert changed.links == expected_links and changed.link_cache_status == "stored"
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
    # A damaged output with intact inputs relinks once: the link reports the
    # last receipt's inventory, unchanged across it. A damaged receipt has no
    # inventory to predict, so it takes the discovery and qualifying links.
    assert report.links == (2 if damage == "receipt" else 1) and report.link_cache_status == "stored"
    assert output(options) == "1\n"


def test_an_unchanged_input_inventory_qualifies_a_relink_with_one_link(tmp_path):
    options, _early, _late = library_build(tmp_path)
    assert NativePlanBuilder().build(**options).links == 2
    options["output"].unlink()
    report = NativePlanBuilder().build(**options)
    assert report.links == 1 and report.link_cache_status == "stored"
    assert output(options) == "1\n"
    assert NativePlanBuilder().build(**options).links == 0


def test_an_input_changed_during_a_predicted_link_takes_the_qualifying_link(tmp_path):
    options, _early, late = library_build(tmp_path)
    NativePlanBuilder().build(**options)
    options["output"].unlink()
    changed = False

    def run(command, **kwargs):
        nonlocal changed
        result = subprocess.run(command, **kwargs)
        if "-dependency_info" in command and not changed:
            changed = True
            archive(late, 2)
        return result

    report = NativePlanBuilder(runner=run).build(**options)
    assert report.links == 2 and report.link_cache_status == "stored"
    assert output(options) == "2\n"


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
    # The receipt for this output predicts the link's input inventory; the
    # release configuration and later source changes alter objects and the
    # context, not that inventory, so each relink qualifies with one link.
    assert release.link_cache_status == "stored" and release.links == 1
    assert NativePlanBuilder().build(**options).links == 0
    original = options["generated_c"].stat()
    options["generated_c"].write_text(options["generated_c"].read_text().replace("first", "other"))
    os.utime(options["generated_c"], ns=(original.st_atime_ns, original.st_mtime_ns))
    assert NativePlanBuilder().build(**options).links == 1
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
    # Deliberately Nix's Clang: link reuse is the store-pinned toolchain's contract.
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
    # Without the last receipt's inventory the relink needs a verification link.
    next((options["object_cache"] / "links").glob("link-v1-*.json")).unlink()
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
    # A replaced driver changes the context, not the link's input inventory.
    assert report.as_dict()["compiled_units"] == 1 and report.links == 1
    assert output(options) == "2\n"


def test_scratch_directories_do_not_change_cache_identities(tmp_path, monkeypatch):
    """Each `nix develop` shell draws new scratch directories; a build from a
    new shell must still reuse the objects and executable of the last one."""
    options = setup_build(tmp_path)
    for name in ("first", "second"):
        (tmp_path / name).mkdir()
    for variable in ("TMPDIR", "TMP", "TEMP", "TEMPDIR", "NIX_BUILD_TOP"):
        monkeypatch.setenv(variable, str(tmp_path / "first"))
    assert NativePlanBuilder().build(**options).link_cache_status == "stored"
    for variable in ("TMPDIR", "TMP", "TEMP", "TEMPDIR", "NIX_BUILD_TOP"):
        monkeypatch.setenv(variable, str(tmp_path / "second"))
    report = NativePlanBuilder().build(**options)
    assert report.as_dict()["compiled_units"] == 0
    assert report.link_cache_status == "hit" and report.links == 0


@pytest.mark.parametrize("identifier", [None, "org.btrc.signed-link"])
def test_signed_link_retains_signature_and_executable_on_warm_and_touch(tmp_path, identifier):
    from tools.native_plan import DarwinSigning

    options = setup_build(tmp_path)
    options["output"] = tmp_path / "program.reference"
    NativePlanBuilder().build(**options)
    # Compare the existing caller's signing semantics with staged signing.
    command = ["/usr/bin/codesign", "--force", "--sign", "-"]
    if identifier is not None:
        command.extend(["--identifier", identifier])
    subprocess.run([*command, str(options["output"])], check=True, capture_output=True, timeout=TOOL_TIMEOUT)

    def requirement():
        return subprocess.run(
            ["/usr/bin/codesign", "-d", "-r-", str(options["output"])],
            check=True,
            capture_output=True,
            text=True,
            timeout=TOOL_TIMEOUT,
        ).stdout

    def signature_identifier():
        details = subprocess.run(
            ["/usr/bin/codesign", "-dvv", str(options["output"])],
            check=True,
            capture_output=True,
            text=True,
            timeout=TOOL_TIMEOUT,
        ).stderr
        return next(line for line in details.splitlines() if line.startswith("Identifier="))

    original_requirement = requirement()
    original_identifier = signature_identifier()
    options["signing"] = DarwinSigning("-", identifier=identifier)
    cold = NativePlanBuilder().build(**options)
    assert cold.link_cache_status == "stored" and cold.links > 0
    assert requirement() == original_requirement
    before = identity(options["output"])
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.run(command, **kwargs)

    warm = NativePlanBuilder(runner=run).build(**options)
    assert warm.links == 0 and warm.as_dict()["compiled_units"] == 0
    assert warm.link_cache_status == "hit"
    assert not any("--force" in command for command in calls)
    assert identity(options["output"]) == before
    options["generated_c"].touch()
    assert NativePlanBuilder().build(**options).links == 0
    assert identity(options["output"]) == before
    options["generated_c"].write_text(options["generated_c"].read_text().replace("first", "other"))
    assert NativePlanBuilder().build(**options).links > 0
    # Ad-hoc requirements contain a content hash; the default linker-derived
    # identifier can change too. Preserve the caller's actual codesign policy,
    # not an invented stability promise for ad-hoc identities.
    assert requirement() != original_requirement
    if identifier is not None:
        assert signature_identifier() == original_identifier
    changed_requirement, changed_identifier = requirement(), signature_identifier()
    subprocess.run([*command, str(options["output"])], check=True, capture_output=True, timeout=TOOL_TIMEOUT)
    assert (requirement(), signature_identifier()) == (changed_requirement, changed_identifier)
    assert output(options) == "other\n"


@pytest.mark.parametrize("failure", ["sign", "verify"])
def test_signing_failure_preserves_previous_executable_and_receipt(tmp_path, failure):
    from tools.native_plan import DarwinSigning

    options = setup_build(tmp_path)
    options["signing"] = DarwinSigning("-")
    NativePlanBuilder().build(**options)
    before = identity(options["output"])
    receipt = next((options["object_cache"] / "links").glob("link-v1-*.json"))
    receipt_before = identity(receipt)
    options["generated_c"].write_text(options["generated_c"].read_text().replace("first", "other"))

    def run(command, **kwargs):
        if command[0] == "/usr/bin/codesign" and ("--force" if failure == "sign" else "--verify") in command:
            Path(command[-1]).write_bytes(b"failed staged signing")
            return subprocess.CompletedProcess(command, 1, "", "injected signing failure")
        return subprocess.run(command, **kwargs)

    with pytest.raises(NativePlanError, match="injected signing failure"):
        NativePlanBuilder(runner=run).build(**options)
    assert identity(options["output"]) == before
    assert identity(receipt) == receipt_before
    assert output(options) == "first\n"


@pytest.mark.parametrize("change", ["identifier", "tool", "tamper"])
def test_signed_link_revalidates_configuration_and_output(tmp_path, change):
    from tools.native_plan import DarwinSigning

    options = setup_build(tmp_path)
    tool = tmp_path / "codesign"
    tool.write_text('#!/bin/sh\nexec /usr/bin/codesign "$@"\n# first\n')
    tool.chmod(0o755)
    options["signing"] = DarwinSigning("-", identifier="org.btrc.first", tool=str(tool))
    assert NativePlanBuilder().build(**options).link_cache_status == "stored"
    assert NativePlanBuilder().build(**options).links == 0
    if change == "identifier":
        options["signing"] = DarwinSigning("-", identifier="org.btrc.other", tool=str(tool))
    else:
        path = tool if change == "tool" else options["output"]
        metadata = path.stat()
        before = path.read_bytes()
        after = before.replace(b"# first", b"# other") if change == "tool" else before[:-1] + bytes([before[-1] ^ 1])
        assert len(after) == len(before) and after != before
        path.write_bytes(after)
        os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    changed = NativePlanBuilder().build(**options)
    assert changed.links > 0 and changed.as_dict()["compiled_units"] == 0
    assert NativePlanBuilder().build(**options).links == 0
    assert output(options) == "first\n"


def test_signer_changed_during_receipt_validation_is_not_a_hit(tmp_path, monkeypatch):
    from tools.native_plan import DarwinSigning, _DarwinLinkReceipt

    options = setup_build(tmp_path)
    tool = tmp_path / "codesign"
    tool.write_text('#!/bin/sh\nexec /usr/bin/codesign "$@"\n# first\n')
    tool.chmod(0o755)
    options["signing"] = DarwinSigning("-", tool=str(tool))
    NativePlanBuilder().build(**options)
    before = identity(options["output"])
    receipt = next((options["object_cache"] / "links").glob("link-v1-*.json"))
    receipt_before = identity(receipt)
    retained = _DarwinLinkReceipt.retained

    def replace_signer(owner, context):
        result = retained(owner, context)
        assert result
        tool.write_text(tool.read_text().replace("# first", "# other"))
        return result

    monkeypatch.setattr(_DarwinLinkReceipt, "retained", replace_signer)
    with pytest.raises(NativePlanError, match="codesign configuration changed"):
        NativePlanBuilder().build(**options)
    assert identity(options["output"]) == before
    assert identity(receipt) == receipt_before
