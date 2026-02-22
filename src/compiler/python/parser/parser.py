"""Parser assembly: combines all parsing mixins into the final Parser class."""

from .control_flow import ControlFlowMixin
from .core import ParseError, ParserBase
from .decl_simple import SimpleDeclarationsMixin
from .declarations import DeclarationsMixin
from .expressions import ExpressionsMixin
from .lambdas import LambdasMixin
from .postfix import PostfixMixin
from .primary import PrimaryMixin
from .statements import StatementsMixin
from .types import TypesMixin


class Parser(
    LambdasMixin,
    PrimaryMixin,
    PostfixMixin,
    ExpressionsMixin,
    ControlFlowMixin,
    StatementsMixin,
    SimpleDeclarationsMixin,
    DeclarationsMixin,
    TypesMixin,
    ParserBase,
):
    """Recursive descent parser for the btrc language."""
    pass


__all__ = ["ParseError", "Parser"]
