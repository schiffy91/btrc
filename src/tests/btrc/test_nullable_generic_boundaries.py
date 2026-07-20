"""Nullable generic storage boundaries remain injective through C lowering."""

import re
from pathlib import Path

from src.tests.btrc.production_readiness_harness import (
    compile_fixture_pair,
    run_strict_pair,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

FIXTURES = Path(__file__).with_name("fixtures")


def test_generic_call_operand_result_property_array_and_typedef_boundaries(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_fixture_pair(
        semantic_btrcc,
        tmp_path,
        FIXTURES / "nullable_generic_call_boundary_runtime.btrc",
    )
    for _frontend, generated in compiled:
        source = generated.read_text()
        assert "RawPointer alias" in source
        assert "RawPointer* alias" not in source
        for alias, variable in (
            ("TextAlias", "textAlias"),
            ("IntArray", "arrayAlias"),
            ("CallbackAlias", "callbackAlias"),
            ("ItemAlias", "itemAlias"),
        ):
            assert f"{alias} {variable}" in source
            assert f"{alias}* {variable}" not in source
        assert re.search(r"char\* text = NULL;", source)
        assert re.search(r"char\*\* textSlot = NULL;", source)
        assert re.search(r"int\*\*\s+__btrc_(?:call_)?(?:operand|result)_", source)
        assert re.search(r"int\*\*\*\s+__btrc_(?:call_)?operand_", source)
    run_strict_pair(compiled, tmp_path)


def test_nested_generic_nullable_identity_is_distinct_and_runs_strictly(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_fixture_pair(
        semantic_btrcc,
        tmp_path,
        FIXTURES / "nullable_nested_generic_identity_runtime.btrc",
    )
    for _frontend, generated in compiled:
        source = generated.read_text()
        inner_structs = re.findall(
            r"struct (btrc_[A-Za-z0-9_]+) \{\n\s+__btrc_arc_header __arc;\n\s+int\*+ stored;",
            source,
        )
        assert len(set(inner_structs)) == 2
    run_strict_pair(compiled, tmp_path)
