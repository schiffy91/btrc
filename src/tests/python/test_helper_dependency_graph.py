"""Runtime helper graph ordering and schema failures."""

import pytest

from src.compiler.python.ir.nodes import IRHelperDecl, IRModule
from src.compiler.python.runtime.catalog import RuntimeHelperCatalog


def test_helper_dependencies_are_materialized_before_consumers():
    selection = RuntimeHelperCatalog().selection()
    selection.use("__btrc_thread_join")
    module = IRModule(helper_decls=[IRHelperDecl.from_runtime(definition) for definition in selection.definitions()])

    positions = {helper.name: index for index, helper in enumerate(module.helper_decls)}
    for helper in module.helper_decls:
        for dependency in helper.depends_on:
            assert positions[dependency] < positions[helper.name]


def test_helper_graph_rejects_unknown_roots():
    selection = RuntimeHelperCatalog().selection()

    with pytest.raises(ValueError, match="unknown runtime helper"):
        selection.use("__btrc_missing")
