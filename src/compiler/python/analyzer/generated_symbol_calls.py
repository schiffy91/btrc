"""Source-reference boundaries for compiler-owned C symbols."""

from __future__ import annotations

from dataclasses import fields, is_dataclass

from ..ast_nodes import Identifier, PreprocessorDirective
from ..destructor_symbols import destructor_hook_symbol
from ..hosted_abi import (
    hosted_macro_reference_requires_semantic_call,
    hosted_owned_name,
    hosted_raw_lifetime_arity,
)
from ..source_macros import SourceSymbolDirective
from ..source_runtime_symbols import (
    is_compiler_owned_symbol,
    is_source_runtime_helper,
    is_source_runtime_intrinsic,
)


def claim_gpu_symbols(analyzer, declaration, claims) -> None:
    for suffix, role in (("__gpuitem", "CPU item worker"), ("__gpucpu", "CPU fallback wrapper")):
        analyzer._claim_generated_symbol(
            f"{declaration.name}{suffix}",
            f"{role} for @gpu function '{declaration.name}'",
            declaration.line,
            declaration.col,
            claims,
        )


def claim_destructor_hook(analyzer, emitted_name, owner, info, site, claims) -> None:
    """Claim the hidden hook emitted for a source ``__del__`` method."""
    destructor = info.methods.get("__del__")
    if destructor is None or destructor.body is None:
        return
    analyzer._claim_generated_symbol(
        destructor_hook_symbol(emitted_name),
        f"destructor hook for {owner}",
        destructor.line or site.line,
        destructor.col or site.col,
        claims,
    )


def claim_generic_method_symbols(analyzer, claims) -> None:
    """Claim every concrete generic-method function selected by analysis."""
    for (class_name, method_name), instances in analyzer.generic_method_instances.items():
        info = analyzer.declarations.class_table.get(class_name)
        method = info.methods.get(method_name) if info is not None else None
        if method is None:
            continue
        for class_args, method_args in instances:
            symbol = analyzer.type_identity.method_instance_symbol(
                class_name,
                class_args,
                method_name,
                method_args,
            )
            analyzer._claim_generated_symbol(
                symbol,
                f"generic method instance '{symbol}'",
                method.line,
                method.col,
                claims,
            )


def validate_generated_symbol_ownership(analyzer, symbol, owner, line, col) -> None:
    """Reject a synthesized spelling owned by the canonical hosted registry."""
    if hosted_owned_name(symbol):
        analyzer.context.error(
            f"Generated C symbol '{symbol}' for {owner} collides with compiler-owned hosted C symbol '{symbol}'",
            line,
            col,
        )


def validate_generated_symbol_references(analyzer, program, claims) -> None:
    """Resolve deferred identifiers after every generated claim is known."""
    for declaration in analyzer.context.declarations(program):
        if isinstance(declaration, PreprocessorDirective):
            _validate_preprocessor_symbols(analyzer, declaration, claims)
        for node in _walk_ast(declaration):
            if not isinstance(node, Identifier):
                continue
            node_id = id(node)
            if node_id not in analyzer._unresolved_c_symbol_reference_ids:
                continue
            symbol = node.name
            direct_call = node_id in analyzer._unresolved_direct_callee_ids
            action = "Direct call to" if direct_call else "Source reference to"
            owner = claims.get(symbol)
            if owner is not None:
                analyzer.context.error(
                    f"{action} compiler-generated C symbol '{symbol}' for {owner} is not allowed",
                    node.line,
                    node.col,
                )
                continue
            supported = is_source_runtime_helper(symbol) or (direct_call and is_source_runtime_intrinsic(symbol))
            if is_compiler_owned_symbol(symbol) and not supported:
                analyzer.context.error(
                    f"{action} compiler-owned C symbol '{symbol}' is not allowed",
                    node.line,
                    node.col,
                )
            elif not direct_call and not symbol.isupper() and not supported:
                analyzer.context.error(
                    f"Unresolved identifier '{symbol}' used as a value",
                    node.line,
                    node.col,
                )


def _validate_preprocessor_symbols(analyzer, declaration, claims) -> None:
    directive = SourceSymbolDirective.parse(declaration.text)
    if directive is None:
        return
    if directive.operation == "undef":
        _reject_preprocessor_symbol(
            analyzer,
            directive.name,
            "Source #undef of",
            declaration,
            claims,
        )
        return
    if directive.uses_token_paste():
        analyzer.context.error(
            f"Source macro '{directive.name}' uses token pasting, which can construct compiler-owned C symbols",
            declaration.line,
            declaration.col,
        )
    for identifier in directive.replacement_identifiers():
        _validate_macro_replacement_symbol(
            analyzer,
            identifier,
            directive.name,
            declaration,
            claims,
        )


def _validate_macro_replacement_symbol(
    analyzer,
    symbol,
    macro_name,
    declaration,
    claims,
) -> None:
    """Apply semantic policies to one parsed replacement identifier."""
    if hosted_raw_lifetime_arity(symbol) is not None:
        analyzer.context.error(
            f"Raw lifetime consumer '{symbol}' cannot be referenced from macro replacement '{macro_name}'",
            declaration.line,
            declaration.col,
        )
    elif hosted_macro_reference_requires_semantic_call(symbol):
        analyzer.context.error(
            f"Hosted function '{symbol}' requires semantic call analysis and cannot be referenced from macro replacement '{macro_name}'",
            declaration.line,
            declaration.col,
        )
    analyzer._validate_macro_replacement_language_symbol(
        SourceSymbolDirective.parse(declaration.text),
        symbol,
        declaration,
    )
    _reject_preprocessor_symbol(
        analyzer,
        symbol,
        f"Replacement list for source macro '{macro_name}' references",
        declaration,
        claims,
    )


def _reject_preprocessor_symbol(
    analyzer,
    symbol,
    action,
    declaration,
    claims,
) -> None:
    owner = claims.get(symbol)
    if owner is not None:
        analyzer.context.error(
            f"{action} compiler-generated C symbol '{symbol}' for {owner} is not allowed",
            declaration.line,
            declaration.col,
        )
    elif is_compiler_owned_symbol(symbol):
        analyzer.context.error(
            f"{action} compiler-owned C symbol '{symbol}' is not allowed",
            declaration.line,
            declaration.col,
        )


def _walk_ast(root):
    pending = [root]
    seen: set[int] = set()
    while pending:
        value = pending.pop()
        if value is None or isinstance(value, (str, bytes, int, float, bool)):
            continue
        if isinstance(value, (list, tuple)):
            pending.extend(reversed(value))
            continue
        if not is_dataclass(value) or id(value) in seen:
            continue
        seen.add(id(value))
        yield value
        pending.extend(reversed([getattr(value, field.name) for field in fields(value)]))


__all__ = [
    "claim_destructor_hook",
    "claim_generic_method_symbols",
    "claim_gpu_symbols",
    "validate_generated_symbol_ownership",
    "validate_generated_symbol_references",
]
