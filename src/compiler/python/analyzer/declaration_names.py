"""C identifier and lexical declaration-name contracts."""

from ..hosted_abi import HOSTED_MACROS
from ..source_provenance import is_compiler_stdlib_source
from .declaration_contracts import is_magic_method_name

_C11_RESERVED_NAMES = frozenset(
    {
        "auto",
        "break",
        "case",
        "char",
        "const",
        "continue",
        "default",
        "do",
        "double",
        "else",
        "enum",
        "extern",
        "float",
        "for",
        "goto",
        "if",
        "inline",
        "int",
        "long",
        "register",
        "restrict",
        "return",
        "short",
        "signed",
        "sizeof",
        "static",
        "struct",
        "switch",
        "typedef",
        "union",
        "unsigned",
        "void",
        "volatile",
        "while",
        "_Alignas",
        "_Alignof",
        "_Atomic",
        "_Bool",
        "_Complex",
        "_Generic",
        "_Imaginary",
        "_Noreturn",
        "_Static_assert",
        "_Thread_local",
    }
)
_PUBLIC_NATIVE_BINDINGS = frozenset({"btrc_gpu_available", "btrc_gui_surface_width", "btrc_tray_show"})
_COMPILER_RESERVED_PREFIXES = ("__btrc_", "__BTRC_", "__gpu_", "btrc_")


def compiler_reserved_prefix(name: str) -> str | None:
    """Return the reserved compiler/runtime namespace owning ``name``."""
    return next(
        (prefix for prefix in _COMPILER_RESERVED_PREFIXES if name.startswith(prefix)),
        None,
    )


def c_reserved_identifier(name: str) -> bool:
    """Whether C11 reserves this identifier in every source context."""
    return name.startswith("__") or (len(name) > 1 and name[0] == "_" and "A" <= name[1] <= "Z")


def c_file_scope_reserved_identifier(name: str) -> bool:
    """Whether C11 reserves this identifier when declared at file scope."""
    return name.startswith("_")


class DeclarationNamesMixin:
    def _validate_declared_name(
        self,
        name,
        subject,
        line=0,
        col=0,
        *,
        allow_magic=False,
        file_scope=False,
        trusted_prototype=False,
        trusted_hosted=False,
        c_name_generated=False,
    ) -> bool:
        """Reject spellings that cannot safely become user-owned C names."""
        if not name:
            return True
        if name in self.declarations.source_macro_names:
            self._error(
                f"{subject} name '{name}' collides with source macro '{name}'",
                line,
                col,
            )
            return False
        if name in HOSTED_MACROS and not (c_name_generated or trusted_hosted):
            self._error(
                f"{subject} name '{name}' collides with an automatically included C macro",
                line,
                col,
            )
            return False
        if name in _C11_RESERVED_NAMES:
            self._error(
                f"{subject} name '{name}' is reserved by C11",
                line,
                col,
            )
            return False
        reserved_prefix = compiler_reserved_prefix(name)
        if reserved_prefix:
            if trusted_prototype and self._is_trusted_native_binding(name):
                return True
            self._error(
                f"{subject} name '{name}' uses the compiler-reserved '{reserved_prefix}' prefix",
                line,
                col,
            )
            return False
        if c_reserved_identifier(name) and not (allow_magic and is_magic_method_name(name)):
            self._error(
                f"{subject} name '{name}' is reserved by C11",
                line,
                col,
            )
            return False
        if file_scope and c_file_scope_reserved_identifier(name):
            self._error(
                f"{subject} name '{name}' is reserved by C11 at file scope",
                line,
                col,
            )
            return False
        return True

    def _is_trusted_native_binding(self, name) -> bool:
        if name in _PUBLIC_NATIVE_BINDINGS:
            return True
        return is_compiler_stdlib_source(self.current_source_file)

    def _validate_parameter_names(self, parameters, owner) -> None:
        seen = set()
        for parameter in parameters:
            line = parameter.name_line or parameter.line
            col = parameter.name_col or parameter.col
            # Parameter spelling is part of the source-level named-argument
            # API, while its C identifier is compiler-generated and can be
            # isolated from automatically included object-like macros.
            self._validate_declared_name(
                parameter.name,
                "Parameter",
                line,
                col,
                c_name_generated=True,
            )
            if parameter.name in seen:
                self._error(
                    f"Duplicate parameter name '{parameter.name}' in {owner}",
                    line,
                    col,
                )
            seen.add(parameter.name)

    def _validate_generic_parameter_names(self, names, owner, line=0, col=0) -> None:
        seen = set()
        for name in names:
            self._validate_declared_name(name, "Generic parameter", line, col)
            if name in seen:
                self._error(
                    f"Duplicate generic parameter name '{name}' in {owner}",
                    line,
                    col,
                )
            seen.add(name)

    def _claim_local_binding(
        self,
        name,
        kind,
        line=0,
        col=0,
        *,
        c_name_generated=False,
    ) -> bool:
        """Claim a name in exactly the current lexical scope."""
        self._validate_declared_name(
            name,
            kind.capitalize(),
            line,
            col,
            c_name_generated=c_name_generated,
        )
        existing = self.scope.symbols.get(name)
        if existing is None or existing.kind == "function":
            outer = self.scope.parent.lookup(name) if self.scope.parent else None
            if outer is not None and self._contains_thread_storage(outer.type):
                self._error(
                    f"Binding '{name}' cannot shadow an active Thread owner",
                    line,
                    col,
                )
                return False
            return True
        self._error(
            f"Duplicate {kind} name '{name}' in the same scope",
            line,
            col,
        )
        return False


__all__ = [
    "DeclarationNamesMixin",
    "c_file_scope_reserved_identifier",
    "c_reserved_identifier",
    "compiler_reserved_prefix",
]
