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

from tools.qualification.tiers import MANIFEST as TIER_MANIFEST
from tools.qualification.tiers import TierManifest

REPO = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO / ".github/workflows"
UPLOAD_ARTIFACT = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
SETUP_NODE = "actions/setup-node@48b55a011bda9f5d6aeb4c2d9c7362e8dae4041e"
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
    # A job that calls a reusable workflow has no steps.
    ends = [*starts[1:], len(lines)] if starts else []
    return ["\n".join(lines[start:end]) for start, end in zip(starts, ends, strict=True)]


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
            if reference.startswith("./.github/workflows/"):
                # A reusable workflow of this repository runs at the caller's commit.
                assert (REPO / reference).is_file(), (workflow.name, reference)
                continue
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

    lines = text.splitlines()
    value, index = _yaml_node(lines, 0, 0)
    index = _yaml_skip(lines, index)
    assert index == len(lines), f"unparsed workflow line {index + 1}: {lines[index]!r}"
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
        match = re.fullmatch(r"([^\s:#'\"][^:#]*?|\"[^\"]*\"|'[^']*'):(?:\s+(.*))?", lines[index].strip())
        assert match is not None, f"not a mapping entry: {lines[index]!r}"
        key, rest = (
            match.group(1)[1:-1] if match.group(1)[0] in "'\"" else match.group(1),
            _yaml_comment(match.group(2) or ""),
        )
        assert key != "<<", f"merge keys are outside the subset: {lines[index]!r}"
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
    assert not text.startswith(("&", "*", "!")), f"anchors, aliases and tags are outside the subset: {text!r}"
    if text in ("~", "null"):
        return None
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


# The workflow classes (WORKSTREAMS.md §3.2). The core three gate every change
# and are what release.yml calls; a lane workflow belongs to one packet and
# runs when its paths change; a dispatch-only workflow is a probe someone
# starts by hand; release runs on dispatch, tags and the nightly schedule.
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


def _dispatch_violations(dispatch: object, event: str = "workflow_dispatch") -> list[str]:
    if dispatch is None or (isinstance(dispatch, dict) and set(dispatch) <= {"inputs"}):
        return []
    return [f"{event} may carry only inputs: {dispatch!r}"]


def _trigger_violations(name: str, triggers: object) -> list[str]:
    """Every way `triggers` (a parsed `on:` block) breaks `name`'s class policy."""

    kind = _workflow_class(name)
    if kind is None:
        return [f"{name} is in no workflow class; name it in test_ci_workflow_contracts.py"]
    if not isinstance(triggers, dict):
        return [f"{name}'s on: block is not a mapping"]
    main = {"branches": ["main"]}
    if kind == "core":
        core = {"push", "pull_request", "workflow_dispatch", "workflow_call"}
        problems = [] if set(triggers) == core else [f"triggers {sorted(triggers)}"]
        problems += [f"{event} must be {main}" for event in ("push", "pull_request") if triggers.get(event) != main]
        return (
            problems
            + _dispatch_violations(triggers.get("workflow_dispatch"))
            + _dispatch_violations(triggers.get("workflow_call"), "workflow_call")
        )
    if kind == "dispatch-only":
        return (
            [] if set(triggers) == {"workflow_dispatch"} else [f"triggers {sorted(triggers)}"]
        ) + _dispatch_violations(triggers.get("workflow_dispatch"))
    if kind == "tag":
        push = triggers.get("push")
        allowed = {"push", "workflow_dispatch", "schedule"}
        problems = [] if set(triggers) <= allowed else [f"triggers {sorted(triggers)}"]
        if not (isinstance(push, dict) and set(push) == {"tags"} and push["tags"]):
            problems.append(f"push must name tags only: {push!r}")
        schedule = triggers.get("schedule", [])
        if not (
            isinstance(schedule, list) and all(isinstance(entry, dict) and set(entry) == {"cron"} for entry in schedule)
        ):
            problems.append(f"schedule must be a list of crons: {schedule!r}")
        return problems + _dispatch_violations(triggers.get("workflow_dispatch"))
    required = {"push", "pull_request", "workflow_dispatch"}
    problems = [] if required <= set(triggers) <= required | {"workflow_call"} else [f"triggers {sorted(triggers)}"]
    for event in ("push", "pull_request"):
        rule = triggers.get(event)
        paths = rule.get("paths") if isinstance(rule, dict) else None
        if not (isinstance(rule, dict) and set(rule) == {"branches", "paths"} and rule["branches"] == ["main"]):
            problems.append(f"{event} must be branches [main] with a paths filter: {rule!r}")
        elif not (isinstance(paths, list) and paths and all(isinstance(path, str) for path in paths)):
            problems.append(f"{event}'s paths filter must be a list of patterns: {paths!r}")
        elif not _github_paths_match(paths, f".github/workflows/{name}"):
            problems.append(f"{event}'s paths filter must include .github/workflows/{name}")
    return problems + _dispatch_violations(triggers.get("workflow_dispatch"))


def _github_paths_match(patterns: list[str], path: str) -> bool:
    """Whether GitHub's `paths` filter selects `path`.

    `*` stays within one directory, `**` crosses them, and a later `!pattern`
    excludes what an earlier pattern included (GitHub's filter-pattern rules).
    """

    selected = False
    for pattern in patterns:
        negated = pattern.startswith("!")
        glob = re.escape(pattern.removeprefix("!"))
        glob = glob.replace(r"\*\*/", "(?:.*/)?").replace(r"\*\*", ".*").replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
        if re.fullmatch(glob, path):
            selected = not negated
    return selected


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
        (
            "ci.yml",
            "push:\n  branches: [main]\npull_request:\n  branches: [main]\nworkflow_dispatch:\nworkflow_call:\n",
            0,
        ),
        (
            "macos.yml",
            "push:\n  branches: [main]\npull_request:\n  branches: [main]\n"
            "workflow_dispatch:\n  inputs:\n    focus:\n      type: choice\n      options: [full, native-gui]\n"
            "workflow_call:\n  inputs:\n    tier:\n      type: string\n",
            0,
        ),
        ("ci.yml", "push:\n  branches: [main]\npull_request:\n  branches: [main]\nworkflow_dispatch:\n", 1),
        (
            "ci.yml",
            "push:\n  branches: [main, dev]\npull_request:\n  branches: [main]\nworkflow_dispatch:\n"
            "workflow_call:\n  secrets:\n    token:\n      required: true\n",
            2,
        ),
        ("windows.yml", "push:\n  branches: [main]\npull_request:\n  branches: [main]\nworkflow_call:\n", 1),
        (
            "host-linux.yml",
            "push:\n  branches: [main]\n  paths: [.github/workflows/host-linux.yml]\npull_request:\n  branches: [main]\n"
            "  paths:\n    - .github/workflows/host-linux.yml\n    - tools/target_hosts/**\nworkflow_dispatch:\nworkflow_call:\n",
            0,
        ),
        (
            "host-linux.yml",
            "push:\n  branches: [main]\n  paths: ['*']\npull_request:\n  branches: [main]\n"
            "  paths: ['.github/**', '!.github/workflows/host-*.yml']\nworkflow_dispatch: ~\n",
            2,
        ),
        (
            "host-linux.yml",
            "push:\n  branches: [main]\n  paths: src/**\npull_request:\n  branches: [main]\n"
            "  paths: ['**/*.yml']\nworkflow_dispatch:\n",
            1,
        ),
        (
            "windows-x64.yml",
            "push:\n  branches: [main]\npull_request:\n  branches: [main]\n  paths: ['**']\nworkflow_dispatch:\n",
            1,
        ),
        (
            "ios.yml",
            "push:\n  branches: [main]\n  paths: ['.github/workflows/*.yml']\npull_request:\n  branches: [main]\n"
            "  paths: ['.github/workflows/*.yml', src/stdlib/GUI/IOS/**]\nworkflow_dispatch:\n",
            0,
        ),
        ("android.yml", "push:\n  branches: [main]\npull_request:\n  branches: [main]\nworkflow_dispatch:\n", 2),
        (
            "windows-arm64.yml",
            "push:\n  branches: [main]\n  paths: [.github/workflows/windows-arm64.yml]\npull_request:\n  branches: [main]\n"
            "  paths: [src/stdlib/**]\nworkflow_dispatch:\n",
            1,
        ),
        ("host-macos.yml", "pull_request:\n  branches: [main]\n  paths: [.github/workflows/host-macos.yml]\n", 2),
        ("windows-msvc-probe.yml", "workflow_dispatch:\n  inputs:\n    toolset:\n      default: v143\n", 0),
        ("acceptance-x86.yml", "workflow_dispatch:\npush:\n  branches: [main]\n", 1),
        ("release.yml", "push:\n  tags: ['v*']\nworkflow_dispatch:\n", 0),
        ("release.yml", "push:\n  tags: ['v*']\nschedule:\n  - cron: '23 8 * * *'\nworkflow_dispatch:\n", 0),
        ("release.yml", "push:\n  tags: ['v*']\nschedule: daily\nworkflow_call:\n", 2),
        ("release.yml", "push:\n  branches: [main]\n  tags: ['v*']\n", 1),
        ("nightly.yml", "workflow_dispatch:\n", 1),
    ],
)
def test_the_trigger_policy_holds_each_workflow_class_to_its_shape(name: str, on: str, problems: int) -> None:
    assert len(_trigger_violations(name, _yaml(on))) == problems


def test_core_workflows_cancel_superseded_pull_request_runs_and_queue_main() -> None:
    # The literal prefix keeps them apart when release.yml calls all three:
    # a called workflow's github.workflow is its caller's name.
    for name in CORE_WORKFLOWS:
        stem = name.rsplit(".", 1)[0]
        assert _parsed(name)["concurrency"] == {
            "group": f"{stem}-${{{{ inputs.tier && format('call-{{0}}', github.run_id) || "
            "github.event_name == 'pull_request' && format('pr-{0}', github.head_ref) || "
            "github.event_name == 'push' && 'main' || format('dispatch-{0}', github.run_id) }}",
            "cancel-in-progress": "${{ github.event_name == 'pull_request' }}",
        }, name


def _job_names(workflow: dict[str, object]) -> list[str]:
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    return list(jobs)


# A job runs the suite when a step calls pytest or a make target that does:
# test, test-<anything> (the shards, test-c11-one, test-native-gui) or linux-ci.
RUNS_PYTEST = re.compile(r"\bpytest\b|\bmake\b.*\s(?:test(?:-[a-z0-9-]+)?|linux-ci)(?:\s|$)")
TIERS = TierManifest.load(TIER_MANIFEST)
PLAN = "fromJSON(needs.scope.outputs.plan)"


def _plan_matrix(job: str) -> str:
    access = f".{job}" if re.fullmatch(r"[a-z]+", job) else f"['{job}']"
    return f"${{{{ {PLAN}.matrix{access} }}}}"


def _matrix_rows(matrix: object, workflow: str | None = None, job: str | None = None) -> list[dict[str, object]] | None:
    """The combinations a matrix expands to; None when an expression decides them.

    A matrix the scope job's plan supplies expands to every row ci/tiers.toml
    lists for that job, with the pytest_addopts a pr-tier corpus row adds.
    """

    if matrix == _plan_matrix(job or "") and workflow is not None:
        tiered = next(entry for entry in TIERS.jobs if entry.reference == f"{workflow}/{job}")
        return [{**shard.row, "pytest_addopts": ""} for shard in TIERS.shards_of(tiered)]
    if not isinstance(matrix, dict):
        return None
    axes = {key: value for key, value in matrix.items() if key not in ("include", "exclude")}
    if any(not isinstance(value, list) for value in axes.values()) or "exclude" in matrix:
        return None
    rows: list[dict[str, object]] = [{}]
    for key, values in axes.items():
        rows = [{**row, key: value} for row in rows for value in values]
    include = matrix.get("include", [])
    if not isinstance(include, list):
        return None
    if not axes:
        return [dict(row) for row in include]
    return rows + [dict(row) for row in include if not any(row.items() <= base.items() for base in rows)]


def _job_commands(job: dict[str, object], workflow: str | None = None, name: str | None = None) -> list[str]:
    """Each step's script, once per matrix combination with its values filled in."""

    scripts = [_code(str(step.get("run", ""))) for step in job.get("steps", [])]
    rows = _matrix_rows(job.get("strategy", {}).get("matrix"), workflow, name) or [{}]
    return [
        re.sub(r"\$\{\{ matrix\.([a-z_]+) \}\}", lambda use, row=row: str(row.get(use.group(1), use.group(0))), script)
        for script in scripts
        for row in rows
    ]


def test_every_test_job_retains_its_skip_report_as_its_last_step() -> None:
    # Any job that runs the suite keeps the skip report its pytest sessions
    # write, even when a test failed, under a name unique within the run that
    # the workflow and job derive: skip-report-<workflow stem>-<job>, then one
    # `-${{ matrix.<key> }}` per key that tells the job's combinations apart.
    test_jobs = {
        (path.name, name): job
        for path in _workflow_paths()
        for name, job in _parsed(path.name)["jobs"].items()
        if "steps" in job and any(RUNS_PYTEST.search(command) for command in _job_commands(job, path.name, name))
    }
    assert {
        ("ci.yml", "static"),
        ("ci.yml", "tests"),
        ("ci.yml", "native-gui"),
        ("ci.yml", "linux-gui"),
        ("macos.yml", "tests"),
        ("macos.yml", "native-gui"),
        ("windows.yml", "windows"),
        ("windows.yml", "bootstrap"),
    } <= set(test_jobs)
    for (workflow, name), job in test_jobs.items():
        final = job["steps"][-1]
        assert final.get("if") == "always()", (workflow, name)
        assert final.get("uses") == UPLOAD_ARTIFACT, (workflow, name)
        upload = final["with"]
        assert upload["path"] == SKIP_REPORTS, (workflow, name)
        assert upload["if-no-files-found"] == "warn", (workflow, name)
        base = f"skip-report-{workflow.rsplit('.', 1)[0]}-{name}"
        assert upload["name"].startswith(base), (workflow, name, upload["name"])
        keys = re.findall(r"-\$\{\{ matrix\.([a-z_]+) \}\}", upload["name"][len(base) :])
        assert upload["name"] == base + "".join(f"-${{{{ matrix.{key} }}}}" for key in keys), (workflow, name)
        assert len(set(keys)) == len(keys), (workflow, name)
        matrix = job.get("strategy", {}).get("matrix")
        if matrix is None:
            assert keys == [], (workflow, name)
            continue
        assert keys, f"{workflow} {name}: a matrix job needs a matrix suffix"
        rows = _matrix_rows(matrix, workflow, name)
        if rows is None:
            # An expression decides the combinations: name only its own axes.
            assert set(keys) <= set(matrix), (workflow, name, keys)
            continue
        names = [tuple(row.get(key) for key in keys) for row in rows]
        assert all(None not in values for values in names), (workflow, name, keys)
        assert len(set(names)) == len(rows), f"{workflow} {name}: skip-report names collide across the matrix"
        # The tier manifest names the same reports, so the bundle expects them.
        tiered = next(entry for entry in TIERS.jobs if entry.reference == f"{workflow}/{name}")
        assert "skip-report" in tiered.reports, (workflow, name)
        if tiered.key is not None:
            assert keys == [tiered.key], (workflow, name)


def test_sharded_workflows_name_every_report_the_plan_expected_that_is_missing() -> None:
    """A lost runner never reaches its own upload, so a later job names the gap."""

    for workflow in ("ci.yml", "macos.yml"):
        job = _job(_workflow(workflow), "skip-reports")
        parsed = _parsed(workflow)["jobs"]["skip-reports"]
        assert parsed["needs"] == ["scope", "tests"], workflow
        assert parsed["if"] == (
            f"${{{{ !cancelled() && needs.scope.result == 'success' && contains({PLAN}.jobs, 'tests') }}}}"
        ), workflow
        assert re.search(r"(?m)^    timeout-minutes: \d+$", job), workflow
        assert "actions: read" in job, workflow
        step = _parsed(workflow)["jobs"]["skip-reports"]["steps"][-1]
        assert step["env"]["EXPECTED"] == f"${{{{ join({PLAN}.reports.tests, ' ') }}}}", workflow
        script = _code(step["run"])
        assert "/actions/runs/$GITHUB_RUN_ID/artifacts" in script, workflow
        # Job names carry release.yml's call prefix, so the plan names the shards.
        assert "/jobs" not in script, workflow
        assert 'grep -qx "$name"' in script, workflow
        assert "::warning::" in script and "GITHUB_STEP_SUMMARY" in script, workflow


def _scope_step(workflow: str, name: str = "Classify the change") -> dict[str, object]:
    steps = _parsed(workflow)["jobs"]["scope"]["steps"]
    return next(step for step in steps if step.get("name") == name)


def test_scope_runs_first_and_gates_every_other_job_by_the_tier_plan() -> None:
    scope = _parsed("ci.yml")["jobs"]["scope"]
    for workflow in CORE_WORKFLOWS:
        document = _parsed(workflow)
        assert document["jobs"]["scope"] == scope, workflow
        assert document["env"]["CI_WORKFLOW"] == workflow, workflow
        assert _job_names(document)[0] == "scope", workflow
        listed = {entry.job for entry in TIERS.jobs if entry.workflow == workflow}
        jobs = document["jobs"]
        assert set(jobs) - {"scope", "skip-reports"} == listed, workflow
        for name in listed:
            job = jobs[name]
            assert job["needs"] == "scope", (workflow, name)
            assert job["if"] == f"contains({PLAN}.jobs, '{name}')", (workflow, name)
            tiered = next(entry for entry in TIERS.jobs if entry.reference == f"{workflow}/{name}")
            matrix = job.get("strategy", {}).get("matrix")
            if tiered.key is None:
                assert matrix is None, (workflow, name)
            else:
                assert matrix == _plan_matrix(name), (workflow, name)
                assert job["strategy"]["fail-fast"] == "false", (workflow, name)
    assert scope["runs-on"] == "ubuntu-latest"
    assert scope["permissions"] == {"contents": "read", "pull-requests": "read"}
    assert scope["outputs"] == {
        "tier": "${{ steps.classify.outputs.tier }}",
        "plan": "${{ steps.plan.outputs.plan }}",
    }
    plan = _scope_step("ci.yml", "Plan the tier's jobs")
    assert plan["env"] == {"TIER": "${{ steps.classify.outputs.tier }}"}
    assert (
        'python3 -m tools.qualification tiers --workflow "$CI_WORKFLOW" --tier "$TIER" '
        "--changed build/changed-files.txt" in plan["run"]
    )
    assert 'echo "plan=$plan" >> "$GITHUB_OUTPUT"' in plan["run"]
    # The classifier's tiers are the manifest's scheduled tiers.
    script = _scope_step("ci.yml")["run"]
    case = re.search(r"case \"\$tier\" in\n\s*(.+?)\) ;;", script)
    assert case is not None
    assert set(case.group(1).split(" | ")) == set(TIERS.scheduled_tiers())


def test_a_pr_tier_corpus_row_reaches_pytest_through_pytest_addopts() -> None:
    corpus = [shard for shard in TIERS.shards if shard.corpus_tiers]
    assert {shard.job for shard in corpus} == {"ci.yml/tests"}
    for workflow in ("ci.yml", "macos.yml"):
        suite = next(
            step for step in _parsed(workflow)["jobs"]["tests"]["steps"] if "matrix.target" in step.get("run", "")
        )
        assert suite["env"] == {"PYTEST_ADDOPTS": "${{ matrix.pytest_addopts }}"}, workflow
    linux = next(step for step in _parsed("ci.yml")["jobs"]["tests"]["steps"] if "matrix.target" in step.get("run", ""))
    assert '-v "$PWD:/workspace" -e PYTEST_ADDOPTS btrc-devcontainer:latest' in linux["run"]


def test_bootstrap_shards_keep_their_boundary_report_for_the_bundle() -> None:
    for workflow in ("ci.yml", "macos.yml"):
        steps = _parsed(workflow)["jobs"]["tests"]["steps"]
        upload = next(step for step in steps if step.get("name") == "Retain the boundary report")
        assert steps.index(upload) == len(steps) - 2, workflow
        assert upload["if"] == "always()" and upload["uses"] == UPLOAD_ARTIFACT, workflow
        stem = workflow.rsplit(".", 1)[0]
        assert upload["with"]["name"] == f"boundary-report-{stem}-tests-${{{{ matrix.shard }}}}", workflow
        assert upload["with"]["path"] == "build/boundary-report.json", workflow
        assert upload["with"]["if-no-files-found"] == "ignore", workflow
        bootstrap = [
            shard for shard in TIERS.shards if shard.job == f"{workflow}/tests" and "boundary-report" in shard.reports
        ]
        assert [shard.row["shard"] for shard in bootstrap] == ["bootstrap"], workflow
    # test-shard-bootstrap is what writes it.
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    assert "test-boundaries" in _makefile_recipe(makefile, "test-shard-bootstrap")
    assert "--report build/boundary-report.json" in _makefile_recipe(makefile, "test-boundaries")


def test_release_runs_every_tiered_workflow_at_one_tier_then_bundles_them() -> None:
    release = _parsed("release.yml")
    assert release["on"]["workflow_dispatch"]["inputs"]["tier"]["options"] == ["release", "extended"]
    tier = "${{ github.event_name == 'schedule' && 'extended' || inputs.tier || 'release' }}"
    jobs = release["jobs"]
    calls = {name: job for name, job in jobs.items() if "uses" in job}
    assert {job["uses"] for job in calls.values()} == {f"./.github/workflows/{name}" for name in CORE_WORKFLOWS}
    for name, job in calls.items():
        assert job["with"] == {"tier": tier}, name
        assert job["permissions"] == {"contents": "read", "pull-requests": "read", "actions": "read"}, name
    bundle = jobs["bundle"]
    assert bundle["needs"] == sorted(calls) and bundle["if"] == "${{ !cancelled() }}"
    steps = bundle["steps"]
    download = next(step for step in steps if str(step.get("uses", "")).startswith("actions/download-artifact@"))
    # Every artifact: the bundle sorts evidence from archives by name.
    assert download["with"] == {"path": "build/release-artifacts"}
    command = next(step for step in steps if "tools.qualification bundle" in step.get("run", ""))
    assert command["env"] == {"TIER": tier}
    for option in ("--artifacts build/release-artifacts", '--tier "$TIER"', '--revision "$GITHUB_SHA"'):
        assert option in command["run"], option
    upload = steps[-1]
    assert upload["if"] == "always()" and upload["uses"] == UPLOAD_ARTIFACT
    assert upload["with"]["name"] == "ledger-bundle-${{ github.sha }}"
    assert upload["with"]["path"] == "build/ledger-bundle-${{ github.sha }}"
    assert upload["with"]["if-no-files-found"] == "error"
    assert '--output "build/ledger-bundle-$GITHUB_SHA"' in command["run"]
    # A called workflow plans its jobs for the tier it is given.
    for name in CORE_WORKFLOWS:
        assert _parsed(name)["on"]["workflow_call"] == {
            "inputs": {"tier": {"description": "The ci/tiers.toml tier to run", "type": "string", "required": "true"}}
        }, name
    assert _scope_step("ci.yml")["env"]["TIER"] == "${{ inputs.tier }}"


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
        ".github/workflows/release.yml",
        "ci/tiers.toml",
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
    assert {"CLAUDE.md", "AGENTS.md", "docs/design/platform-parity.md"} <= read
    assert sorted(name for name in read if not test_read.search(name)) == []
    for name in ("CLAUDE.md", "src/stdlib/GUI/README.md", "docs/design/compiler-structure.md"):
        assert test_read.search(name), name
    for name in (
        "docs/design/ui0-catalog.md",
        "WORKSTREAMS.md",
        "CODEX.md",
        "docs/design/claude-integration-record.md",
        "docs/qualification/ui-agent-runbook.md",
    ):
        assert not test_read.search(name), name


# A shell function, sourced before the step's script: it shadows any gh on
# PATH and needs no executable file (a test's tmp directory may be noexec).
FAKE_GH = """gh() {
  local argument endpoint
  for argument; do endpoint=$argument; done
  case "$endpoint" in
    */files\\?per_page=100)
      [[ " $* " == *" --paginate --slurp "* ]] || { echo "files need --paginate --slurp" >&2; return 2; }
      cat "$FAKE_GH/files.json" ;;
    */pulls/*) cat "$FAKE_GH/pull.json" ;;
    *) echo "unexpected gh $*" >&2; return 2 ;;
  esac
}
"""


def _classify(tmp_path: Path, event: str, head: str = "", files: tuple[str, ...] = (), **pull: object) -> str:
    """Run the scope step's script against a stand-in `gh` that serves one pull request.

    A dispatch's `focus` input rides in `pull` as `focus`, a call's `tier` as
    `tier`. The script runs in `tmp_path`, where it leaves
    build/changed-files.txt for the plan step.
    """

    step = _scope_step("ci.yml")
    (tmp_path / "gh.sh").write_text(FAKE_GH, encoding="utf-8")
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
    output.unlink(missing_ok=True)
    environment = {
        **os.environ,
        "FAKE_GH": str(tmp_path),
        "GITHUB_REPOSITORY": "schiffy91/btrc",
        "GITHUB_OUTPUT": str(output),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
        "EVENT": event,
        "TIER": str(pull.get("tier", "")),
        "FOCUS": str(pull.get("focus", "")),
        "PULL_REQUEST": "21" if event == "pull_request" else "",
        "HEAD_REF": head,
        "FULL_PATHS": step["env"]["FULL_PATHS"],
        "TEST_READ_MARKDOWN": step["env"]["TEST_READ_MARKDOWN"],
    }
    completed = subprocess.run(
        ["bash", "-c", f'source "$FAKE_GH/gh.sh"\n{step["run"]}'],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    lines = output.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and lines[0].startswith("tier="), lines
    return lines[0].removeprefix("tier=")


def _plan(tmp_path: Path, workflow: str, tier: str) -> dict[str, object]:
    """Run the scope job's plan step after `_classify`, as the job runs it."""

    step = _scope_step(workflow, "Plan the tier's jobs")
    output = tmp_path / "plan-output"
    output.unlink(missing_ok=True)
    environment = {
        **os.environ,
        "PYTHONPATH": str(REPO),
        "CI_WORKFLOW": workflow,
        "TIER": tier,
        "GITHUB_OUTPUT": str(output),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
    }
    completed = subprocess.run(
        ["bash", "-c", step["run"]],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    lines = output.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and lines[0].startswith("plan="), lines
    return json.loads(lines[0].removeprefix("plan="))


@pytest.mark.parametrize(
    ("event", "head", "files", "pull", "expected"),
    [
        ("push", "", (), {}, "main"),
        ("workflow_dispatch", "", (), {}, "main"),
        ("workflow_dispatch", "", (), {"focus": "full"}, "main"),
        ("workflow_dispatch", "", (), {"focus": "native-gui"}, "native-gui"),
        ("workflow_dispatch", "", (), {"focus": "extended"}, "extended"),
        ("workflow_dispatch", "", (), {"tier": "release", "focus": ""}, "release"),
        ("push", "", (), {"tier": "extended"}, "extended"),
        ("pull_request", "codex/cx-uia-07", ("docs/design/ui0-catalog.md", "docs/qualification/notes.md"), {}, "docs"),
        ("pull_request", "stage30/notes", ("WORKSTREAMS.md",), {}, "docs"),
        ("pull_request", "codex/cx-uia-07", ("docs/design/ui0-catalog.md", "CLAUDE.md"), {}, "lane"),
        ("pull_request", "codex/cx-stdlib-01", ("CODEX.md",), {}, "docs"),
        ("pull_request", "stage30/notes", ("src/stdlib/GUI/README.md",), {}, "pr"),
        (
            "pull_request",
            "codex/ui0-catalog",
            ("docs/design/native-ui-catalog.toml", "src/tests/python/test_ui0_catalog.py"),
            {},
            "lane",
        ),
        ("pull_request", "codex/cx-p2-04", ("src/stdlib/FileSystem/Windows/FileSystemProvider.btrc",), {}, "main"),
        (
            "pull_request",
            "codex/cx-uia-09",
            ("src/stdlib/GUI/Linux/Window.btrc", "src/stdlib/Strings.btrc"),
            {},
            "main",
        ),
        ("pull_request", "codex/cx-uia-09", ("tools/ui/moved.py <- src/compiler/python/main.py",), {}, "main"),
        ("pull_request", "codex/cx-uia-09", ("src/stdlib/GUI/Linux/Window.btrc",), {"labels": ("ci:full",)}, "main"),
        ("pull_request", "codex/cx-uia-09", ("src/stdlib/GUI/Linux/Window.btrc",), {"labels": ("ci:fast",)}, "lane"),
        ("pull_request", "codex/cx-uia-09", tuple(f"docs/n{i}.md" for i in range(150)), {}, "docs"),
        ("pull_request", "codex/cx-uia-09", ("docs/a.md",), {"changed_files": 3001}, "main"),
        ("pull_request", "stage30/ci-codex-lanes", ("src/tests/python/test_x.py",), {}, "pr"),
        ("pull_request", "stage38/ci-tiers", ("ci/tiers.toml",), {}, "main"),
        ("pull_request", "stage38/ci-tiers", (".github/workflows/release.yml",), {}, "main"),
    ],
)
def test_scope_classifies_a_pull_requests_diff(
    tmp_path: Path, event: str, head: str, files: tuple[str, ...], pull: dict[str, object], expected: str
) -> None:
    assert shutil.which("jq") and shutil.which("bash"), "the dev shell provides jq and bash"
    assert _classify(tmp_path, event, head, files, **pull) == expected
    changed = (tmp_path / "build" / "changed-files.txt").read_text(encoding="utf-8").split()
    if event == "pull_request" and "changed_files" not in pull and "labels" not in pull:
        # Both sides of a rename, as the plan step reads them.
        assert changed == [part for name in files for part in name.split(" <- ")]
    elif event != "pull_request":
        assert changed == []


def test_a_docs_only_pull_request_runs_only_the_static_job(tmp_path: Path) -> None:
    files = ("docs/design/ui0-catalog.md",)
    for workflow in CORE_WORKFLOWS:
        tier = _classify(tmp_path, "pull_request", "stage30/notes", files)
        plan = _plan(tmp_path, workflow, tier)
        assert plan["jobs"] == (["static"] if workflow == "ci.yml" else []), workflow


def test_a_compiler_pull_request_runs_the_full_main_matrix(tmp_path: Path) -> None:
    files = ("src/compiler/python/main.py", "src/stdlib/GUI/MacOS/Window.btrc")
    tier = _classify(tmp_path, "pull_request", "stage38/ci-tiers", files)
    assert tier == "main"
    for workflow in CORE_WORKFLOWS:
        assert _plan(tmp_path, workflow, tier) == TIERS.plan(workflow, "main"), workflow
    assert len(TIERS.plan("ci.yml", "main")["matrix"]["tests"]["include"]) == 13


def test_a_plain_pull_request_plans_from_its_changed_paths(tmp_path: Path) -> None:
    files = ("tools/qualification/report.py", "src/tests/strings/Escapes.btrc")
    tier = _classify(tmp_path, "pull_request", "stage38/ci-tiers", files)
    assert tier == "pr"
    plan = _plan(tmp_path, "ci.yml", tier)
    assert plan["jobs"] == ["static", "tests"]
    rows = {row["shard"]: row for row in plan["matrix"]["tests"]["include"]}
    assert list(rows) == ["unit", "corpus-python", "corpus-btrc"]
    assert rows["corpus-btrc"]["pytest_addopts"] == '-k "python-strings/ or btrc-strings/"'
    assert _plan(tmp_path, "macos.yml", tier)["jobs"] == []
    assert _plan(tmp_path, "windows.yml", tier)["jobs"] == []


LANE_HEAVY_LINUX = ["static", "release", "tests", "bench", "linux-arm64-bundle"]
LANE_LIGHT_LINUX = ["static", "release", "tests"]
LANE_GUI_LINUX = [*LANE_HEAVY_LINUX, "linux-gui"]


@pytest.mark.parametrize(
    ("files", "linux", "macos"),
    [
        # A catalog-data packet: scope, the static gates, release and the unit shard only.
        (
            (
                "docs/design/native-ui-catalog/families.toml",
                "tools/qualification/ui_catalog.py",
                "src/tests/python/test_ui0_catalog.py",
            ),
            LANE_LIGHT_LINUX,
            [],
        ),
        (("tools/ui/codex-setup.sh",), LANE_LIGHT_LINUX, ["native-bundle", "native-gui"]),
        (("src/stdlib/GUI/MacOS/Window.btrc",), LANE_HEAVY_LINUX, ["native-bundle", "native-gui"]),
        (("src/stdlib/GUI/Linux/Window.btrc",), LANE_GUI_LINUX, ["native-bundle", "native-gui"]),
        (("src/stdlib/HTTP/Client.btrc",), LANE_HEAVY_LINUX, []),
        (
            ("src/tests/python/test_native_gui_target.py",),
            [*LANE_LIGHT_LINUX, "linux-gui"],
            ["native-bundle", "native-gui"],
        ),
        # A pull request with no listed file plans the whole lane selection.
        ((), LANE_GUI_LINUX, ["native-bundle", "native-gui"]),
    ],
)
def test_a_lane_pull_request_runs_the_jobs_its_paths_select(
    tmp_path: Path, files: tuple[str, ...], linux: list[str], macos: list[str]
) -> None:
    tier = _classify(tmp_path, "pull_request", "codex/cx-uia-03", files)
    assert tier == "lane"
    ci = _plan(tmp_path, "ci.yml", tier)
    assert ci["jobs"] == linux
    shards = [row["shard"] for row in ci["matrix"]["tests"]["include"]]
    assert shards == ([name for name, _ in _tier_shards("ci.yml", "main")] if "bench" in linux else ["unit"])
    assert _plan(tmp_path, "macos.yml", tier)["jobs"] == macos
    assert _plan(tmp_path, "windows.yml", tier)["jobs"] == []


def test_a_lane_pull_request_too_large_to_list_fails_safe_to_the_main_tier(tmp_path: Path) -> None:
    files = ("docs/design/native-ui-catalog/families.toml",)
    tier = _classify(tmp_path, "pull_request", "codex/cx-uia-03", files, changed_files=3001)
    assert tier == "main"
    for workflow in CORE_WORKFLOWS:
        assert _plan(tmp_path, workflow, tier) == TIERS.plan(workflow, "main"), workflow


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
    shards = _tier_shards("ci.yml", "main")
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
    # Every tier's rows are rows of this list: the extended and release tiers
    # add none on Linux.
    for tier in TIERS.scheduled_tiers():
        assert {name for name, _ in _tier_shards("ci.yml", tier)} <= {name for name, _ in shards}, tier


def _tier_shards(workflow: str, tier: str) -> list[tuple[str, str]]:
    """The (shard, target) rows ci/tiers.toml gives a workflow's tests job in one tier."""

    matrix = TIERS.plan(workflow, tier)["matrix"].get("tests", {"include": []})
    return [(row["shard"], row["target"]) for row in matrix["include"]]


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
    linux = dict(_tier_shards("ci.yml", "main"))
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")

    assert "runs-on: macos-15" in job
    assert "fail-fast: false" in job
    shards = _tier_shards("macos.yml", "main")
    assert [shard for shard, _ in shards] == [
        "unit",
        "btrc",
        "corpus-python",
        "corpus-btrc",
        "bootstrap",
        "c11-clang-O0",
        "c11-clang-O2",
    ]
    # The extended tier adds clang's other two levels; it never adds gcc,
    # whose Objective-C support the native cases need.
    extended = _tier_shards("macos.yml", "extended")
    assert [shard for shard, _ in extended if shard not in dict(shards)] == ["c11-clang-O1", "c11-clang-O3"]
    shards = extended
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
        "BTRC_TEST_TRANSPILE_TIMEOUT=600 BTRC_TEST_RUN_TIMEOUT=60 ${{ matrix.target }}\n"
        "        env:\n"
        "          PYTEST_ADDOPTS: ${{ matrix.pytest_addopts }}"
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
    # The bootstrap runs in its own job, which the pr and lane tiers leave out.
    assert "src.tests.btrc.test_bootstrap" not in _code(job)
    bootstrap = _job(_workflow("windows.yml"), "bootstrap")
    assert "runs-on: windows-latest" in bootstrap
    assert "python -m pip install '.[dev]'" in bootstrap
    assert "zig-x86_64-windows-$ver.zip" in bootstrap and "$expectedSha256" in bootstrap
    assert 'BTRC_CC: "zig cc -target x86_64-windows-gnu"' in bootstrap
    assert 'BTRC_BOOTSTRAP_TIMEOUT_SECONDS: "3600"' in bootstrap
    # The bootstrap imports src.tests; as a script beside the installed wheel
    # it cannot, so it runs as a module from the checkout.
    assert "python -m unittest -v src.tests.btrc.test_bootstrap" in _code(bootstrap)
    assert "python src/tests/btrc/test_bootstrap.py" not in _code(bootstrap)
    assert "python -m tools.qualification skip-gate build/skip-report-windows-bootstrap-harness.json" in bootstrap
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


def test_a_focused_dispatch_runs_only_the_native_gui_jobs() -> None:
    # `gh workflow run ci.yml -f focus=native-gui` (likewise macos.yml) skips
    # every other job: the native-gui tier lists only the native-GUI job and,
    # on Linux, the GUI shard's two sessions, and the scope step passes the
    # input through.
    for workflow in CORE_WORKFLOWS:
        document = _parsed(workflow)
        assert document["on"]["workflow_dispatch"] == {
            "inputs": {
                "focus": {
                    "description": "Which jobs to run",
                    "type": "choice",
                    "options": ["full", "native-gui", "extended"],
                    "default": "full",
                }
            }
        }, workflow
        assert _scope_step(workflow)["env"]["FOCUS"] == "${{ inputs.focus }}", workflow
        expected = {"ci.yml": ["native-gui", "linux-gui"], "macos.yml": ["native-gui"]}.get(workflow, [])
        assert TIERS.plan(workflow, "native-gui")["jobs"] == expected, workflow

    linux = _job(_workflow("ci.yml"), "native-gui")
    assert _code(linux).count("make NIX=") == 1
    assert (
        'podman run --rm --init -v "$PWD:/workspace" -e PYTEST_ADDOPTS=--junitxml=build/junit/native-gui.xml '
        "btrc-devcontainer:latest tools/virtual-display.sh make NIX= PYTEST_WORKERS=4 "
        "BTRC_TEST_TRANSPILE_TIMEOUT=600 BTRC_TEST_RUN_TIMEOUT=60 test-native-gui"
    ) in linux
    assert "make devcontainer" in linux

    macos = _parsed("macos.yml")["jobs"]
    assert macos["native-gui"]["runs-on"] == "macos-15"
    reader = next(step for step in macos["tests"]["steps"] if step.get("name") == "Build the native header reader")
    steps = macos["native-gui"]["steps"]
    suite = next(index for index, step in enumerate(steps) if "test-native-gui" in step.get("run", ""))
    assert reader in steps[:suite], "the reader builds before the suite"
    assert steps[suite] == {
        "run": "nix develop --command make NIX= PYTEST_WORKERS=3 BTRC_TEST_TRANSPILE_TIMEOUT=600 "
        "BTRC_TEST_RUN_TIMEOUT=60 test-native-gui",
        "env": {"PYTEST_ADDOPTS": "--junitxml=build/junit/native-gui.xml"},
    }

    # Each keeps its JUnit results, then (the skip-report contract) its skip report.
    for workflow, stem in (("ci.yml", "ci"), ("macos.yml", "macos")):
        junit = _parsed(workflow)["jobs"]["native-gui"]["steps"][-2]
        assert junit["if"] == "always()", workflow
        assert junit["with"]["name"] == f"junit-{stem}-native-gui", workflow
        assert junit["with"]["path"] == "build/junit/native-gui.xml", workflow


def test_mobile_host_workflows_wait_for_their_tooling_and_run_every_slice() -> None:
    # Claude writes the mobile host workflows Codex requested (D28). Each lands
    # before its host directory, so a guard job skips the device job on a
    # revision without the tooling instead of failing main.
    for workflow, tool in (("host-ios.yml", "ios/spike.py"), ("host-android.yml", "android/check.py")):
        jobs = _parsed(workflow)["jobs"]
        assert f"tools/target_hosts/{tool}" in _code(_job(_workflow(workflow), "tooling")), workflow
        device = next(name for name in jobs if name != "tooling")
        assert jobs[device]["needs"] == "tooling", workflow
        assert jobs[device]["if"] == "needs.tooling.outputs.present == 'true'", workflow
        # Steps pipe into tee, so the job runs bash with pipefail.
        assert jobs[device]["defaults"] == {"run": {"shell": "bash"}}, workflow
        final = jobs[device]["steps"][-1]
        assert final["if"] == "always()" and final["uses"] == UPLOAD_ARTIFACT, workflow

    ios = _code(_job(_workflow("host-ios.yml"), "simulator"))
    assert "python3 -m unittest tools.target_hosts.ios.test_executor -v" in ios
    for device in ("iphone", "ipad"):
        for mode in ("spawn", "app"):
            assert f"--device-class {device} --mode {mode}" in ios, (device, mode)

    # CX-P1-05's request: sdkmanager installs exactly the pinned package list,
    # and the installed revisions are verified rather than trusted.
    android = _code(_job(_workflow("host-android.yml"), "emulator"))
    assert "python3 -m tools.target_hosts.android.sdk packages | tee build/android-sdk-packages.txt" in android
    assert '"$sdkmanager" --install "${packages[@]}"' in android
    assert 'python3 -m tools.target_hosts.android.sdk verify --sdk "$ANDROID_SDK_ROOT"' in android
    assert "nix/android-repo-overlay.json" in android
    assert ".#platforms" not in android
    assert _parsed("host-android.yml")["jobs"]["emulator"]["strategy"]["matrix"]["api"] == ["29", "36"]


def test_the_linux_gui_shard_runs_each_session_and_keeps_its_evidence() -> None:
    """CL-UIA-11: the GUI and audio suites under X11 and Wayland, on every push."""

    job = _parsed("ci.yml")["jobs"]["linux-gui"]
    assert job["name"] == "linux-gui (${{ matrix.session }})"
    assert job["runs-on"] == "ubuntu-latest"
    rows = [shard.row for shard in TIERS.shards if shard.job == "ci.yml/linux-gui"]
    # X11 gates; Wayland reports only until its sanitized shell journey is stable.
    assert rows == [{"session": "x11", "report_only": "false"}, {"session": "wayland", "report_only": "true"}]
    assert job["continue-on-error"] == "${{ matrix.report_only == 'true' }}"
    for tier in ("main", "extended", "release", "native-gui"):
        plan = TIERS.plan("ci.yml", tier)
        assert plan["matrix"]["linux-gui"]["include"] == rows, tier
    assert "linux-gui" not in TIERS.plan("ci.yml", "docs")["jobs"]
    assert "linux-gui" not in TIERS.plan("ci.yml", "pr", ["src/stdlib/GUI/MacOS/Window.btrc"])["jobs"]
    assert "linux-gui" in TIERS.plan("ci.yml", "pr", ["src/stdlib/Audio/Linux/Alsa.btrc"])["jobs"]
    for macos_only in (
        "src/tests/native/audio/CoreAudioDevice.btrc",
        "src/tests/native/gui/MacOSTextFieldConformance.btrc",
        "src/tests/python/test_native_gui_appkit.py",
        "src/tests/python/test_native_ui_shell_macos.py",
        "src/tests/python/test_native_objective_c_blocks.py",
    ):
        assert "linux-gui" not in TIERS.plan("ci.yml", "pr", [macos_only])["jobs"], macos_only
    for linux in ("src/stdlib/Image/EncodedImage.btrc", "src/tests/python/test_build_safety.py"):
        assert "linux-gui" in TIERS.plan("ci.yml", "pr", [linux])["jobs"], linux
    # One container run of the shard target per row, with the CI shard budgets.
    commands = _job_commands(job, "ci.yml", "linux-gui")
    for session in ("x11", "wayland"):
        assert (
            'podman run --rm --init -v "$PWD:/workspace" btrc-devcontainer:latest make NIX= PYTEST_WORKERS=4 '
            f"BTRC_TEST_TRANSPILE_TIMEOUT=600 BTRC_TEST_RUN_TIMEOUT=60 GUI_SESSION={session} test-shard-gui"
        ) in commands
    steps = job["steps"]
    evidence, junit, skips = steps[-3:]
    assert all(step["if"] == "always()" and step["uses"] == UPLOAD_ARTIFACT for step in (evidence, junit, skips))
    assert evidence["with"]["name"] == "gui-evidence-ci-linux-gui-${{ matrix.session }}"
    for path in ("build/linux-gui/${{ matrix.session }}/atspi.json", "build/ui-shell/"):
        assert path in evidence["with"]["path"], path
    assert junit["with"]["name"] == "junit-ci-linux-gui-${{ matrix.session }}"
    assert junit["with"]["path"] == "build/linux-gui/${{ matrix.session }}/junit.xml"
    # The make target runs the focused GUI suites plus the null-PCM check in one
    # headless session per protocol, with the null PCM, the AT-SPI dump and the
    # skip gate on its own report.
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    recipe = _makefile_recipe(makefile, "test-shard-gui")
    assert "tools/ui/headless-session.sh --$(GUI_SESSION) --" in recipe
    assert 'ALSA_CONFIG_PATH="$(abspath nix/asound.conf)"' in recipe
    assert "python3 tools/ui/status_notifier_watcher.py -- python3 tools/ui/session_evidence.py" in recipe
    assert "tools/ui/session_evidence.py --output $(GUI_SHARD_DIR)" in recipe
    assert "$(GUI_SHARD_TESTS)" in recipe and "--junitxml=$(GUI_SHARD_DIR)/junit.xml" in recipe
    assert "$(SKIP_GATE) build/skip-report-gui-$(GUI_SESSION).json" in recipe
    assert re.search(r"(?m)^GUI_SHARD_TESTS := \$\(NATIVE_GUI_TESTS\) ", makefile)
    assert "test_native_linux_providers.py" in makefile
