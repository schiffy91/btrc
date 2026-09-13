"""Owner-admitted SDK record snapshots, including hostile strided-plane metadata."""

import subprocess
from pathlib import Path

import pytest

from src.tests.python.test_native_import_consumer import apple_environment
from src.tests.python.test_native_import_consumer import native_compile as native_compile
from src.tests.python.test_native_import_consumer import native_project as native_project
from tools.native_plan import NativePlanBuilder


@pytest.fixture(params=["unique", "reference-counted"], ids=["unique", "rc"])
def snapshot_project(native_project, request):
    source, _, _ = native_project
    root = source.parent.parent
    # Test-only SDK manufacture. The compiler generates every snapshot accessor
    # and byte copy; this fixture exports only owner creation/mutation/destruction.
    (root / "Snapshot.h").write_text("""#include <stdlib.h>
#include <stdint.h>
#include <limits.h>
typedef struct SnapshotPlane { int width; long long rows, pitch; unsigned char *data; int value; } SnapshotPlane;
typedef struct SnapshotOwner { SnapshotPlane *plane; unsigned char storage[8]; int references; } *SnapshotOwner;
static int living;
static SnapshotOwner CreateSnapshotOwner(void) {
    SnapshotOwner owner = calloc(1, sizeof(*owner)); if (!owner) abort();
    owner->plane = calloc(1, sizeof(*owner->plane)); if (!owner->plane) abort();
    ++living; owner->references = 1; return owner;
}
static inline SnapshotOwner RetainSnapshotOwner(SnapshotOwner owner) { if (owner) ++owner->references; return owner; }
static void DestroySnapshotOwner(SnapshotOwner owner) { if (owner && --owner->references == 0) { free(owner->plane); free(owner); --living; } }
static int SnapshotLiving(void) { return living; }
static void ConfigureSnapshot(SnapshotOwner owner, int mode) {
    SnapshotPlane *plane = owner->plane;
    if (mode == 99) { free(plane); owner->plane = NULL; return; }
    for (int i = 0; i < 8; ++i) owner->storage[i] = (unsigned char)(i + 1);
    plane->width = 2; plane->rows = 2; plane->pitch = 4; plane->data = owner->storage; plane->value = 42;
    if (mode == 1) { plane->pitch = -4; plane->data += 4; }
    if (mode == 2) plane->width = 0;
    if (mode == 3) plane->rows = 0;
    if (mode == 4) plane->width = -1;
    if (mode == 5) plane->rows = -1;
    if (mode == 6) plane->pitch = 0;
    if (mode == 7) plane->data = NULL;
    if (mode == 8) plane->pitch = LLONG_MIN;
    if (mode == 9) plane->rows = LLONG_MAX;
    if (mode == 10) plane->data = (unsigned char *)(uintptr_t)(UINTPTR_MAX - 3);
    if (mode == 11) { plane->pitch = -4; plane->data = (unsigned char *)(uintptr_t)3; }
    if (mode == 2 || mode == 3) { plane->data = NULL; plane->pitch = LLONG_MIN; }
}
""")
    (source.parent / "Snapshot.btrc").write_text("import Library.Bytes;\n")
    (root / "btrc.toml").write_text("""manifest-version = 1
[package]
name = "recordSnapshots"
[[native.bindings]]
module = "Snapshot"
header = "Snapshot.h"
language = "c"
standard = "c11"
symbols = ["SnapshotOwner", "CreateSnapshotOwner", "DestroySnapshotOwner", "SnapshotLiving", "ConfigureSnapshot"]
owned-results = ["CreateSnapshotOwner"]
borrowed-parameters = ["ConfigureSnapshot.owner"]
[native.bindings.resources.SnapshotOwner]
ownership = "unique"
release = "DestroySnapshotOwner"
[native.bindings.record-snapshots.CopiedSnapshot]
owner = "SnapshotOwner"
name = "copySnapshot"
fields = { value = "plane.value", width = "plane.width", rows = "plane.rows", pitch = "plane.pitch" }
[native.bindings.record-snapshots.CopiedSnapshot.byte-plane]
field = "pixels"
pointer = "plane.data"
width = "plane.width"
rows = "plane.rows"
pitch = "plane.pitch"
""")
    if request.param == "reference-counted":
        manifest = root / "btrc.toml"
        manifest.write_text(
            manifest.read_text()
            .replace('"CreateSnapshotOwner",', '"CreateSnapshotOwner", "RetainSnapshotOwner",')
            .replace('ownership = "unique"', 'ownership = "reference-counted"\nretain = "RetainSnapshotOwner"')
        )
    return source


@pytest.mark.parametrize("sanitize", [False, True])
def test_owned_snapshot_plane(snapshot_project, native_compile, sanitize):
    source = snapshot_project
    source.write_text("""import ./Snapshot.btrc;
import Library.Bytes;
#include <assert.h>
int main() {
    for (int iteration = 0; iteration < 100; iteration++) {
        var owner = CreateSnapshotOwner();
        if (owner == null) { throw "Cannot create snapshot test owner"; }
        ConfigureSnapshot(owner, 0);
        assert(copySnapshot(owner, -1) == null);
        assert(copySnapshot(owner, 0) == null);
        assert(copySnapshot(owner, 7) == null);
        var first = copySnapshot(owner, 8);
        if (first == null) { throw "Cannot snapshot positive plane"; }
        assert(first.value == 42 && first.pitch == 4LL && first.pixels.length() == 8);
        for (int i = 0; i < 8; i++) { assert(first.pixels.get(i) == i + 1); }
        ConfigureSnapshot(owner, 1);
        var second = copySnapshot(owner, 8);
        if (second == null) { throw "Cannot snapshot negative plane"; }
        assert(second.pitch == -4LL && second.pixels.length() == 8);
        for (int i = 0; i < 8; i++) { assert(second.pixels.get(i) == i + 1); }
        for (int mode = 2; mode < 12; mode++) {
            ConfigureSnapshot(owner, mode);
            var checked = copySnapshot(owner, 2147483647);
            if (mode == 2 || mode == 3) {
                if (checked == null) { throw "Empty snapshot must be owned"; }
                assert(checked.pixels.length() == 0);
                assert(copySnapshot(owner, 0) != null);
            } else { assert(checked == null); }
        }
        ConfigureSnapshot(owner, 99);
        assert(copySnapshot(owner, 8) == null);
        owner.close();
        assert(SnapshotLiving() == 0);
        assert(first.pixels.get(0) == 1 && second.pixels.get(7) == 8);
    }
    return 0;
}
""")
    if 'ownership = "reference-counted"' in (source.parent.parent / "btrc.toml").read_text():
        source.write_text(source.read_text().replace("owner.close();", "owner = null;"))
    plan = source.with_suffix(".link.json")
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    assert not compiled.diagnostics
    generated = source.with_suffix(".c")
    generated.write_text(compiled.c_source)

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    executable = source.with_suffix(".exe")
    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    result = subprocess.run([str(executable)], capture_output=True, text=True, env=apple_environment(), timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "before,after",
    [
        ('owner = "SnapshotOwner"', "owner = []"),
        ('name = "copySnapshot"', 'name = "ConfigureSnapshot"'),
        ('value = "plane.value"', 'value = "plane.unknown"'),
        ('value = "plane.value"', 'value = "plane.data"'),
        ('pitch = "plane.pitch"', 'pitch = "plane.data"'),
        ('pointer = "plane.data"', 'pointer = "plane.value"'),
        ('rows = "plane.rows"', 'rows = "plane.data"'),
        ('field = "pixels"', 'field = "value"'),
    ],
)
def test_snapshot_rejects_invalid_contract(snapshot_project, native_compile, before, after):
    source = snapshot_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(manifest.read_text().replace(before, after))
    source.write_text("import ./Snapshot.btrc;\nint main() { return 0; }\n")
    result = native_compile(source)
    assert not result.successful
    assert not result.c_source


@pytest.mark.parametrize(
    "before,after",
    [
        ("int width;", "double width;"),
        ("long long rows, pitch;", "long long rows; unsigned long long pitch;"),
        ("SnapshotPlane *plane;", "volatile SnapshotPlane *plane;"),
    ],
)
def test_snapshot_rejects_unsupported_sdk_field_types(snapshot_project, native_compile, before, after):
    source = snapshot_project
    header = source.parent.parent / "Snapshot.h"
    header.write_text(header.read_text().replace(before, after))
    source.write_text("import ./Snapshot.btrc;\nint main() { return 0; }\n")
    result = native_compile(source)
    assert not result.successful
    assert not result.c_source


def test_snapshot_copy_requires_authenticated_bytes(snapshot_project, native_compile):
    source = snapshot_project
    (source.parent / "Snapshot.btrc").write_text(
        "class Bytes { class Bytes fromRaw(char* data, int length) { return new Bytes(); } }\n"
    )
    source.write_text("import ./Snapshot.btrc;\nint main() { return 0; }\n")
    result = native_compile(source)
    assert not result.successful
    assert not result.c_source
    assert "authenticated import Library.Bytes" in str(result.failure) + str(result.diagnostics)


def test_snapshot_rejects_empty_byte_plane(snapshot_project, native_compile):
    source = snapshot_project
    manifest = source.parent.parent / "btrc.toml"
    marker = "[native.bindings.record-snapshots.CopiedSnapshot.byte-plane]"
    manifest.write_text(manifest.read_text().split(marker)[0] + marker + "\n")
    source.write_text("import ./Snapshot.btrc;\nint main() { return 0; }\n")
    result = native_compile(source)
    assert not result.successful
    assert not result.c_source
