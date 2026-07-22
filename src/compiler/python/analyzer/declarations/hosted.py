"""Declaration and provenance policy for the hosted C ABI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...hosted_abi import HOSTED_MACROS, AbiType, hosted_function, hosted_owned_name
from ...source_provenance import is_compiler_stdlib_source
from ...type_composition import nullable_collapses_reference_layer
from .c_names import trusted_native_binding
from .type_resolution import canonical_declaration_type

if TYPE_CHECKING:
    from ..analysis_context import AnalysisContext
    from .registry import DeclarationRegistry

_C_BASES = {
    "byte": "unsigned char",
    "long int": "long",
    "long long int": "long long",
    "short int": "short",
    "signed": "int",
    "signed int": "int",
    "string": "char",
    "unsigned": "unsigned int",
    "uint": "unsigned int",
    "unsigned long int": "unsigned long",
    "unsigned long long int": "unsigned long long",
    "unsigned short int": "unsigned short",
}


class HostedDeclarationPolicy:
    def __init__(
        self,
        context: AnalysisContext,
        registry: DeclarationRegistry,
    ) -> None:
        self.context = context
        self.registry = registry

    def type_declaration_allowed(self, declaration) -> bool:
        return bool(
            is_compiler_stdlib_source(self.context.current_source_file)
            and declaration.name == "winsize"
            and declaration.is_forward
            and not declaration.fields
        )

    def object_declaration_allowed(self, declaration) -> bool:
        type_expr = declaration.type
        canonical = self._canonical_type(type_expr)
        return bool(
            is_compiler_stdlib_source(self.context.current_source_file)
            and declaration.name == "environ"
            and declaration.initializer is None
            and type_expr is not None
            and type_expr.is_extern
            and canonical is not None
            and canonical.base == "char"
            and canonical.pointer_depth == 2
            and not canonical.is_array
            and not canonical.generic_args
        )

    def validate_function(self, declaration) -> None:
        if declaration.body is not None:
            return
        name = declaration.name
        if name in HOSTED_MACROS:
            self.context.error(
                f"Hosted macro '{name}' cannot be redeclared as a function",
                declaration.line,
                declaration.col,
            )
            return
        spec = hosted_function(name)
        if (
            spec is None
            and trusted_native_binding(name, self.context.current_source_file)
            and is_compiler_stdlib_source(self.context.current_source_file)
        ):
            return
        if spec is None:
            if hosted_owned_name(name):
                self.context.error(
                    f"Hosted symbol '{name}' has no source-representable "
                    "prototype; include its standard header and call it directly",
                    declaration.line,
                    declaration.col,
                )
            return
        if spec.parameters is None or spec.variadic:
            self.context.error(
                f"Hosted function '{name}' has an ABI that btrc "
                "prototypes cannot represent; include its standard header "
                "and call it directly",
                declaration.line,
                declaration.col,
            )
            return
        actual_result = self.abi_type(declaration.return_type)
        actual_parameters = tuple(self.abi_type(parameter.type) for parameter in declaration.params)
        modifiers_valid = bool(
            not declaration.return_type.is_static
            and not declaration.return_type.is_volatile
            and not declaration.is_gpu
            and not declaration.keep_return
            and all(
                not parameter.keep
                and parameter.default is None
                and not parameter.type.is_static
                and not parameter.type.is_extern
                and not parameter.type.is_volatile
                for parameter in declaration.params
            )
        )
        if not modifiers_valid or actual_result != spec.result or actual_parameters != spec.parameters:
            self.context.error(
                f"Hosted function declaration '{name}' does not match "
                f"compiler-owned C ABI '{self._format_hosted_abi(spec)}'",
                declaration.line,
                declaration.col,
            )

    def _canonical_type(self, type_expr):
        return canonical_declaration_type(type_expr, self.registry.typedef_table)

    def abi_type(self, type_expr) -> AbiType | None:
        canonical = self._canonical_type(type_expr)
        if canonical is None or canonical.generic_args:
            return None
        base = _C_BASES.get(canonical.base, canonical.base)
        depth = canonical.pointer_depth + int(canonical.is_array)
        if canonical.base == "string":
            depth += 1
        if nullable_collapses_reference_layer(
            canonical,
            base_is_reference=canonical.base == "string",
        ):
            depth -= 1
        return AbiType(base, depth, bool(canonical.is_const))

    @staticmethod
    def _format_hosted_abi(spec) -> str:
        def render(type_shape: AbiType) -> str:
            qualifier = "const " if type_shape.is_const else ""
            return qualifier + type_shape.base + "*" * type_shape.pointer_depth

        parameters = ", ".join(render(item) for item in spec.parameters or ())
        if spec.variadic:
            parameters = f"{parameters}, ..." if parameters else "..."
        return f"{render(spec.result)} ({parameters or 'void'})"


__all__ = ["HostedDeclarationPolicy"]
