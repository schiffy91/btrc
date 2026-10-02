"""Run snippets through the reference compiler's stages in process: analysis, IR and emitted C."""

from __future__ import annotations

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.application.pipeline import CompilationPipeline
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.ir.lowering.lowerer import IRLowerer
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def emit_c(source: str) -> str:
    """Run the full pipeline on a self-contained snippet, return emitted C.

    No stdlib is auto-included, so the output is exactly what the snippet
    lowers to -- which keeps these assertions precise and fast.
    """
    tokens = Lexer(source, "<test>").tokenize()
    program = Parser(tokens).parse()
    analyzed = SemanticAnalyzer().analyze(program)
    assert not analyzed.errors, f"analyzer errors: {analyzed.errors}"
    ir_module = IRLowerer(analyzed).lower()
    pipeline = CompilationPipeline()
    ir_module = pipeline.optimize(ir_module, CompilerOptions())
    return pipeline.emit(ir_module)


def analyze(source: str):
    tokens = Lexer(source).tokenize()
    program = Parser(tokens).parse()
    analyzer = SemanticAnalyzer()
    return analyzer.analyze(program)


def analyze_realtime(source: str):
    program = Parser(Lexer(source, "realtime-test.btrc").tokenize()).parse()
    return program, SemanticAnalyzer().analyze(program)


def realtime_errors(source: str) -> list[str]:
    return [error for error in analyze_realtime(source)[1].errors if "@realtime" in error]


def lower_gpu_dispatch(source: str):
    program = Parser(Lexer(source, "<gpu-dispatch-ir>").tokenize()).parse()
    analyzed = SemanticAnalyzer().analyze(program)
    assert not analyzed.errors
    return IRLowerer(analyzed).lower()


def emit_ownership_c(source: str) -> str:
    program = Parser(Lexer(source, "<arc-ownership>").tokenize()).parse()
    analyzed = SemanticAnalyzer().analyze(program)
    assert analyzed.errors == []
    pipeline = CompilationPipeline()
    module = pipeline.optimize(IRLowerer(analyzed).lower(), CompilerOptions())
    return pipeline.emit(module)
