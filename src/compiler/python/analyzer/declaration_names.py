"""C identifier and lexical declaration-name contracts."""

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


class DeclarationNamesMixin:
    def _validate_declared_name(self, name, subject, line=0, col=0) -> bool:
        """Reject spellings that cannot safely become user-owned C names."""
        if not name:
            return True
        if name in getattr(self, "_source_macro_names", ()):
            self._error(
                f"{subject} name '{name}' collides with source macro '{name}'",
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
        reserved_prefix = next(
            (prefix for prefix in ("__btrc_", "btrc_") if name.startswith(prefix)),
            None,
        )
        if reserved_prefix:
            if self._is_trusted_native_binding(name):
                return True
            self._error(
                f"{subject} name '{name}' uses the compiler-reserved '{reserved_prefix}' prefix",
                line,
                col,
            )
            return False
        return True

    def _is_trusted_native_binding(self, name) -> bool:
        if name in _PUBLIC_NATIVE_BINDINGS:
            return True
        source = (self.current_source_file or "").replace("\\", "/")
        return source.startswith("src/stdlib/") or "/src/stdlib/" in source

    def _validate_parameter_names(self, parameters, owner) -> None:
        seen = set()
        for parameter in parameters:
            line = parameter.name_line or parameter.line
            col = parameter.name_col or parameter.col
            self._validate_declared_name(parameter.name, "Parameter", line, col)
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

    def _claim_local_binding(self, name, kind, line=0, col=0) -> bool:
        """Claim a name in exactly the current lexical scope."""
        self._validate_declared_name(name, kind.capitalize(), line, col)
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


__all__ = ["DeclarationNamesMixin"]
