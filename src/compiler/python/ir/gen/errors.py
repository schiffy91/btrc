"""IR generation errors."""


class CodegenError(RuntimeError):
    """Raised when analyzed AST cannot be lowered to IR."""


class TypedOperatorError(CodegenError):
    """A concrete operator specialization has no portable lowering."""


def unsupported_node(phase: str, node) -> CodegenError:
    return CodegenError(f"unsupported {phase} node: {type(node).__name__}")
