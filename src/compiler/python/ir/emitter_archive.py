"""Archive header and implementation emission."""

from __future__ import annotations

from .nodes import IRInclude, IRModule


class _ArchiveEmitterMixin:
    def emit_header(self, module: IRModule, shared_decls: dict | None = None) -> str:
        """Emit the public header for a precompiled archive."""

        module.validate_declarations()
        shared_decls = shared_decls or {}
        self._lines = []
        self._indent = 0

        self._line("#ifndef BTRC_STDLIB_H")
        self._line("#define BTRC_STDLIB_H")
        self._line("")

        self._emit_preprocessor_declarations(module)

        for helper in module.helper_decls:
            self._raw(shared_decls.get(helper.name, helper.c_source))
            self._line("")

        for declaration in module.struct_forwards:
            self._emit_struct_forward(declaration)
        if module.struct_forwards:
            self._line("")

        for declaration in module.ordered_type_declarations:
            self._emit_type_declaration(declaration)

        for declaration in module.function_decls:
            self._emit_function_decl(declaration)
        if module.function_decls:
            self._line("")

        for declaration in module.global_decls:
            if declaration.is_extern:
                self._emit_global_decl(declaration)

        self._line("#endif")
        return "\n".join(self._lines) + "\n"

    def emit_impl(self, module: IRModule, header_include: str, shared_names: set | None = None) -> str:
        """Emit the definition-only implementation for a precompiled archive."""

        module.validate_declarations()
        shared_names = shared_names or set()
        self._lines = []
        self._indent = 0

        self._line(self._include_text(IRInclude(header=header_include, is_system=False)))
        self._line("")

        for helper in module.helper_decls:
            if helper.name in shared_names:
                self._raw(helper.c_source)
                self._line("")

        for declaration in module.global_decls:
            self._emit_global_decl(declaration)
        if module.global_decls:
            self._line("")

        for kernel in module.gpu_kernels:
            self._emit_gpu_kernel(kernel)

        for func in module.function_defs:
            self._emit_function(func)

        return "\n".join(self._lines) + "\n"
