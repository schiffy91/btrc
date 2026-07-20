"""Destructor hooks cannot short-circuit terminal object finalization."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.tests.btrc.test_mutex_value_contract import (
    _compile_pair,
    _strict_matrix,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

FIXTURE = Path(__file__).with_name("fixtures") / "destructor_hook_isolation_runtime.btrc"
FUNCTION_START = re.compile(r"(?m)^(?:static\s+)?void\s+([A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{")
FUNCTION_END = re.compile(r"(?m)^}")


def _void_function_bodies(generated: str) -> dict[str, str]:
    """Extract the generated void functions needed by this focused contract."""
    functions = {}
    for match in FUNCTION_START.finditer(generated):
        end = FUNCTION_END.search(generated, match.end())
        assert end is not None, f"unterminated generated function {match.group(1)}"
        functions[match.group(1)] = generated[match.end() : end.start()]
    return functions


def _detach_position(body: str, field: str) -> int:
    field_expr = rf"self\s*->\s*{field}"
    patterns = (
        rf"__btrc_arc_replace_edge\([^;]*{field_expr}[^;]*NULL",
        rf"{field_expr}\s*=\s*NULL",
    )
    positions = [match.start() for pattern in patterns if (match := re.search(pattern, body, re.S))]
    assert positions, f"terminal destructor does not detach owned field {field!r}:\n{body}"
    return min(positions)


def _assert_isolated_finalizer(generated: str, hook_counter: str) -> None:
    functions = _void_function_bodies(generated)
    hooks = {
        name: body
        for name, body in functions.items()
        if hook_counter in body and not re.search(r"\bfree\s*\(\s*self\s*\)", body)
    }
    assert len(hooks) == 1, f"expected one isolated source destructor hook for {hook_counter}, found {sorted(hooks)}"
    hook_name, hook_body = next(iter(hooks.items()))
    assert re.search(r"\breturn\s*;", hook_body), hook_body

    terminal = {
        name: body
        for name, body in functions.items()
        if name.endswith("_destroy")
        and re.search(r"\bfree\s*\(\s*self\s*\)", body)
        and re.search(r"self\s*->\s*first", body)
        and re.search(r"self\s*->\s*second", body)
        and re.search(rf"\b{re.escape(hook_name)}\s*\(", body)
    }
    assert len(terminal) == 1, (
        f"expected one terminal destructor to call {hook_name} and finalize two fields, found {sorted(terminal)}"
    )
    terminal_body = next(iter(terminal.values()))
    hook_call = re.search(rf"\b{re.escape(hook_name)}\s*\(", terminal_body)
    terminal_free = re.search(r"\bfree\s*\(\s*self\s*\)", terminal_body)
    assert hook_call is not None and terminal_free is not None
    first_detach = _detach_position(terminal_body, "first")
    second_detach = _detach_position(terminal_body, "second")
    assert hook_call.start() < first_detach < terminal_free.start()
    assert hook_call.start() < second_detach < terminal_free.start()


@pytest.fixture(scope="module")
def compiled_lifecycle_contract(
    semantic_btrcc: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, tuple[tuple[str, Path], ...]]:
    output = tmp_path_factory.mktemp("destructor-hook-isolation")
    compiled = _compile_pair(
        semantic_btrcc,
        output,
        FIXTURE.read_text(),
        "destructor-hook-isolation",
    )
    return output, compiled


def test_source_destructor_return_is_isolated_from_terminal_finalization(
    compiled_lifecycle_contract: tuple[Path, tuple[tuple[str, Path], ...]],
) -> None:
    _, compiled = compiled_lifecycle_contract
    for _, generated in compiled:
        source = generated.read_text()
        _assert_isolated_finalizer(source, "ordinaryHookCalls")
        _assert_isolated_finalizer(source, "genericHookCalls")


def test_destructor_hook_return_preserves_explicit_and_scope_cleanup(
    compiled_lifecycle_contract: tuple[Path, tuple[tuple[str, Path], ...]],
) -> None:
    output, compiled = compiled_lifecycle_contract
    for artifact in compiled:
        _strict_matrix(artifact, output)
