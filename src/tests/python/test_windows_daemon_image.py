"""Consumer-only supervisor image admission; native Windows ownership evidence is separate."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.abi.generated import TARGET_ROWS
from src.tests.c_toolchains import configured_c_compiler
from src.tests.process_limits import RUN_TIMEOUT, TOOL_TIMEOUT

REPO = Path(__file__).resolve().parents[3]
RUNTIME = REPO / "src/runtime/c"
HARNESS = REPO / "src/tests/native/daemon_windows/image_harness.c"
TARGETS = {row.label: row for row in TARGET_ROWS if row.operating_system == "windows" and row.environment == "gnu"}
STRICT = ["-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", "-O2"]


def run_build(command: list[str], *, success: bool = True):
    result = subprocess.run(command, capture_output=True, text=True, timeout=TOOL_TIMEOUT, check=False)
    if success:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0
    return result


def metadata(destination: Path, image: Path, label: str, *, protocol: int = 1, basename: str | None = None):
    digest = ", ".join(f"0x{byte:02x}" for byte in hashlib.sha256(image.read_bytes()).digest())
    destination.write_text(
        '#include "windows_daemon_image.h"\n'
        "const __btrc_windows_daemon_metadata_t __btrc_windows_daemon_metadata = {\n"
        f"    {{ {digest} }}, {protocol}, {json.dumps(label)}, {json.dumps(basename or image.name)}\n"
        "};\n"
    )


def test_non_windows_object_has_no_metadata_or_bcrypt_link_dependency(tmp_path):
    if sys.platform == "win32":
        pytest.skip("the unsupported branch belongs to non-Windows hosts")
    executable = tmp_path / "image-probe"
    run_build(
        [
            *configured_c_compiler(),
            *STRICT,
            "-I",
            str(RUNTIME),
            str(HARNESS),
            str(RUNTIME / "windows_daemon_image.c"),
            "-o",
            str(executable),
        ]
    )
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT, check=False)
    assert result.returncode == 0 and result.stdout.strip() == "image-unsupported PASS", result.stderr


@pytest.fixture(params=sorted(TARGETS), scope="module")
def bundle(request, tmp_path_factory):
    label = request.param
    target = TARGETS[label]
    root = tmp_path_factory.mktemp(f"daemon-image-{label}")
    driver = [shutil.which("zig"), "cc", "-target", target.zig_target, *STRICT, "-I", str(RUNTIME)]
    leaf = root / "Leaf.c"
    leaf.write_text("int main(void) { return 0; }\n")
    image = root / "consumer.exe.btrc-supervisor.exe"
    run_build([*driver, str(leaf), "-o", str(image)])
    native_object = root / "image.o"
    harness_object = root / "harness.o"
    for source, output in [(RUNTIME / "windows_daemon_image.c", native_object), (HARNESS, harness_object)]:
        run_build([*driver, "-c", str(source), "-o", str(output)])
    link = [*driver, str(harness_object), str(native_object), "-lbcrypt"]
    missing = run_build([*link, "-o", str(root / "missing.exe")], success=False)
    assert "__btrc_windows_daemon_metadata" in missing.stderr
    for name, abi, protocol, basename in [
        ("consumer", label, 1, image.name),
        ("bad-protocol", label, 2, image.name),
        ("bad-abi", "windows-invalid", 1, image.name),
        ("bad-name", label, 1, "../" + image.name),
    ]:
        source = root / f"{name}-metadata.c"
        metadata(source, image, abi, protocol=protocol, basename=basename)
        run_build([*link, str(source), "-o", str(root / f"{name}.exe")])
    evidence = os.environ.get("BTRC_WIN32_EVIDENCE_DIR")
    if evidence:
        output = Path(evidence) / f"daemon-image-{label}"
        output.mkdir(parents=True, exist_ok=True)
        for artifact in root.glob("*.exe"):
            shutil.copy2(artifact, output / artifact.name)
    return label, root


def test_consumer_image_object_requires_metadata_and_links_both_windows_abis(bundle):
    _, root = bundle
    assert (root / "consumer.exe").read_bytes().startswith(b"MZ")


def test_native_image_verification_holds_and_releases_files(bundle, tmp_path):
    label, built = bundle
    if sys.platform != "win32":
        pytest.skip("requires native Windows image and directory handles")
    if label == "windows-aarch64" and os.environ.get("PROCESSOR_ARCHITECTURE", "").upper() != "ARM64":
        pytest.skip("ARM64 image requires an ARM64 Windows host")
    root = tmp_path / "image tests é😀"
    shutil.copytree(built, root)

    def probe(name="consumer", *, refusal=False, code=0):
        result = subprocess.run(
            [str(root / f"{name}.exe"), *(["--refuse", str(code)] if refusal else [])],
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT,
            check=False,
        )
        assert result.returncode == 0, (result.stdout, result.stderr, result.returncode)
        assert result.stdout.strip() == ("image-refusal PASS" if refusal else "image-verification PASS")

    probe()
    shutil.copy2(root / "consumer.exe", root / "renamed.exe")
    probe("renamed")
    for name, code in (("bad-protocol", 1306), ("bad-abi", 1306), ("bad-name", 123)):
        probe(name, refusal=True, code=code)
    image = root / "consumer.exe.btrc-supervisor.exe"
    original = image.read_bytes()
    with image.open("r+b"):
        probe(refusal=True, code=0xC0000043)  # Raw STATUS_SHARING_VIOLATION from relative open.
    image.write_bytes(original + b"changed final bytes")
    probe(refusal=True, code=23)  # ERROR_CRC after hashing the changed bytes.
    image.write_bytes(b"bad" + original[3:])
    probe(refusal=True, code=193)  # ERROR_BAD_EXE_FORMAT before hashing.
    wrong_machine = bytearray(original)
    pe = int.from_bytes(original[60:64], "little")
    wrong_machine[pe + 4 : pe + 6] = (0x8664 if label == "windows-aarch64" else 0xAA64).to_bytes(2, "little")
    image.write_bytes(wrong_machine)
    probe(refusal=True, code=193)
    image.write_bytes(original)
    image.rename(root / "wrong-name.exe")
    probe(refusal=True)
