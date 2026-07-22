"""A source method named ``free`` is never an implicit lifecycle hook."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from src.tests.btrc.test_mutex_value_contract import (
    COMPILERS,
    REPO,
    _compile_pair,
    _strict_matrix,
)
from src.tests.btrc.test_semantic_validation import _compile_source

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

FIXTURES = Path(__file__).with_name("fixtures")
GENERIC_FIXTURE = FIXTURES / "generic_free_lifecycle_runtime.btrc"
COLLECTION_FIXTURE = FIXTURES / "collection_explicit_free_then_scope_runtime.btrc"

pytestmark = pytest.mark.skipif(
    not COMPILERS,
    reason="requires GCC or Clang with strict C11 support",
)


def _function_body(generated: str, name: str) -> str:
    signature = re.search(
        rf"\bvoid\s+{re.escape(name)}\s*\([^;{{}}]*\)\s*\{{",
        generated,
    )
    assert signature is not None, f"missing generated function {name}"
    opening = signature.end() - 1
    depth = 1
    cursor = opening + 1
    while cursor < len(generated) and depth:
        if generated[cursor] == "{":
            depth += 1
        elif generated[cursor] == "}":
            depth -= 1
        cursor += 1
    assert depth == 0, f"unterminated generated function {name}"
    return generated[opening + 1 : cursor - 1]


def _pool_destroy(generated: str) -> tuple[str, str]:
    candidates = []
    seen = set()
    for match in re.finditer(
        r"\bvoid\s+([A-Za-z_]\w*_destroy)\s*\(\s*void\s*\*\s*object\s*\)",
        generated,
    ):
        name = match.group(1)
        if name in seen:
            continue
        seen.add(name)
        body = _function_body(generated, name)
        if "Pool" in name:
            candidates.append((name, body))
    assert len(candidates) == 1, (
        f"expected exactly one generic Pool terminal destructor, found {[name for name, _ in candidates]}"
    )
    return candidates[0]


def _assert_pool_terminal_contract(generated: str) -> None:
    destroy_name, body = _pool_destroy(generated)
    free_method = f"{destroy_name.removesuffix('_destroy')}_free"

    assert not re.search(rf"\b{re.escape(free_method)}\s*\(", body), (
        f"ordinary method {free_method} was called from {destroy_name}:\n{body}"
    )
    detached = re.search(
        r"__btrc_arc_replace_edge\s*\([^;]*self\s*->\s*item[^;]*NULL",
        body,
        re.S,
    ) or re.search(r"self\s*->\s*item\s*=\s*NULL", body)
    assert detached is not None, f"{destroy_name} must detach its managed item before terminal free:\n{body}"
    assert re.search(r"(?<!\w)free\s*\(\s*self\s*\)", body), body
    direct_marker_call = re.search(
        rf"\b{re.escape(free_method)}\s*\([^;]*,\s*73\s*\)",
        generated,
    )
    temp_marker_call = re.search(
        rf"(\w+)\s*=\s*73[^;]*\b{re.escape(free_method)}\s*\([^;]*,\s*\1\s*\)",
        generated,
        re.S,
    )
    assert direct_marker_call or temp_marker_call, "the explicit source call to Pool.free(73) was not emitted"


@pytest.fixture(scope="module")
def compiled_generic_contract(
    semantic_btrcc: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, tuple[tuple[str, Path], ...]]:
    output = tmp_path_factory.mktemp("generic-free-lifecycle")
    compiled = _compile_pair(
        semantic_btrcc,
        output,
        GENERIC_FIXTURE.read_text(),
        "generic-free-lifecycle",
    )
    return output, compiled


def test_generic_terminal_ignores_ordinary_free_method(
    compiled_generic_contract: tuple[Path, tuple[tuple[str, Path], ...]],
) -> None:
    _, compiled = compiled_generic_contract
    for _, generated in compiled:
        _assert_pool_terminal_contract(generated.read_text())


def test_generic_free_lifecycle_runs_strictly_through_both_compilers(
    compiled_generic_contract: tuple[Path, tuple[tuple[str, Path], ...]],
) -> None:
    output, compiled = compiled_generic_contract
    for artifact in compiled:
        _strict_matrix(artifact, output)


def _compile_reference_with_stdlib(
    tmp_path: Path,
    source: str,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    program = tmp_path / "collection-explicit-free.btrc"
    generated = tmp_path / "collection-explicit-free.reference.c"
    program.write_text(source)
    result = subprocess.run(
        [
            "python3",
            "-m",
            "src.compiler.python.main",
            str(program),
            "--no-cache",
            "-o",
            str(generated),
        ],
        cwd=REPO,
        env={**os.environ, "BTRC_CACHE_DIR": str(tmp_path / "collection-cache")},
        capture_output=True,
        text=True,
        timeout=180,
    )
    return result, generated


@pytest.fixture(scope="module")
def compiled_collection_contract(
    semantic_btrcc: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, tuple[tuple[str, Path], ...]]:
    output = tmp_path_factory.mktemp("collection-explicit-free")
    source = COLLECTION_FIXTURE.read_text()
    selfhost, selfhost_source = _compile_source(
        semantic_btrcc,
        output,
        source,
        no_stdlib=False,
    )
    reference, reference_source = _compile_reference_with_stdlib(output, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    return output, (
        ("selfhost-collections", selfhost_source),
        ("reference-collections", reference_source),
    )


def test_explicit_free_then_scope_is_safe_for_all_stdlib_collections(
    compiled_collection_contract: tuple[Path, tuple[tuple[str, Path], ...]],
) -> None:
    output, compiled = compiled_collection_contract
    for artifact in compiled:
        _strict_matrix(artifact, output)
