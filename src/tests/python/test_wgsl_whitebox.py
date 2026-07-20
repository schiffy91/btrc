"""White-box tests for typed WGSL statement and expression emission."""

import re

from src.compiler.python.ast_nodes import FunctionDecl, TypeExpr
from src.compiler.python.ir.gen.gpu_wgsl import WgslEmitter, btrc_type_to_wgsl
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def test_btrc_type_to_wgsl():
    assert btrc_type_to_wgsl(None) == "void"
    assert btrc_type_to_wgsl(TypeExpr(base="float")) == "f32"
    arr = TypeExpr(base="float", is_array=True)
    assert btrc_type_to_wgsl(arr) == "array<f32>"


def test_emit_block_none_is_empty():
    assert WgslEmitter(array_params=[]).emit_block(None) == ""


def test_emit_kernel_body_all_forms():
    src = """
    @gpu
    void k(float[] xs, int n) {
        int i = gpu_id();
        int u;
        float f = 1.0;
        bool b = f > 0.0;
        int neg = -i;
        xs[i] += f;
        for (i = 0; i < n; i = i + 1) { xs[i] = abs(f); }
        if (b) { xs[i] = 0.0; } else { xs[i] = 1.0; }
    }
    int main() { return 0; }
    """
    prog = Parser(Lexer(src, "<t>").tokenize()).parse()
    kern = next(d for d in prog.declarations if isinstance(d, FunctionDecl) and d.name == "k")
    emitter = WgslEmitter(
        array_params=["xs"],
        has_output=False,
        uniform_params=["n"],
        array_lengths={"xs": "btrc_len_0"},
    )
    wgsl = emitter.emit_block(kern.body)
    assert "var" in wgsl
    assert "loop {" in wgsl
    assert re.search(r"xs\[btrc_e_\d+\] \+= btrc_v_\d+;", wgsl)
    assert "xs[i] xs[i]" not in wgsl
