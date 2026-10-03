"""Static contracts for platform CI and release-bundle smoke tests."""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO / ".github/workflows"
UPLOAD_ARTIFACT = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
SETUP_NODE = "actions/setup-node@48b55a011bda9f5d6aeb4c2d9c7362e8dae4041e"
SHARD_ROW = r"- \{ shard: ([a-zA-Z0-9-]+), target: ([^}]+?) \}"
SKIP_REPORTS = "build/skip-report*.json"


def _workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def _workflow_paths() -> list[Path]:
    return sorted((*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")))


def _code(text: str) -> str:
    """Drop YAML comment lines, so prose about a command never counts as one."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _job(workflow: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(name)}:\s*$.*?(?=^  [a-zA-Z0-9_-]+:\s*$|\Z)",
        workflow,
    )
    assert match is not None, f"workflow has no {name!r} job"
    return match.group()


def _step_containing(job: str, needle: str) -> str:
    lines = job.splitlines()
    needle_index = next((index for index, line in enumerate(lines) if needle in line), None)
    assert needle_index is not None, f"job has no step containing {needle!r}"
    starts = [index for index, line in enumerate(lines[: needle_index + 1]) if line.startswith("      - ")]
    assert starts, f"{needle!r} is not inside a workflow step"
    start = starts[-1]
    end = next(
        (index for index, line in enumerate(lines[start + 1 :], start + 1) if line.startswith("      - ")),
        len(lines),
    )
    return "\n".join(lines[start:end])


def _jobs(workflow: str) -> dict[str, str]:
    jobs = workflow.split("\njobs:\n", 1)[1]
    return {name: _job(workflow, name) for name in re.findall(r"(?m)^  ([a-zA-Z0-9_-]+):\s*$", jobs)}


def _steps(job: str) -> list[str]:
    lines = job.splitlines()
    starts = [index for index, line in enumerate(lines) if line.startswith("      - ")]
    return ["\n".join(lines[start:end]) for start, end in zip(starts, [*starts[1:], len(lines)], strict=True)]


def _makefile_recipe(makefile: str, rule: str) -> str:
    match = re.search(rf"(?ms)^{re.escape(rule)}:.*?(?=^\S|\Z)", makefile)
    assert match is not None, f"Makefile has no {rule!r} rule"
    return match.group()


def _assert_archive_upload(job: str, archive: str) -> None:
    upload = _step_containing(job, UPLOAD_ARTIFACT)
    assert archive in upload
    assert f"{archive}.sha256" in upload
    assert "if-no-files-found: error" in upload


def _assert_linux_archive_smoke(job: str, target: str) -> None:
    archive = f"dist/btrcc-{target}.tar.gz"
    assert archive in job
    assert "tar -xzf" in job
    assert re.search(rf'compiler="\$[a-z_]+/btrcc-{re.escape(target)}/bin/btrcc"', job)
    assert f"dist/btrcc-{target}/bin/btrcc" not in job
    assert "unset BTRC_HOME" in job
    assert 'actual_stdlib=$(cd "$run" && "$compiler" --stdlib-dir)' in job
    assert 'test "$actual_stdlib" = "$expected_stdlib"' in job
    assert '(cd "$run" && "$compiler" "$source")' in job
    assert 'cmp "$run/program.stdout" "$expected"' in job
    _assert_archive_upload(job, archive)


def test_every_workflow_action_reference_is_pinned_to_a_commit() -> None:
    workflows = (*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml"))
    for workflow in workflows:
        for line in workflow.read_text(encoding="utf-8").splitlines():
            if "uses:" not in line:
                continue
            reference = line.split("uses:", 1)[1].split("#", 1)[0].strip()
            revision = reference.rsplit("@", 1)[-1]
            assert len(revision) == 40, (workflow.name, reference)
            assert all(character in "0123456789abcdef" for character in revision), (
                workflow.name,
                reference,
            )


def test_every_nix_cache_step_keeps_flakehub_off() -> None:
    # PLAN.md D26: there is no binary-cache account. At its default the action
    # tries FlakeHub first, and the failed login was the first error in every
    # Nix job's log (flakehub-auth-warning in docs/design/ci-health.md).
    steps = [
        _code(step)
        for path in _workflow_paths()
        for job in _jobs(path.read_text(encoding="utf-8")).values()
        for step in _steps(job)
        if "DeterminateSystems/magic-nix-cache-action@" in step
    ]
    assert steps
    for step in steps:
        assert re.search(r"(?m)^        with:\n(?:          .*\n)*?          use-flakehub: false$", step), step


def _yaml(text: str) -> object:
    """Parse the YAML subset the workflow files use.

    PyYAML is not in the dev shell, and these contracts read structure (the
    `on:` block, job conditions, a step's environment and script) rather than
    text. The subset is block mappings and sequences, one-line flow sequences
    and mappings, quoted and plain scalars, and `|` block scalars. Scalars stay
    strings, so `false` reads as "false".
    """

    value, index = _yaml_node(text.splitlines(), 0, 0)
    assert _yaml_skip(text.splitlines(), index) == len(text.splitlines()), "unparsed workflow lines"
    return value


def _yaml_skip(lines: list[str], index: int) -> int:
    while index < len(lines) and (not lines[index].strip() or lines[index].lstrip().startswith("#")):
        index += 1
    return index


def _yaml_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _yaml_node(lines: list[str], index: int, indent: int) -> tuple[object, int]:
    index = _yaml_skip(lines, index)
    if index == len(lines) or _yaml_indent(lines[index]) < indent:
        return None, index
    indent = _yaml_indent(lines[index])
    if lines[index].lstrip().startswith("- "):
        return _yaml_sequence(lines, index, indent)
    return _yaml_mapping(lines, index, indent)


def _yaml_sequence(lines: list[str], index: int, indent: int) -> tuple[list[object], int]:
    items: list[object] = []
    while index < len(lines) and _yaml_indent(lines[index]) == indent and lines[index].lstrip().startswith("- "):
        rest = lines[index][indent + 2 :]
        if re.match(r"[A-Za-z0-9_-]+:(\s|$)", rest):
            # A mapping item: its first key continues on the dash's line.
            lines = [*lines[:index], " " * (indent + 2) + rest, *lines[index + 1 :]]
            item, index = _yaml_mapping(lines, index, indent + 2)
        else:
            item, index = _yaml_scalar(rest), index + 1
        items.append(item)
        index = _yaml_skip(lines, index)
    return items, index


def _yaml_mapping(lines: list[str], index: int, indent: int) -> tuple[dict[str, object], int]:
    mapping: dict[str, object] = {}
    while index < len(lines) and _yaml_indent(lines[index]) == indent and not lines[index].lstrip().startswith("- "):
        match = re.fullmatch(r"([^\s:#][^:#]*?|\"[^\"]*\"):(?:\s+(.*))?", lines[index].strip())
        assert match is not None, f"not a mapping entry: {lines[index]!r}"
        key, rest = match.group(1).strip('"'), _yaml_comment(match.group(2) or "")
        assert key not in mapping, f"duplicate key {key!r}"
        if rest in ("|", "|-"):
            body = index + 1
            while body < len(lines) and (not lines[body].strip() or _yaml_indent(lines[body]) > indent):
                body += 1
            block = lines[index + 1 : body]
            margin = min(_yaml_indent(line) for line in block if line.strip())
            text = "\n".join(line[margin:] for line in block).rstrip("\n")
            mapping[key], index = text + ("" if rest == "|-" else "\n"), body
        elif rest:
            mapping[key], index = _yaml_scalar(rest), index + 1
        else:
            following = _yaml_skip(lines, index + 1)
            nested = following < len(lines) and (
                _yaml_indent(lines[following]) > indent
                or (_yaml_indent(lines[following]) == indent and lines[following].lstrip().startswith("- "))
            )
            mapping[key], index = _yaml_node(lines, following, indent) if nested else (None, index + 1)
        index = _yaml_skip(lines, index)
    return mapping, index


def _yaml_comment(text: str) -> str:
    quote = None
    for position, character in enumerate(text):
        if quote:
            quote = None if character == quote else quote
        elif character in "'\"":
            quote = character
        elif character == "#" and (position == 0 or text[position - 1] == " "):
            return text[:position].rstrip()
    return text.strip()


def _yaml_scalar(text: str) -> object:
    text = _yaml_comment(text)
    if text.startswith("'"):
        assert text.endswith("'"), text
        return text[1:-1].replace("''", "'")
    if text.startswith('"'):
        assert text.endswith('"'), text
        return text[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if text.startswith("["):
        assert text.endswith("]"), text
        return [_yaml_scalar(part) for part in _yaml_flow_items(text[1:-1])]
    if text.startswith("{") and not text.startswith("{{"):
        assert text.endswith("}"), text
        pairs = (part.split(":", 1) for part in _yaml_flow_items(text[1:-1]))
        return {key.strip(): _yaml_scalar(value) for key, value in pairs}
    return text


def _yaml_flow_items(text: str) -> list[str]:
    items, depth, start = [], 0, 0
    for position, character in enumerate(text):
        depth += character in "[{"
        depth -= character in "]}"
        if character == "," and depth == 0:
            items.append(text[start:position])
            start = position + 1
    items.append(text[start:])
    return [item.strip() for item in items if item.strip()]


def _parsed(name: str) -> dict[str, object]:
    document = _yaml(_workflow(name))
    assert isinstance(document, dict), name
    return document


# The workflow classes (WORKSTREAMS.md §3.2). The core three gate every change;
# a lane workflow belongs to one packet and runs when its paths change; a
# dispatch-only workflow is a probe someone starts by hand; release runs on tags.
CORE_WORKFLOWS = ("ci.yml", "macos.yml", "windows.yml")
LANE_WORKFLOWS = ("host-*.yml", "windows-*.yml", "ios.yml", "android.yml")
DISPATCH_ONLY_WORKFLOWS = ("windows-msvc-probe.yml", "acceptance-x86.yml")
TAG_WORKFLOWS = ("release.yml",)


def _workflow_class(name: str) -> str | None:
    if name in CORE_WORKFLOWS:
        return "core"
    if name in DISPATCH_ONLY_WORKFLOWS:
        return "dispatch-only"
    if name in TAG_WORKFLOWS:
        return "tag"
    if any(fnmatch.fnmatchcase(name, pattern) for pattern in LANE_WORKFLOWS):
        return "lane"
    return None


def _dispatch_violations(dispatch: object) -> list[str]:
    if dispatch is None or (isinstance(dispatch, dict) and set(dispatch) <= {"inputs"}):
        return []
    return [f"workflow_dispatch may carry only inputs: {dispatch!r}"]


def _trigger_violations(name: str, triggers: object) -> list[str]:
    """Every way `triggers` (a parsed `on:` block) breaks `name`'s class policy."""

    kind = _workflow_class(name)
    if kind is None:
        return [f"{name} is in no workflow class; name it in test_ci_workflow_contracts.py"]
    if not isinstance(triggers, dict):
        return [f"{name}'s on: block is not a mapping"]
    main = {"branches": ["main"]}
    if kind == "core":
        problems = (
            [] if set(triggers) == {"push", "pull_request", "workflow_dispatch"} else [f"triggers {sorted(triggers)}"]
        )
        problems += [f"{event} must be {main}" for event in ("push", "pull_request") if triggers.get(event) != main]
        return problems + _dispatch_violations(triggers.get("workflow_dispatch"))
    if kind == "dispatch-only":
        return (
            [] if set(triggers) == {"workflow_dispatch"} else [f"triggers {sorted(triggers)}"]
        ) + _dispatch_violations(triggers.get("workflow_dispatch"))
    if kind == "tag":
        push = triggers.get("push")
        problems = [] if set(triggers) <= {"push", "workflow_dispatch"} else [f"triggers {sorted(triggers)}"]
        if not (isinstance(push, dict) and set(push) == {"tags"} and push["tags"]):
            problems.append(f"push must name tags only: {push!r}")
        return problems + _dispatch_violations(triggers.get("workflow_dispatch"))
    required = {"push", "pull_request", "workflow_dispatch"}
    problems = [] if required <= set(triggers) <= required | {"workflow_call"} else [f"triggers {sorted(triggers)}"]
    for event in ("push", "pull_request"):
        rule = triggers.get(event)
        if not (isinstance(rule, dict) and rule.get("branches") == ["main"] and set(rule) <= {"branches", "paths"}):
            problems.append(f"{event} must be branches [main] with an optional paths filter: {rule!r}")
            continue
        paths = rule.get("paths")
        if event == "pull_request" and paths is None:
            problems.append("pull_request needs a paths filter")
        if paths is not None and not any(fnmatch.fnmatchcase(f".github/workflows/{name}", path) for path in paths):
            problems.append(f"{event}'s paths filter must include .github/workflows/{name}")
    return problems + _dispatch_violations(triggers.get("workflow_dispatch"))


def test_every_workflow_parses_and_follows_its_class_trigger_policy() -> None:
    # PLAN.md D4: the main session pushes main after each green batch gate and
    # there are no ci/** branches. Manual dispatch is how the hosted Windows,
    # Arm and macOS runners qualify a commit again without another push.
    names = [path.name for path in _workflow_paths()]
    assert set(CORE_WORKFLOWS) <= set(names)
    for name in names:
        document = _parsed(name)
        assert {"name", "on", "jobs"} <= set(document), name
        assert _trigger_violations(name, document["on"]) == [], name


@pytest.mark.parametrize(
    ("name", "on", "problems"),
    [
        ("ci.yml", "push:\n  branches: [main]\npull_request:\n  branches: [main]\nworkflow_dispatch:\n", 0),
        (
            "macos.yml",
            "push:\n  branches: [main]\npull_request:\n  branches: [main]\n"
            "workflow_dispatch:\n  inputs:\n    focus:\n      type: choice\n      options: [full, native-gui]\n",
            0,
        ),
        ("ci.yml", "push:\n  branches: [main, dev]\npull_request:\n  branches: [main]\nworkflow_dispatch:\n", 1),
        ("windows.yml", "push:\n  branches: [main]\npull_request:\n  branches: [main]\n", 1),
        (
            "host-linux.yml",
            "push:\n  branches: [main]\npull_request:\n  branches: [main]\n"
            "  paths:\n    - .github/workflows/host-linux.yml\n    - tools/target_hosts/**\nworkflow_dispatch:\nworkflow_call:\n",
            0,
        ),
        (
            "ios.yml",
            "push:\n  branches: [main]\n  paths: ['.github/workflows/*.yml']\npull_request:\n  branches: [main]\n"
            "  paths: ['.github/workflows/*.yml', src/stdlib/GUI/IOS/**]\nworkflow_dispatch:\n",
            0,
        ),
        ("android.yml", "push:\n  branches: [main]\npull_request:\n  branches: [main]\nworkflow_dispatch:\n", 1),
        (
            "windows-arm64.yml",
            "push:\n  branches: [main]\npull_request:\n  branches: [main]\n  paths: [src/stdlib/**]\nworkflow_dispatch:\n",
            1,
        ),
        ("host-macos.yml", "pull_request:\n  branches: [main]\n  paths: [.github/workflows/host-macos.yml]\n", 2),
        ("windows-msvc-probe.yml", "workflow_dispatch:\n  inputs:\n    toolset:\n      default: v143\n", 0),
        ("acceptance-x86.yml", "workflow_dispatch:\npush:\n  branches: [main]\n", 1),
        ("release.yml", "push:\n  tags: ['v*']\nworkflow_dispatch:\n", 0),
        ("release.yml", "push:\n  branches: [main]\n  tags: ['v*']\n", 1),
        ("nightly.yml", "workflow_dispatch:\n", 1),
    ],
)
def test_the_trigger_policy_holds_each_workflow_class_to_its_shape(name: str, on: str, problems: int) -> None:
    assert len(_trigger_violations(name, _yaml(on))) == problems


def test_core_workflows_cancel_superseded_pull_request_runs_and_queue_main() -> None:
    for name in CORE_WORKFLOWS:
        assert _parsed(name)["concurrency"] == {
            "group": "${{ github.workflow }}-${{ github.event_name == 'pull_request' && "
            "format('pr-{0}', github.head_ref) || github.event_name == 'push' && 'main' || "
            "format('dispatch-{0}', github.run_id) }}",
            "cancel-in-progress": "${{ github.event_name == 'pull_request' }}",
        }, name


def _job_names(workflow: dict[str, object]) -> list[str]:
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    return list(jobs)


def test_every_test_job_retains_its_skip_report_as_its_last_step() -> None:
    # Any job that runs the suite keeps the skip report its pytest sessions
    # write, even when a test failed, under a name unique within the run that
    # the workflow and job derive: skip-report-<workflow stem>-<job>, then one
    # suffix per matrix key the job fans out on.
    test_jobs = {
        (path.name, name): job
        for path in _workflow_paths()
        for name, job in _jobs(path.read_text(encoding="utf-8")).items()
        if re.search(r"\bpytest\b|\btest-shard-|\btest-c11|\btest-native-gui\b", _code(job))
    }
    assert {("ci.yml", "tests"), ("macos.yml", "tests"), ("windows.yml", "windows")} <= set(test_jobs)
    for (workflow, name), job in test_jobs.items():
        final = _steps(job)[-1]
        stem = workflow.rsplit(".", 1)[0]
        matrix = _parsed(workflow)["jobs"][name].get("strategy", {}).get("matrix")
        suffix = r"(-\$\{\{ matrix\.[a-z_]+ \}\})+" if matrix else ""
        assert "if: always()" in final, (workflow, name)
        assert UPLOAD_ARTIFACT in final, (workflow, name)
        assert re.search(rf"(?m)^          name: skip-report-{re.escape(stem)}-{re.escape(name)}{suffix}$", final), (
            workflow,
            name,
        )
        assert f"path: {SKIP_REPORTS}" in final, (workflow, name)
        assert "if-no-files-found: warn" in final, (workflow, name)


def test_sharded_workflows_name_every_shard_that_left_no_skip_report() -> None:
    """A lost runner never reaches its own upload, so a later job names the gap."""

    for workflow, runs in (("ci.yml", ("full", "lane")), ("macos.yml", ("full",))):
        job = _job(_workflow(workflow), "skip-reports")
        parsed = _parsed(workflow)["jobs"]["skip-reports"]
        assert parsed["needs"] == ["scope", "tests"], workflow
        condition = _class_condition(runs)
        assert parsed["if"] == (f"always() && ({condition})" if len(runs) > 1 else f"always() && {condition}"), workflow
        assert re.search(r"(?m)^    timeout-minutes: \d+$", job), workflow
        assert "actions: read" in job, workflow
        step = _code(_steps(job)[-1])
        assert "/actions/runs/$GITHUB_RUN_ID/artifacts" in step, workflow
        assert "/attempts/$GITHUB_RUN_ATTEMPT/jobs" in step, workflow
        stem = workflow.rsplit(".", 1)[0]
        assert f'"skip-report-{stem}-tests-$shard"' in step, workflow
        assert "::warning::" in step and "GITHUB_STEP_SUMMARY" in step, workflow


# The scope job (WORKSTREAMS.md §3.2): which classes run each job.
SCOPED_JOBS = {
    "ci.yml": {
        "docs": ("docs",),
        "release": ("full", "lane"),
        "tests": ("full", "lane"),
        "skip-reports": ("full", "lane"),
        "bench": ("full", "lane"),
        "linux-arm64-bundle": ("full", "lane"),
    },
    "macos.yml": {
        "native-bundle": ("full", "lane"),
        "tests": ("full",),
        "skip-reports": ("full",),
    },
}


def _class_condition(classes: tuple[str, ...]) -> str:
    return " || ".join(f"needs.scope.outputs.class == '{name}'" for name in classes)


def _scope_step(workflow: str) -> dict[str, object]:
    steps = _parsed(workflow)["jobs"]["scope"]["steps"]
    assert len(steps) == 1, workflow
    return steps[0]


def test_scope_runs_first_and_gates_every_other_job_by_class() -> None:
    assert _parsed("ci.yml")["jobs"]["scope"] == _parsed("macos.yml")["jobs"]["scope"]
    for workflow, classes in SCOPED_JOBS.items():
        jobs = _parsed(workflow)["jobs"]
        assert _job_names(_parsed(workflow))[0] == "scope", workflow
        assert set(jobs) == {"scope", *classes}, workflow
        scope = jobs["scope"]
        assert scope["runs-on"] == "ubuntu-latest", workflow
        assert scope["permissions"] == {"contents": "read", "pull-requests": "read"}, workflow
        assert scope["outputs"] == {"class": "${{ steps.classify.outputs.class }}"}, workflow
        for name, runs in classes.items():
            if name == "skip-reports":
                continue
            assert jobs[name]["needs"] == "scope", (workflow, name)
            assert jobs[name]["if"] == _class_condition(runs), (workflow, name)
    # The lane class builds only the arm64 bundle; x64 runs through Rosetta.
    bundle = _parsed("macos.yml")["jobs"]["native-bundle"]
    assert bundle["strategy"]["matrix"] == {
        "target": "${{ fromJSON(needs.scope.outputs.class == 'full' && "
        '\'["macos-arm64", "macos-x64"]\' || \'["macos-arm64"]\') }}'
    }


def _compiler_import_closure() -> set[str]:
    """Every stdlib file the self-hosted compiler's sources import, transitively."""

    stdlib = REPO / "src/stdlib"
    imports = re.compile(r"(?m)^\s*import\s+Library\.([A-Za-z0-9_.]+)\s*;")
    seen: set[Path] = set()
    pending = list((REPO / "src/compiler/btrc").rglob("*.btrc"))
    while pending:
        for module in imports.findall(pending.pop().read_text(encoding="utf-8")):
            parts = module.split(".")
            candidates = (stdlib.joinpath(*parts).with_suffix(".btrc"), stdlib.joinpath(*parts, f"{parts[-1]}.btrc"))
            target = next((candidate for candidate in candidates if candidate.is_file()), None)
            assert target is not None, f"cannot resolve Library.{module}"
            if target not in seen:
                seen.add(target)
                pending.append(target)
    return {path.relative_to(REPO).as_posix() for path in seen}


def test_scope_full_paths_cover_the_compilers_and_their_stdlib_closure() -> None:
    full = re.compile(_scope_step("ci.yml")["env"]["FULL_PATHS"])
    closure = _compiler_import_closure()
    assert {"src/stdlib/Vector.btrc", "src/stdlib/FileSystem/FileSystem.btrc"} <= closure
    uncovered = sorted(path for path in closure if not full.search(path))
    assert not uncovered, f"FULL_PATHS misses compiler imports: {uncovered}"
    for path in (
        "src/compiler/btrc/Compiler.btrc",
        "src/compiler/python/main.py",
        "src/language/grammar.ebnf",
        "src/runtime/c/core.c",
        "tools/compiler_codegen/ast.py",
        "src/stdlib/Callback.btrc",
        "src/stdlib/BackgroundJobs/Unix/ProcessThreadsProvider.btrc",
        ".github/workflows/macos.yml",
        "Makefile",
        "flake.lock",
    ):
        assert full.search(path), path
    for path in (
        "src/stdlib/GUI/MacOS/Window.btrc",
        "src/stdlib/UI/Button.btrc",
        "src/stdlib/btrc.toml",
        "src/stdlib/btrc.lock",
        "src/tests/python/test_ui0_catalog.py",
        "tools/ui/codex-setup.sh",
        ".github/workflows/host-linux.yml",
        "docs/design/native-ui-catalog.toml",
    ):
        assert not full.search(path), path


def test_scope_counts_every_markdown_file_a_test_or_tool_reads_as_code() -> None:
    test_read = re.compile(_scope_step("ci.yml")["env"]["TEST_READ_MARKDOWN"])
    literal = re.compile(r"""["']([A-Za-z0-9_./-]*\.md)["']""")
    read = {
        name
        for root in ("src/tests", "tools")
        for path in (REPO / root).rglob("*.py")
        # This module's own cases name Markdown files the scope ignores.
        if path != Path(__file__).resolve()
        for name in literal.findall(path.read_text(encoding="utf-8"))
        if (REPO / name).is_file()
    }
    assert {"PLAN.md", "AGENTS.md", "docs/design/platform-parity.md"} <= read
    assert sorted(name for name in read if not test_read.search(name)) == []
    for name in ("CLAUDE.md", "src/stdlib/GUI/README.md", "docs/design/compiler-structure.md"):
        assert test_read.search(name), name
    for name in ("docs/design/ui0-catalog.md", "WORKSTREAMS.md", "docs/qualification/ui-agent-runbook.md"):
        assert not test_read.search(name), name


FAKE_GH = """#!/usr/bin/env bash
set -euo pipefail
for argument; do endpoint=$argument; done
case "$endpoint" in
  */files\\?per_page=100)
    [[ " $* " == *" --paginate --slurp "* ]] || { echo "files need --paginate --slurp" >&2; exit 2; }
    cat "$FAKE_GH/files.json" ;;
  */pulls/*) cat "$FAKE_GH/pull.json" ;;
  *) echo "unexpected gh $*" >&2; exit 2 ;;
esac
"""


def _classify(tmp_path: Path, event: str, head: str = "", files: tuple[str, ...] = (), **pull: object) -> str:
    """Run the scope step's script against a stand-in `gh` that serves one pull request."""

    step = _scope_step("ci.yml")
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    (bin_directory / "gh").write_text(FAKE_GH, encoding="utf-8")
    (bin_directory / "gh").chmod(0o755)
    rows = [
        {"filename": name.split(" <- ")[0], **({"previous_filename": name.split(" <- ")[1]} if " <- " in name else {})}
        for name in files
    ]
    pages = [rows[start : start + 100] for start in range(0, len(rows), 100)] or [[]]
    (tmp_path / "files.json").write_text(json.dumps(pages), encoding="utf-8")
    document = {
        "labels": [{"name": label} for label in pull.get("labels", ())],
        "changed_files": pull.get("changed_files", len(rows)),
    }
    (tmp_path / "pull.json").write_text(json.dumps(document), encoding="utf-8")
    output = tmp_path / "output"
    environment = {
        **os.environ,
        "PATH": f"{bin_directory}{os.pathsep}{os.environ['PATH']}",
        "FAKE_GH": str(tmp_path),
        "GITHUB_REPOSITORY": "schiffy91/btrc",
        "GITHUB_OUTPUT": str(output),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
        "EVENT": event,
        "PULL_REQUEST": "21" if event == "pull_request" else "",
        "HEAD_REF": head,
        "FULL_PATHS": step["env"]["FULL_PATHS"],
        "TEST_READ_MARKDOWN": step["env"]["TEST_READ_MARKDOWN"],
    }
    completed = subprocess.run(
        ["bash", "-c", step["run"]], env=environment, capture_output=True, text=True, timeout=60, check=False
    )
    assert completed.returncode == 0, completed.stderr
    lines = output.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and lines[0].startswith("class="), lines
    return lines[0].removeprefix("class=")


@pytest.mark.parametrize(
    ("event", "head", "files", "pull", "expected"),
    [
        ("push", "", (), {}, "full"),
        ("workflow_dispatch", "", (), {}, "full"),
        ("pull_request", "codex/cx-uia-07", ("docs/design/ui0-catalog.md", "docs/qualification/notes.md"), {}, "docs"),
        ("pull_request", "stage30/notes", ("WORKSTREAMS.md",), {}, "docs"),
        ("pull_request", "codex/cx-uia-07", ("docs/design/ui0-catalog.md", "PLAN.md"), {}, "lane"),
        ("pull_request", "stage30/notes", ("src/stdlib/GUI/README.md",), {}, "full"),
        (
            "pull_request",
            "codex/ui0-catalog",
            ("docs/design/native-ui-catalog.toml", "src/tests/python/test_ui0_catalog.py"),
            {},
            "lane",
        ),
        ("pull_request", "codex/cx-p2-04", ("src/stdlib/FileSystem/Windows/FileSystemProvider.btrc",), {}, "full"),
        (
            "pull_request",
            "codex/cx-uia-09",
            ("src/stdlib/GUI/Linux/Window.btrc", "src/stdlib/Strings.btrc"),
            {},
            "full",
        ),
        ("pull_request", "codex/cx-uia-09", ("tools/ui/moved.py <- src/compiler/python/main.py",), {}, "full"),
        ("pull_request", "codex/cx-uia-09", ("src/stdlib/GUI/Linux/Window.btrc",), {"labels": ("ci:full",)}, "full"),
        ("pull_request", "codex/cx-uia-09", ("src/stdlib/GUI/Linux/Window.btrc",), {"labels": ("ci:fast",)}, "lane"),
        ("pull_request", "codex/cx-uia-09", tuple(f"docs/n{i}.md" for i in range(150)), {}, "docs"),
        ("pull_request", "codex/cx-uia-09", ("docs/a.md",), {"changed_files": 3001}, "full"),
        ("pull_request", "stage30/ci-codex-lanes", ("src/tests/python/test_x.py",), {}, "full"),
    ],
)
def test_scope_classifies_a_pull_requests_diff(
    tmp_path: Path, event: str, head: str, files: tuple[str, ...], pull: dict[str, object], expected: str
) -> None:
    assert shutil.which("jq") and shutil.which("bash"), "the dev shell provides jq and bash"
    assert _classify(tmp_path, event, head, files, **pull) == expected


def test_linux_x64_ci_runs_and_uploads_the_archived_bundle() -> None:
    job = _job(_workflow("ci.yml"), "release")

    assert 'test "$(uname -m)" = x86_64' in job
    assert "make NIX= btrcc-linux-x64" in job
    assert "btrcc-dist" not in job
    assert "mktemp -d" in job
    assert "src/tests/strings/expected/BracesInCodeGen.stdout" in job
    assert "-std=c11 -pedantic-errors -Wall -Wextra -Werror" in job
    # The release job builds and smokes artifacts only; the suite runs as the
    # sharded `tests` job so no test shares a runner with a release build.
    assert "PYTEST_WORKERS" not in job
    assert job.count('podman run --rm --init -v "$PWD:/workspace"') == 3
    _assert_linux_archive_smoke(job, "linux-x64")


def test_linux_test_shards_partition_the_suite_across_parallel_jobs() -> None:
    job = _job(_workflow("ci.yml"), "tests")
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")

    assert "fail-fast: false" in job
    shards = re.findall(SHARD_ROW, job)
    assert [shard for shard, _ in shards] == [
        "unit",
        "btrc",
        "corpus-python",
        "corpus-btrc",
        "bootstrap",
        *(f"c11-{cc}-{opt}" for cc in ("gcc", "clang") for opt in ("O0", "O1", "O2", "O3")),
    ]
    for _, target in shards:
        rule = target.split()[0]
        assert f"\n{rule}:" in makefile, target
    assert all(
        f"C11_CC={shard.split('-')[1]} C11_OPT={shard.split('-')[2]}" in target
        for shard, target in shards
        if shard.startswith("c11-")
    )
    # Every shard rebuilds the container from the Nix cache and runs one make
    # target with the budgets the container needs: it rebuilds the self-hosted
    # compiler against a cold cache, and the corpus's heaviest program does not
    # finish inside the default run budget at -O0.
    assert "make devcontainer" in job
    assert job.count('podman run --rm --init -v "$PWD:/workspace"') == 1
    assert "PYTEST_WORKERS=4 BTRC_TEST_TRANSPILE_TIMEOUT=600 BTRC_TEST_RUN_TIMEOUT=60 ${{ matrix.target }}" in job
    # The runner is headless: every shard runs under the virtual display and
    # software Vulkan, as `make linux-ci` does, so the GUI and adapter tests run.
    assert "btrc-devcontainer:latest tools/virtual-display.sh make NIX=" in _code(job)
    assert "tools/virtual-display.sh make NIX=" in (REPO / "tools/linux-ci.sh").read_text(encoding="utf-8")


def test_linux_arm64_ci_runs_and_uploads_the_archived_bundle() -> None:
    job = _job(_workflow("ci.yml"), "linux-arm64-bundle")

    assert "runs-on: ubuntu-24.04-arm" in job
    assert 'test "$(uname -m)" = aarch64' in job
    assert "make NIX= btrcc-linux-arm64" in job
    _assert_linux_archive_smoke(job, "linux-arm64")


def test_macos_ci_matrix_runs_and_uploads_both_archived_bundles() -> None:
    workflow = _workflow("macos.yml")
    job = _job(workflow, "native-bundle")

    parsed = _parsed("macos.yml")["jobs"]["native-bundle"]
    assert parsed["runs-on"] == "macos-15"
    assert "macos-15-intel" not in job
    assert parsed["env"] == {
        "BUNDLE_MACHINE": "${{ matrix.target == 'macos-x64' && 'x86_64' || 'arm64' }}",
        "ROSETTA": "${{ matrix.target == 'macos-x64' }}",
    }
    assert "if: env.ROSETTA == 'true'" in job
    assert job.count('test "$(uname -m)" = arm64') >= 2
    assert 'lipo -archs "$compiler" | grep -qw "${{ env.BUNDLE_MACHINE }}"' in job
    assert "arch -x86_64" in job
    assert 'make NIX= "btrcc-${{ matrix.target }}"' in job
    assert "btrcc_bundle" not in job
    assert "dist/btrcc-${{ matrix.target }}.tar.gz" in job
    assert "tar -xzf" in job
    assert 'root="$work/btrcc-${{ matrix.target }}"' in job
    assert 'compiler="$root/bin/btrcc"' in job
    assert 'actual_stdlib=$(cd "$run" && "${compiler_command[@]}" --stdlib-dir)' in job
    assert '(cd "$run" && "${compiler_command[@]}" "$source")' in job
    assert 'test "$actual_stdlib" = "$expected_stdlib"' in job
    assert 'cmp "$run/program.stdout" "$expected"' in job
    _assert_archive_upload(job, "dist/btrcc-${{ matrix.target }}.tar.gz")


def test_macos_test_shards_run_the_native_suite_with_clang() -> None:
    job = _job(_workflow("macos.yml"), "tests")
    linux = dict(re.findall(SHARD_ROW, _job(_workflow("ci.yml"), "tests")))
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")

    assert "runs-on: macos-15" in job
    assert "fail-fast: false" in job
    shards = re.findall(SHARD_ROW, job)
    assert [shard for shard, _ in shards] == [
        "unit",
        "btrc",
        "corpus-python",
        "corpus-btrc",
        "bootstrap",
        "c11-clang-O0",
        "c11-clang-O2",
    ]
    # The shards reuse Linux CI's Makefile targets. Only the bootstrap row
    # differs: test_bootstrap.py compiles with `cc`, which is GCC in the dev
    # shell, not through default_c_compiler(), so the macOS row names clang.
    targets = dict(shards)
    for shard, target in targets.items():
        assert f"\n{target.split()[0]}:" in makefile, target
        if shard == "bootstrap":
            assert target == f"{linux[shard]} BTRC_CC=clang"
        else:
            assert target == linux[shard], shard
    # The unit shard is where src/tests/debug runs, so it alone needs lldb.
    unit = _makefile_recipe(makefile, "test-shard-unit")
    assert "src/tests/ " in unit and "--ignore=src/tests/debug" not in unit

    reader = _step_containing(job, "nix build .#btrc-native-header")
    assert 'test "$(uname -s)" = Darwin' in reader
    assert 'test "$(uname -m)" = arm64' in reader
    assert "exported=$(nix develop --command printenv BTRC_NATIVE_HEADER_READER)" in reader
    assert 'test "$exported" = "$reader"' in reader
    clang = _step_containing(job, "from src.tests.runner import default_c_compiler")
    assert 'test "$selected" = clang' in clang
    debugger = _step_containing(job, "sudo /usr/sbin/DevToolsSecurity -enable")
    assert "if: matrix.shard == 'unit'" in debugger
    assert _code(debugger).rstrip().endswith('/usr/sbin/DevToolsSecurity -status | grep -q "currently enabled"')
    suite = _step_containing(job, "make NIX=")
    assert _code(suite).strip() == (
        "- run: nix develop --command make NIX= PYTEST_WORKERS=3 "
        "BTRC_TEST_TRANSPILE_TIMEOUT=600 BTRC_TEST_RUN_TIMEOUT=60 ${{ matrix.target }}"
    )
    assert "podman" not in job


def test_windows_ci_runs_and_uploads_the_extracted_zip() -> None:
    job = _job(_workflow("windows.yml"), "windows")

    assert SETUP_NODE in job
    assert 'node-version: "22.23.1"' in job
    assert "cache-dependency-path: src/devex/vscode/package-lock.json" in job
    extension = _step_containing(job, "npm test")
    assert "working-directory:" not in extension
    assert "python -m pip install '.[dev]'" in extension
    assert "node src/devex/vscode/packaging/prepare.js" in extension
    assert "cd build/devex/vscode" in extension
    assert "npm ci" in extension
    assert "npm run package" in extension
    assert 'ZipFile("dist/btrc.vsix")' in extension
    assert '"extension/out/extension.js"' in extension
    assert '"extension/server/src/devex/debug/__main__.py"' in extension
    assert '"extension/server/vendor/pygls/__init__.py"' in extension
    assert "python -m zipfile -e" in job
    assert "btrcc-windows-smoke" in job
    assert 'compiler="$bundle/bin/btrcc.exe"' in job
    assert '[sys.argv[1], "--stdlib-dir"]' in job
    assert "expected_stdlib = [str(Path(sys.argv[2]).resolve())]" in job
    assert "if actual_stdlib != expected_stdlib:" in job
    assert re.search(r"grep[^\n]*PASS", job) is None
    assert job.count("src/tests/strings/expected/BracesInCodeGen.stdout") >= 2
    assert "src/tests/stdlib/expected/PathWindowsLexical.stdout" in job
    # The bootstrap imports src.tests; as a script beside the installed wheel
    # it cannot, so it runs as a module from the checkout.
    assert "python -m unittest -v src.tests.btrc.test_bootstrap" in _code(job)
    assert "python src/tests/btrc/test_bootstrap.py" not in _code(job)
    # Logical-line equality tolerates Git's platform EOL checkout while still
    # rejecting any extra, missing, or otherwise changed output line.
    assert job.count(".splitlines()") >= 4
    _assert_archive_upload(job, "dist/btrcc-windows-x64.zip")


def test_linux_bench_job_guards_every_performance_indicator() -> None:
    job = _job(_workflow("ci.yml"), "bench")
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")

    # One container run measures compile time, startup, emitted-C size, cc
    # time and generated-code speed, and fails on a regression against the
    # tracked baseline; the raw numbers are kept as an artifact either way.
    assert "\nbench-check:" in makefile and "\nbench-baseline:" in makefile
    assert 'podman run --rm --init -v "$PWD:/workspace" btrc-devcontainer:latest make NIX= bench-check' in job
    assert "if: always()" in job
    assert "name: bench-results" in job and "build/bench/results.json" in job
