"""Generated C symbol claims and runtime source symbols."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import TYPE_CHECKING

from src.compiler.python.abi.hosted import HOSTED_ABI
from src.compiler.python.analyzer.program import DeclarationIndex
from src.compiler.python.analyzer.types import GENERIC_INTRINSICS
from src.compiler.python.runtime.catalog import RuntimeHelperCatalog
from src.compiler.python.syntax.ast.generated import (
    ClassDecl,
    EnumDecl,
    FieldDecl,
    FunctionDecl,
    Identifier,
    PreprocessorDirective,
    PropertyDecl,
    RichEnumDecl,
)
from src.compiler.python.syntax.tokens import SourceSymbolDirective

if TYPE_CHECKING:
    from src.compiler.python.analyzer.macros import SourceMacroAnalyzer
    from src.compiler.python.analyzer.program import AnalysisSession
    from src.compiler.python.analyzer.storage import StorageModel
    from src.compiler.python.analyzer.types import TypeSystem


class SourceRuntimeSymbols:
    """Classify source-visible runtime and compiler-owned symbol spellings."""

    def __init__(self, runtime_helpers: RuntimeHelperCatalog) -> None:
        self._runtime_helpers = runtime_helpers
        self._generic_intrinsics = frozenset(GENERIC_INTRINSICS)

    def is_helper(self, name: str) -> bool:
        return self._runtime_helpers.is_source_visible(name)

    def is_intrinsic(self, name: str) -> bool:
        """Whether ``name`` is supported specifically as a direct source call."""
        return self.is_helper(name) or name in self._generic_intrinsics

    @staticmethod
    def is_compiler_owned(name: str) -> bool:
        """Whether an unresolved spelling belongs to a btrc-owned namespace.

        C reserves every double-underscore declaration, but preprocessing
        replacements legitimately reference standard predefined macros such as
        ``__FILE__``, ``__LINE__``, and ``__VA_ARGS__``. Declaration validation
        enforces the broader C rule; unresolved reference validation owns only
        the namespaces the compiler can actually synthesize.
        """
        return name.startswith(("__btrc_", "__BTRC_", "__gpu_", "btrc_"))


_CYCLE_COLLECTIONS = frozenset({"Vector", "Array", "List", "Map", "Set"})


class GeneratedSymbolRegistry:
    """Generated C symbol claims and runtime source symbols."""

    def __init__(
        self,
        session: AnalysisSession,
        index: DeclarationIndex,
        types: TypeSystem,
        storage: StorageModel,
        macros: SourceMacroAnalyzer,
        runtime_catalog: RuntimeHelperCatalog,
    ) -> None:
        self.session = session
        self.index = index
        self.macros = macros
        self.storage = storage
        self.types = types
        self._source_symbols = SourceRuntimeSymbols(runtime_catalog)

    def claim_gpu_symbols(self, declaration, claims) -> None:
        for suffix, role in (("__gpuitem", "CPU item worker"), ("__gpucpu", "CPU fallback wrapper")):
            self._claim_generated_symbol(
                f"{declaration.name}{suffix}",
                f"{role} for @gpu function '{declaration.name}'",
                declaration.line,
                declaration.col,
                claims,
            )

    def claim_destructor_hook(self, emitted_name, owner, info, site, claims) -> None:
        """Claim the hidden hook emitted for a source ``__del__`` method."""
        destructor = info.methods.get("__del__")
        if destructor is None or destructor.body is None:
            return
        self._claim_generated_symbol(
            self.destructor_hook_symbol(emitted_name),
            f"destructor hook for {owner}",
            destructor.line or site.line,
            destructor.col or site.col,
            claims,
        )

    def claim_generic_method_symbols(self, claims) -> None:
        """Claim every concrete generic-method function selected by analysis."""
        for (class_name, method_name), instances in self.session.generic_method_instances.items():
            info = self.index.class_table.get(class_name)
            method = info.methods.get(method_name) if info is not None else None
            if method is None:
                continue
            for class_args, method_args in instances:
                symbol = self.types.method_instance_symbol(class_name, class_args, method_name, method_args)
                self._claim_generated_symbol(
                    symbol, f"generic method instance '{symbol}'", method.line, method.col, claims
                )

    def validate_generated_symbol_ownership(self, symbol, owner, line, col) -> None:
        """Reject a synthesized spelling owned by the canonical hosted registry."""
        if HOSTED_ABI.owned_name(symbol):
            self.session.error(
                f"Generated C symbol '{symbol}' for {owner} collides with compiler-owned hosted C symbol '{symbol}'",
                line,
                col,
            )

    def validate_generated_symbol_references(self, program, claims) -> None:
        """Resolve deferred identifiers after every generated claim is known."""
        for declaration in self.session.declarations(program):
            if isinstance(declaration, PreprocessorDirective):
                self._validate_preprocessor_symbols(declaration, claims)
            for node in self._walk_ast(declaration):
                if not isinstance(node, Identifier):
                    continue
                node_id = id(node)
                if node_id not in self.session.unresolved_c_symbol_reference_ids:
                    continue
                symbol = node.name
                direct_call = node_id in self.session.unresolved_direct_callee_ids
                action = "Direct call to" if direct_call else "Source reference to"
                owner = claims.get(symbol)
                if owner is not None:
                    self.session.error(
                        f"{action} compiler-generated C symbol '{symbol}' for {owner} is not allowed",
                        node.line,
                        node.col,
                    )
                    continue
                supported = self._source_symbols.is_helper(symbol) or (
                    direct_call and self._source_symbols.is_intrinsic(symbol)
                )
                if self._source_symbols.is_compiler_owned(symbol) and (not supported):
                    self.session.error(
                        f"{action} compiler-owned C symbol '{symbol}' is not allowed", node.line, node.col
                    )
                elif not direct_call and (not symbol.isupper()) and (not supported):
                    self.session.error(f"Unresolved identifier '{symbol}' used as a value", node.line, node.col)

    def _validate_preprocessor_symbols(self, declaration, claims) -> None:
        directive = SourceSymbolDirective.parse(declaration.text)
        if directive is None:
            return
        if directive.operation == "undef":
            self._reject_preprocessor_symbol(directive.name, "Source #undef of", declaration, claims)
            return
        if directive.uses_token_paste():
            self.session.error(
                f"Source macro '{directive.name}' uses token pasting, which can construct compiler-owned C symbols",
                declaration.line,
                declaration.col,
            )
        for identifier in directive.replacement_identifiers():
            self._validate_macro_replacement_symbol(identifier, directive.name, declaration, claims)

    def _validate_macro_replacement_symbol(self, symbol, macro_name, declaration, claims) -> None:
        """Apply semantic policies to one parsed replacement identifier."""
        if HOSTED_ABI.raw_lifetime_arity(symbol) is not None:
            self.session.error(
                f"Raw lifetime consumer '{symbol}' cannot be referenced from macro replacement '{macro_name}'",
                declaration.line,
                declaration.col,
            )
        elif HOSTED_ABI.macro_reference_requires_semantic_call(symbol):
            self.session.error(
                f"Hosted function '{symbol}' requires semantic call analysis and cannot be referenced from macro replacement '{macro_name}'",
                declaration.line,
                declaration.col,
            )
        self.macros.validate_replacement_language_symbol(
            SourceSymbolDirective.parse(declaration.text), symbol, declaration
        )
        self._reject_preprocessor_symbol(
            symbol, f"Replacement list for source macro '{macro_name}' references", declaration, claims
        )

    def _reject_preprocessor_symbol(self, symbol, action, declaration, claims) -> None:
        owner = claims.get(symbol)
        if owner is not None:
            self.session.error(
                f"{action} compiler-generated C symbol '{symbol}' for {owner} is not allowed",
                declaration.line,
                declaration.col,
            )
        elif self._source_symbols.is_compiler_owned(symbol):
            self.session.error(
                f"{action} compiler-owned C symbol '{symbol}' is not allowed", declaration.line, declaration.col
            )

    @staticmethod
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

    def managed_storage_type(self, type_expr) -> bool:
        type_expr = self.types.canonical_type(type_expr)
        return bool(
            type_expr is not None
            and (not type_expr.is_array)
            and (type_expr.pointer_depth <= 1)
            and (type_expr.base in self.index.class_table)
        )

    def claim_class_symbols(self, declaration, claims) -> None:
        name = declaration.name
        info = self.index.class_table[name]
        for suffix, role in (("init", "initializer"), ("new", "allocator"), ("destroy", "destructor")):
            self._claim_generated_symbol(
                f"{name}_{suffix}", f"{role} for class '{name}'", declaration.line, declaration.col, claims
            )
        self.claim_destructor_hook(name, f"class '{name}'", info, declaration, claims)
        if any((self.managed_storage_type(field.type) for _name, field in info.instance_storage)):
            self._claim_generated_symbol(
                self.cycle_visitor_symbol(name),
                f"cycle visitor for class '{name}'",
                declaration.line,
                declaration.col,
                claims,
            )
        self._claim_class_members(declaration, info, claims)

    def _claim_class_members(self, declaration, info, claims) -> None:
        name = declaration.name
        for method_name, method in info.methods.items():
            if method.is_constructor or method_name == "__del__" or method.generic_params:
                continue
            self._claim_generated_symbol(
                f"{name}_{method_name}", f"method '{name}.{method_name}'", method.line, method.col, claims
            )
        for property_name, prop in info.properties.items():
            for enabled, prefix, role in ((prop.has_getter, "get", "getter"), (prop.has_setter, "set", "setter")):
                if enabled:
                    self._claim_generated_symbol(
                        f"{name}_{prefix}_{property_name}",
                        f"{role} '{name}.{property_name}'",
                        prop.line,
                        prop.col,
                        claims,
                    )
        for member in declaration.members:
            if isinstance(member, FieldDecl) and member.access == "class":
                self._claim_generated_symbol(
                    f"{name}_{member.name}", f"static field '{name}.{member.name}'", member.line, member.col, claims
                )
            elif isinstance(member, PropertyDecl) and self.storage.property_needs_backing(member):
                self._reject_generated_member_macro(
                    f"_prop_{member.name}", f"property backing field '{name}.{member.name}'", member.line, member.col
                )
        for symbol, role in (("__arc", "ARC header"), ("__rc", "reference count"), ("__cycle_safe_rc", "cycle proof")):
            self._reject_generated_member_macro(
                symbol, f"{role} field for class '{name}'", declaration.line, declaration.col
            )

    def claim_enum_symbols(self, declaration, claims) -> None:
        for value in declaration.values:
            self._claim_generated_symbol(
                f"{declaration.name}_{value.name}",
                f"enum value '{declaration.name}.{value.name}'",
                value.line,
                value.col,
                claims,
            )
        self._claim_generated_symbol(
            f"{declaration.name}_toString",
            f"enum helper for '{declaration.name}'",
            declaration.line,
            declaration.col,
            claims,
        )

    def claim_rich_enum_symbols(self, declaration, claims) -> None:
        name = declaration.name
        self._claim_generated_symbol(
            f"{name}_Tag", f"tag type for rich enum '{name}'", declaration.line, declaration.col, claims
        )
        for variant in declaration.variants:
            for symbol, role in (
                (f"{name}_{variant.name}_TAG", "tag value"),
                (f"{name}_{variant.name}", "constructor"),
            ):
                self._claim_generated_symbol(
                    symbol, f"{role} for rich-enum variant '{name}.{variant.name}'", variant.line, variant.col, claims
                )
            if variant.params:
                self._claim_generated_symbol(
                    f"{name}_{variant.name}_Data",
                    f"payload type for rich-enum variant '{name}.{variant.name}'",
                    variant.line,
                    variant.col,
                    claims,
                )
        self._claim_generated_symbol(
            f"{name}_toString", f"enum helper for '{name}'", declaration.line, declaration.col, claims
        )

    def claim_generic_instance_symbols(self, declarations, claims) -> None:
        for base_name, instances in self.session.generic_instances.items():
            declaration = declarations.get(base_name)
            info = self.index.class_table.get(base_name)
            if declaration is None or info is None:
                continue
            for arguments in instances:
                emitted_name = self.types.generic_symbol(base_name, arguments)
                owner = f"generic instance '{emitted_name}'"
                self._claim_generic_lifecycle(declaration, emitted_name, owner, claims)
                self.claim_destructor_hook(emitted_name, owner, info, declaration, claims)
                if self._generic_needs_cycle_visitor(base_name, arguments, info):
                    self._claim_generated_symbol(
                        self.cycle_visitor_symbol(emitted_name),
                        f"cycle visitor for {owner}",
                        declaration.line,
                        declaration.col,
                        claims,
                    )
                self._claim_generic_members(emitted_name, owner, info, claims)

    def _claim_generic_lifecycle(self, declaration, emitted_name, owner, claims) -> None:
        for suffix, role in (("init", "initializer"), ("new", "allocator"), ("destroy", "destructor")):
            self._claim_generated_symbol(
                f"{emitted_name}_{suffix}", f"{role} for {owner}", declaration.line, declaration.col, claims
            )

    def _generic_needs_cycle_visitor(self, base_name, arguments, info) -> bool:
        if base_name in _CYCLE_COLLECTIONS:
            return base_name == "List" or any(self.managed_storage_type(arg) for arg in arguments)
        substitutions = dict(zip(info.generic_params, arguments))
        return any(
            (
                self.managed_storage_type(self.types.substitute_type(field.type, substitutions))
                for _name, field in info.instance_storage
            )
        )

    def _claim_generic_members(self, emitted_name, owner, info, claims) -> None:
        for method_name, method in info.methods.items():
            if method.is_constructor or method_name == "__del__" or method.generic_params:
                continue
            self._claim_generated_symbol(
                f"{emitted_name}_{method_name}", f"method '{method_name}' for {owner}", method.line, method.col, claims
            )
        for property_name, prop in info.properties.items():
            for enabled, prefix, role in ((prop.has_getter, "get", "getter"), (prop.has_setter, "set", "setter")):
                if enabled:
                    self._claim_generated_symbol(
                        f"{emitted_name}_{prefix}_{property_name}",
                        f"{role} '{property_name}' for {owner}",
                        prop.line,
                        prop.col,
                        claims,
                    )

    def validate_program_symbols(self, program) -> None:
        claims: dict[str, str] = {}
        generic_declarations = {}
        for declaration in self.session.declarations(program):
            if isinstance(declaration, FunctionDecl) and declaration.is_gpu:
                self.claim_gpu_symbols(declaration, claims)
            elif isinstance(declaration, ClassDecl):
                if declaration.generic_params:
                    generic_declarations[declaration.name] = declaration
                else:
                    self.claim_class_symbols(declaration, claims)
            elif isinstance(declaration, EnumDecl) and declaration.name:
                self.claim_enum_symbols(declaration, claims)
            elif isinstance(declaration, RichEnumDecl):
                self.claim_rich_enum_symbols(declaration, claims)
        self.claim_generic_instance_symbols(generic_declarations, claims)
        self.claim_generic_method_symbols(claims)
        self.validate_generated_symbol_references(program, claims)

    def _claim_generated_symbol(self, symbol, owner, line, col, claims) -> None:
        self.validate_generated_symbol_ownership(symbol, owner, line, col)
        source_kind = self.index.top_level_kinds.get(symbol)
        if source_kind is not None:
            self.session.error(
                f"Generated C symbol '{symbol}' for {owner} collides with source {source_kind} '{symbol}'", line, col
            )
        if self.index.source_macros.declared(symbol):
            self.session.error(
                f"Generated C symbol '{symbol}' for {owner} collides with source macro '{symbol}'", line, col
            )
        previous = claims.get(symbol)
        if previous is not None:
            self.session.error(f"Generated C symbol '{symbol}' for {owner} collides with {previous}", line, col)
        else:
            claims[symbol] = owner

    def _reject_generated_member_macro(self, symbol, owner, line, col) -> None:
        if self.index.source_macros.declared(symbol):
            self.session.error(
                f"Generated C member '{symbol}' for {owner} collides with source macro '{symbol}'", line, col
            )

    @staticmethod
    def cycle_visitor_symbol(emitted_name: str) -> str:
        return f"__btrc_arc_visit_{emitted_name}"

    @staticmethod
    def destructor_hook_symbol(owner_name: str) -> str:
        return f"__btrc_{owner_name}_destructor_hook"


__all__ = ["GeneratedSymbolRegistry", "SourceRuntimeSymbols"]
