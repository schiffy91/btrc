"""Runtime helper graph ordering and schema failures."""

import pytest

from src.compiler.python.ir.gen.helpers import RuntimeHelperRegistry
from src.compiler.python.ir.nodes import IRModule


def test_helper_dependencies_are_materialized_before_consumers():
    registry = RuntimeHelperRegistry()
    registry.use("__btrc_thread_join")
    module = IRModule()
    registry.materialize(module, lambda _header: None)

    positions = {
        helper.name: index for index, helper in enumerate(module.helper_decls)
    }
    for helper in module.helper_decls:
        for dependency in helper.depends_on:
            assert positions[dependency] < positions[helper.name]


def test_helper_graph_rejects_unknown_roots():
    registry = RuntimeHelperRegistry()

    with pytest.raises(ValueError, match="unknown runtime helper"):
        registry.use("__btrc_missing")
