"""Analyzer assembly: combines all analysis mixins into the final Analyzer class."""

from .core import (
    AnalyzedProgram,
    AnalyzerBase,
    AnalyzerError,
    ClassInfo,
    InterfaceInfo,
    Scope,
    SymbolInfo,
)
from .expressions import ExpressionsMixin
from .functions import FunctionsMixin
from .registration import RegistrationMixin
from .statements import StatementsMixin
from .type_inference import TypeInferenceMixin
from .type_utils import TypeUtilsMixin
from .validation import ValidationMixin


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
    "AnalyzedProgram",
    "Analyzer",
    "AnalyzerError",
    "ClassInfo",
    "InterfaceInfo",
    "Scope",
    "SymbolInfo",
]
