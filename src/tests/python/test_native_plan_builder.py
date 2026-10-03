"""Production Make adapter proofs for compiler-emitted native plans."""

from __future__ import annotations

import ast
import contextlib
import hashlib
import json
import multiprocessing
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.compiler.python.artifacts.cache import CompilerGenerationPublisher, CompilerOutput
from src.compiler.python.artifacts.publication import ArtifactPublisher, PublicationLock, PublishedArtifact
from src.compiler.python.frontend.packages import NativeGeneratedUnit, NativeLinkPlan, PackageTarget
from src.tests.native_targets import cross_target_environment
from src.tests.process_limits import RUN_TIMEOUT, TRANSPILE_TIMEOUT
from src.tests.python.native_plan_fixtures import publish_native_generation
from tools.native_plan import (
    NativeBuildReport,
    NativePlanBuilder,
    NativePlanError,
    NativePlanReader,
    _PreludeAccelerator,
    main,
)

REPO = Path(__file__).resolve().parents[3]
EXAMPLE = REPO / "examples" / "native-package"


def generated_plan(source="int answer(void) { return 42; }\n", language="c", standard="c11", memory="manual"):
    return NativeLinkPlan(
        PackageTarget.parse(None),
        generated_units=(NativeGeneratedUnit("Adapter", language, standard, memory, source),),
    ).as_dict()


@pytest.mark.parametrize("participant", ["primary", "plan", "secondary"])
def test_pending_generation_rejects_build_before_tools(tmp_path, participant):
    directories = {name: tmp_path / name for name in ("primary", "plan", "secondary")}
    for directory in directories.values():
        directory.mkdir()
    primary = directories["primary"] / "main.c"
    secondary = directories["secondary"] / "part.c"
    plan = directories["plan"] / "plan.json"
    primary.write_text("int main(void) { return 0; }\n")
    secondary.write_text("int answer(void) { return 42; }\n")
    payload = NativeLinkPlan.empty(PackageTarget.parse(None)).as_dict()
    payload.update(schema=4)
    payload["emitted-units"] = [str(secondary)]
    plan.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")
    # An untrusted journal is evidence to stop, never authority to recover paths.
    marker = directories[participant] / ".unknown.publish.journal"
    marker.write_text('{"targets":["/outside/reader/authority"]}')
    before = {path: path.read_bytes() for path in (primary, secondary, plan, marker)}

    def never_run(*args, **kwargs):
        pytest.fail("a pending compiler generation reached a native build tool")

    with pytest.raises(NativePlanError, match="publication requires recovery"):
        NativePlanBuilder(runner=never_run).build(plan_path=plan, generated_c=primary, output=tmp_path / "program")
    assert {path: path.read_bytes() for path in before} == before


def test_receipt_requests_are_chunked_within_the_protocol_bound():
    """Hundreds of units with SDK-length commands still get batched receipts.

    One request for every unit exceeded the protocol bound, and the build then
    opened one reader session per unit.
    """
    from tools.native_plan import MAX_PLAN_BYTES, _PreprocessingReceipts

    arguments = ["clang", "-cc1", *(["-isystem", "/nix/store/" + "x" * 200] * 60)]
    requested = [(index, [*arguments, f"unit-{index}.c"]) for index in range(600)]
    chunks = list(_PreprocessingReceipts._chunks(requested))
    assert len(chunks) > 1
    assert [unit for chunk in chunks for unit in chunk] == requested
    for chunk in chunks:
        size = sum(len(json.dumps({"id": str(index), "cc1": cc1}).encode()) for index, cc1 in chunk)
        assert size <= MAX_PLAN_BYTES // 2
    assert list(_PreprocessingReceipts._chunks([])) == []
    # A small batch still spreads over the build's jobs, in order.
    spread = list(_PreprocessingReceipts._chunks(requested[:40], pieces=8))
    assert len(spread) == 8 and [unit for chunk in spread for unit in chunk] == requested[:40]


@pytest.mark.parametrize("faithful", [True, False])
def test_units_sharing_flags_share_one_verified_driver_expansion(tmp_path, faithful):
    """Only two driver runs per command shape, unless the derived job would differ."""
    from tools.native_plan import _PreprocessingReceipts

    receipts = _PreprocessingReceipts(tmp_path, (), subprocess.run)
    calls = []

    def expand(command, directory):
        calls.append(command)
        source = command[command.index("-c") + 1]
        name = Path(source).name
        # An unfaithful driver adds a per-unit detail the template cannot know.
        extra = [] if faithful else [f"-unit-{len(calls)}"]
        return ["clang", "-cc1", "-main-file-name", name, *extra, source, "-o", str(directory / "source.i")]

    receipts._expand = expand
    commands = [
        (
            ["clang", "-std=c11", "-c", str(tmp_path / f"unit-{index}.c"), "-o", str(tmp_path / f"unit-{index}.o")],
            tmp_path / f"unit-{index}.c",
        )
        for index in range(6)
    ]
    expanded = receipts._expand_all(commands, tmp_path, 4)
    assert len(calls) == (2 if faithful else 8)
    for (_, source), job in zip(commands, expanded, strict=True):
        assert job[3] == source.name and str(source) in job


def test_unchanged_generation_outputs_keep_their_files(tmp_path):
    """Only outputs whose bytes changed are replaced; the rest keep inode and mtime.

    Native preprocessing receipts are bound to a unit's inode and mtime, so a
    rewrite of an unchanged unit would force it to be preprocessed again.
    """
    publish_native_generation(tmp_path, 41)
    secondary, plan, primary = tmp_path / "secondary/part.c", tmp_path / "plan/plan.json", tmp_path / "primary/main.c"
    before = {path: path.stat() for path in (primary, secondary, plan)}
    state = tmp_path / "state"
    staged = primary.with_name("candidate-changed")
    staged.write_text("int answer(void); int main(void) { return answer() == 41 ? 0 : 2; }\n")
    unchanged = []
    for path in (secondary, plan):
        copy = path.with_name("candidate-same")
        copy.write_bytes(path.read_bytes())
        unchanged.append(copy)
    CompilerGenerationPublisher(state).publish(
        [
            CompilerOutput(staged, primary, "primary"),
            CompilerOutput(unchanged[0], secondary, "secondary"),
            CompilerOutput(unchanged[1], plan, "link-plan"),
        ]
    )
    after = {path: path.stat() for path in (primary, secondary, plan)}
    assert "? 0 : 2" in primary.read_text()
    assert after[primary].st_ino != before[primary].st_ino
    for path in (secondary, plan):
        assert (after[path].st_ino, after[path].st_mtime_ns) == (before[path].st_ino, before[path].st_mtime_ns)
    assert not any(copy.exists() for copy in unchanged)


@pytest.mark.parametrize("boundary", ["primary", "secondary", "commit"])
def test_crashed_generation_requires_owner_recovery_before_native_build(tmp_path, boundary):
    # The link plan is identical across both generations and is kept in place,
    # so the interrupted replacement is a unit whose bytes differ.
    publish_native_generation(tmp_path, 41)
    child = multiprocessing.get_context("spawn").Process(
        target=publish_native_generation, args=(tmp_path, 42), kwargs={"boundary": boundary}
    )
    child.start()
    child.join(20)
    try:
        assert child.exitcode == 91
        primary, plan = tmp_path / "primary/main.c", tmp_path / "plan/plan.json"

        def never_run(*args, **kwargs):
            pytest.fail("crashed generation reached a tool")

        with pytest.raises(NativePlanError, match="publication requires recovery"):
            NativePlanBuilder(runner=never_run).build(plan_path=plan, generated_c=primary, output=tmp_path / "program")
        CompilerGenerationPublisher(tmp_path / "state").recover(primary)
        NativePlanBuilder().build(plan_path=plan, generated_c=primary, output=tmp_path / "program")
        assert subprocess.run([str(tmp_path / "program")], timeout=15).returncode == 0
        assert f"== {42 if boundary == 'commit' else 41}" in primary.read_text()
    finally:
        if child.is_alive():
            child.terminate()
        child.join(10)


@pytest.mark.parametrize("cached", [False, True])
def test_native_build_holds_generation_through_compilation_and_link(tmp_path, cached):
    publish_native_generation(tmp_path, 41)
    context = multiprocessing.get_context("spawn")
    ready, done = context.Event(), context.Event()
    writer = context.Process(
        target=publish_native_generation, args=(tmp_path, 42), kwargs={"ready": ready, "done": done}
    )
    primary, plan = tmp_path / "primary/main.c", tmp_path / "plan/plan.json"
    output = tmp_path / "program"
    cache = tmp_path / "objects" if cached else None
    if cached:
        # Both builds use an injected runner and therefore ordinary validation.
        # Receipt admission intentionally requires the real subprocess capability.
        NativePlanBuilder(runner=lambda command, **kwargs: subprocess.run(command, **kwargs)).build(
            plan_path=plan, generated_c=primary, output=output, object_cache=cache
        )
    started = False

    def run(command, **kwargs):
        nonlocal started
        if not started:
            started = True
            writer.start()
            assert ready.wait(15), "writer did not reach the publication lock"
        assert not done.wait(0.1), "writer replaced an input during the native build"
        assert writer.is_alive()
        return subprocess.run(command, **kwargs)

    try:
        report = NativePlanBuilder(runner=run).build(
            plan_path=plan, generated_c=primary, output=output, object_cache=cache, jobs=1
        )
        assert started
        assert done.wait(15), "native builder failed to release its locks"
        writer.join(10)
        assert writer.exitcode == 0
        assert subprocess.run([str(output)], timeout=15).returncode == 0
        assert "== 42" in primary.read_text()
        if cached:
            assert all(unit.cache_status == "hit" for unit in report.units)
    finally:
        if started:
            if writer.is_alive():
                writer.terminate()
            writer.join(10)


def test_native_reader_rediscovers_changed_secondary_directories(tmp_path, monkeypatch):
    publish_native_generation(tmp_path, 41)
    read = ArtifactPublisher.read_directories
    attempts = []

    @contextlib.contextmanager
    def changed_between_locks(owner, directories):
        attempts.append(set(directories))
        with read(owner, directories):
            yield
        if len(attempts) == 1:
            publish_native_generation(tmp_path, 42, "moved")

    monkeypatch.setattr(ArtifactPublisher, "read_directories", changed_between_locks)
    output = tmp_path / "program"
    report = NativePlanBuilder().build(
        plan_path=tmp_path / "plan/plan.json", generated_c=tmp_path / "primary/main.c", output=output
    )
    assert len(attempts) == 3
    assert tmp_path / "moved" in attempts[-1]
    assert not (tmp_path / "secondary/part.c").exists()
    assert report.emitted_units == 2
    assert subprocess.run([str(output)], timeout=15).returncode == 0


@pytest.fixture
def aliased_generation(tmp_path):
    aliases = tmp_path / "aliases"
    aliases.mkdir()
    paths = {}
    for role, name in (("primary", "main.c"), ("secondary", "main.c.unit-1.c"), ("plan", "plan.json")):
        directory = tmp_path / role
        directory.mkdir()
        target = directory / name
        target.touch()
        alias = aliases / name
        alias.symlink_to(target)
        paths[role] = alias
    # Quoted includes must resolve beside the compiler's requested source path.
    (aliases / "config.h").write_text("#define EXPECTED 42\n")
    paths["primary"].write_text(
        '#include "config.h"\nint answer(void); int main(void) { return answer() == EXPECTED ? 0 : 1; }\n'
    )
    paths["secondary"].write_text("int answer(void) { return 42; }\n")
    payload = NativeLinkPlan.empty(PackageTarget.parse(None)).as_dict()
    payload.update(schema=4)
    payload["emitted-units"] = [str(paths["secondary"])]
    paths["plan"].write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")
    return paths


@pytest.mark.parametrize("cached", [False, True])
def test_generated_aliases_build_with_requested_include_paths_and_all_locks(tmp_path, aliased_generation, cached):
    paths = aliased_generation
    directories = {p.parent for p in paths.values()} | {p.resolve().parent for p in paths.values()}
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        if os.name != "nt":
            import fcntl

            for directory in directories:
                with (
                    (directory / ".btrc-publications.lock").open("r+b") as lock,
                    pytest.raises(BlockingIOError),
                ):
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return subprocess.run(command, **kwargs)

    output = tmp_path / "program"
    builder = NativePlanBuilder(runner=run)
    options = dict(plan_path=paths["plan"], generated_c=paths["primary"], output=output, jobs=1)
    if cached:
        options["object_cache"] = tmp_path / "objects"
    builder.build(**options)
    assert subprocess.run([str(output)], timeout=15).returncode == 0
    assert all(p.is_symlink() for p in paths.values())
    if cached:
        commands.clear()
        report = builder.build(**options)
        assert all(unit.cache_status == "hit" for unit in report.units)
        assert not any("-c" in command for command in commands)


@pytest.mark.parametrize("participant", ["primary", "secondary", "plan"])
def test_generated_alias_target_journal_rejects_before_tools(tmp_path, aliased_generation, participant):
    paths = aliased_generation
    marker = paths[participant].resolve().parent / ".interrupted.publish.journal"
    marker.write_text("untrusted journal")

    def never_run(*args, **kwargs):
        pytest.fail("aliased pending generation reached a native tool")

    with pytest.raises(NativePlanError, match="publication requires recovery"):
        NativePlanBuilder(runner=never_run).build(
            plan_path=paths["plan"], generated_c=paths["primary"], output=tmp_path / "program"
        )
    assert marker.read_text() == "untrusted journal"


@pytest.mark.parametrize("participant", ["primary", "secondary", "plan"])
def test_generated_alias_retarget_between_lock_attempts_is_rediscovered(
    tmp_path, aliased_generation, monkeypatch, participant
):
    paths = aliased_generation
    replacement = tmp_path / "replacement" / paths[participant].name
    replacement.parent.mkdir()
    replacement.write_bytes(paths[participant].read_bytes())
    read = ArtifactPublisher.read_directories
    attempts = []

    @contextlib.contextmanager
    def retarget_between_locks(owner, directories):
        attempts.append(set(directories))
        with read(owner, directories):
            yield
        if len(attempts) == 1:
            paths[participant].unlink()
            paths[participant].symlink_to(replacement)

    monkeypatch.setattr(ArtifactPublisher, "read_directories", retarget_between_locks)
    with NativePlanReader().generation(paths["plan"], paths["primary"]) as plan:
        assert replacement.parent in attempts[-1]
        assert plan.emitted_paths == (paths["secondary"],)
        assert paths[participant].resolve() == replacement


@pytest.mark.parametrize("field", ["headers", "units"])
def test_generated_alias_support_keeps_package_files_no_follow(tmp_path, aliased_generation, field):
    paths = aliased_generation
    package = tmp_path / "package"
    package.mkdir()
    source = package / "source.c"
    source.write_text("int external(void) { return 7; }\n")
    alias = package / "alias.c"
    alias.symlink_to(source)
    payload = json.loads(paths["plan"].read_text())
    payload["packages"] = [{"dependencies": {}, "name": "Package", "root": str(package)}]
    record = {"package": "Package", "path": str(source)}
    if field == "units":
        record.update(language="c", standard="c11")
    payload[field] = [record]
    paths["plan"].write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")
    # Establish that this exact plan is otherwise valid before substituting it.
    with NativePlanReader().generation(paths["plan"], paths["primary"]):
        pass
    record["path"] = str(alias)
    paths["plan"].write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")

    def never_run(*args, **kwargs):
        pytest.fail("package symlink reached a native build tool")

    with pytest.raises(NativePlanError, match="real regular file"):
        NativePlanBuilder(runner=never_run).build(
            plan_path=paths["plan"], generated_c=paths["primary"], output=tmp_path / "program"
        )


@pytest.mark.parametrize("participant", ["primary", "secondary", "plan"])
def test_generated_alias_discovery_is_bounded_under_repeated_retargeting(
    tmp_path, aliased_generation, monkeypatch, participant
):
    paths = aliased_generation
    contents = paths[participant].read_bytes()
    read = ArtifactPublisher.read_directories
    attempts = 0

    @contextlib.contextmanager
    def change_after_acquisition(owner, directories):
        nonlocal attempts
        attempts += 1
        target = tmp_path / f"generation-{attempts}" / paths[participant].name
        target.parent.mkdir()
        target.write_bytes(contents)
        with read(owner, directories):
            paths[participant].unlink()
            paths[participant].symlink_to(target)
            yield

    monkeypatch.setattr(ArtifactPublisher, "read_directories", change_after_acquisition)
    with (
        pytest.raises(NativePlanError, match="keeps changing"),
        NativePlanReader().generation(paths["plan"], paths["primary"]),
    ):
        pytest.fail("unstable alias generation was accepted")
    assert attempts == 8
    # Exhausting discovery releases every lock and permits a later stable read.
    monkeypatch.setattr(ArtifactPublisher, "read_directories", read)
    with NativePlanReader().generation(paths["plan"], paths["primary"]):
        pass


def _publish_secondary(destination, ready, done):
    staged = destination.with_name("new-secondary.c")
    staged.write_text("int answer(void) { return 42; }\n")
    lock = PublicationLock._lock_descriptor

    def locking(owner):
        ready.set()
        return lock(owner)

    PublicationLock._lock_descriptor = locking
    try:
        ArtifactPublisher().publish("secondary", [PublishedArtifact(staged, destination)])
        done.set()
    finally:
        PublicationLock._lock_descriptor = lock


@pytest.mark.parametrize("fail_build", [False, True])
def test_secondary_only_publisher_waits_for_reader_and_failed_build_releases_it(tmp_path, fail_build):
    publish_native_generation(tmp_path, 41)
    context = multiprocessing.get_context("spawn")
    ready, done = context.Event(), context.Event()
    writer = context.Process(target=_publish_secondary, args=(tmp_path / "secondary/part.c", ready, done))
    started = False

    def run(command, **kwargs):
        nonlocal started
        if not started:
            started = True
            writer.start()
            assert ready.wait(15)
        assert not done.wait(0.1), "secondary input was unprotected"
        if fail_build:
            raise NativePlanError("injected compile failure")
        return subprocess.run(command, **kwargs)

    output = tmp_path / "program"
    output.write_bytes(b"old executable")
    try:
        expected = (
            pytest.raises(NativePlanError, match="injected compile failure") if fail_build else contextlib.nullcontext()
        )
        with expected:
            NativePlanBuilder(runner=run).build(
                plan_path=tmp_path / "plan/plan.json", generated_c=tmp_path / "primary/main.c", output=output, jobs=1
            )
        assert done.wait(15)
        writer.join(10)
        assert writer.exitcode == 0
        if fail_build:
            assert output.read_bytes() == b"old executable"
        else:
            assert subprocess.run([str(output)], timeout=15).returncode == 0
    finally:
        if started:
            if writer.is_alive():
                writer.terminate()
            writer.join(10)


@pytest.mark.parametrize("destination", ["output", "report"])
@pytest.mark.parametrize("name", [".btrc-publications.lock", ".example.publish.journal", ".example.publish.previous-0"])
def test_native_outputs_cannot_replace_publication_control_files(tmp_path, destination, name):
    primary = tmp_path / "main.c"
    plan = tmp_path / "plan.json"
    primary.write_text("int main(void) { return 0; }\n")
    plan.write_text(NativeLinkPlan.empty(PackageTarget.parse(None)).canonical_json())

    def never_run(*args, **kwargs):
        pytest.fail("publication control output reached a build tool")

    options = {"output": tmp_path / "program", "report_path": None}
    options["output" if destination == "output" else "report_path"] = tmp_path / name
    with pytest.raises(NativePlanError, match="publication control"):
        NativePlanBuilder(runner=never_run).build(plan_path=plan, generated_c=primary, **options)


def _native_plan_import_closure() -> set[str]:
    """Every repository file that importing and running tools.native_plan executes.

    Function-level imports count: the adapter imports the header reader's owner
    only while it keys cached objects. Package initializers count because
    importing a module runs each enclosing one. ``if TYPE_CHECKING:`` bodies
    never run, so they do not.
    """

    def module_file(module: str) -> Path | None:
        base = REPO.joinpath(*module.split("."))
        for candidate in (base.with_name(f"{base.name}.py"), base / "__init__.py"):
            if candidate.is_file():
                return candidate
        return None

    def executed_imports(tree: ast.AST) -> Iterator[ast.Import | ast.ImportFrom]:
        pending: list[ast.AST] = [tree]
        while pending:
            node = pending.pop()
            if isinstance(node, ast.If) and (
                (isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING")
                or (isinstance(node.test, ast.Attribute) and node.test.attr == "TYPE_CHECKING")
            ):
                pending.extend(node.orelse)
                continue
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                yield node
            pending.extend(ast.iter_child_nodes(node))

    closure: set[str] = set()
    visited: set[str] = set()
    pending = ["tools.native_plan"]
    while pending:
        module = pending.pop()
        if module in visited or module.split(".")[0] not in {"src", "tools"}:
            continue
        visited.add(module)
        parts = module.split(".")
        for depth in range(1, len(parts) + 1):
            executed = module_file(".".join(parts[:depth]))
            if executed is not None:
                closure.add(executed.relative_to(REPO).as_posix())
        source = module_file(module)
        if source is None:
            continue
        package = parts if source.name == "__init__.py" else parts[:-1]
        for node in executed_imports(ast.parse(source.read_text(), str(source))):
            if isinstance(node, ast.Import):
                pending.extend(alias.name for alias in node.names)
                continue
            anchor = package[: len(package) - node.level + 1] if node.level else []
            base = ".".join([*anchor, *([node.module] if node.module else [])])
            # ``from package import name`` imports name when it is a submodule.
            pending.extend([base, *(f"{base}.{alias.name}" for alias in node.names)])
    return closure


def _flake_native_plan_files(flake: str) -> set[str]:
    source = flake.split("nativePlanSource = sourceSubset", 1)[1].split("formatterSource", 1)[0]
    # Exact files only: a directory prefix would ship modules the adapter never imports.
    assert "prefixes = [ ];" in source
    listed = re.search(r"files = \[(.*?)\];", source, re.DOTALL)
    assert listed is not None
    return set(re.findall(r'"([^"\n]+)"', listed.group(1)))


def test_standalone_native_plan_distribution_reuses_cached_objects(tmp_path):
    """The packaged closure alone keys, builds and then reuses a cached object."""
    distribution = tmp_path / "distribution"
    for relative in _flake_native_plan_files((REPO / "flake.nix").read_text()):
        target = distribution / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / relative, target)
    work = tmp_path / "work"
    work.mkdir()
    primary = work / "main.c"
    plan = work / "plan.json"
    primary.write_text("int main(void) { return 0; }\n")
    plan.write_text(NativeLinkPlan.empty(PackageTarget.parse(None)).canonical_json())
    output = work / "program"
    reports = []
    for run in (1, 2):
        report = work / f"report-{run}.json"
        # -P and a working directory outside the checkout: every import must
        # resolve from the distribution, as it does from the Nix store.
        completed = subprocess.run(
            [
                sys.executable,
                "-P",
                "-m",
                "tools.native_plan",
                "--plan",
                str(plan),
                "--generated-c",
                str(primary),
                "--output",
                str(output),
                "--object-cache",
                str(work / "objects"),
                "--report-json",
                str(report),
            ],
            cwd=work,
            env={**os.environ, "PYTHONPATH": str(distribution)},
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert completed.returncode == 0, completed.stderr
        assert subprocess.run([str(output)], timeout=15).returncode == 0
        reports.append(json.loads(report.read_text()))
    assert [(report["compiled_units"], report["reused_units"]) for report in reports] == [(1, 0), (0, 1)]


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="requires POSIX FIFO")
def test_native_plan_fifo_rejects_without_blocking(tmp_path):
    plan = tmp_path / "plan.json"
    os.mkfifo(plan)
    primary = tmp_path / "main.c"
    primary.write_text("int main(void) { return 0; }\n")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.native_plan",
            "--plan",
            str(plan),
            "--generated-c",
            str(primary),
            "--output",
            str(tmp_path / "program"),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 1
    assert "regular file" in completed.stderr


@pytest.mark.parametrize("adapter", [False, True])
def test_secondary_inventory_builds_from_another_working_directory(tmp_path, monkeypatch, adapter):
    primary = tmp_path / "main.c"
    function = "bridge" if adapter else "answer"
    primary.write_text(f"int {function}(void); int main(void) {{ return {function}() == 42 ? 0 : 1; }}\n")
    directory = tmp_path / "secondary units"
    directory.mkdir()
    secondary = directory / "part.c"
    secondary.write_text("int answer(void) { return 42; }\n")
    payload = (
        generated_plan("int answer(void); int bridge(void) { return answer(); }\n")
        if adapter
        else NativeLinkPlan.empty(PackageTarget.parse(None)).as_dict()
    )
    payload.update(schema=4)
    payload["emitted-units"] = [str(secondary)]
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")
    monkeypatch.chdir(directory)
    output = tmp_path / "program"
    report = NativePlanBuilder().build(plan_path=plan, generated_c=primary, output=output)
    assert report.emitted_units == 2
    assert report.adapter_units == int(adapter)
    assert subprocess.run([str(output)], timeout=15).returncode == 0


@pytest.mark.parametrize(
    "damage",
    [
        "integer",
        "bool",
        "empty",
        "relative",
        "nul",
        "object",
        "duplicate",
        "hardlink",
        "symlink-duplicate",
        "symlink-dangling",
        "symlink-loop",
        "directory",
        "missing",
        "primary",
    ],
)
def test_invalid_secondary_inventory_never_invokes_tools(tmp_path, damage):
    primary = tmp_path / "main.c"
    primary.write_text("int main(void) { return 0; }\n")
    secondary = tmp_path / "part.c"
    secondary.write_text("int answer(void) { return 42; }\n")
    records = [str(secondary)]
    if damage in {"integer", "bool", "empty", "relative", "nul", "object"}:
        records = {
            "integer": 1,
            "bool": True,
            "empty": [],
            "relative": ["part.c"],
            "nul": ["bad\0path"],
            "object": [{}],
        }[damage]
    elif damage == "duplicate":
        records *= 2
    elif damage == "hardlink":
        alias = tmp_path / "alias.c"
        os.link(secondary, alias)
        records.append(str(alias))
    elif damage.startswith("symlink-"):
        alias = tmp_path / "alias.c"
        alias.symlink_to(alias if damage == "symlink-loop" else secondary)
        if damage == "symlink-duplicate":
            records.append(str(alias))
        else:
            records = [str(alias)]
            if damage == "symlink-dangling":
                secondary.unlink()
    elif damage == "directory":
        records = [str(tmp_path)]
    elif damage == "missing":
        secondary.unlink()
    elif damage == "primary":
        records = [str(primary)]
    payload = NativeLinkPlan.empty(PackageTarget.parse(None)).as_dict()
    payload.update(schema=4)
    payload["emitted-units"] = records
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")

    def never_run(*args, **kwargs):
        pytest.fail("invalid secondary inventory reached a build tool")

    with pytest.raises(NativePlanError):
        NativePlanBuilder(runner=never_run).build(plan_path=plan, generated_c=primary, output=tmp_path / "program")


@pytest.mark.parametrize(
    "corruption",
    ["empty", "duplicate", "name", "language", "standard", "memory", "source", "flags", "linker", "schema"],
)
def test_generated_unit_invalid_plan_never_invokes_compiler(tmp_path, corruption):
    payload = generated_plan()
    unit = payload["generated-units"][0]
    if corruption == "empty":
        payload["generated-units"] = []
    elif corruption == "duplicate":
        payload["generated-units"].append(dict(unit))
    elif corruption == "name":
        unit["name"] = "../Escape"
    elif corruption == "language":
        unit["language"] = "c -include injected.h"
    elif corruption == "standard":
        unit["standard"] = "c89"
    elif corruption == "memory":
        unit["memory-management"] = "arc"
    elif corruption == "source":
        unit["source"] = "bad\0source"
    elif corruption == "flags":
        unit["flags"] = ["-include", "injected.h"]
    elif corruption == "linker":
        payload["linker-language"] = "c++"
    else:
        payload["schema"] = 1
    plan = tmp_path / "Program.link.json"
    plan.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")

    def never_run(*args, **kwargs):
        pytest.fail("invalid generated plan reached a build tool")

    with pytest.raises(NativePlanError):
        NativePlanBuilder(runner=never_run).build(
            plan_path=plan, generated_c=tmp_path / "absent.c", output=tmp_path / "absent"
        )


@pytest.mark.parametrize(
    "language,standard,memory,source",
    [
        ("c", "c11", "manual", "int answer(void) { return 42; }\n"),
        (
            "c++",
            "c++17",
            "raii",
            '#include <string>\nextern "C" int answer(void) { try { throw std::string("forty two"); } catch (const std::string& text) { return text.size() == 9 ? 42 : 0; } }\n',
        ),
    ],
)
def test_generated_unit_build_isolated_from_source_tree(tmp_path, language, standard, memory, source):
    payload = generated_plan(source, language, standard, memory)
    plan = tmp_path / "Program.link.json"
    plan.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")
    caller = tmp_path / "Caller.c"
    caller.write_text("int answer(void); int main(void) { return answer() == 42 ? 0 : 1; }\n")
    output = tmp_path / "Program"
    NativePlanBuilder().build(plan_path=plan, generated_c=caller, output=output)
    run = subprocess.run([str(output)], capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stderr
    locks = list(tmp_path.glob(".native-*.publish.lock"))
    assert len(locks) == 1
    assert {path.name for path in tmp_path.iterdir() if path not in locks} == {
        "Program.link.json",
        "Caller.c",
        "Program",
        ".btrc-publications.lock",
    }


def test_failed_generated_unit_preserves_output_and_removes_temporary_files(tmp_path):
    payload = generated_plan('#error "generated adapter failure"\n')
    plan = tmp_path / "Program.link.json"
    plan.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")
    caller = tmp_path / "Caller.c"
    caller.write_text("int main(void) { return 0; }\n")
    output = tmp_path / "Program"
    output.write_bytes(b"previous output")
    with pytest.raises(NativePlanError, match="generated adapter failure"):
        NativePlanBuilder().build(plan_path=plan, generated_c=caller, output=output)
    assert output.read_bytes() == b"previous output"
    assert set(path.name for path in tmp_path.iterdir()) == {
        "Program.link.json",
        "Caller.c",
        "Program",
        ".btrc-publications.lock",
    }


def _emit_plan(root: Path, generated: Path, plan: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            "--no-stdlib",
            "--no-cache",
            "--target",
            "linux-x64",
            "--emit-link-plan",
            str(plan),
            str(root / "src/Main.btrc"),
            "-o",
            str(generated),
        ],
        cwd=REPO,
        env=cross_target_environment(generated.parent, "linux-x64"),
        capture_output=True,
        text=True,
        timeout=TRANSPILE_TIMEOUT,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("optimization", [None, 0, 1, 2, 3])
def test_builder_compiles_only_plan_units_and_runs(tmp_path: Path, optimization: int | None) -> None:
    project = tmp_path / "project"
    shutil.copytree(EXAMPLE, project, ignore=shutil.ignore_patterns(".btrc-cache", "build"))
    poison = project / "packages/middle/native/not-declared.c"
    poison.write_text('#error "a native-plan consumer must not scan source directories"\n')
    generated = tmp_path / "program.c"
    plan = tmp_path / "program.link.json"
    output = tmp_path / "program"
    _emit_plan(project, generated, plan)

    commands: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.run(command, **kwargs)

    options = {} if optimization is None else {"optimization": optimization}
    NativePlanBuilder(runner=run).build(plan_path=plan, generated_c=generated, output=output, **options)

    compiles = [command for command in commands if "-c" in command]
    assert len(compiles) == 1 + len(json.loads(plan.read_text())["units"])
    for command in compiles:
        assert [flag for flag in command if flag.startswith("-O")] == [
            f"-O{2 if optimization is None else optimization}"
        ]
        assert "-Werror" in command

    completed = subprocess.run([str(output)], capture_output=True, check=True, text=True, timeout=RUN_TIMEOUT)
    assert completed.stdout == "PASS: native package graph\n"
    assert poison.is_file()


@pytest.mark.parametrize("optimization", [-1, 4, True, 2.0, "2 -ffast-math"])
def test_builder_rejects_invalid_optimization_before_build(tmp_path: Path, optimization: object) -> None:
    with pytest.raises(NativePlanError, match="optimization must be an integer from 0 through 3"):
        NativePlanBuilder().build(
            plan_path=tmp_path / "absent.link.json",
            generated_c=tmp_path / "absent.c",
            output=tmp_path / "must-not-exist",
            optimization=optimization,
        )
    assert not (tmp_path / "must-not-exist").exists()


def test_cli_rejects_free_form_optimization(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as failure:
        main(
            [
                "--plan",
                str(tmp_path / "absent.link.json"),
                "--generated-c",
                str(tmp_path / "absent.c"),
                "--output",
                str(tmp_path / "must-not-exist"),
                "--optimization",
                "2 -ffast-math",
            ]
        )
    assert failure.value.code == 2


def test_builder_rejects_non_schema_flags_before_build(tmp_path: Path) -> None:
    project = tmp_path / "project"
    shutil.copytree(EXAMPLE, project, ignore=shutil.ignore_patterns(".btrc-cache", "build"))
    generated = tmp_path / "program.c"
    plan = tmp_path / "program.link.json"
    _emit_plan(project, generated, plan)
    payload = json.loads(plan.read_text())
    payload["cflags"] = ["-include", "/tmp/injected.h"]
    plan.write_text(
        json.dumps(payload, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    )

    with pytest.raises(NativePlanError, match="must contain exactly"):
        NativePlanBuilder().build(
            plan_path=plan,
            generated_c=generated,
            output=tmp_path / "must-not-exist",
        )

    assert not (tmp_path / "must-not-exist").exists()


def test_reader_compares_real_paths_for_package_containment(tmp_path: Path) -> None:
    project = tmp_path / "project"
    shutil.copytree(EXAMPLE, project, ignore=shutil.ignore_patterns(".btrc-cache", "build"))
    generated = tmp_path / "program.c"
    plan = tmp_path / "program.link.json"
    _emit_plan(project, generated, plan)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "escaped.c").write_text("int escaped(void) { return 0; }\n")
    escape = project / "packages/leaf/native/escape"
    try:
        escape.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink containment proof is unavailable on this host")
    payload = json.loads(plan.read_text())
    payload["units"].append(
        {
            "language": "c",
            "package": "leaf",
            "path": str(escape / "escaped.c"),
            "standard": "c11",
        }
    )
    payload["units"].sort(key=lambda unit: (unit["package"], unit["path"], unit["language"]))
    plan.write_text(
        json.dumps(payload, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    )

    with pytest.raises(NativePlanError, match="escapes package root"):
        NativePlanReader().read(plan)


def test_reader_rejects_frameworks_for_non_macos_target(tmp_path: Path) -> None:
    project = tmp_path / "project"
    shutil.copytree(EXAMPLE, project, ignore=shutil.ignore_patterns(".btrc-cache", "build"))
    generated = tmp_path / "program.c"
    plan = tmp_path / "program.link.json"
    _emit_plan(project, generated, plan)
    payload = json.loads(plan.read_text())
    payload["frameworks"] = [{"name": "Cocoa", "package": "middle"}]
    plan.write_text(
        json.dumps(payload, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    )

    with pytest.raises(NativePlanError, match="frameworks require a macos target"):
        NativePlanReader().read(plan)


def test_example_makefile_realizes_the_canonical_plan(tmp_path: Path) -> None:
    cc = shutil.which("cc")
    cxx = shutil.which("c++")
    make = shutil.which("make")
    if cc is None or cxx is None or make is None:
        pytest.skip("native Make proof needs make, C, and C++ compilers")
    environment = cross_target_environment(tmp_path, "linux-x64", {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    try:
        completed = subprocess.run(
            [
                make,
                "-C",
                str(EXAMPLE),
                "clean",
                "run",
                "TARGET=linux-x64",
                f"PYTHON={sys.executable}",
                f"CC={cc}",
                f"CXX={cxx}",
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
            env=environment,
            timeout=TRANSPILE_TIMEOUT,
        )
        assert completed.returncode == 0, completed.stderr
        assert "PASS: native package graph" in completed.stdout
        plan = EXAMPLE / "build/native-package.link.json"
        assert plan.is_file()
        assert json.loads(plan.read_text())["units"][1]["language"] == "c++"
    finally:
        shutil.rmtree(EXAMPLE / "build", ignore_errors=True)


def test_adapter_has_no_shell_or_source_discovery_surface() -> None:
    source = (REPO / "tools/native_plan.py").read_text()

    assert "shell=False" in source
    assert ".glob(" not in source
    assert ".rglob(" not in source
    assert "os.walk(" not in source
    marker = "ROOT_FIELDS = frozenset("
    start = source.index(marker)
    end = source.index("TARGET_OPERATING_SYSTEMS", start)
    assert '"cflags"' not in source[start:end]


def test_flake_installs_adapter_and_runs_native_plan_check() -> None:
    flake = (REPO / "flake.nix").read_text()

    assert 'name = "btrc-native-plan";' in flake
    closure = _native_plan_import_closure()
    # The lazily imported header reader owner is what the package once lacked.
    assert "src/compiler/python/frontend/native_imports.py" in closure
    assert _flake_native_plan_files(flake) == closure
    # The devcontainer evaluates this flake from a copied subset of the tree.
    copied = [
        source
        for line in (REPO / "nix" / "containerfile.nix").read_text().splitlines()
        if line.strip().startswith("COPY ")
        for source in line.split()[2:-1]
    ]
    assert not [
        file
        for file in closure
        if not any(file == source or (source.endswith("/") and file.startswith(source)) for source in copied)
    ]
    launcher = flake.split("nativePlan = pkgs.writeShellApplication", 1)[1].split("nativeHeaderReader", 1)[0]
    assert 'export PYTHONPATH="${nativePlanSource}"' in launcher
    assert "python3 -P -m tools.native_plan" in launcher
    assert "btrc = pkgs.symlinkJoin" in flake
    assert "native-package-plan = pkgs.runCommand" in flake
    assert "NATIVE_PLAN=${self.packages.${system}.btrc-native-plan}/bin/btrc-native-plan" in flake
    check = flake.split("native-package-plan = pkgs.runCommand", 1)[1]
    # The sandbox HOME is read-only, and both compilers publish through state.
    assert 'export BTRC_STATE_DIR="$TMPDIR/btrc-state"' in check
    assert "--object-cache build/objects" in check
    assert "for run in 1 2; do" in check
    assert "jq -e '.compiled_units == 0 and .reused_units == (.units | length)'" in check


def test_object_cache_skips_unchanged_compiles(tmp_path: Path) -> None:
    project = tmp_path / "project"
    shutil.copytree(EXAMPLE, project, ignore=shutil.ignore_patterns(".btrc-cache", "build"))
    generated = tmp_path / "program.c"
    plan = tmp_path / "program.link.json"
    output = tmp_path / "program"
    cache = tmp_path / "objects"
    _emit_plan(project, generated, plan)

    commands: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.run(command, **kwargs)

    builder = NativePlanBuilder(runner=run)
    builder.build(plan_path=plan, generated_c=generated, output=output, object_cache=cache)
    first = [command for command in commands if "-c" in command]
    assert len(first) == 1 + len(json.loads(plan.read_text())["units"])
    assert len(list(cache.glob("*.o"))) == len(first)

    commands.clear()
    output.unlink()
    builder.build(plan_path=plan, generated_c=generated, output=output, object_cache=cache)
    assert [command for command in commands if "-c" in command] == []
    assert (
        subprocess.run([str(output)], capture_output=True, check=True, text=True, timeout=RUN_TIMEOUT).stdout
        == "PASS: native package graph\n"
    )

    generated.write_text(generated.read_text().replace("PASS: native package graph", "PASS: edited"))
    commands.clear()
    builder.build(plan_path=plan, generated_c=generated, output=output, object_cache=cache, optimization=0)
    recompiled = [command for command in commands if "-c" in command]
    assert len(recompiled) == 1 + len(json.loads(plan.read_text())["units"]), "new flags miss for every source"
    commands.clear()
    builder.build(plan_path=plan, generated_c=generated, output=output, object_cache=cache)
    assert [command[command.index("-c") + 1] for command in commands if "-c" in command] == [str(generated)]
    assert (
        subprocess.run([str(output)], capture_output=True, check=True, text=True, timeout=RUN_TIMEOUT).stdout
        == "PASS: edited\n"
    )


def test_object_cache_reports_the_receipt_path_it_took(tmp_path: Path) -> None:
    """Off Darwin the object cache stands on its dependency scan and every build relinks."""
    project = tmp_path / "project"
    shutil.copytree(EXAMPLE, project, ignore=shutil.ignore_patterns(".btrc-cache", "build"))
    generated = tmp_path / "program.c"
    plan = tmp_path / "program.link.json"
    output = tmp_path / "program"
    _emit_plan(project, generated, plan)
    options = {"plan_path": plan, "generated_c": generated, "output": output, "object_cache": tmp_path / "objects"}
    cold = NativePlanBuilder().build(**options)
    warm = NativePlanBuilder().build(**options)
    assert warm.as_dict()["compiled_units"] == 0 and warm.as_dict()["reused_units"] == len(warm.units)
    if sys.platform == "darwin":
        assert cold.preprocessing_provider != "none"
    else:
        for report in (cold, warm):
            assert report.preprocessing_provider == "dependency-scan: host has no receipt provider"
            assert report.link_cache_status == "host-unsupported" and report.links == 1
            assert {unit.preprocessing_status for unit in report.units} == {"ordinary"}
    assert NativePlanBuilder().build(plan_path=plan, generated_c=generated, output=output).preprocessing_provider == (
        "none"
    )


@pytest.mark.parametrize(
    ("system", "runner", "drivers", "environment", "reason"),
    [
        ("linux", subprocess.run, ("/nix/store/x/bin/clang",), {}, "host has no receipt provider"),
        ("darwin", subprocess.check_output, ("/nix/store/x/bin/clang",), {}, "injected runner"),
        ("darwin", subprocess.run, ("/usr/bin/clang",), {}, "drivers outside the store"),
        ("darwin", subprocess.run, (), {}, "drivers outside the store"),
        (
            "darwin",
            subprocess.run,
            ("/nix/store/x/bin/clang",),
            {"BTRC_NATIVE_PREPROCESS_RECEIPTS": "0"},
            "BTRC_NATIVE_PREPROCESS_RECEIPTS=0",
        ),
        ("darwin", subprocess.run, ("/nix/store/x/bin/clang",), {}, None),
    ],
)
def test_preprocessing_receipts_name_why_a_build_cannot_use_them(
    monkeypatch, system, runner, drivers, environment, reason
):
    from tools.native_plan import _PreprocessingReceipts

    monkeypatch.delenv("BTRC_NATIVE_PREPROCESS_RECEIPTS", raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    found = _PreprocessingReceipts.unavailable(drivers, runner, system)
    assert found == (None if reason is None else f"dependency-scan: {reason}")


@pytest.fixture
def cached_program(tmp_path):
    """Exercise the real build adapter and executable, retaining every tool invocation."""
    plan = tmp_path / "program.link.json"
    plan.write_text(NativeLinkPlan(PackageTarget.parse(None)).canonical_json())
    source = tmp_path / "program.c"
    output = tmp_path / "program"
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return subprocess.run(command, **kwargs)

    def build(**options):
        commands.clear()
        NativePlanBuilder(runner=run).build(
            plan_path=plan,
            generated_c=options.pop("generated_c", source),
            output=output,
            object_cache=tmp_path / "objects",
            **options,
        )
        return subprocess.run([str(output)], capture_output=True, text=True, check=True, timeout=RUN_TIMEOUT).stdout

    return source, output, commands, build


def test_object_cache_tracks_transitive_headers_and_removal(cached_program):
    source, output, commands, build = cached_program
    header = source.parent / "value.h"
    nested = source.parent / "nested.h"
    source.write_text('#include <stdio.h>\n#include "value.h"\nint main(void) { printf("%d\\n", VALUE); }\n')
    header.write_text('#include "nested.h"\n')
    nested.write_text("#define VALUE 41\n")
    assert build() == "41\n"
    assert build() == "41\n"
    assert not any("-c" in command for command in commands)
    original_times = nested.stat()
    nested.write_text("#define VALUE 42\n")
    os.utime(nested, ns=(original_times.st_atime_ns, original_times.st_mtime_ns))
    assert build() == "42\n", "same-size, same-mtime transitive header edit must invalidate"
    assert sum("-c" in command for command in commands) == 1
    previous = output.read_bytes()
    nested.unlink()
    with pytest.raises(NativePlanError, match=r"nested\.h"):
        build()
    assert output.read_bytes() == previous


def test_object_cache_rescans_include_resolution(cached_program, monkeypatch):
    source, _, commands, build = cached_program
    early, late = source.parent / "early", source.parent / "late"
    early.mkdir()
    late.mkdir()
    monkeypatch.setenv("CPATH", os.pathsep.join(map(str, (early, late))))
    source.write_text('#include <stdio.h>\n#include <choice.h>\nint main(void) { printf("%d\\n", VALUE); }\n')
    (late / "choice.h").write_text("#define VALUE 1\n")
    assert build() == "1\n"
    (early / "choice.h").write_text("#define VALUE 2\n")
    assert build() == "2\n", "a new earlier include did not exist in the old dependency list"
    assert sum("-c" in command for command in commands) == 1
    monkeypatch.setenv("CPATH", str(late))
    assert build() == "1\n"


def test_object_cache_preserves_observable_source_path(cached_program):
    source, _, commands, build = cached_program
    source.write_text("#include <stdio.h>\nint main(void) { puts(__FILE__); }\n")
    assert build().strip() == str(source)
    moved = source.parent / "moved.c"
    shutil.copyfile(source, moved)
    assert build(generated_c=moved).strip() == str(moved)
    assert sum("-c" in command for command in commands) == 1


@pytest.mark.parametrize("damage", ["object", "manifest"])
def test_object_cache_rebuilds_corrupt_entries(cached_program, damage):
    source, _, commands, build = cached_program
    source.write_text("int main(void) { return 0; }\n")
    build()
    suffix = ".o" if damage == "object" else ".json"
    records = list((source.parent / "objects").glob(f"*{suffix}"))
    assert len(records) == 1
    records[0].write_bytes(b"interrupted or corrupt cache entry")
    build()
    assert sum("-c" in command for command in commands) == 1


def test_object_cache_hashes_compiler_executable(cached_program):
    if os.name == "nt":
        pytest.skip("this compiler-wrapper fixture uses a POSIX shell")
    import shlex

    source, _, commands, build = cached_program
    source.write_text("int main(void) { return 0; }\n")
    wrapper = source.parent / "compiler"
    script = f'#!/bin/sh\nexec {shlex.quote(shutil.which("cc"))} "$@"\n'
    wrapper.write_text(script)
    wrapper.chmod(0o755)
    build(cc=str(wrapper))
    build(cc=str(wrapper))
    assert not any("-c" in command for command in commands)
    wrapper.write_text(script + "# replacement with identical --version output\n")
    build(cc=str(wrapper))
    assert sum("-c" in command for command in commands) == 1


def test_object_cache_handles_make_escaped_header_paths(cached_program, monkeypatch):
    source, _, commands, build = cached_program
    headers = source.parent / "header space $ #"
    headers.mkdir()
    header = headers / "values.h"
    header.write_text("#define VALUE 10\n")
    monkeypatch.setenv("CPATH", str(headers))
    source.write_text('#include <stdio.h>\n#include <values.h>\nint main(void) { printf("%d\\n", VALUE); }\n')
    assert build() == "10\n"
    assert build() == "10\n"
    assert not any("-c" in command for command in commands), "escaped paths must permit validated hits"
    header.write_text("#define VALUE 20\n")
    assert build() == "20\n"


def test_object_cache_validates_system_headers(cached_program, monkeypatch):
    source, _, commands, build = cached_program
    header = source.parent / "system-value.h"
    header.write_text("#define VALUE 31\n")
    # C_INCLUDE_PATH is a system-header search path, unlike ordinary -I/CPATH.
    monkeypatch.setenv("C_INCLUDE_PATH", str(source.parent))
    source.write_text('#include <stdio.h>\n#include <system-value.h>\nint main(void) { printf("%d\\n", VALUE); }\n')
    assert build() == "31\n"
    header.write_text("#define VALUE 32\n")
    assert build() == "32\n"
    assert sum("-c" in command for command in commands) == 1


def test_object_cache_does_not_publish_inputs_changed_during_compile(tmp_path):
    plan = tmp_path / "program.link.json"
    plan.write_text(NativeLinkPlan(PackageTarget.parse(None)).canonical_json())
    source = tmp_path / "program.c"
    header = tmp_path / "value.h"
    source.write_text('#include <stdio.h>\n#include "value.h"\nint main(void) { printf("%d\\n", VALUE); }\n')
    header.write_text("#define VALUE 1\n")
    output = tmp_path / "program"
    cache = tmp_path / "objects"

    def run(command, **kwargs):
        completed = subprocess.run(command, **kwargs)
        if "-c" in command:
            header.write_text("#define VALUE 2\n")
        return completed

    NativePlanBuilder(runner=run).build(plan_path=plan, generated_c=source, output=output, object_cache=cache)
    assert not list(cache.glob("*.json")), "changed dependencies cannot publish the pre-compile key"
    NativePlanBuilder().build(plan_path=plan, generated_c=source, output=output, object_cache=cache)
    assert (
        subprocess.run([str(output)], capture_output=True, text=True, check=True, timeout=RUN_TIMEOUT).stdout == "2\n"
    )


def test_object_cache_publication_supports_concurrent_builds(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    plan = tmp_path / "program.link.json"
    plan.write_text(NativeLinkPlan(PackageTarget.parse(None)).canonical_json())
    source = tmp_path / "program.c"
    source.write_text("int main(void) { return 0; }\n")
    cache = tmp_path / "objects"

    def build(index):
        output = tmp_path / f"program-{index}"
        NativePlanBuilder().build(plan_path=plan, generated_c=source, output=output, object_cache=cache)
        subprocess.run([str(output)], check=True, timeout=RUN_TIMEOUT)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(build, range(8)))
    assert len(list(cache.glob("*.o"))) == len(list(cache.glob("*.json"))) == 1
    assert not list(cache.glob(".*")), "completed scans and publications leave no temporary entries"


def test_object_cache_unavailable_directory_does_not_prevent_build(cached_program):
    source, _, commands, build = cached_program
    source.write_text("int main(void) { return 0; }\n")
    (source.parent / "objects").write_text("not a directory")
    build()
    assert sum("-c" in command for command in commands) == 1


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("aliased", [False, True])
def test_emitted_native_plan_cache_through_both_frontends(tmp_path, request, frontend, aliased):
    project = tmp_path / "project"
    shutil.copytree(EXAMPLE, project, ignore=shutil.ignore_patterns(".btrc-cache", "build"))
    generated = tmp_path / "program.c"
    plan = tmp_path / "program.link.json"
    output = tmp_path / "program"
    secondary = tmp_path / "secondary units"
    secondary.mkdir()
    prefix = secondary / "parts"
    aliases = (generated, plan, Path(f"{prefix}.unit-1.c")) if aliased else ()
    for index, alias in enumerate(aliases):
        directory = tmp_path / f"storage-{index}"
        directory.mkdir()
        target = directory / alias.name
        target.touch(mode=0o640)
        alias.symlink_to(target)
    driver = (
        [sys.executable, "-m", "src.compiler.python.main", "--no-cache"]
        if frontend == "python"
        else [str(request.getfixturevalue("immutable_btrcc"))]
    )
    emitted = subprocess.run(
        [
            *driver,
            "--no-stdlib",
            "--strict-imports",
            "--target",
            "linux-x64",
            "--emit-link-plan",
            str(plan),
            "--emit-units",
            str(prefix),
            str(project / "src/Main.btrc"),
            "-o",
            str(generated),
        ],
        cwd=REPO,
        env=cross_target_environment(tmp_path, "linux-x64", {**os.environ, "BTRC_UNIT_LINES": "1"}),
        capture_output=True,
        text=True,
        timeout=TRANSPILE_TIMEOUT,
    )
    assert emitted.returncode == 0, emitted.stderr
    assert all(alias.is_symlink() for alias in aliases)
    assert len(json.loads(plan.read_text())["emitted-units"]) >= 1
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return subprocess.run(command, **kwargs)

    builder = NativePlanBuilder(runner=run)
    cache = tmp_path / "objects"
    builder.build(plan_path=plan, generated_c=generated, output=output, object_cache=cache)
    commands.clear()
    builder.build(plan_path=plan, generated_c=generated, output=output, object_cache=cache)
    assert not any("-c" in command for command in commands)
    assert (
        subprocess.run([str(output)], check=True, capture_output=True, text=True, timeout=RUN_TIMEOUT).stdout
        == "PASS: native package graph\n"
    )


@pytest.mark.parametrize("kind", ["native", "adapter"])
@pytest.mark.parametrize("jobs", [1, 2])
@pytest.mark.parametrize("fail_native", [False, True])
def test_all_translation_units_share_bounded_workers(tmp_path, kind, jobs, fail_native):
    import threading

    source = tmp_path / "main.c"
    source.write_text("int answer(void); int main(void) { return answer() == 42 ? 0 : 1; }\n")
    adapter = 'extern "C" int answer(void) { return 42; }\n'
    if fail_native:
        adapter += "#error worker failure\n"
    if kind == "adapter":
        payload = generated_plan(adapter, "c++", "c++17", "raii")
    else:
        package = tmp_path / "package"
        package.mkdir()
        native = package / "answer.cpp"
        native.write_text(adapter)
        payload = NativeLinkPlan.empty(PackageTarget.parse(None)).as_dict()
        payload["packages"] = [{"dependencies": {}, "name": "Package", "root": str(package)}]
        payload["units"] = [{"package": "Package", "path": str(native), "language": "c++", "standard": "c++17"}]
        payload["linker-language"] = "c++"
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    output = tmp_path / "program"
    output.write_bytes(b"previous executable")
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    active = maximum = 0
    completed = []

    def run(command, **kwargs):
        nonlocal active, maximum
        if "-c" not in command:
            assert active == 0 and len(completed) == 2, "link began before every unit completed"
            return subprocess.run(command, **kwargs)
        with lock:
            active += 1
            maximum = max(maximum, active)
        try:
            if jobs == 2:
                barrier.wait(timeout=15)
            result = subprocess.run(command, **kwargs)
            with lock:
                completed.append(command)
            return result
        finally:
            with lock:
                active -= 1

    expected = pytest.raises(NativePlanError, match="worker failure") if fail_native else contextlib.nullcontext()
    with expected:
        report = NativePlanBuilder(runner=run).build(plan_path=plan, generated_c=source, output=output, jobs=jobs)
    assert maximum == jobs
    assert active == 0 and len(completed) == 2
    assert not list(tmp_path.glob(".btrc-native-*")), "worker inputs outlived the build"
    if fail_native:
        assert output.read_bytes() == b"previous executable"
        return
    assert report.as_dict()["compiled_units"] == 2
    assert report.units[0].source == str(source)
    assert "-std=c++17" in report.units[1].command
    subprocess.run([output], check=True, timeout=15)


def test_native_build_report_covers_generated_cpp_adapter_and_link(tmp_path):
    payload = generated_plan('extern "C" int answer(void) { return 42; }\n', "c++", "c++17", "raii")
    plan = tmp_path / "program.link.json"
    plan.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    source = tmp_path / "program.c"
    source.write_text("int answer(void); int main(void) { return answer() == 42 ? 0 : 1; }\n")
    output = tmp_path / "program"
    report_path = tmp_path / "report.json"
    assert (
        main(
            [
                "--plan",
                str(plan),
                "--generated-c",
                str(source),
                "--output",
                str(output),
                "--report-json",
                str(report_path),
                "--jobs",
                "2",
            ]
        )
        == 0
    )
    report = json.loads(report_path.read_text())
    assert report["emitted_units"] == report["adapter_units"] == report["links"] == 1
    assert report["compiled_units"] == 2 and report["reused_units"] == 0
    assert report["native_units"] == 0
    assert len(report["units"]) == 2
    assert "-fexceptions" in report["units"][1]["command"]
    assert Path(report["link_command"][0]).name == Path(shutil.which("c++")).name
    assert report["wall_s"] >= report["link_s"] > 0
    subprocess.run([str(output)], check=True, timeout=RUN_TIMEOUT)


@pytest.mark.parametrize("target", ["program.c", "program.link.json", "program"])
def test_native_report_cannot_overwrite_build_inputs_or_output(tmp_path, target):
    plan = tmp_path / "program.link.json"
    plan.write_text(NativeLinkPlan(PackageTarget.parse(None)).canonical_json())
    source = tmp_path / "program.c"
    source.write_text("int main(void) { return 0; }\n")
    output = tmp_path / "program"
    output.write_bytes(b"previous executable")
    before = {path: path.read_bytes() for path in (plan, source, output)}
    assert (
        main(
            [
                "--plan",
                str(plan),
                "--generated-c",
                str(source),
                "--output",
                str(output),
                "--report-json",
                str(tmp_path / target),
            ]
        )
        == 1
    )
    assert all(path.read_bytes() == content for path, content in before.items())


@pytest.mark.parametrize("language", ["c", "c++"])
def test_generated_adapter_cache_keeps_real_source_path_and_relative_headers(tmp_path, language):
    header = tmp_path / "value.h"
    header.write_text("#define VALUE 41\n")
    linkage = 'extern "C" ' if language == "c++" else ""
    source_text = (
        '#include "../value.h"\n'
        + linkage
        + "int answer(void) { return VALUE; }\n"
        + linkage
        + "const char *origin(void) { return __FILE__; }\n"
    )
    payload = generated_plan(
        source_text, language, "c++17" if language == "c++" else "c11", "raii" if language == "c++" else "manual"
    )
    plan = tmp_path / "program.link.json"
    plan.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    source = tmp_path / "program.c"
    source.write_text(
        '#include <stdio.h>\nint answer(void); const char *origin(void); int main(void) { printf("%d %s\\n", answer(), origin()); }\n'
    )
    output = tmp_path / "program"
    options = dict(
        plan_path=plan, generated_c=source, output=output, object_cache=tmp_path / "objects", debug_info=True
    )
    cold = NativePlanBuilder().build(**options)
    adapter = Path(cold.units[-1].source)
    assert adapter.read_text() == source_text, "debugger-visible source must survive the build"
    assert (
        subprocess.run([output], capture_output=True, text=True, check=True, timeout=RUN_TIMEOUT).stdout
        == f"41 {adapter}\n"
    )
    warm = NativePlanBuilder().build(**options)
    assert warm.units[-1].source == str(adapter)
    assert warm.as_dict()["compiled_units"] == 0
    assert warm.as_dict()["reused_units"] == 2
    assert warm.adapter_source_status == "retained"
    header.write_text("#define VALUE 42\n")
    changed = NativePlanBuilder().build(**options)
    assert changed.as_dict()["compiled_units"] == 1
    assert (
        subprocess.run([output], capture_output=True, text=True, check=True, timeout=RUN_TIMEOUT).stdout
        == f"42 {adapter}\n"
    )


def test_generated_adapter_generations_do_not_replace_each_other(tmp_path):
    plan = tmp_path / "program.link.json"
    source = tmp_path / "program.c"
    source.write_text('#include <stdio.h>\nint answer(void); int main(void) { printf("%d\\n", answer()); }\n')
    output = tmp_path / "program"
    paths = []
    for answer, expected_compiles in [(41, 2), (42, 1), (41, 0)]:
        payload = generated_plan(f"int answer(void) {{ return {answer}; }}\n")
        plan.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
        report = NativePlanBuilder().build(
            plan_path=plan, generated_c=source, output=output, object_cache=tmp_path / "objects"
        )
        assert report.as_dict()["compiled_units"] == expected_compiles
        assert (
            subprocess.run([output], capture_output=True, text=True, check=True, timeout=RUN_TIMEOUT).stdout
            == f"{answer}\n"
        )
        paths.append(Path(report.units[-1].source))
    assert paths[0] == paths[2] != paths[1]
    assert paths[0].read_text() == "int answer(void) { return 41; }\n"
    assert paths[1].read_text() == "int answer(void) { return 42; }\n"


@pytest.mark.parametrize("damage", ["source", "manifest", "missing", "extra", "symlink", "directory-symlink"])
def test_generated_adapter_corruption_falls_back_without_mutating_shared_generation(tmp_path, damage):
    plan = tmp_path / "program.link.json"
    plan.write_text(json.dumps(generated_plan(), sort_keys=True, separators=(",", ":")) + "\n")
    source = tmp_path / "program.c"
    source.write_text("int answer(void); int main(void) { return answer() == 42 ? 0 : 1; }\n")
    output = tmp_path / "program"
    options = dict(plan_path=plan, generated_c=source, output=output, object_cache=tmp_path / "objects")
    first = NativePlanBuilder().build(**options)
    adapter = Path(first.units[-1].source)
    directory = adapter.parent
    if damage == "source":
        adapter.write_text("int answer(void) { return 0; }\n")
    elif damage == "manifest":
        (directory / "manifest.json").write_text("{}\n")
    elif damage == "missing":
        adapter.unlink()
    elif damage == "extra":
        (directory / "unplanned.h").write_text("#error unexpected source neighbor\n")
    elif damage == "symlink":
        other = tmp_path / "foreign.c"
        other.write_text("int answer(void) { return 0; }\n")
        adapter.unlink()
        adapter.symlink_to(other)
    else:
        other = tmp_path / "foreign-directory"
        directory.rename(other)
        directory.symlink_to(other, target_is_directory=True)
    # Corrupt/foreign contents are never repaired in place or removed while a
    # concurrent reader might still have the generation open.
    before = {path.name: path.read_bytes() for path in directory.iterdir()}
    report = NativePlanBuilder().build(**options)
    assert report.adapter_source_status == "fallback"
    assert report.as_dict()["compiled_units"] == 1
    subprocess.run([output], check=True, timeout=RUN_TIMEOUT)
    assert before == {path.name: path.read_bytes() for path in directory.iterdir()}
    assert not Path(report.units[-1].source).exists()


def test_generated_adapter_publication_failure_preserves_normal_build(tmp_path, monkeypatch):
    plan = tmp_path / "program.link.json"
    plan.write_text(json.dumps(generated_plan(), sort_keys=True, separators=(",", ":")) + "\n")
    source = tmp_path / "program.c"
    source.write_text("int answer(void); int main(void) { return answer() == 42 ? 0 : 1; }\n")
    original = Path.rename

    def fail_source_publication(self, target):
        if Path(target).name.startswith(".btrc-adapters-"):
            raise OSError("injected publication failure")
        return original(self, target)

    monkeypatch.setattr(Path, "rename", fail_source_publication)
    output = tmp_path / "program"
    report = NativePlanBuilder().build(
        plan_path=plan, generated_c=source, output=output, object_cache=tmp_path / "objects"
    )
    assert report.adapter_source_status == "fallback"
    subprocess.run([output], check=True, timeout=RUN_TIMEOUT)
    assert {path.name for path in tmp_path.glob(".btrc-*")} == {".btrc-publications.lock"}


def test_generated_adapter_publication_supports_concurrent_builds(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    plan = tmp_path / "program.link.json"
    plan.write_text(json.dumps(generated_plan(), sort_keys=True, separators=(",", ":")) + "\n")
    source = tmp_path / "program.c"
    source.write_text("int answer(void); int main(void) { return answer() == 42 ? 0 : 1; }\n")
    cache = tmp_path / "objects"

    def build(index):
        output = tmp_path / f"program-{index}"
        report = NativePlanBuilder().build(plan_path=plan, generated_c=source, output=output, object_cache=cache)
        subprocess.run([output], check=True, timeout=RUN_TIMEOUT)
        return report

    with ThreadPoolExecutor(max_workers=4) as pool:
        reports = list(pool.map(build, range(8)))
    paths = {report.units[-1].source for report in reports}
    assert len(paths) == 1
    assert all(report.adapter_source_status == "retained" for report in reports)
    assert len(list(tmp_path.glob(".btrc-adapters-*"))) == 1
    assert not list(tmp_path.glob(".btrc-native-*"))
    warm = build(8)
    assert warm.as_dict()["compiled_units"] == 0
    assert warm.as_dict()["reused_units"] == 2


def test_native_report_cannot_modify_retained_adapter_generation(tmp_path):
    plan = tmp_path / "program.link.json"
    plan.write_text(json.dumps(generated_plan(), sort_keys=True, separators=(",", ":")) + "\n")
    source = tmp_path / "program.c"
    source.write_text("int answer(void); int main(void) { return answer() == 42 ? 0 : 1; }\n")
    options = dict(plan_path=plan, generated_c=source, output=tmp_path / "program", object_cache=tmp_path / "objects")
    first = NativePlanBuilder().build(**options)
    path = Path(first.units[-1].source)
    original = path.read_bytes()
    with pytest.raises(NativePlanError, match="outside generated adapter directories"):
        NativePlanBuilder().build(**options, report_path=path)
    assert path.read_bytes() == original


@pytest.mark.parametrize("operation", ["cache-directory", "generation-metadata"])
def test_generated_adapter_inaccessible_cache_does_not_prevent_build(tmp_path, monkeypatch, operation):
    plan = tmp_path / "program.link.json"
    plan.write_text(json.dumps(generated_plan(), sort_keys=True, separators=(",", ":")) + "\n")
    source = tmp_path / "program.c"
    source.write_text("int answer(void); int main(void) { return answer() == 42 ? 0 : 1; }\n")
    cache = tmp_path / "objects"
    cache.mkdir()
    method = "is_dir" if operation == "cache-directory" else "exists"
    original = getattr(Path, method)

    def inaccessible(self, *args, **kwargs):
        if self == cache or self.name.startswith(".btrc-adapters-"):
            raise PermissionError("injected cache metadata denial")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, method, inaccessible)
    output = tmp_path / "program"
    report = NativePlanBuilder().build(plan_path=plan, generated_c=source, output=output, object_cache=cache)
    assert report.adapter_source_status in {"temporary", "fallback"}
    subprocess.run([output], check=True, timeout=RUN_TIMEOUT)


def _guarded_include(header: Path) -> str:
    """The include-once block a module-unit program emits for a native header."""
    import hashlib

    guard = "BTRC_INCLUDE_" + hashlib.sha256(str(header).encode()).hexdigest()[:16].upper()
    return f'#ifndef {guard}\n#define {guard}\n#include "{header}"\n#endif\n'


def _build_units_sharing_a_prologue(tmp_path: Path, header_text: str, first_unit_tail: str = "") -> NativeBuildReport:
    """Build a program of MINIMUM_UNITS + 4 emitted units that share one
    prologue -- a feature macro, system includes and a guarded native header
    holding `header_text` -- each returning SHARED_BASE plus its index."""
    native = tmp_path / "native"
    native.mkdir()
    header = native / "Shared.h"
    header.write_text(header_text)
    count = _PreludeAccelerator.MINIMUM_UNITS + 4
    prologue = "#define _DEFAULT_SOURCE\n#include <stdio.h>\n#include <stdlib.h>\n" + _guarded_include(header)
    units = []
    for index in range(count):
        unit = tmp_path / f"program.unit-{index}.c"
        unit.write_text(
            f'/* Generated by btrc */\n#pragma GCC diagnostic ignored "-Wunused-function"\n{prologue}\n'
            f"int part{index}(void);\nint part{index}(void) {{ return SHARED_BASE + {index}; }}\n"
            + ("" if index else first_unit_tail)
        )
        units.append(unit)
    primary = tmp_path / "program.c"
    calls = " + ".join(f"part{index}()" for index in range(count))
    declarations = "".join(f"int part{index}(void);\n" for index in range(count))
    primary.write_text(f'#include <stdio.h>\n{declarations}int main(void) {{ printf("%d\\n", {calls}); return 0; }}\n')
    payload = NativeLinkPlan.empty(PackageTarget.parse(None)).as_dict()
    payload.update(schema=4)
    payload["emitted-units"] = [str(unit) for unit in units]
    plan = tmp_path / "program.json"
    plan.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")
    return NativePlanBuilder().build(
        plan_path=plan,
        generated_c=primary,
        output=tmp_path / "program",
        cc="clang",
        cxx="clang++",
        optimization=0,
        debug_info=True,
        jobs=4,
    )


@pytest.mark.skipif(shutil.which("clang") is None, reason="precompiled preludes need Clang")
@pytest.mark.parametrize(
    "rewrite",
    ["", "#undef _DEFAULT_SOURCE\n#define _DEFAULT_SOURCE 1\n"],
    ids=["plain", "header-rewrites-feature-macro"],
)
def test_units_sharing_a_prologue_compile_with_one_precompiled_prelude(tmp_path: Path, rewrite: str) -> None:
    """Many units that begin with the same includes compile with one precompiled
    header of them, and run exactly as without it. The shared native header
    has no include guard of its own: the emitted include-once block is what
    lets the unit's copy stand beside the prelude's. A prologue header may
    rewrite the feature macro the unit defined before it, as glibc's
    features.h makes `_DEFAULT_SOURCE` 1; the unit's own definition, read
    again after the prelude, must still not be a redefinition."""
    report = _build_units_sharing_a_prologue(tmp_path, f"{rewrite}enum SharedValue {{ SHARED_BASE = 100 }};\n")
    count = _PreludeAccelerator.MINIMUM_UNITS + 4
    assert report.prelude_status == "built-1"
    assert report.as_dict()["prelude_units"] == count
    ran = subprocess.run([str(tmp_path / "program")], capture_output=True, text=True, check=True, timeout=30)
    assert ran.stdout == f"{sum(100 + index for index in range(count))}\n"


@pytest.mark.skipif(shutil.which("clang") is None, reason="precompiled preludes need Clang")
def test_a_prelude_does_not_hide_a_real_feature_macro_redefinition(tmp_path: Path) -> None:
    """A unit that redefines a prologue feature macro after its prologue is
    rejected with a prelude exactly as without one."""
    with pytest.raises(NativePlanError, match="'_DEFAULT_SOURCE' macro redefined"):
        _build_units_sharing_a_prologue(
            tmp_path, "enum SharedValue { SHARED_BASE = 100 };\n", first_unit_tail="#define _DEFAULT_SOURCE 2\n"
        )


def test_prelude_prologue_takes_only_whole_guarded_absolute_includes(tmp_path: Path) -> None:
    """A prologue ends before anything a precompiled header could not stand for:
    a relative include, which would resolve against the header, a native
    include outside its include-once block, or a block cut short."""
    header = tmp_path / "Native.h"
    guarded = _guarded_include(header).rstrip("\n").split("\n")
    system = ["#define _DEFAULT_SOURCE", "#include <stdio.h>"]
    cases = {
        "whole": (system + guarded + ["int x;"], system + guarded),
        "relative": (system + [guarded[0], guarded[1], '#include "Native.h"', "#endif"], system),
        "unguarded": (system + [f'#include "{header}"'] + guarded, system),
        "cut-short": (system + guarded[:3] + ["int x;"], system),
    }
    for name, (lines, expected) in cases.items():
        source = tmp_path / f"{name}.c"
        source.write_text(
            '/* Generated by btrc */\n#pragma GCC diagnostic ignored "-Wunused-function"\n' + "\n".join(lines) + "\n"
        )
        assert _PreludeAccelerator.prologue(source) == tuple(expected), name


def test_unwritten_schema_three_link_plans_are_rejected(tmp_path):
    # Neither compiler ever wrote schema 3 (a bare emitted-unit count).
    payload = NativeLinkPlan.empty(PackageTarget.parse(None)).as_dict()
    payload.update(schema=3)
    payload["emitted-units"] = 1
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")

    with pytest.raises(NativePlanError, match="schema must be integer 1, 2 or 4"):
        NativePlanReader().read(plan)


@pytest.mark.parametrize("digests", ["absent", "matching", "short", "uppercase", "missing-unit"])
def test_emitted_unit_digests_name_one_sha256_per_unit(tmp_path, digests):
    """Plans record each secondary unit's digest; older plans omit the field."""
    units = [tmp_path / "program.unit-1.c", tmp_path / "program.unit-2.c"]
    for unit in units:
        unit.write_text(f"int {unit.stem.replace('.', '_').replace('-', '_')}(void) {{ return 0; }}\n")
    plan = NativeLinkPlan.empty(PackageTarget.parse(None)).with_emitted_units(
        str(tmp_path / "program"), 2, tuple(unit.read_text() for unit in units)
    )
    payload = plan.as_dict()
    assert payload["emitted-unit-digests"] == [hashlib.sha256(unit.read_bytes()).hexdigest() for unit in units]
    if digests == "absent":
        del payload["emitted-unit-digests"]
    elif digests == "short":
        payload["emitted-unit-digests"][0] = payload["emitted-unit-digests"][0][:63]
    elif digests == "uppercase":
        payload["emitted-unit-digests"][1] = payload["emitted-unit-digests"][1].upper()
    elif digests == "missing-unit":
        payload["emitted-unit-digests"].pop()
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")

    if digests in ("absent", "matching"):
        assert NativePlanReader().read(path).emitted_paths == tuple(units)
    else:
        with pytest.raises(NativePlanError, match="emitted-unit-digests must give one SHA-256 per emitted unit"):
            NativePlanReader().read(path)
