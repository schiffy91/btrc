"""Cohesive translation unit IR lowering owner."""

from __future__ import annotations

import re
from dataclasses import fields, is_dataclass
from typing import TYPE_CHECKING

from src.compiler.python.analyzer.storage import StorageModel
from src.compiler.python.analyzer.types import TypeIdentity
from src.compiler.python.ir.nodes import (
    CType,
    IRFunctionDecl,
    IRGlobalDecl,
    IRHelperDecl,
    IRInclude,
    IRLiteral,
    IRMacroDef,
    IRParam,
    IRStructDef,
    IRStructField,
    IRStructForward,
    IRTypedefDef,
)
from src.compiler.python.syntax.ast.generated import (
    BraceInitializer,
    ClassDecl,
    EnumDecl,
    FieldDecl,
    FunctionDecl,
    ImportDecl,
    InterfaceDecl,
    ListLiteral,
    MethodDecl,
    PreprocessorDirective,
    PropertyDecl,
    RichEnumDecl,
    StructDecl,
    ThrowStmt,
    TryCatchStmt,
    TypedefDecl,
    VarDeclStmt,
)

from .calls import CallableProvenance, CallableSignatureLowerer
from .types import CodegenError, CTypeLowerer

if TYPE_CHECKING:
    from src.compiler.python.analyzer.program import AnalyzedProgram

    from .calls import CallableStorageBoundary
    from .classes import ClassLowerer
    from .collections import CollectionLowerer
    from .declarations import DeclarationLowerer
    from .exceptions import ExceptionLowerer
    from .expressions import ExpressionLowerer
    from .functions import FunctionLowerer
    from .generics import GenericSpecializer
    from .gpu import GpuLowerer
    from .ownership import CleanupSlotRegistry
    from .session import LoweringSession
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
_PUSH = re.compile("^#pragma\\s+pack\\s*\\(\\s*push\\s*(?:,\\s*(\\d+)\\s*)?\\)\\s*$")
_POP = re.compile("^#pragma\\s+pack\\s*\\(\\s*pop\\s*\\)\\s*$")
_DIRECTIVE = re.compile("^#\\s*([A-Za-z_][A-Za-z0-9_]*)(.*)$")
_DEFINE_NAME = re.compile("^\\s+([A-Za-z_][A-Za-z0-9_]*)(.*)$")
_IDENTIFIER = re.compile("^[A-Za-z_][A-Za-z0-9_]*$")
_INCLUDE = re.compile('^\\s*(?:<([^>\\r\\n]+)>|"([^"\\r\\n]+)")\\s*$')
_C11_TRIGRAPH = re.compile("\\?\\?[=/'()!<>-]")


class TranslationUnitLowerer:
    """Own translation unit lowering for one run."""

    def __init__(
        self,
        session: LoweringSession,
        analyzed: AnalyzedProgram,
        types: CTypeLowerer,
        signatures: CallableSignatureLowerer,
        type_identity: TypeIdentity,
        expressions: ExpressionLowerer,
        collections: CollectionLowerer,
        declarations: DeclarationLowerer,
        classes: ClassLowerer,
        functions: FunctionLowerer,
        specializer: GenericSpecializer,
        gpu: GpuLowerer,
        exceptions: ExceptionLowerer,
        callable_boundaries: CallableStorageBoundary,
        cleanup_slots: CleanupSlotRegistry,
    ) -> None:
        self._session = session
        self._analyzed = analyzed
        self._types = types
        self._signatures = signatures
        self._type_identity = type_identity
        self._expressions = expressions
        self._collections = collections
        self._declarations = declarations
        self._classes = classes
        self._functions = functions
        self._specializer = specializer
        self._gpu = gpu
        self._exceptions = exceptions
        self._callable_boundaries = callable_boundaries
        self._cleanup_slots = cleanup_slots
        self._preprocessor_prefix_end = 0

    def lower(self):
        """Run the ordered translation-unit phase cascade."""
        self._classes.configure_pack_alignments(self.declaration_pack_alignments(self._analyzed.program))
        self._emit_includes()
        self._emit_forward_decls()
        self._emit_fn_ptr_typedefs()
        self._emit_structs()
        self._gpu.emit_gpu_functions()
        for view in self._specializer.class_views():
            with self._session.specialization(view):
                self._classes.lower_specialization(view)
        for view in self._specializer.method_views():
            with self._session.specialization(view):
                self._functions.lower_specialization(view)
        self._emit_enums()
        self._emit_declarations()
        self._functions.materialize_default_helpers(
            self._session.deferred_specializations,
        )
        self._functions.materialize_deferred_functions()
        self._emit_fn_ptr_typedefs()
        self._cleanup_slots.finalize()
        self._exceptions.apply_setjmp_volatility(self._session.module)
        self._gpu.finalize_translation_unit()
        self._emit_helpers()
        return self._session.module

    def require_runtime_include(self, header: str) -> None:
        """Record a dependency on a hosted-libc header or runtime seam."""
        if self._session.freestanding:
            return
        else:
            include = IRInclude(header=header)
            if include not in self._session.module.preprocessor_decls:
                self._session.module.preprocessor_decls.insert(self._preprocessor_prefix_end, include)
                self._preprocessor_prefix_end += 1

    def _emit_includes(self):
        if not self._session.freestanding:
            self._session.module.preprocessor_decls.extend(IRMacroDef(name=name) for name in _STANDARD_FEATURE_MACROS)
            self._session.module.preprocessor_decls.extend(IRInclude(header=header) for header in _STANDARD_INCLUDES)
        self._preprocessor_prefix_end = len(self._session.module.preprocessor_decls)
        if any(TranslationUnitLowerer.uses_trycatch(decl) for decl in self._analyzed.program.declarations):
            self.require_runtime_include("setjmp.h")

    def _emit_forward_decls(self):
        """Collect typed type and callable declarations."""
        function_decls: list[IRFunctionDecl] = []
        for decl in self._analyzed.program.declarations:
            if isinstance(decl, EnumDecl) and decl.name:
                function_decls.append(TranslationUnitLowerer._enum_to_string_decl(decl.name))
            elif (isinstance(decl, ClassDecl) and (not decl.generic_params)) or isinstance(decl, StructDecl):
                forward = IRStructForward(name=decl.name)
                if forward not in self._session.module.struct_forwards:
                    self._session.module.struct_forwards.append(forward)
                if isinstance(decl, ClassDecl) and (not decl.generic_params):
                    class_info = self._analyzed.class_table[decl.name]
                    function_decls.append(
                        IRFunctionDecl(
                            name=f"{decl.name}_destroy",
                            return_type=CType(text="void"),
                            params=[IRParam(c_type=CType(text="void*"), name="object")],
                        )
                    )
                    function_decls.extend(
                        self._classes.class_callable_declarations(
                            decl,
                            class_info,
                        )
                    )
            elif isinstance(decl, RichEnumDecl):
                self._session.module.struct_forwards.append(IRStructForward(name=decl.name))
                for variant in decl.variants:
                    function_decls.append(
                        IRFunctionDecl(
                            name=f"{decl.name}_{variant.name}",
                            return_type=CType(text=decl.name),
                            params=[self._signatures.lower_source_param(param) for param in variant.params],
                            is_static=True,
                        )
                    )
                function_decls.append(TranslationUnitLowerer._enum_to_string_decl(decl.name))
            elif isinstance(decl, FunctionDecl) and decl.body and (not decl.is_gpu) and (decl.name != "main"):
                function_decls.append(
                    IRFunctionDecl(
                        name=self._signatures.source_function_c_name(decl.name),
                        return_type=CType(text=self._types.render(decl.return_type)),
                        params=[self._signatures.lower_source_param(param) for param in decl.params],
                        is_static=bool(decl.return_type.is_static),
                    )
                )
        builtin_generics = {"Thread", "Mutex"}
        seen = set()
        for base_name, instances in self._analyzed.generic_instances.items():
            if base_name in builtin_generics:
                continue
            for args in instances:
                mangled = self._type_identity.specialization_symbol(base_name, args)
                if mangled not in seen:
                    seen.add(mangled)
                    self._session.module.struct_forwards.append(IRStructForward(name=mangled))
        self._emit_tuple_structs()
        self._session.module.function_decls.extend(function_decls)

    def _emit_structs(self):
        for decl in self._analyzed.program.declarations:
            if isinstance(decl, StructDecl):
                self._classes.emit_struct_decl(
                    decl,
                )

    def _emit_enums(self):
        self._declarations.emit_enum_decls()

    def _emit_declarations(self):
        """Emit executable and non-executable top-level declarations."""
        emitted_globals = set()
        declarations = self._analyzed.program.declarations
        for decl in declarations:
            if isinstance(decl, ImportDecl):
                continue
            if isinstance(decl, ClassDecl):
                if not decl.generic_params:
                    self._classes.emit_class_decl(
                        decl,
                    )
            elif isinstance(decl, FunctionDecl):
                self._functions.emit_function_decl(
                    decl,
                )
            elif isinstance(decl, TypedefDecl):
                self._session.module.typedef_defs.append(
                    IRTypedefDef(
                        target_type=CType(text=self._types.render(decl.original)),
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
                        if not (candidate.type and candidate.type.is_extern and (candidate.initializer is None))
                    ),
                    None,
                )
                chosen = definition or group[0]
                paired_extern = definition is not None and any(
                    candidate.type and candidate.type.is_extern for candidate in group
                )
                self._emit_global_var(chosen, force_external=paired_extern)
            elif isinstance(decl, PreprocessorDirective):
                self.lower_preprocessor(decl)

    def _emit_global_var(self, decl: VarDeclStmt, *, force_external=False):
        self.emit_global_var(decl, force_external=force_external)

    def _emit_fn_ptr_typedefs(self):
        """Emit function-pointer typedefs accumulated during lowering."""
        self._session.module.function_pointer_typedefs.extend(self._types.consume_function_pointer_typedefs())

    def _emit_helpers(self):
        for definition in self._session.runtime_helpers.definitions():
            declaration = IRHelperDecl.from_runtime(definition)
            for header in declaration.required_headers:
                self.require_runtime_include(header)
            self._session.module.helper_decls.append(declaration)

    def _emit_tuple_structs(self):
        seen = {}
        for declaration in self._analyzed.program.declarations:
            for type_expr in TranslationUnitLowerer._declaration_types(declaration):
                self._collect_tuple_types(type_expr, seen)
        for type_expr in self._analyzed.node_types.values():
            self._collect_tuple_types(type_expr, seen)
        for mangled, arguments in seen.items():
            self._session.module.struct_defs.append(
                IRStructDef(
                    name=mangled,
                    fields=[
                        IRStructField(
                            c_type=CType(text=self._types.render(argument)),
                            name=f"_{index}",
                            is_volatile=bool(argument.is_volatile),
                            effective_is_volatile=StorageModel.effective_outer_volatile(
                                argument, self._analyzed.typedef_table
                            ),
                        )
                        for index, argument in enumerate(arguments)
                    ],
                )
            )
            forward = IRStructForward(name=mangled)
            if forward not in self._session.module.struct_forwards:
                self._session.module.struct_forwards.append(forward)

    @staticmethod
    def uses_trycatch(decl) -> bool:
        """Return whether an AST declaration contains exception syntax.

        Exception capability is a module-wide ownership contract: a try frame in a
        lambda may catch a throw from an allocating constructor several calls away.
        Walk every generated AST field instead of maintaining a second, incomplete
        list of statement shapes.  The identity set keeps the conservative walk
        safe if an analyzer ever introduces shared or cyclic annotations.
        """
        return TranslationUnitLowerer._value_uses_trycatch(decl, set())

    @staticmethod
    def program_uses_trycatch(program) -> bool:
        """Return whether any declaration establishes an exception contract.

        This deliberately runs before dead-code elimination.  A reachable bundled
        stdlib try frame can catch a throw that crosses user or stdlib callees, so
        source provenance is not a safe substitute for a whole-program call graph.
        """
        return any(
            TranslationUnitLowerer.uses_trycatch(declaration) for declaration in getattr(program, "declarations", ())
        )

    @staticmethod
    def _value_uses_trycatch(value, seen: set[int]) -> bool:
        if value is None:
            return False
        if isinstance(value, (ThrowStmt, TryCatchStmt)):
            return True
        if not (is_dataclass(value) or isinstance(value, (dict, list, tuple, set, frozenset))):
            return False
        identity = id(value)
        if identity in seen:
            return False
        seen.add(identity)
        if isinstance(value, dict):
            return any(
                TranslationUnitLowerer._value_uses_trycatch(item, seen) for pair in value.items() for item in pair
            )
        if isinstance(value, (list, tuple, set, frozenset)):
            return any(TranslationUnitLowerer._value_uses_trycatch(item, seen) for item in value)
        return any(
            TranslationUnitLowerer._value_uses_trycatch(
                getattr(value, field.name),
                seen,
            )
            for field in fields(value)
        )

    @staticmethod
    def _enum_to_string_decl(name: str) -> IRFunctionDecl:
        """Typed declaration shared by plain and rich enum stringification."""
        return IRFunctionDecl(
            name=f"{name}_toString",
            return_type=CType(text="const char*"),
            params=[IRParam(c_type=CType(text=name), name="val")],
            is_static=True,
        )

    def emit_global_var(self, declaration, *, force_external=False) -> None:
        provenance = CallableProvenance(self._analyzed, self._session, self._types, self._signatures)
        if declaration.initializer is not None:
            self._callable_boundaries.reject_persistent_escape(
                declaration.type,
                declaration.initializer,
                "global storage",
                provenance,
            )
        if TranslationUnitLowerer._materialized_array(declaration):
            self._emit_array_global(declaration, force_external, provenance)
            return
        type_expr = declaration.type
        is_extern = bool(type_expr and type_expr.is_extern and (not force_external))
        self._session.module.global_decls.append(
            IRGlobalDecl(
                c_type=CType(text=self._types.render(type_expr) if type_expr else "int"),
                name=declaration.name,
                init=self._expressions.lower_static_initializer(
                    declaration.initializer,
                    provenance,
                )
                if declaration.initializer and (not is_extern)
                else None,
                is_static=not (is_extern or force_external),
                is_extern=is_extern,
                is_volatile=bool(type_expr and type_expr.is_volatile),
                effective_is_volatile=StorageModel.effective_outer_volatile(type_expr, self._analyzed.typedef_table),
            )
        )

    @staticmethod
    def _materialized_array(declaration) -> bool:
        type_expr = declaration.type
        return bool(
            type_expr
            and type_expr.is_array
            and (
                type_expr.array_size is not None
                or isinstance(declaration.initializer, (BraceInitializer, ListLiteral))
                or type_expr.is_extern
            )
        )

    def _emit_array_global(
        self,
        declaration,
        force_external,
        provenance: CallableProvenance,
    ) -> None:
        from src.compiler.python.analyzer.types import TypeSystem

        type_expr = declaration.type
        element_type = TypeSystem.strip_outer_storage(type_expr, array=True)
        is_extern = bool(type_expr.is_extern and (not force_external))
        initializer = declaration.initializer
        self._session.module.global_decls.append(
            IRGlobalDecl(
                c_type=CType(text=self._types.render(element_type)),
                name=declaration.name,
                init=self._expressions.lower_static_initializer(
                    initializer,
                    provenance,
                )
                if initializer
                else None,
                array_size=self._expressions.lower_expr(
                    type_expr.array_size,
                    provenance,
                )
                if type_expr.array_size is not None
                else IRLiteral(text=str(len(initializer.elements)))
                if initializer is not None
                else None,
                is_unsized_array=type_expr.array_size is None and initializer is None,
                is_static=not (is_extern or force_external),
                is_extern=is_extern,
                is_volatile=bool(type_expr.is_volatile),
                effective_is_volatile=StorageModel.effective_outer_volatile(type_expr, self._analyzed.typedef_table),
            )
        )

    @staticmethod
    def declaration_pack_alignments(program) -> dict[int, int]:
        """Map packed class/struct declarations to their active alignment."""
        stack: list[int | None] = []
        current: int | None = None
        result: dict[int, int] = {}
        for declaration in program.declarations:
            if isinstance(declaration, PreprocessorDirective):
                text = declaration.text.strip()
                push = _PUSH.fullmatch(text)
                if push:
                    stack.append(current)
                    if push.group(1) is not None:
                        alignment = int(push.group(1))
                        if alignment not in {1, 2, 4, 8, 16}:
                            raise CodegenError(f"unsupported #pragma pack alignment {alignment}")
                        current = alignment
                    continue
                if _POP.fullmatch(text):
                    if not stack:
                        raise CodegenError("#pragma pack(pop) has no matching push")
                    current = stack.pop()
                    continue
            if current is not None and isinstance(declaration, (ClassDecl, StructDecl)):
                result[id(declaration)] = current
        if stack:
            raise CodegenError("#pragma pack(push) has no matching pop")
        return result

    @staticmethod
    def is_pack_pragma(text: str) -> bool:
        """Whether a source directive is represented by struct IR metadata."""
        stripped = text.strip()
        return bool(_PUSH.fullmatch(stripped) or _POP.fullmatch(stripped))

    def lower_preprocessor(self, declaration: PreprocessorDirective) -> None:
        """Lower one directive or reject it before C emission."""
        if _C11_TRIGRAPH.search(declaration.text):
            raise CodegenError("C11 trigraphs in preprocessor directives are unsupported")
        if "\n" in declaration.text or "\r" in declaration.text:
            raise CodegenError("multi-line preprocessor directives are unsupported")
        text = declaration.text.strip()
        if text.endswith("\\"):
            raise CodegenError("multi-line preprocessor directives are unsupported")
        if self.is_pack_pragma(text):
            return
        match = _DIRECTIVE.fullmatch(text)
        if match is None:
            raise CodegenError(f"malformed preprocessor directive: {text!r}")
        directive, payload = match.groups()
        if directive == "include":
            self._session.module.preprocessor_decls.append(self._parse_include(payload, text))
        elif directive == "define":
            self._session.module.preprocessor_decls.append(self._parse_define(payload, text))
        elif directive == "pragma":
            raise CodegenError(f"unsupported #pragma directive: {text}")
        else:
            raise CodegenError(f"unsupported preprocessor directive '#{directive}'")

    @staticmethod
    def _parse_include(payload: str, source: str) -> IRInclude:
        match = _INCLUDE.fullmatch(payload)
        if match is None:
            raise CodegenError(f"malformed #include directive: {source}")
        system_header, local_header = match.groups()
        header = system_header or local_header
        if not header:
            raise CodegenError(f"malformed #include directive: {source}")
        try:
            return IRInclude(header=header, is_system=system_header is not None)
        except (TypeError, ValueError) as error:
            raise CodegenError(f"malformed #include directive: {source}") from error

    @staticmethod
    def _parse_define(payload: str, source: str) -> IRMacroDef:
        match = _DEFINE_NAME.fullmatch(payload)
        if match is None:
            raise CodegenError(f"malformed #define directive: {source}")
        name, suffix = match.groups()
        if not suffix.startswith("("):
            try:
                return IRMacroDef(name=name, replacement=suffix.lstrip())
            except (TypeError, ValueError) as error:
                raise CodegenError(f"malformed #define directive: {source}") from error
        close = suffix.find(")")
        if close < 0:
            raise CodegenError(f"malformed function-like #define: {source}")
        parameter_text = suffix[1:close].strip()
        params = [] if not parameter_text else [parameter.strip() for parameter in parameter_text.split(",")]
        if any(
            (
                not _IDENTIFIER.fullmatch(parameter) and (not (parameter == "..." and index == len(params) - 1))
                for index, parameter in enumerate(params)
            )
        ):
            raise CodegenError(f"invalid function-like macro parameters: {source}")
        if len(params) != len(set(params)):
            raise CodegenError(f"duplicate function-like macro parameter: {source}")
        try:
            return IRMacroDef(name=name, params=params, replacement=suffix[close + 1 :].lstrip())
        except (TypeError, ValueError) as error:
            raise CodegenError(f"malformed #define directive: {source}") from error

    @staticmethod
    def _declaration_types(declaration):
        if isinstance(declaration, FunctionDecl):
            yield declaration.return_type
            yield from (parameter.type for parameter in declaration.params)
        elif isinstance(declaration, ClassDecl):
            for member in declaration.members:
                if isinstance(member, (FieldDecl, PropertyDecl)):
                    yield member.type
                elif isinstance(member, MethodDecl):
                    yield member.return_type
                    yield from (parameter.type for parameter in member.params)
        elif isinstance(declaration, InterfaceDecl):
            for method in declaration.methods:
                yield method.return_type
                yield from (parameter.type for parameter in method.params)
        elif isinstance(declaration, StructDecl):
            yield from (field.type for field in declaration.fields)
        elif isinstance(declaration, RichEnumDecl):
            for variant in declaration.variants:
                yield from (parameter.type for parameter in variant.params)
        elif isinstance(declaration, TypedefDecl):
            yield declaration.original
        elif isinstance(declaration, VarDeclStmt) and declaration.type is not None:
            yield declaration.type

    def _collect_tuple_types(self, type_expr, seen) -> None:
        if type_expr is None:
            return
        for argument in type_expr.generic_args:
            self._collect_tuple_types(argument, seen)
        if type_expr.base == "Tuple" and type_expr.generic_args:
            seen.setdefault(
                self._type_identity.generic_symbol("Tuple", type_expr.generic_args), list(type_expr.generic_args)
            )
