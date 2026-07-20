"""Declaration and provenance contracts for the hosted C ABI."""

from ..hosted_abi import HOSTED_MACROS, AbiType, hosted_function, hosted_owned_name
from ..source_provenance import is_compiler_stdlib_source
from ..type_composition import nullable_collapses_reference_layer

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


class HostedAbiDeclarationContractsMixin:
    def _hosted_type_declaration_allowed(self, declaration) -> bool:
        """Allow only incomplete hosted tags required by exact stdlib ABIs."""
        return bool(
            self._hosted_stdlib_source(self.current_source_file)
            and declaration.name == "winsize"
            and declaration.is_forward
            and not declaration.fields
        )

    def _hosted_object_declaration_allowed(self, declaration) -> bool:
        """Recognize the canonical portable ``environ`` extern seam."""
        type_expr = declaration.type
        canonical = self._canonical_type(type_expr)
        return bool(
            self._hosted_stdlib_source(self.current_source_file)
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

    @staticmethod
    def _hosted_stdlib_source(source_file) -> bool:
        return is_compiler_stdlib_source(source_file)

    def _validate_hosted_abi_declaration(self, declaration) -> None:
        """Require exact ABI parity for a surviving hosted prototype."""
        if declaration.body is not None:
            return
        name = declaration.name
        if name in HOSTED_MACROS:
            self._error(
                f"Hosted macro '{name}' cannot be redeclared as a function",
                declaration.line,
                declaration.col,
            )
            return
        spec = hosted_function(name)
        if (
            spec is None
            and self._is_trusted_native_binding(name)
            and self._hosted_stdlib_source(self.current_source_file)
        ):
            return
        if spec is None:
            if hosted_owned_name(name):
                self._error(
                    f"Hosted symbol '{name}' has no source-representable "
                    "prototype; include its standard header and call it directly",
                    declaration.line,
                    declaration.col,
                )
            return
        if spec.parameters is None or spec.variadic:
            self._error(
                f"Hosted function '{name}' has an ABI that btrc "
                "prototypes cannot represent; include its standard header "
                "and call it directly",
                declaration.line,
                declaration.col,
            )
            return
        actual_result = self._hosted_abi_type(declaration.return_type)
        actual_parameters = tuple(self._hosted_abi_type(parameter.type) for parameter in declaration.params)
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
            self._error(
                f"Hosted function declaration '{name}' does not match "
                f"compiler-owned C ABI '{self._format_hosted_abi(spec)}'",
                declaration.line,
                declaration.col,
            )

    def _hosted_abi_type(self, type_expr) -> AbiType | None:
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


__all__ = ["HostedAbiDeclarationContractsMixin"]
