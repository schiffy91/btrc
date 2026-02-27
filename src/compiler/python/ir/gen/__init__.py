"""IR generation package: AST → structured IR lowering."""

from ...analyzer import AnalyzedProgram
from ..nodes import IRModule
from .generator import IRGenerator


def generate_ir(analyzed: AnalyzedProgram, *,
                debug: bool = False, source_file: str = "") -> IRModule:
    """Generate an IR module from an analyzed program.

    This is the main entry point for the IR generation pipeline.
    """
    gen = IRGenerator(analyzed, debug=debug, source_file=source_file)
    return gen.generate()


__all__ = ["generate_ir", "IRGenerator"]
