"""Self-host emitted generations: fresh resolution, reuse and real native execution."""

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

from src.tests.python.test_native_import_consumer import native_project as native_project
from tools.native_plan import NativePlanBuilder

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.skipif(os.name == "nt", reason="native private artifact storage is not available on Windows")


class ArtifactBuild:
    def __init__(self, compiler, root, source, monkeypatch, *, target=None):
        self.compiler = compiler
        self.root = root
        self.source = source
        self.generated = root / "program.c"
        self.plan = root / "program.link.json"
        self.cache = root / "cache"
        host_os = "macos" if sys.platform == "darwin" else "linux"
        host_arch = "arm64" if platform.machine() in {"arm64", "aarch64"} else "x64"
        self.target = target or f"{host_os}-{host_arch}"
        monkeypatch.setenv("BTRC_CACHE_DIR", str(self.cache))
        monkeypatch.setenv("BTRC_STATE_DIR", str(root / "state"))
        monkeypatch.setenv("BTRC_UNIT_LINES", "120")
        monkeypatch.setenv("BTRC_TIMING", "1")

    def compile(self, *, hit, extra=(), success=True):
        command = [
            str(self.compiler),
            "--no-stdlib",
            "--debug",
            "--emit-units",
            str(self.generated),
            "--emit-link-plan",
            str(self.plan),
            "-o",
            str(self.generated),
        ]
        if self.target:
            command.extend(["--target", self.target])
        result = subprocess.run(
            [*command, *extra, str(self.source)], cwd=ROOT, capture_output=True, text=True, timeout=120
        )
        assert (result.returncode == 0) == success, result.stderr
        assert ("artifact-hit=" in result.stderr) == hit, result.stderr
        if hit:
            assert "lex=" not in result.stderr, result.stderr
        return result

    def output_files(self):
        plan = json.loads(self.plan.read_text())
        return [self.generated, *(Path(path) for path in plan.get("emitted-units", [])), self.plan]

    def execute(self, expected):
        executable = self.root / "program"
        NativePlanBuilder().build(plan_path=self.plan, generated_c=self.generated, output=executable)
        run = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
        assert run.returncode == 0, run.stderr
        assert run.stdout == f"{expected}\n"


@pytest.fixture
def artifact_build(immutable_btrcc, tmp_path, monkeypatch):
    source = tmp_path / "Main.btrc"
    helper = tmp_path / "Helper.btrc"
    helper.write_text("int extra() { return 1; }\n" + "\n".join(f"int value{i}() {{ return {i}; }}" for i in range(40)))
    source.write_text(
        'import ./Helper.btrc;\nint main() { printf("%d\\n", extra() + '
        + " + ".join(f"value{i}()" for i in range(40))
        + "); return 0; }\n"
    )
    return ArtifactBuild(immutable_btrcc, tmp_path, source, monkeypatch)


def test_selfhost_restores_complete_generation_after_outputs_removed(artifact_build):
    build = artifact_build
    build.compile(hit=False)
    files = build.output_files()
    assert len(files) > 2
    original = {path: path.read_bytes() for path in files}
    build.execute(781)
    for path in files:
        path.unlink()
    build.compile(hit=True)
    assert {path: path.read_bytes() for path in build.output_files()} == original
    build.execute(781)
    build.compile(hit=False, extra=("--no-cache",))
    assert {path: path.read_bytes() for path in build.output_files()} == original


@pytest.mark.parametrize("damage", ["checksum", "schema", "key", "range", "fragment", "truncated", "oversized"])
def test_selfhost_directive_cache_falls_back_without_changing_output(artifact_build, damage):
    build = artifact_build
    build.source.write_text("/*\nimport }\n*/\n" + build.source.read_text())
    build.compile(hit=False)
    records = list((build.cache / "selfhost-directives-v1").glob("*.json"))
    assert records, "source directive ranges were not persisted"
    entry = next(path for path in records if json.loads(path.read_text())["ranges"])
    original = json.loads(entry.read_text())
    outputs = {path: path.read_bytes() for path in build.output_files()}
    changed = dict(original)
    if damage == "checksum":
        changed["sha256"] = "0" * 64
    elif damage == "schema":
        changed["schema"] = 999
    elif damage == "key":
        changed["key"] = "0" * 64
    elif damage in {"range", "fragment"}:
        changed["ranges"] = [[0, 1]] if damage == "range" else [[2, 2]]
        changed["sha256"] = hashlib.sha256(json.dumps(changed["ranges"], separators=(",", ":")).encode()).hexdigest()
    entry.write_text(
        " " * (8 * 1024 * 1024 + 1) if damage == "oversized" else "{" if damage == "truncated" else json.dumps(changed)
    )
    build.compile(hit=True)
    assert json.loads(entry.read_text()) == original
    assert {path: path.read_bytes() for path in build.output_files()} == outputs


def test_selfhost_no_cache_does_not_create_directive_storage(artifact_build):
    build = artifact_build
    build.compile(hit=False, extra=("--no-cache",))
    assert not (build.cache / "selfhost-directives-v1").exists()
    expected = {path: path.read_bytes() for path in build.output_files()}
    build.compile(hit=False)
    records = list((build.cache / "selfhost-directives-v1").glob("*.json"))
    assert records
    before = {path: (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes()) for path in records}
    build.compile(hit=True)
    assert {path: (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes()) for path in records} == before
    assert {path: path.read_bytes() for path in build.output_files()} == expected


def test_selfhost_directive_cache_binds_grammar(artifact_build, monkeypatch):
    build = artifact_build
    data = build.root / "data"
    (data / "language").mkdir(parents=True)
    (data / "stdlib").symlink_to(ROOT / "src/stdlib", target_is_directory=True)
    grammar = data / "language/grammar.ebnf"
    grammar.write_text((ROOT / "src/language/grammar.ebnf").read_text())
    monkeypatch.setenv("BTRC_HOME", str(data))
    build.compile(hit=False)
    directory = build.cache / "selfhost-directives-v1"
    original = {path: path.read_bytes() for path in directory.glob("*.json")}
    assert original
    before = grammar.read_text()
    after = before.replace("null override parallel", "null parallel")
    assert after != before
    grammar.write_text(after)
    build.compile(hit=False)
    assert len(list(directory.glob("*.json"))) == len(original) * 2
    assert {path: path.read_bytes() for path in original} == original
    build.compile(hit=True)


def test_selfhost_directive_cache_storage_failure_is_optional(artifact_build):
    build = artifact_build
    build.compile(hit=False, extra=("--no-cache",))
    expected = {path: path.read_bytes() for path in build.output_files()}
    build.cache.mkdir(exist_ok=True)
    blocked = build.cache / "selfhost-directives-v1"
    blocked.write_text("not a directory")
    build.compile(hit=False)
    build.compile(hit=True)
    assert blocked.read_text() == "not a directory"
    assert {path: path.read_bytes() for path in build.output_files()} == expected


def test_selfhost_validates_touched_changed_and_removed_imports(artifact_build):
    build = artifact_build
    build.compile(hit=False)
    helper = build.root / "Helper.btrc"
    helper.touch()
    build.compile(hit=True)
    previous = helper.stat()
    helper.write_text(helper.read_text().replace("return 1;", "return 2;", 1))
    os.utime(helper, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    build.compile(hit=False)
    build.execute(782)
    build.compile(hit=True)
    helper.unlink()
    build.compile(hit=False, success=False)


def test_selfhost_cache_tracks_published_package_lock(artifact_build):
    build = artifact_build
    manifest = build.root / "btrc.toml"
    manifest.write_text('manifest-version = 1\n[package]\nname = "cacheOne"\n')
    lock = build.root / "btrc.lock"
    assert not lock.exists()
    build.compile(hit=False)
    original = lock.read_bytes()
    build.compile(hit=True)
    lock.unlink()
    build.compile(hit=True)
    assert lock.read_bytes() == original
    previous = manifest.stat()
    manifest.write_text(manifest.read_text().replace("cacheOne", "cacheTwo"))
    os.utime(manifest, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    build.compile(hit=False)
    assert lock.read_bytes() != original
    build.compile(hit=True)
    build.execute(781)
    lock.write_text('{"schema":3}')
    build.compile(hit=False, success=False)


@pytest.mark.parametrize("extra", [("--no-dce",), ("--relaxed-imports",)])
def test_selfhost_cache_options_are_distinct(artifact_build, extra):
    artifact_build.compile(hit=False)
    artifact_build.compile(hit=False, extra=extra)
    artifact_build.compile(hit=True, extra=extra)
    artifact_build.compile(hit=True)


@pytest.mark.parametrize("damage", ["missing", "corrupt", "tail-corrupt", "digest", "symlink", "hardlink", "manifest"])
def test_selfhost_corrupt_artifact_is_a_miss(artifact_build, damage):
    build = artifact_build
    build.compile(hit=False)
    manifest = next(build.cache.glob("selfhost-artifacts-v1/*/manifest.json"))
    payload = manifest.parent / "part-0"
    if damage == "missing":
        payload.unlink()
    elif damage == "corrupt":
        payload.write_text("invalid C cached under the previous digest")
    elif damage == "tail-corrupt":
        hashes = json.loads(manifest.read_text())["hashes"]
        assert len(hashes) > 2
        tail = manifest.parent / f"part-{len(hashes) - 2}"
        original = tail.read_bytes()
        tail.write_bytes(b"!" + original[1:])
    elif damage == "digest":
        record = json.loads(manifest.read_text())
        record["hashes"][-1] = "0" * 64
        manifest.write_text(json.dumps(record))
    elif damage == "manifest":
        manifest.write_text('{"schema":1}')
    else:
        sentinel = build.root / "sentinel"
        payload.rename(sentinel)
        original = sentinel.read_bytes()
        if damage == "symlink":
            payload.symlink_to(sentinel)
        else:
            os.link(sentinel, payload)
    build.compile(hit=False)
    build.execute(781)
    if damage in {"symlink", "hardlink"}:
        assert sentinel.read_bytes() == original
    else:
        build.compile(hit=True)


def test_selfhost_cache_rescans_native_headers_and_search_roots(native_project, immutable_btrcc, monkeypatch):
    source, _, triple = native_project
    root = source.parent.parent
    early, later = root / "early", root / "later"
    early.mkdir()
    later.mkdir()
    selected = later / "Selected.h"
    header = "enum { sdkValue = 41 };\nstatic inline int sdkEcho(int value) { return value; }\n"
    selected.write_text(header)
    (root / "Foundation.h").write_text("#include <Selected.h>\n")
    manifest = root / "btrc.toml"
    manifest.write_text(
        'manifest-version = 1\n[package]\nname = "cacheSdk"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "c"\nstandard = "c11"\nsymbols = ["sdkValue", "sdkEcho"]\n'
        '[[native.include-directories]]\npath = "early"\n'
        '[[native.include-directories]]\npath = "later"\n'
    )
    (source.parent / "Foundation.btrc").write_text("int nativeValue() { return sdkEcho(sdkValue); }\n")
    source.write_text('import ./Foundation.btrc;\nint main() { printf("%d\\n", nativeValue()); return 0; }\n')
    build = ArtifactBuild(
        immutable_btrcc, root, source, monkeypatch, target="macos-arm64" if triple.startswith("arm64") else "macos-x64"
    )
    build.compile(hit=False)
    build.compile(hit=True)
    build.execute(41)
    previous = selected.stat()
    selected.write_text(header.replace("41", "42"))
    os.utime(selected, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    build.compile(hit=False)
    build.compile(hit=True)
    build.execute(42)
    (early / "Selected.h").write_text(header.replace("41", "43"))
    build.compile(hit=False)
    build.execute(43)
    manifest.write_text(
        manifest.read_text().replace(
            'symbols = ["sdkValue", "sdkEcho"]', 'symbols = ["sdkValue", "sdkEcho"]\nrealtime-safe = ["sdkEcho"]'
        )
    )
    build.compile(hit=False)
    build.compile(hit=True)
    wrapper = root / "reader"
    wrapper.write_text(
        "#!/bin/sh\n# revision=0\nexec " + shlex.quote(os.environ["BTRC_NATIVE_HEADER_READER"]) + ' "$@"\n'
    )
    wrapper.chmod(0o700)
    monkeypatch.setenv("BTRC_NATIVE_HEADER_READER", str(wrapper))
    build.compile(hit=False)
    build.compile(hit=True)
    previous = wrapper.stat()
    wrapper.write_text(wrapper.read_text().replace("revision=0", "revision=1"))
    os.utime(wrapper, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    build.compile(hit=False)
    build.execute(43)
    (early / "Selected.h").unlink()
    selected.unlink()
    build.compile(hit=False, success=False)


def test_selfhost_rejects_checksummed_plan_with_stale_resolved_facts(artifact_build):
    build = artifact_build
    build.compile(hit=False)
    path = next(build.cache.glob("selfhost-artifacts-v1/*/manifest.json"))
    manifest = json.loads(path.read_text())
    payload = path.parent / f"part-{len(manifest['hashes']) - 1}"
    plan = json.loads(payload.read_text())
    plan["target"]["arch"] = "stale-target"
    encoded = (json.dumps(plan, sort_keys=True, separators=(",", ":")) + "\n").encode()
    payload.write_bytes(encoded)
    manifest["hashes"][-1] = hashlib.sha256(encoded).hexdigest()
    path.write_text(json.dumps(manifest))
    build.compile(hit=False)
    build.execute(781)
    build.compile(hit=True)


def test_selfhost_retains_owned_generation_with_and_without_cache(artifact_build):
    build = artifact_build
    build.compile(hit=False)
    files = [*build.output_files(), *build.root.glob("state/*/committed.json")]
    assert len(files) > 3
    original = {path: (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes()) for path in files}
    build.compile(hit=True)
    assert {path: (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes()) for path in files} == original
    (build.root / "Helper.btrc").touch()
    build.compile(hit=True)
    build.compile(hit=False, extra=("--no-cache",))
    assert {path: (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes()) for path in files} == original
    build.execute(781)


@pytest.mark.parametrize("damage", ["content", "missing", "mode"])
def test_selfhost_retention_checks_actual_output_before_reuse(artifact_build, damage):
    build = artifact_build
    build.compile(hit=False)
    secondary = build.output_files()[1]
    expected = secondary.read_bytes()
    if damage == "content":
        metadata = secondary.stat()
        secondary.write_bytes(b"x" * len(expected))
        os.utime(secondary, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    elif damage == "missing":
        secondary.unlink()
    else:
        secondary.chmod(0o640)
    build.compile(hit=True)
    assert secondary.read_bytes() == expected
    if damage == "mode":
        record = json.loads(next(build.root.glob("state/*/committed.json")).read_text())
        assert next(row["mode"] for row in record["files"] if row["path"] == str(secondary)) == 0o640
    build.execute(781)
