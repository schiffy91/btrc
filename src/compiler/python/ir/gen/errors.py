"""IR generation errors."""


class CodegenError(RuntimeError):
    """Raised when analyzed AST cannot be lowered to IR."""


def unsupported_node(phase: str, node) -> CodegenError:
    return CodegenError(f"unsupported {phase} node: {type(node).__name__}")
