"""Runtime helper graph ordering and schema failures."""

from types import SimpleNamespace

import pytest

from src.compiler.python.ir.gen.helpers import collect_helpers
from src.compiler.python.ir.nodes import IRModule


def _generator(*roots: str):
    return SimpleNamespace(
        _used_helpers=set(roots),
        module=IRModule(),
        require_runtime_include=lambda _header: None,
    )


def test_helper_dependencies_are_materialized_before_consumers():
    generator = _generator("__btrc_thread_join")

    collect_helpers(generator)

    positions = {helper.name: index for index, helper in enumerate(generator.module.helper_decls)}
    for helper in generator.module.helper_decls:
        for dependency in helper.depends_on:
            assert positions[dependency] < positions[helper.name]


def test_helper_graph_rejects_unknown_roots():
    generator = _generator("__btrc_missing")

    with pytest.raises(ValueError, match="unknown runtime helper"):
        collect_helpers(generator)
