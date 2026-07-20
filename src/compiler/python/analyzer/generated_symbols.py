"""Orchestration and shared collision checks for synthesized C symbols."""

from ..ast_nodes import ClassDecl, EnumDecl, FunctionDecl, RichEnumDecl
from .generated_symbol_calls import (
    claim_generic_method_symbols,
    claim_gpu_symbols,
    validate_generated_symbol_ownership,
    validate_generated_symbol_references,
)
from .generated_symbol_classes import claim_class_symbols
from .generated_symbol_enums import claim_enum_symbols, claim_rich_enum_symbols
from .generated_symbol_generics import claim_generic_instance_symbols


class GeneratedSymbolContractsMixin:
    def _validate_generated_c_symbols(self, program) -> None:
        claims: dict[str, str] = {}
        generic_declarations = {}
        for declaration in self._decls_with_file(program):
            if isinstance(declaration, FunctionDecl) and declaration.is_gpu:
                claim_gpu_symbols(self, declaration, claims)
            elif isinstance(declaration, ClassDecl):
                if declaration.generic_params:
                    generic_declarations[declaration.name] = declaration
                else:
                    claim_class_symbols(self, declaration, claims)
            elif isinstance(declaration, EnumDecl) and declaration.name:
                claim_enum_symbols(self, declaration, claims)
            elif isinstance(declaration, RichEnumDecl):
                claim_rich_enum_symbols(self, declaration, claims)
        claim_generic_instance_symbols(self, generic_declarations, claims)
        claim_generic_method_symbols(self, claims)
        validate_generated_symbol_references(self, program, claims)

    def _claim_generated_symbol(self, symbol, owner, line, col, claims) -> None:
        validate_generated_symbol_ownership(self, symbol, owner, line, col)
        source_kind = self._top_level_kinds.get(symbol)
        if source_kind is not None:
            self._error(
                f"Generated C symbol '{symbol}' for {owner} collides with source {source_kind} '{symbol}'",
                line,
                col,
            )
        if symbol in self._source_macro_names:
            self._error(
                f"Generated C symbol '{symbol}' for {owner} collides with source macro '{symbol}'",
                line,
                col,
            )
        previous = claims.get(symbol)
        if previous is not None:
            self._error(
                f"Generated C symbol '{symbol}' for {owner} collides with {previous}",
                line,
                col,
            )
        else:
            claims[symbol] = owner

    def _reject_generated_member_macro(self, symbol, owner, line, col) -> None:
        if symbol in self._source_macro_names:
            self._error(
                f"Generated C member '{symbol}' for {owner} collides with source macro '{symbol}'",
                line,
                col,
            )


__all__ = ["GeneratedSymbolContractsMixin"]
