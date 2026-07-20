"""Self-host/reference parity for typedef-based member dispatch and ARC."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tests.btrc.test_ownership_semantics_contract import _compile_reference_source
from src.tests.btrc.test_semantic_validation import _compile_source, _strict_build_and_run

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

FIXTURE = Path(__file__).with_name("fixtures") / "typedef_member_alias_runtime.btrc"


def test_alias_member_dispatch_and_scope_cleanup_have_runtime_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = FIXTURE.read_text()
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = _compile_reference_source(tmp_path, source)

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    reference_c = reference_source.read_text()
    assert "BoxAlias box = Box_new(10);" in reference_c
    assert "CellAlias cell = btrc_Cell_int_new(5);" in reference_c
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-typedef-members")
    _strict_build_and_run(reference_source, tmp_path / "reference-typedef-members")


@pytest.mark.parametrize(
    ("source", "diagnostic"),
    (
        (
            "class Vault { private int secret; } typedef Vault Alias; int read(Alias value) { return value.secret; }",
            "private field 'secret'",
        ),
        (
            "class Vault { private int secret { get; set; } } typedef Vault Alias; "
            "int read(Alias value) { return value.secret; }",
            "private property 'secret'",
        ),
        (
            "class Accessors { public int readOnly { get; } } typedef Accessors Alias; "
            "void write(Alias value) { value.readOnly = 1; }",
            "has no setter",
        ),
        (
            "class Accessors { public int writeOnly { set; } } typedef Accessors Alias; "
            "int read(Alias value) { return value.writeOnly; }",
            "has no getter",
        ),
        (
            "class Accessors { public int writeOnly { set; } } typedef Accessors Alias; "
            "void update(Alias value) { value.writeOnly += 1; }",
            "has no getter",
        ),
        (
            "class Slots { public int get(string key) { return 0; } } typedef Slots Alias; "
            "int read(Alias value) { return value[1]; }",
            "string",
        ),
        (
            "class Vault { private int reveal() { return 1; } } typedef Vault Alias; "
            "int read(Alias value) { return value.reveal(); }",
            "private method 'reveal'",
        ),
    ),
)
def test_alias_member_diagnostics_have_compiler_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    diagnostic: str,
) -> None:
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)

    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert diagnostic in selfhost.stderr.lower()
    assert diagnostic in reference.stderr.lower()
