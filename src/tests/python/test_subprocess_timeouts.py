"""Every subprocess a test or test tool waits on has a wall-clock limit.

An untimed ``subprocess.run`` turns a hung child -- a deadlocked program, a
tool waiting on a terminal -- into a stalled suite with no diagnostic. The
limits live in ``src/tests/process_limits.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CHECKED_ROOTS = ("src/tests", "tools/compiler_codegen", "tools/bench")
WAITING_CALLS = frozenset({"run", "check_output", "check_call", "call"})
# Owned by the tools-ci lane in the Stage 4 campaign; its two `make --dry-run`
# probes get their limits there.
PENDING = frozenset({"src/tests/python/test_build_safety.py"})


def _sources() -> list[Path]:
    return sorted(
        path
        for root in CHECKED_ROOTS
        for path in (REPO / root).rglob("*.py")
        if "__pycache__" not in path.parts and path.relative_to(REPO).as_posix() not in PENDING
    )


def _untimed_calls(source: str, filename: str) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in WAITING_CALLS:
            continue
        if not isinstance(node.func.value, ast.Name) or node.func.value.id != "subprocess":
            continue
        if any(keyword.arg in {"timeout", None} for keyword in node.keywords):
            continue
        lines.append(node.lineno)
    return lines


def test_the_audit_recognizes_untimed_and_timed_calls() -> None:
    source = (
        "import subprocess\n"
        "subprocess.run(['a'])\n"
        "subprocess.run(['b'], timeout=1)\n"
        "subprocess.check_output(['c'], **options)\n"
        "subprocess.check_call(['d'])\n"
    )

    assert _untimed_calls(source, "probe.py") == [2, 5]


def test_every_waited_subprocess_has_a_timeout() -> None:
    untimed = [
        f"{path.relative_to(REPO).as_posix()}:{line}"
        for path in _sources()
        for line in _untimed_calls(path.read_text(encoding="utf-8"), str(path))
    ]

    assert untimed == []
