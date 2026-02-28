"""Analyzer assembly: combines all analysis mixins into the final Analyzer class."""

from .core import (
    AnalyzerBase, AnalyzerError, AnalyzedProgram,
    ClassInfo, InterfaceInfo, Scope, SymbolInfo,
)
from .registration import RegistrationMixin
from .functions import FunctionsMixin
from .statements import StatementsMixin
from .expressions import ExpressionsMixin
from .validation import ValidationMixin
from .type_inference import TypeInferenceMixin
from .type_utils import TypeUtilsMixin


class Analyzer(
    TypeUtilsMixin,
    TypeInferenceMixin,
    ValidationMixin,
    ExpressionsMixin,
    StatementsMixin,
    FunctionsMixin,
    RegistrationMixin,
    AnalyzerBase,
):
    """Semantic analyzer for the btrc language."""
    pass


__all__ = [
    "Analyzer", "AnalyzerError", "AnalyzedProgram",
    "ClassInfo", "InterfaceInfo", "Scope", "SymbolInfo",
]
