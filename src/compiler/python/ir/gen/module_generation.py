"""Translation-unit declaration and dependency generation."""

from ...ast_nodes import (
    ClassDecl,
    EnumDecl,
    FunctionDecl,
    ImportDecl,
    PreprocessorDirective,
    RichEnumDecl,
    StructDecl,
    TypedefDecl,
    VarDeclStmt,
)
from ..nodes import (
    CType,
    IRFunctionDecl,
    IRInclude,
    IRMacroDef,
    IRParam,
    IRStructForward,
    IRTypedefDef,
)
from .feature_scan import uses_trycatch
from .function_symbols import source_function_c_name
from .parameters import lower_source_param
from .types import mangle_generic_type

_STANDARD_FEATURE_MACROS = ("_DEFAULT_SOURCE", "_DARWIN_C_SOURCE")
_STANDARD_INCLUDES = [
    "stdio.h",
    "stdlib.h",
    "string.h",
    "stdbool.h",
    "stdint.h",
    "ctype.h",
    "math.h",
    "assert.h",
    "limits.h",
]


def _enum_to_string_decl(name: str) -> IRFunctionDecl:
    """Typed declaration shared by plain and rich enum stringification."""

    return IRFunctionDecl(
        name=f"{name}_toString",
        return_type=CType(text="const char*"),
        params=[IRParam(c_type=CType(text=name), name="val")],
        is_static=True,
    )


class _ModuleGenerationMixin:
    def require_runtime_include(self, header: str) -> None:
        """Record a dependency on a hosted-libc header or runtime seam."""

        if self.freestanding:
            # The structured dependency pass derives freestanding features
            # from surviving helper metadata after DCE. Direct setjmp/longjmp
            # requirements remain visible in ordinary IR.
            return
        else:
            include = IRInclude(header=header)
            if include not in self.module.preprocessor_decls:
                self.module.preprocessor_decls.insert(
                    self._preprocessor_prefix_end,
                    include,
                )
                self._preprocessor_prefix_end += 1

    def _emit_includes(self):
        if not self.freestanding:
            self.module.preprocessor_decls.extend(IRMacroDef(name=name) for name in _STANDARD_FEATURE_MACROS)
            self.module.preprocessor_decls.extend(IRInclude(header=header) for header in _STANDARD_INCLUDES)
        self._preprocessor_prefix_end = len(self.module.preprocessor_decls)
        if any(uses_trycatch(decl) for decl in self.analyzed.program.declarations):
            self.require_runtime_include("setjmp.h")

    def _emit_forward_decls(self):
        """Collect typed type and callable declarations."""

        function_decls: list[IRFunctionDecl] = []
        for decl in self.analyzed.program.declarations:
            if isinstance(decl, EnumDecl) and decl.name:
                function_decls.append(_enum_to_string_decl(decl.name))
            elif (isinstance(decl, ClassDecl) and not decl.generic_params) or isinstance(decl, StructDecl):
                forward = IRStructForward(name=decl.name)
                if forward not in self.module.struct_forwards:
                    self.module.struct_forwards.append(forward)
                if isinstance(decl, ClassDecl) and not decl.generic_params:
                    from .class_declarations import class_callable_declarations

                    class_info = self.analyzed.class_table[decl.name]
                    function_decls.append(
                        IRFunctionDecl(
                            name=f"{decl.name}_destroy",
                            return_type=CType(text="void"),
                            params=[
                                IRParam(
                                    c_type=CType(text="void*"),
                                    name="object",
                                )
                            ],
                        )
                    )
                    function_decls.extend(
                        class_callable_declarations(
                            decl,
                            class_info,
                            self.analyzed.class_table,
                            self.analyzed,
                            self.type_renderer,
                        )
                    )
            elif isinstance(decl, RichEnumDecl):
                self.module.struct_forwards.append(IRStructForward(name=decl.name))
                function_decls.extend(
                    IRFunctionDecl(
                        name=f"{decl.name}_{variant.name}",
                        return_type=CType(text=decl.name),
                        params=[
                            lower_source_param(
                                param,
                                self.type_renderer.render,
                                analyzed=self.analyzed,
                            )
                            for param in variant.params
                        ],
                        is_static=True,
                    )
                    for variant in decl.variants
                )
                function_decls.append(_enum_to_string_decl(decl.name))
            elif isinstance(decl, FunctionDecl) and decl.body and not decl.is_gpu and decl.name != "main":
                function_decls.append(
                    IRFunctionDecl(
                        name=source_function_c_name(self.analyzed, decl.name),
                        return_type=CType(text=self.type_renderer.render(decl.return_type)),
                        params=[
                            lower_source_param(
                                param,
                                self.type_renderer.render,
                                analyzed=self.analyzed,
                            )
                            for param in decl.params
                        ],
                        is_static=bool(decl.return_type.is_static),
                    )
                )

        builtin_generics = {"Thread", "Mutex"}
        seen = set()
        for base_name, instances in self.analyzed.generic_instances.items():
            if base_name in builtin_generics:
                continue
            for args in instances:
                mangled = mangle_generic_type(base_name, list(args))
                if mangled not in seen:
                    seen.add(mangled)
                    self.module.struct_forwards.append(IRStructForward(name=mangled))

        self._emit_tuple_structs()
        self.module.function_decls.extend(function_decls)

    def _emit_structs(self):
        from .classes import emit_struct_decl

        for decl in self.analyzed.program.declarations:
            if isinstance(decl, StructDecl):
                emit_struct_decl(self, decl, self.type_renderer)

    def _emit_generic_collections(self):
        from .generics.core import emit_generic_instances
        from .generics.methods_mono import emit_generic_method_instances

        emit_generic_instances(self, self.type_renderer)
        emit_generic_method_instances(self, self.type_renderer)

    def _emit_enums(self):
        from .enums import emit_enum_decls

        emit_enum_decls(self, self.type_renderer)

    def _emit_declarations(self):
        """Emit executable and non-executable top-level declarations."""

        from .classes import emit_class_decl
        from .functions import emit_function_decl

        emitted_globals = set()
        declarations = self.analyzed.program.declarations
        for decl in declarations:
            if isinstance(decl, ImportDecl):
                continue
            if isinstance(decl, ClassDecl):
                if not decl.generic_params:
                    emit_class_decl(self, decl, self.type_renderer)
            elif isinstance(decl, FunctionDecl):
                emit_function_decl(self, decl, self.type_renderer)
            elif isinstance(decl, TypedefDecl):
                self.module.typedef_defs.append(
                    IRTypedefDef(
                        target_type=CType(text=self.type_renderer.render(decl.original)),
                        name=decl.alias,
                        is_volatile=bool(decl.original.is_volatile),
                    )
                )
            elif isinstance(decl, VarDeclStmt):
                if decl.name in emitted_globals:
                    continue
                emitted_globals.add(decl.name)
                group = [
                    candidate
                    for candidate in declarations
                    if isinstance(candidate, VarDeclStmt) and candidate.name == decl.name
                ]
                definition = next(
                    (
                        candidate
                        for candidate in group
                        if not (candidate.type and candidate.type.is_extern and candidate.initializer is None)
                    ),
                    None,
                )
                chosen = definition or group[0]
                paired_extern = definition is not None and any(
                    candidate.type and candidate.type.is_extern for candidate in group
                )
                self._emit_global_var(chosen, force_external=paired_extern)
            elif isinstance(decl, PreprocessorDirective):
                from .preprocessor import lower_preprocessor

                lower_preprocessor(self, decl)

    def _emit_global_var(self, decl: VarDeclStmt, *, force_external=False):
        from .module_globals import emit_global_var

        emit_global_var(
            self,
            decl,
            self.type_renderer,
            force_external=force_external,
        )

    def _emit_fn_ptr_typedefs(self):
        """Emit function-pointer typedefs accumulated during lowering."""

        self.module.function_pointer_typedefs.extend(self.type_renderer.consume_function_pointer_typedefs())

    def _emit_helpers(self):
        self.helpers.materialize(self.module, self.require_runtime_include)

    def _emit_tuple_structs(self):
        from .tuple_declarations import emit_tuple_structs

        emit_tuple_structs(self, self.type_renderer)
