"""Parser assembly: combines all parsing mixins into the final Parser class."""

from .core import ParserBase, ParseError
from .types import TypesMixin
from .declarations import DeclarationsMixin
from .decl_simple import SimpleDeclarationsMixin
from .statements import StatementsMixin
from .control_flow import ControlFlowMixin
from .expressions import ExpressionsMixin
from .postfix import PostfixMixin
from .primary import PrimaryMixin
from .lambdas import LambdasMixin


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


__all__ = ["Parser", "ParseError"]
