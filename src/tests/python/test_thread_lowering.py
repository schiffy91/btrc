"""Focused contracts for pthread wrapper lowering and runtime dependencies."""

import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
from src.compiler.python.ir.emitter import CEmitter
from src.compiler.python.ir.gen.generator import IRGenerator
from src.compiler.python.ir.nodes import (
    IRCall,
    IRCast,
    IRFunctionRef,
    IRLiteral,
    IRTernary,
)
from src.compiler.python.ir.optimizer import optimize
from src.compiler.python.ir.optimizer_walk import iter_ir_nodes
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.tests.python.test_codegen import emit_c

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def _generate_ir(source: str):
    analyzed = _analyze(source)
    assert not analyzed.errors
    return IRGenerator(analyzed).generate()


def _analyze(source: str):
    program = Parser(Lexer(source, "<thread-lowering>").tokenize()).parse()
    return SemanticAnalyzer().analyze(program)


def _spawn_calls(module):
    return [node for node in iter_ir_nodes(module) if isinstance(node, IRCall) and node.callee == "__btrc_thread_spawn"]


def test_thread_only_program_includes_transitive_try_state_header():
    source = """
        int main() {
            Thread<int> thread = spawn(() => { return 7; });
            return thread.join() == 7 ? 0 : 1;
        }
    """

    generated = emit_c(source)

    assert "try" not in source
    assert "#include <pthread.h>" in generated
    assert "#include <setjmp.h>" in generated
    assert "jmp_buf" in generated


def test_spawn_is_an_ordinary_call_with_structured_dynamic_entry():
    module = _generate_ir("""
        extern void* first(void* arg);
        extern void* second(void* arg);
        int main() {
            __fn_ptr<void*, void*> left = first;
            __fn_ptr<void*, void*> right = second;
            bool choose = false;
            var thread = spawn(choose ? left : right);
            thread.join();
            return 0;
        }
    """)

    [spawn] = _spawn_calls(module)
    assert spawn.helper_ref == "__btrc_thread_spawn"
    (
        entry,
        capture,
        arg_disposer,
        context,
        context_size,
        disposer,
        result_raise,
    ) = spawn.args
    assert isinstance(entry, IRCast)
    assert entry.target_type.text == "void*(*)(void*)"
    assert isinstance(entry.expr, IRTernary)
    assert capture == IRLiteral(text="NULL")
    assert arg_disposer == IRLiteral(text="NULL")
    assert context == IRLiteral(text="NULL")
    assert context_size == IRLiteral(text="0")
    assert disposer == IRLiteral(text="NULL")
    assert result_raise == IRLiteral(text="NULL")


def test_spawn_call_drives_helper_and_wrapper_reachability():
    module = optimize(
        _generate_ir("""
        int main() {
            int captured = 41;
            var thread = spawn(() => captured + 1);
            return thread.join() == 42 ? 0 : 1;
        }
    """)
    )

    assert _spawn_calls(module)
    assert any(function.name.startswith("__btrc_spawn_wrapper_") for function in module.function_defs)
    helpers = {helper.name for helper in module.helper_decls}
    assert "__btrc_thread_spawn" in helpers
    assert "__btrc_launder_state" in helpers
    # Every worker has a final ARC drain, even when this particular lambda
    # captures no managed value. Cleanup failures are guarded in the worker
    # and transferred through the generic caller-thread raise callback.
    assert "__btrc_arc_thread_state_cleanup" in helpers
    assert "__btrc_arc_guard_hook" in helpers
    assert "__btrc_throw" in helpers
    assert "__btrc_suspect_state" in helpers
    assert "__btrc_launder" not in helpers


def test_managed_capture_disposer_retains_structured_raise_callback():
    module = optimize(
        _generate_ir("""
        class Item {}
        int main() {
            Item captured = new Item();
            var thread = spawn(() => captured == null ? 0 : 1);
            return thread.join() == 1 ? 0 : 1;
        }
    """)
    )

    disposer = next(
        function for function in module.function_defs if function.name.startswith("__btrc_spawn_env_dispose_")
    )
    raise_call = next(
        node
        for node in iter_ir_nodes(disposer.body)
        if isinstance(node, IRCall) and node.callee == "__btrc_raise_captured"
    )
    assert isinstance(raise_call.args[0], IRFunctionRef)
    assert raise_call.args[0].name == "__btrc_throw"
    assert "__btrc_throw" in {helper.name for helper in module.helper_decls}
    assert "static _Noreturn void __btrc_throw(const char* msg)" in CEmitter().emit(module)


@pytest.mark.parametrize(
    "copy",
    [
        "Thread<int> alias = worker;",
        "Thread<int> alias = spawn(() => 8); alias = worker;",
    ],
)
def test_thread_handle_lvalue_copy_is_rejected(copy):
    analyzed = _analyze(f"""
        int main() {{
            Thread<int> worker = spawn(() => 7);
            {copy}
            return 0;
        }}
    """)

    assert any("Thread handles cannot be copied" in error for error in analyzed.errors)


def test_fresh_thread_ternary_is_a_valid_transfer():
    _generate_ir("""
        int main() {
            bool choose = true;
            var worker = choose ? spawn(() => 7) : spawn(() => 8);
            return worker.join();
        }
    """)


def test_fresh_thread_result_can_be_joined_directly():
    _generate_ir("""
        int main() {
            return spawn(() => 7).join();
        }
    """)


_CAPTURE_SOURCE = """
int main() {
    int captured = 41;
    var thread = spawn(() => captured + 1);
    captured = 0;
    return thread.join() == 42 ? 0 : 1;
}
"""

_DYNAMIC_FNPTR_SOURCE = """
extern int marker;
extern void* first(void* arg);
extern void* second(void* arg);

int main() {
    __fn_ptr<void*, void*> left = first;
    __fn_ptr<void*, void*> right = second;
    bool choose = false;
    var thread = spawn(choose ? left : right);
    thread.join();
    return marker == 2 ? 0 : 1;
}
"""

_DYNAMIC_FNPTR_SUPPORT = """
int marker = 0;
void* first(void* arg) { marker = 1; return arg; }
void* second(void* arg) { marker = 2; return arg; }
"""

_ALIASED_FNPTR_SOURCE = """
extern void* echo(void* arg);
typedef __fn_ptr<void*, void*> ThreadEntry;

int main() {
    ThreadEntry entry = echo;
    var thread = spawn(entry);
    return thread.join() == null ? 0 : 1;
}
"""

_ALIASED_FNPTR_SUPPORT = """
void* echo(void* arg) { return arg; }
"""

_ALIASED_THREAD_SOURCE = """
typedef Thread<int> Worker;

Worker launch() {
    Worker worker = spawn(() => 42);
    return worker;
}

int main() {
    Worker worker = launch();
    return worker.join() == 42 ? 0 : 1;
}
"""


@pytest.mark.skipif(not COMPILERS, reason="requires a pthread C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
@pytest.mark.parametrize(
    "source, support",
    [
        pytest.param(_CAPTURE_SOURCE, "", id="lambda-capture"),
        pytest.param(
            _DYNAMIC_FNPTR_SOURCE,
            _DYNAMIC_FNPTR_SUPPORT,
            id="dynamic-function-pointer",
        ),
        pytest.param(
            _ALIASED_FNPTR_SOURCE,
            _ALIASED_FNPTR_SUPPORT,
            id="typedef-function-pointer",
        ),
        pytest.param(
            _ALIASED_THREAD_SOURCE,
            "",
            id="typedef-thread-owner",
        ),
    ],
)
def test_spawn_executes_under_strict_c11(
    tmp_path: Path,
    c_compiler: str,
    source: str,
    support: str,
):
    generated_path = tmp_path / "spawn.c"
    generated_path.write_text(emit_c(source))
    inputs = [str(generated_path)]
    if support:
        support_path = tmp_path / "spawn_support.c"
        support_path.write_text(support)
        inputs.append(str(support_path))
    executable = tmp_path / "spawn"

    subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror=implicit-function-declaration",
            "-O1",
            *inputs,
            "-pthread",
            "-lm",
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=90,
    )
    subprocess.run(
        [str(executable)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
