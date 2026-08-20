"""Destroyed-pointer state/query ownership and reachability contracts."""

import pytest

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.application.pipeline import CompilationPipeline, StdlibArchiveAdapter
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.ir.lowering.lowerer import IRLowerer
from src.compiler.python.ir.nodes import (
    CType,
    IRBlock,
    IRCall,
    IRExprStmt,
    IRFunctionDef,
    IRHelperDecl,
    IRModule,
)
from src.compiler.python.ir.optimizer import IROptimizer
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.runtime.catalog import RuntimeHelperCatalog

RUNTIME_CATALOG = RuntimeHelperCatalog()
CYCLES = {helper.name: helper for helper in RUNTIME_CATALOG.definitions_in_category("cycles")}
TRYCATCH = {helper.name: helper for helper in RUNTIME_CATALOG.definitions_in_category("trycatch")}


def _emit_c(source: str) -> str:
    program = Parser(Lexer(source, "<test>").tokenize()).parse()
    analyzed = SemanticAnalyzer().analyze(program)
    assert not analyzed.errors
    pipeline = CompilationPipeline()
    module = pipeline.optimize(IRLowerer(analyzed).lower(), CompilerOptions())
    return pipeline.emit(module)


def _optimized_helper_names(root: str) -> set[str]:
    helper_decls = [IRHelperDecl.from_runtime(definition) for definition in RUNTIME_CATALOG.definitions]
    main = IRFunctionDef(
        name="main",
        return_type=CType(text="void"),
        params=[],
        body=IRBlock(
            stmts=[
                IRExprStmt(
                    expr=IRCall(
                        callee=root,
                        helper_ref=root,
                        args=[],
                    )
                )
            ]
        ),
    )
    module = IROptimizer(
        IRModule(
            function_defs=[main],
            helper_decls=helper_decls,
        )
    ).optimize()
    return {helper.name for helper in module.helper_decls}


def test_destroyed_query_is_separate_from_shared_state():
    state = CYCLES["__btrc_destroyed_tracking"]
    query = CYCLES["__btrc_is_destroyed"]

    assert "__btrc_is_destroyed(" not in state.c_source
    assert "static int __btrc_is_destroyed(" in query.c_source
    assert query.depends_on == (
        "__btrc_destroyed_tracking",
        "__btrc_arc_mutation_lock",
    )
    shared_helpers = StdlibArchiveAdapter.HELPER_NAMES
    assert "__btrc_destroyed_tracking" in shared_helpers
    assert "__btrc_is_destroyed" not in shared_helpers
    assert "__btrc_is_destroyed" not in CYCLES["__btrc_mark_destroyed"].depends_on
    assert "__btrc_is_destroyed" not in CYCLES["__btrc_collect_cycles"].depends_on
    assert "__btrc_is_destroyed" in TRYCATCH["__btrc_run_cleanups"].depends_on


def test_mark_only_helper_dce_omits_destroyed_query():
    names = _optimized_helper_names("__btrc_mark_destroyed")

    assert "__btrc_mark_destroyed" in names
    assert "__btrc_destroyed_tracking" in names
    assert "__btrc_is_destroyed" not in names


@pytest.mark.parametrize(
    "root",
    ("__btrc_is_destroyed", "__btrc_run_cleanups"),
)
def test_query_paths_retain_destroyed_query_through_dce(root: str):
    assert "__btrc_is_destroyed" in _optimized_helper_names(root)


def test_snapshot_collector_does_not_retain_destroyed_query_through_dce():
    names = _optimized_helper_names("__btrc_collect_cycles")

    assert "__btrc_collect_cycles" in names
    assert "__btrc_is_destroyed" not in names
    assert "__btrc_destroyed_tracking" not in names


def test_mark_only_generated_c_omits_destroyed_query():
    c_source = _emit_c("""
        class Leaf { public int value; }
        class Owner {
            public Leaf leaf;
            public Owner(Leaf leaf) { self.leaf = leaf; }
        }
        int main() { Owner owner = new Owner(new Leaf()); return 0; }
    """)

    assert "static void __btrc_mark_destroyed(" in c_source
    assert "static int __btrc_is_destroyed(" not in c_source


def test_snapshot_cycle_generated_c_omits_destroyed_query():
    c_source = _emit_c("""
        class Link {
            public Link next;
            public Link() { self.next = null; }
        }
        int main() { Link link = new Link(); return 0; }
    """)

    assert "static int __btrc_is_destroyed(" not in c_source
    assert "static int __btrc_flush_cycles(" in c_source


def test_exception_cleanup_generated_c_retains_destroyed_query():
    c_source = _emit_c("""
        class Box { public int value; }
        int main() {
            try {
                Box box = new Box();
                throw "boom";
            } catch (string error) {
                return 0;
            }
        }
    """)

    assert "static int __btrc_is_destroyed(" in c_source
    assert "static inline void __btrc_run_cleanups(" in c_source
