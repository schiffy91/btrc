"""btrcc command-line shape: options may surround the single input file."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
PROGRAM = REPO / "src/tests/basics/BoolToString.btrc"


def _run(compiler: Path, *arguments: str):
    return subprocess.run([str(compiler), *arguments], cwd=REPO, capture_output=True, text=True, timeout=300)


@pytest.mark.parametrize(
    "damage",
    ["pending", "malformed", "public", "symlink", "hardlink", "wrong-anchor", "duplicate-role", "noncanonical"],
)
def test_selfhost_checks_private_generation_authority_before_outputs(immutable_btrcc, tmp_path, monkeypatch, damage):
    import hashlib

    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    monkeypatch.setenv("BTRC_STATE_DIR", str(state))
    source = tmp_path / "Main.btrc"
    source.write_text("int main() { return 0; }\n")
    output = tmp_path / "program.c"
    output.write_text("previous generation")
    key = hashlib.sha256(os.fsencode(output)).hexdigest()
    entry = state / key
    entry.mkdir(mode=0o700)
    record = entry / ("intent.json" if damage == "pending" else "committed.json")
    identity = {
        "path": str(output),
        "role": "primary",
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "mode": 0o644,
    }
    payload = {"schema": 1, "anchor": str(output), "files": [identity]}
    if damage == "wrong-anchor":
        payload["anchor"] = str(tmp_path / "other.c")
    elif damage == "duplicate-role":
        payload["files"].append({**identity, "path": str(tmp_path / "other.c")})
    elif damage == "noncanonical":
        payload["files"].append({**identity, "path": f"{tmp_path}/missing/../other.c", "role": "secondary"})
    record.write_text("invalid record" if damage in {"pending", "malformed"} else json.dumps(payload))
    record.chmod(0o600)
    if damage == "public":
        record.chmod(0o644)
    elif damage in {"symlink", "hardlink"}:
        other = tmp_path / "unowned.json"
        record.rename(other)
        if damage == "symlink":
            record.symlink_to(other)
        else:
            os.link(other, record)
    before = record.read_bytes()
    result = _run(immutable_btrcc, "--no-stdlib", str(source), "-o", str(output))
    assert result.returncode == 1, result.stderr
    assert "generation" in result.stderr
    assert output.read_text() == "previous generation"
    assert record.read_bytes() == before
    assert not (tmp_path / ".btrc-publications.lock").exists()
    assert not list(tmp_path.glob(".btrc-package-*"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX generation-owner lock interoperability")
@pytest.mark.parametrize("mutation", ["none", "intent", "permissions", "directory"])
def test_selfhost_owner_lock_precedes_directory_locks_and_rechecks_after_wait(
    immutable_btrcc, tmp_path, monkeypatch, mutation
):
    import hashlib
    import threading

    from src.compiler.python.artifacts.publication import ArtifactStorage, PublicationLock

    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    monkeypatch.setenv("BTRC_STATE_DIR", str(state))
    source = tmp_path / "Main.btrc"
    source.write_text("int main() { return 0; }\n")
    output = tmp_path / "program.c"
    output.write_text("previous generation")
    entry = state / hashlib.sha256(os.fsencode(output)).hexdigest()
    entry.mkdir(mode=0o700)
    process = None
    try:
        with PublicationLock(entry, "compiler-owner", threading.Lock(), ArtifactStorage()):
            process = subprocess.Popen(
                [str(immutable_btrcc), "--no-stdlib", str(source), "-o", str(output)],
                cwd=REPO,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            with pytest.raises(subprocess.TimeoutExpired):
                process.communicate(timeout=1)
            assert not (tmp_path / ".btrc-publications.lock").exists()
            assert output.read_text() == "previous generation"
            if mutation == "intent":
                intent = entry / "intent.json"
                intent.write_text("prepared while the compiler waited")
                intent.chmod(0o600)
            elif mutation == "permissions":
                state.chmod(0o755)
            elif mutation == "directory":
                entry.rename(state / "moved-owner")
                entry.mkdir(mode=0o700)
        _, stderr = process.communicate(timeout=30)
        assert process.returncode == (0 if mutation == "none" else 1), stderr
        if mutation == "none":
            assert "int main" in output.read_text()
        else:
            assert "generation" in stderr
            assert output.read_text() == "previous generation"
    finally:
        state.chmod(0o700)
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate()


@pytest.mark.skipif(os.name == "nt", reason="POSIX generation-owner lock interoperability")
def test_selfhost_rejects_replaced_owner_lock_after_directory_wait(immutable_btrcc, tmp_path, monkeypatch):
    import fcntl
    import hashlib
    import time

    from src.compiler.python.artifacts.publication import ArtifactPublisher

    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    monkeypatch.setenv("BTRC_STATE_DIR", str(state))
    source = tmp_path / "Main.btrc"
    source.write_text("int main() { return 0; }\n")
    output = tmp_path / "program.c"
    output.write_text("previous generation")
    entry = state / hashlib.sha256(os.fsencode(output)).hexdigest()
    lock = entry / ".compiler-owner.publish.lock"
    process = None
    try:
        with ArtifactPublisher().read_directories([tmp_path]):
            process = subprocess.Popen(
                [str(immutable_btrcc), "--no-stdlib", str(source), "-o", str(output)],
                cwd=REPO,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            deadline = time.monotonic() + 10
            held = False
            while time.monotonic() < deadline:
                if lock.exists():
                    with lock.open("r+b") as opened:
                        try:
                            fcntl.flock(opened.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except BlockingIOError:
                            held = True
                            break
                assert process.poll() is None
                time.sleep(0.01)
            assert held, "self-host did not acquire the owner before waiting on outputs"
            lock.unlink()
            lock.touch(mode=0o600)
        _, stderr = process.communicate(timeout=30)
        assert process.returncode == 1, stderr
        assert "generation owner lock changed" in stderr
        assert output.read_text() == "previous generation"
        assert not list(tmp_path.glob(".btrc-package-*"))
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate()


def test_selfhost_advances_reference_committed_generation(immutable_btrcc, tmp_path, monkeypatch):
    import sys

    state = tmp_path / "state"
    monkeypatch.setenv("BTRC_STATE_DIR", str(state))
    source = tmp_path / "Main.btrc"
    source.write_text("int main() { return 0; }\n")
    output = tmp_path / "program.c"
    reference = subprocess.run(
        [sys.executable, "-m", "src.compiler.python.main", "--no-cache", "--no-stdlib", str(source), "-o", str(output)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert reference.returncode == 0, reference.stderr
    record = next(state.glob("*/committed.json"))
    before = record.read_bytes()
    result = _run(immutable_btrcc, "--no-stdlib", str(source), "-o", str(output))
    assert result.returncode == 0, result.stderr
    assert "int main" in output.read_text()
    import hashlib

    assert record.read_bytes() != before
    manifest = json.loads(record.read_text())
    assert manifest["anchor"] == str(output)
    assert manifest["files"] == [
        {
            "path": str(output),
            "role": "primary",
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "mode": output.stat().st_mode & 0o7777,
        }
    ]
    assert not (record.parent / "intent.json").exists()
    assert not (record.parent / "candidate.json").exists()


def test_selfhost_default_generation_state_matches_reference_location(immutable_btrcc, tmp_path, monkeypatch):
    import sys

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("BTRC_STATE_DIR", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    source = tmp_path / "Main.btrc"
    source.write_text("int main() { return 0; }\n")
    result = _run(immutable_btrcc, "--no-stdlib", str(source), "-o", str(tmp_path / "program.c"))
    assert result.returncode == 0, result.stderr
    root = home / ("Library/Application Support" if sys.platform == "darwin" else ".local/state") / "btrc/generations"
    assert len(list(root.glob("*/.compiler-owner.publish.lock"))) == 1
    assert root.stat().st_mode & 0o777 == 0o700


def test_selfhost_stdout_and_failed_compile_do_not_provision_generation_state(immutable_btrcc, tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setenv("BTRC_STATE_DIR", str(state))
    source = tmp_path / "Main.btrc"
    source.write_text("int main() { return 0; }\n")
    result = _run(immutable_btrcc, "--no-stdlib", str(source))
    assert result.returncode == 0, result.stderr
    assert not state.exists()
    source.write_text("this is not a program")
    result = _run(immutable_btrcc, "--no-stdlib", str(source), "-o", str(tmp_path / "program.c"))
    assert result.returncode == 1
    assert not state.exists()


def test_output_and_debug_may_follow_the_input(immutable_btrcc, tmp_path):
    out = tmp_path / "program.c"
    result = _run(immutable_btrcc, "--strict-imports", str(PROGRAM), "-o", str(out), "--debug")
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert f'"{PROGRAM}"' in out.read_text()


def test_options_before_the_input_still_work(immutable_btrcc, tmp_path):
    out = tmp_path / "program.c"
    result = _run(immutable_btrcc, "-o", str(out), "--strict-imports", "--", str(PROGRAM))
    assert result.returncode == 0, result.stderr
    assert "#line" not in out.read_text()


def test_two_inputs_are_rejected(immutable_btrcc):
    result = _run(immutable_btrcc, str(PROGRAM), str(PROGRAM))
    assert result.returncode != 0
    assert "only one input file" in result.stderr


def test_output_needs_a_path(immutable_btrcc):
    result = _run(immutable_btrcc, str(PROGRAM), "-o")
    assert result.returncode != 0
    assert "-o requires an output path" in result.stderr


@pytest.mark.parametrize("kind", ["root", "import", "include", "native-header", "native-source", "manifest"])
@pytest.mark.parametrize("role", ["primary", "plan"])
@pytest.mark.parametrize("alias", ["direct", "symlink", "hardlink"])
def test_selfhost_outputs_cannot_replace_inputs(immutable_btrcc, tmp_path, kind, role, alias):
    source = tmp_path / "Main.btrc"
    dependency = tmp_path / "Value.btrc"
    dependency.write_text("int value() { return 7; }\n")
    source.write_text("import ./Value.btrc;\nint main() { return value(); }\n")
    if kind == "include":
        source.write_text('#include "Value.btrc"\nint main() { return value(); }\n')
    header = tmp_path / "native.h"
    native = tmp_path / "native.c"
    header.write_text("int nativeValue(void);\n")
    native.write_text("int nativeValue(void) { return 8; }\n")
    manifest = tmp_path / "btrc.toml"
    manifest.write_text(
        'manifest-version = 1\n[package]\nname = "test"\n[[native.headers]]\npath = "native.h"\n[[native.sources]]\npath = "native.c"\nlanguage = "c"\nstandard = "c11"\n'
    )
    protected = {
        "root": source,
        "import": dependency,
        "include": dependency,
        "native-header": header,
        "native-source": native,
        "manifest": manifest,
    }[kind]
    target = protected
    if alias != "direct":
        target = tmp_path / "alias.out"
        if alias == "symlink":
            target.symlink_to(protected)
        else:
            os.link(protected, target)
    other = tmp_path / "other.out"
    other.write_text("previous successful output")
    before = {path: path.read_bytes() for path in (source, dependency, header, native, manifest, target, other)}
    output, plan = (target, other) if role == "primary" else (other, target)
    result = _run(
        immutable_btrcc,
        "--target",
        "linux-x64",
        "--no-stdlib",
        str(source),
        "-o",
        str(output),
        "--emit-link-plan",
        str(plan),
    )
    assert result.returncode == 1, result.stderr
    assert "output" in result.stderr and "source" in result.stderr, result.stderr
    assert all(path.read_bytes() == content for path, content in before.items())
    if alias == "symlink":
        assert target.is_symlink()


@pytest.mark.parametrize("alias", ["direct", "symlink", "hardlink", "dot"])
def test_selfhost_primary_and_plan_must_be_distinct(immutable_btrcc, tmp_path, alias):
    source = tmp_path / "Main.btrc"
    source.write_text("int main() { return 0; }\n")
    output = tmp_path / "program.c"
    output.write_text("previous output")
    plan = output
    if alias in {"symlink", "hardlink"}:
        plan = tmp_path / "alias.json"
        if alias == "symlink":
            plan.symlink_to(output)
        else:
            os.link(output, plan)
    elif alias == "dot":
        plan = str(tmp_path) + "/./program.c"
    result = _run(
        immutable_btrcc,
        "--target",
        "linux-x64",
        "--no-stdlib",
        str(source),
        "-o",
        str(output),
        "--emit-link-plan",
        str(plan),
    )
    assert result.returncode == 1
    assert "output paths" in result.stderr
    assert output.read_text() == "previous output"


@pytest.mark.parametrize("invalid", ["directory", "missing-parent", "trailing-slash"])
def test_selfhost_validates_all_output_paths_before_writing(immutable_btrcc, tmp_path, invalid):
    source = tmp_path / "Main.btrc"
    source.write_text("int main() { return 0; }\n")
    plan = tmp_path / "plan.json"
    plan.write_text("previous plan")
    target = {
        "directory": str(tmp_path),
        "missing-parent": str(tmp_path / "absent/program.c"),
        "trailing-slash": str(tmp_path / "program.c") + "/",
    }[invalid]
    result = _run(immutable_btrcc, "--no-stdlib", str(source), "-o", target, "--emit-link-plan", str(plan))
    assert result.returncode == 1
    assert plan.read_text() == "previous plan"


@pytest.mark.parametrize("conflict", ["source-symlink", "source-hardlink", "primary", "plan", "secondary-hardlink"])
def test_selfhost_secondary_inventory_is_validated_before_any_write(immutable_btrcc, tmp_path, monkeypatch, conflict):
    monkeypatch.setenv("BTRC_UNIT_LINES", "1")
    source = tmp_path / "Main.btrc"
    # Splitting preserves each source module's run of functions.
    for index in range(3):
        (tmp_path / f"Value{index}.btrc").write_text(f"int value{index}() {{ return {index}; }}\n")
    source.write_text(
        "\n".join(f"import ./Value{index}.btrc;" for index in range(3))
        + "\nint main() { return value0() + value1() + value2(); }\n"
    )
    output, plan, prefix = tmp_path / "program.c", tmp_path / "plan.json", tmp_path / "parts"
    arguments = ["--no-stdlib", str(source), "--emit-units", str(prefix)]
    first = _run(immutable_btrcc, *arguments, "-o", str(output), "--emit-link-plan", str(plan))
    assert first.returncode == 0, first.stderr
    units = [Path(path) for path in json.loads(plan.read_text())["emitted-units"]]
    assert len(units) >= 2
    if conflict in {"source-symlink", "source-hardlink"}:
        units[0].unlink()
        if conflict == "source-symlink":
            units[0].symlink_to(source)
        else:
            os.link(source, units[0])
    elif conflict == "secondary-hardlink":
        units[1].unlink()
        os.link(units[0], units[1])
    before = {path: path.read_bytes() for path in (source, output, plan, *units)}
    requested_output = units[0] if conflict == "primary" else output
    requested_plan = units[0] if conflict == "plan" else plan
    result = _run(immutable_btrcc, *arguments, "-o", str(requested_output), "--emit-link-plan", str(requested_plan))
    assert result.returncode == 1
    assert "output" in result.stderr
    assert all(path.read_bytes() == content for path, content in before.items())
    if conflict == "source-symlink":
        assert units[0].is_symlink()


@pytest.mark.parametrize("name", [".btrc-publications.lock", ".another.publish.journal", ".another.publish.previous-0"])
def test_selfhost_outputs_preserve_publication_control_files(immutable_btrcc, tmp_path, name):
    source = tmp_path / "Main.btrc"
    source.write_text("int main() { return 0; }\n")
    control = tmp_path / name
    control.write_text("previous control contents")
    plan = tmp_path / "plan.json"
    plan.write_text("previous plan")
    result = _run(immutable_btrcc, "--no-stdlib", str(source), "-o", str(control), "--emit-link-plan", str(plan))
    assert result.returncode == 1
    assert "publication control" in result.stderr
    assert control.read_text() == "previous control contents"
    assert plan.read_text() == "previous plan"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="requires POSIX FIFO")
def test_selfhost_fifo_output_is_rejected_without_blocking_or_other_writes(immutable_btrcc, tmp_path):
    source = tmp_path / "Main.btrc"
    source.write_text("int main() { return 0; }\n")
    fifo = tmp_path / "output.c"
    os.mkfifo(fifo)
    plan = tmp_path / "plan.json"
    plan.write_text("previous plan")
    result = subprocess.run(
        [str(immutable_btrcc), "--no-stdlib", str(source), "-o", str(fifo), "--emit-link-plan", str(plan)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 1
    assert "regular file" in result.stderr
    assert plan.read_text() == "previous plan"


def test_selfhost_reserves_an_absent_package_lock_path(immutable_btrcc, tmp_path):
    source = tmp_path / "Main.btrc"
    source.write_text("int main() { return 0; }\n")
    manifest = tmp_path / "btrc.toml"
    manifest.write_text('manifest-version = 1\n[package]\nname = "test"\n')
    lock = tmp_path / "btrc.lock"
    result = _run(immutable_btrcc, "--target", "linux-x64", "--no-stdlib", str(source), "-o", str(lock))
    assert result.returncode == 1
    assert "source input" in result.stderr
    # Resolution creates its own lock before output validation. It must remain
    # a valid dependency lock rather than being overwritten with generated C.
    payload = json.loads(lock.read_text())
    assert payload["schema"] == 3
    assert payload["root"] == "test"
    assert payload["packages"][0]["name"] == "test"


@pytest.mark.skipif(os.name == "nt", reason="POSIX publication-lock interoperability")
@pytest.mark.parametrize("role", ["primary", "plan", "secondary"])
def test_selfhost_waits_for_cooperating_reader(immutable_btrcc, tmp_path, monkeypatch, role):
    from src.compiler.python.artifacts.publication import ArtifactPublisher

    monkeypatch.setenv("BTRC_UNIT_LINES", "1")
    source = tmp_path / "Main.btrc"
    (tmp_path / "Value.btrc").write_text("int value() { return 3; }\n")
    source.write_text("import ./Value.btrc;\nint main() { return value(); }\n")
    directories = {name: tmp_path / name for name in ("primary", "plan", "secondary")}
    for directory in directories.values():
        directory.mkdir()
    output = directories["primary"] / "program.c"
    output.write_text("previous generated C")
    plan = directories["plan"] / "plan.json"
    plan.write_text("previous plan")
    process = None
    try:
        with ArtifactPublisher().read_directories([directories[role]]):
            process = subprocess.Popen(
                [
                    str(immutable_btrcc),
                    "--no-stdlib",
                    str(source),
                    "-o",
                    str(output),
                    "--emit-link-plan",
                    str(plan),
                    "--emit-units",
                    str(directories["secondary"] / "part"),
                ],
                cwd=REPO,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            with pytest.raises(subprocess.TimeoutExpired):
                process.communicate(timeout=1)
            assert output.read_text() == "previous generated C"
            assert plan.read_text() == "previous plan"
            assert not list(directories["secondary"].glob("*.c"))
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == 0, stderr
        assert stdout == ""
        assert "int main" in output.read_text()
        assert json.loads(plan.read_text())["emitted-units"]
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate()


@pytest.mark.parametrize("role", ["primary", "plan", "secondary"])
def test_selfhost_refuses_pending_publication(immutable_btrcc, tmp_path, monkeypatch, role):
    monkeypatch.setenv("BTRC_UNIT_LINES", "1")
    source = tmp_path / "Main.btrc"
    dependency = tmp_path / "Value.btrc"
    dependency.write_text("int value() { return 3; }\n")
    source.write_text("import ./Value.btrc;\nint main() { return value(); }\n")
    directories = {name: tmp_path / name for name in ("primary", "plan", "secondary")}
    for directory in directories.values():
        directory.mkdir()
    output, plan = directories["primary"] / "program.c", directories["plan"] / "plan.json"
    output.write_text("previous generated C")
    plan.write_text("previous plan")
    marker = directories[role] / ".interrupted.publish.journal"
    marker.write_text("untrusted recovery data")
    result = _run(
        immutable_btrcc,
        "--no-stdlib",
        str(source),
        "-o",
        str(output),
        "--emit-link-plan",
        str(plan),
        "--emit-units",
        str(directories["secondary"] / "part"),
    )
    assert result.returncode == 1, result.stderr
    assert "requires recovery" in result.stderr
    assert output.read_text() == "previous generated C"
    assert plan.read_text() == "previous plan"
    assert marker.read_text() == "untrusted recovery data"
    assert not list(directories["secondary"].glob("*.c"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX publication-lock interoperability")
@pytest.mark.parametrize("kind", ["symlink", "hardlink", "directory", "fifo"])
def test_selfhost_rejects_invalid_coordination_file(immutable_btrcc, tmp_path, kind):
    source = tmp_path / "Main.btrc"
    source.write_text("int main() { return 0; }\n")
    output = tmp_path / "program.c"
    output.write_text("previous generated C")
    lock = tmp_path / ".btrc-publications.lock"
    if kind == "symlink":
        lock.symlink_to(source)
    elif kind == "hardlink":
        os.link(source, lock)
    elif kind == "directory":
        lock.mkdir()
    else:
        os.mkfifo(lock)
    result = subprocess.run(
        [str(immutable_btrcc), "--no-stdlib", str(source), "-o", str(output)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 1, result.stderr
    assert "cannot lock publication directory" in result.stderr
    assert output.read_text() == "previous generated C"
    assert source.read_text() == "int main() { return 0; }\n"


@pytest.mark.skipif(os.name == "nt", reason="POSIX publication-lock interoperability")
@pytest.mark.parametrize("mutation", ["output-symlink", "input-alias", "lock-inode", "pending-journal"])
def test_selfhost_revalidates_after_lock_wait(immutable_btrcc, tmp_path, mutation):
    from src.compiler.python.artifacts.publication import ArtifactPublisher

    source = tmp_path / "Main.btrc"
    source.write_text("int main() { return 0; }\n")
    old = tmp_path / "old.c"
    old.write_text("old target")
    new_directory = tmp_path / "new"
    new_directory.mkdir()
    new = new_directory / "new.c"
    new.write_text("new target")
    output = tmp_path / "program.c"
    output.symlink_to(old)
    process = None
    try:
        with ArtifactPublisher().read_directories([tmp_path]):
            process = subprocess.Popen(
                [str(immutable_btrcc), "--no-stdlib", str(source), "-o", str(output)],
                cwd=REPO,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            with pytest.raises(subprocess.TimeoutExpired):
                process.communicate(timeout=1)
            if mutation == "output-symlink":
                output.unlink()
                output.symlink_to(new)
            elif mutation == "input-alias":
                source.unlink()
                os.link(old, source)
            elif mutation == "lock-inode":
                lock = tmp_path / ".btrc-publications.lock"
                lock.rename(tmp_path / "previous.lock")
                lock.write_text("replacement coordination file")
            else:
                (tmp_path / ".interrupted.publish.journal").write_text("untrusted")
        _, stderr = process.communicate(timeout=30)
        assert process.returncode == 1, stderr
        assert "publication" in stderr or "source input" in stderr
        assert output.is_symlink()
        assert old.read_text() == "old target"
        assert new.read_text() == "new target"
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate()


@pytest.mark.skipif(os.name == "nt", reason="POSIX publication-lock interoperability")
def test_selfhost_writers_lock_directories_in_one_order(immutable_btrcc, tmp_path):
    from src.compiler.python.artifacts.publication import ArtifactPublisher

    source = tmp_path / "Main.btrc"
    source.write_text("int main() { return 0; }\n")
    left, right = tmp_path / "a", tmp_path / "z"
    left.mkdir()
    right.mkdir()
    outputs = [left / "output", right / "output"]
    processes = []
    try:
        with ArtifactPublisher().read_directories([left]):
            for primary, plan in (outputs, outputs[::-1]):
                processes.append(
                    subprocess.Popen(
                        [
                            str(immutable_btrcc),
                            "--no-stdlib",
                            str(source),
                            "-o",
                            str(primary),
                            "--emit-link-plan",
                            str(plan),
                        ],
                        cwd=REPO,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                )
            for process in processes:
                with pytest.raises(subprocess.TimeoutExpired):
                    process.communicate(timeout=1)
            assert not any(path.exists() for path in outputs)
        for process in processes:
            _, stderr = process.communicate(timeout=30)
            assert process.returncode == 0, stderr
        contents = [path.read_text() for path in outputs]
        assert sum("int main" in content for content in contents) == 1
        plan_text = next(content for content in contents if "int main" not in content)
        assert json.loads(plan_text)["schema"] == 1
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate()


@pytest.mark.skipif(
    os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), reason="POSIX non-root directory permissions"
)
@pytest.mark.parametrize("role", ["primary", "secondary", "plan"])
def test_selfhost_stages_every_output_before_replacing_any(immutable_btrcc, tmp_path, monkeypatch, role):
    monkeypatch.setenv("BTRC_UNIT_LINES", "1")
    source = tmp_path / "Main.btrc"
    for index in range(3):
        (tmp_path / f"Value{index}.btrc").write_text(f"int value{index}() {{ return {index}; }}\n")
    source.write_text(
        "\n".join(f"import ./Value{index}.btrc;" for index in range(3))
        + "\nint main() { return value0() + value1() + value2(); }\n"
    )
    directories = {name: tmp_path / name for name in ("primary", "plan", "secondary")}
    for directory in directories.values():
        directory.mkdir()
    primary, plan = directories["primary"] / "program.c", directories["plan"] / "plan.json"
    arguments = [
        "--no-stdlib",
        str(source),
        "-o",
        str(primary),
        "--emit-link-plan",
        str(plan),
        "--emit-units",
        str(directories["secondary"] / "part"),
    ]
    first = _run(immutable_btrcc, *arguments)
    assert first.returncode == 0, first.stderr
    units = [Path(path) for path in json.loads(plan.read_text())["emitted-units"]]
    assert len(units) >= 2
    for path in (primary, plan, *units):
        path.write_text(f"previous output: {path.name}")
    before = {path: path.read_bytes() for path in (primary, plan, *units)}
    # Existing regular lock files remain usable even when no new candidate can
    # be created in this directory. This reaches staging after lock acquisition.
    directories[role].chmod(0o500)
    try:
        result = _run(immutable_btrcc, *arguments)
    finally:
        directories[role].chmod(0o700)
    assert result.returncode == 1, result.stderr
    assert {path: path.read_bytes() for path in before} == before
    assert not list(tmp_path.rglob(".btrc-package-*"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink and mode preservation")
@pytest.mark.parametrize("role", ["primary", "plan", "secondary"])
def test_selfhost_preserves_output_symlink_and_permissions(immutable_btrcc, tmp_path, monkeypatch, role):
    monkeypatch.setenv("BTRC_UNIT_LINES", "1")
    source = tmp_path / "Main.btrc"
    (tmp_path / "Value.btrc").write_text("int value() { return 3; }\n")
    source.write_text("import ./Value.btrc;\nint main() { return value(); }\n")
    storage = tmp_path / "storage"
    storage.mkdir()
    target = storage / "target"
    target.write_text("previous output")
    target.chmod(0o640)
    alias = tmp_path / ("parts.unit-1.c" if role == "secondary" else "alias")
    alias.symlink_to(target)
    primary = alias if role == "primary" else tmp_path / "program.c"
    plan = alias if role == "plan" else tmp_path / "plan.json"
    result = _run(
        immutable_btrcc,
        "--no-stdlib",
        str(source),
        "-o",
        str(primary),
        "--emit-link-plan",
        str(plan),
        "--emit-units",
        str(tmp_path / "parts"),
    )
    assert result.returncode == 0, result.stderr
    assert alias.is_symlink()
    assert target.stat().st_mode & 0o777 == 0o640
    assert target.read_text() != "previous output"
    assert not list(tmp_path.rglob(".btrc-package-*"))


@pytest.mark.parametrize("frontend", ["python", "btrc"])
def test_staged_file_owner_preserves_destinations_and_unowned_replacements(
    selfhost_driver, request, tmp_path, frontend
):
    import shlex

    from src.tests.runner import default_c_compiler

    source = REPO / "src/tests/btrc/fixtures/StagedFileDriver.btrc"
    if frontend == "python":
        executable = selfhost_driver(source)
    else:
        generated, executable = tmp_path / "staged.c", tmp_path / "staged"
        result = _run(request.getfixturevalue("immutable_btrcc"), str(source), "-o", str(generated))
        assert result.returncode == 0, result.stderr
        built = subprocess.run(
            [
                *shlex.split(os.environ.get("BTRC_CC", default_c_compiler())),
                "-std=c11",
                "-pedantic",
                str(generated),
                "-o",
                str(executable),
                "-lm",
                "-lpthread",
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert built.returncode == 0, built.stderr
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "PASS: staged file lifetime and publication\n"


@pytest.mark.skipif(os.name == "nt", reason="POSIX file-size limit fault injection")
def test_selfhost_staging_write_failure_preserves_all_outputs(immutable_btrcc, tmp_path):
    import sys

    source = tmp_path / "Main.btrc"
    source.write_text('int main() { print("' + "generated output" * 1024 + '"); return 0; }\n')
    primary, plan = tmp_path / "program.c", tmp_path / "plan.json"
    arguments = ["--no-stdlib", str(source), "-o", str(primary), "--emit-link-plan", str(plan)]
    first = _run(immutable_btrcc, *arguments)
    assert first.returncode == 0, first.stderr
    limit = max(4096, plan.stat().st_size + 64)
    assert primary.stat().st_size > limit
    primary.write_text("previous generated C")
    plan.write_text("previous plan")
    launcher = (
        "import os, resource, signal, sys\n"
        "signal.signal(signal.SIGXFSZ, signal.SIG_IGN)\n"
        "limit = int(sys.argv[1])\n"
        "resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))\n"
        "os.execv(sys.argv[2], sys.argv[2:])\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", launcher, str(limit), str(immutable_btrcc), *arguments],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1, result.stderr
    assert "cannot stage publication payload" in result.stderr
    assert primary.read_text() == "previous generated C"
    assert plan.read_text() == "previous plan"
    assert not list(tmp_path.glob(".btrc-package-*"))


@pytest.mark.parametrize("boundary", ["primary", "plan", "commit"])
def test_selfhost_recovers_reference_generation_then_retires_previous_layout(
    immutable_btrcc, tmp_path, monkeypatch, boundary
):
    import hashlib
    import multiprocessing

    from src.compiler.python.artifacts.cache import CompilerGenerationPublisher
    from src.tests.python.test_native_plan_builder import _publish_native_generation

    monkeypatch.setenv("BTRC_STATE_DIR", str(tmp_path / "state"))
    _publish_native_generation(tmp_path, 41)
    process = multiprocessing.get_context("spawn").Process(
        target=_publish_native_generation,
        args=(tmp_path, 42, "changed-secondary"),
        kwargs={"boundary": boundary},
    )
    process.start()
    process.join(30)
    if process.is_alive():
        process.kill()
        process.join()
        pytest.fail("reference generation did not reach crash boundary")
    assert process.exitcode == 91
    primary = tmp_path / "primary/main.c"
    source = tmp_path / "Main.btrc"
    source.write_text("int main() { return 17; }\n")
    result = _run(immutable_btrcc, "--no-stdlib", str(source), "-o", str(primary))
    assert result.returncode == 0, result.stderr
    assert "return 17;" in primary.read_text()
    assert not (tmp_path / "secondary/part.c").exists()
    assert not (tmp_path / "changed-secondary/part.c").exists()
    assert not (tmp_path / "plan/plan.json").exists()
    recovered = CompilerGenerationPublisher(tmp_path / "state").recover(primary)
    assert len(recovered) == 1
    assert recovered[0].destination == primary
    assert recovered[0].sha256 == hashlib.sha256(primary.read_bytes()).hexdigest()
    assert not list(tmp_path.rglob(".*.publish.journal"))
    assert not list((tmp_path / "state").glob("*/intent.json"))


@pytest.mark.parametrize("conflict", ["edited", "input"])
def test_selfhost_retirement_preserves_modified_files_and_current_inputs(
    immutable_btrcc, tmp_path, monkeypatch, conflict
):
    from src.tests.python.test_native_plan_builder import _publish_native_generation

    monkeypatch.setenv("BTRC_STATE_DIR", str(tmp_path / "state"))
    _publish_native_generation(tmp_path, 41)
    primary = tmp_path / "primary/main.c"
    retired = tmp_path / "secondary/part.c"
    source = tmp_path / "Main.btrc"
    if conflict == "edited":
        retired.write_text("user edit\n")
        source.write_text("int main() { return 0; }\n")
    else:
        source = retired
        source.write_text("int main() { return 0; }\n")
    before = {path: path.read_bytes() for path in (primary, retired, source)}
    result = _run(immutable_btrcc, "--no-stdlib", str(source), "-o", str(primary))
    assert result.returncode == 1, result.stderr
    assert ("retired artifact changed" if conflict == "edited" else "source input") in result.stderr
    assert all(path.read_bytes() == content for path, content in before.items())
