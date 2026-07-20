"""White-box contracts for structured GPU dispatch helper IR."""

import re

from src.compiler.python.analyzer.analyzer import Analyzer
from src.compiler.python.ir.gen.generator import IRGenerator
from src.compiler.python.ir.nodes import (
    IRCall,
    IRFor,
    IRIf,
    IRStructDef,
)
from src.compiler.python.ir.optimizer import optimize
from src.compiler.python.ir.optimizer_walk import iter_ir_nodes
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _generate(source: str):
    program = Parser(Lexer(source, "<gpu-dispatch-ir>").tokenize()).parse()
    analyzed = Analyzer().analyze(program)
    assert not analyzed.errors
    return IRGenerator(analyzed).generate()


def test_dispatch_helper_contains_only_ordinary_control_and_call_nodes():
    module = _generate("""
        @gpu
        void scale(float factor, int[] values) {
            int i = gpu_id();
            values[i] *= (int)factor;
        }
        int main() {
            int[] values = {1, 2};
            scale(2.0, values);
            return 0;
        }
    """)

    [helper] = [function for function in module.function_defs if function.name.startswith("__gpu_dispatch_")]
    assert helper.is_static
    assert [parameter.name for parameter in helper.params] == [
        "factor",
        "values",
        "__gpu_len_values",
    ]
    nodes = list(iter_ir_nodes(helper.body))
    assert any(isinstance(node, IRIf) for node in nodes)
    assert any(isinstance(node, IRFor) for node in nodes)
    assert {node.callee for node in nodes if isinstance(node, IRCall) and isinstance(node.callee, str)} >= {
        "btrc_gpu_create_buffer",
        "btrc_gpu_dispatch",
        "btrc_gpu_read_buffer_checked",
        "scale__gpucpu",
    }
    assert any(
        isinstance(struct, IRStructDef) and struct.name.endswith("_uniforms_type") for struct in module.struct_defs
    )


def test_ordinary_call_graph_keeps_dispatch_helper_and_cpu_fallback():
    module = optimize(
        _generate("""
        @gpu
        void bump(int[] values) {
            int i = gpu_id();
            values[i] += 1;
        }
        int dead() { return 99; }
        int main() {
            int[] values = {1};
            bump(values);
            return values[0] == 2 ? 0 : 1;
        }
    """)
    )

    names = {function.name for function in module.function_defs}
    assert "bump__gpucpu" in names
    assert any(name.startswith("__gpu_dispatch_") for name in names)
    assert "dead" not in names


def test_bool_uniform_uses_host_shareable_storage_and_boolean_wgsl_use():
    module = _generate("""
        @gpu
        void choose(float threshold, bool enabled, int bias, int[] values) {
            int i = gpu_id();
            if (enabled) { values[i] = (int)threshold + bias; }
        }
        int main() {
            int[] values = {0};
            choose(2.0, true, 3, values);
            return 0;
        }
    """)

    uniform_struct = next(struct for struct in module.struct_defs if struct.name.endswith("_uniforms_type"))
    assert [(field.name, field.c_type.text) for field in uniform_struct.fields] == [
        ("threshold", "float"),
        ("enabled", "uint32_t"),
        ("bias", "int"),
        ("__gpu_len_values", "int"),
        ("__gpu_off", "int"),
        ("__gpu_n", "int"),
    ]
    [kernel] = module.gpu_kernels
    bool_field = re.search(r"\s+(btrc_p_\d+): u32,", kernel.wgsl_source)
    assert bool_field is not None
    assert f"uniforms.{bool_field.group(1)} != 0u" in kernel.wgsl_source
    assert "enabled:" not in kernel.wgsl_source


def test_gpu_kernel_dce_follows_surviving_dispatch_helper_reference():
    module = _generate("""
        @gpu
        void live(int[] values) {
            int i = gpu_id(); values[i] += 1;
        }
        @gpu
        void dead(int[] values) {
            int i = gpu_id(); values[i] += 2;
        }
        int main() {
            int[] values = {0}; live(values); return 0;
        }
    """)

    assert {kernel.name for kernel in module.gpu_kernels} == {"live", "dead"}
    optimize(module)
    assert [kernel.name for kernel in module.gpu_kernels] == ["live"]


def test_no_dce_retains_unreferenced_gpu_kernel():
    module = _generate("""
        @gpu
        void dormant(int[] values) {
            int i = gpu_id(); values[i] += 1;
        }
        int main() { return 0; }
    """)

    optimize(module, dce=False)

    assert [kernel.name for kernel in module.gpu_kernels] == ["dormant"]
