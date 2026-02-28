"""IR Generator: main class and module-level orchestration.

Walks AnalyzedProgram → IRModule. All lowering happens here and in sub-modules.
"""

from __future__ import annotations

from ...ast_nodes import (
    ClassDecl, EnumDecl, FunctionDecl, InterfaceDecl, Param,
    PreprocessorDirective, RichEnumDecl, StructDecl, TypedefDecl, TypeExpr,
)
from ...analyzer.core import AnalyzedProgram, ClassInfo
from ..nodes import (
    CType, IRBlock, IRFunctionDef, IRHelperDecl, IRModule, IRParam,
    IRStructDef, IRStructField, IRRawC,
)
from .types import type_to_c, mangle_generic_type, is_concrete_instance


_STANDARD_INCLUDES = [
    "stdio.h", "stdlib.h", "string.h", "stdbool.h", "stdint.h",
    "ctype.h", "math.h", "assert.h",
]


class IRGenerator:
    """Walks an analyzed AST and produces an IRModule."""

    def __init__(self, analyzed: AnalyzedProgram, *,
                 debug: bool = False, source_file: str = ""):
        self.analyzed = analyzed
        self.debug = debug
        self.source_file = source_file
        self.module = IRModule()
        self._lambda_counter = 0
        self._temp_counter = 0
        # Track which helpers are needed
        self._used_helpers: set[str] = set()
        # Track forward declarations
        self._forward_decls: list[str] = []
        # Current class context (for method lowering)
        self.current_class: ClassInfo | None = None
        self.current_class_name: str = ""
        # ARC: managed variable tracking
        # Stack of sets — each set contains (var_name, class_type_name) tuples
        # for variables auto-managed in the current scope
        self._managed_vars_stack: list[list[tuple[str, str]]] = []

    def generate(self) -> IRModule:
        """Generate the complete IR module from the analyzed program."""
        self._emit_includes()
        self._emit_forward_decls()
        self._emit_structs()
        self._emit_generic_collections()
        self._emit_enums()
        self._emit_declarations()
        self._emit_fn_ptr_typedefs()
        self._emit_helpers()
        return self.module

    def fresh_temp(self, prefix: str = "__tmp") -> str:
        """Generate a unique temporary variable name."""
        self._temp_counter += 1
        return f"{prefix}_{self._temp_counter}"

    def fresh_lambda_id(self) -> int:
        """Generate a unique lambda ID."""
        self._lambda_counter += 1
        return self._lambda_counter

    def use_helper(self, name: str):
        """Mark a runtime helper as used."""
        self._used_helpers.add(name)

    # --- ARC managed variable tracking ---

    def push_managed_scope(self):
        """Push a new scope for managed variable tracking."""
        self._managed_vars_stack.append([])

    def pop_managed_scope(self) -> list[tuple[str, str]]:
        """Pop the current managed scope, returning its managed vars."""
        if self._managed_vars_stack:
            return self._managed_vars_stack.pop()
        return []

    def register_managed_var(self, var_name: str, class_type: str):
        """Register a variable as auto-managed in the current scope."""
        if self._managed_vars_stack:
            self._managed_vars_stack[-1].append((var_name, class_type))

    def get_all_managed_vars(self) -> list[tuple[str, str]]:
        """Get all managed vars across all active scopes (for return/break)."""
        result = []
        for scope in self._managed_vars_stack:
            result.extend(scope)
        return result

    # --- Module setup ---

    def _emit_includes(self):
        for inc in _STANDARD_INCLUDES:
            self.module.includes.append(inc)
        # Check if try/catch is used
        for decl in self.analyzed.program.declarations:
            if _uses_trycatch(decl):
                self.module.includes.append("setjmp.h")
                break

    def _emit_forward_decls(self):
        """Emit forward declarations for all classes, structs, and functions."""
        # Phase 1: Type forward declarations (struct/class/generic)
        func_fwd_decls = []
        for decl in self.analyzed.program.declarations:
            if isinstance(decl, ClassDecl) and not decl.generic_params:
                self.module.forward_decls.append(
                    f"typedef struct {decl.name} {decl.name};")
            elif isinstance(decl, StructDecl):
                self.module.forward_decls.append(
                    f"typedef struct {decl.name} {decl.name};")
            elif isinstance(decl, FunctionDecl) and decl.body and decl.name != "main":
                # Defer function forward decls until after tuple struct defs
                ret_type = type_to_c(decl.return_type) if decl.return_type else "void"
                params = ", ".join(
                    type_to_c(p.type) + " " + p.name for p in decl.params)
                if not params:
                    params = "void"
                func_fwd_decls.append(f"{ret_type} {decl.name}({params});")
        # Forward declarations for concrete generic instances (skip T, K, V)
        # Skip Thread<T> — it maps to __btrc_thread_t*, not a struct
        seen = set()
        for base_name, instances in self.analyzed.generic_instances.items():
            if base_name == "Thread":
                continue
            for args in instances:
                if not is_concrete_instance(args):
                    continue
                mangled = mangle_generic_type(base_name, list(args))
                if mangled not in seen:
                    seen.add(mangled)
                    self.module.forward_decls.append(
                        f"typedef struct {mangled} {mangled};")
        # Emit tuple struct definitions (found by scanning node_types)
        self._emit_tuple_structs()
        # Phase 2: Function forward declarations (after all types are defined)
        self.module.forward_decls.extend(func_fwd_decls)

    def _emit_structs(self):
        """Emit struct definitions for plain structs."""
        from .classes import emit_struct_decl
        for decl in self.analyzed.program.declarations:
            if isinstance(decl, StructDecl):
                emit_struct_decl(self, decl)

    def _emit_generic_collections(self):
        """Emit monomorphized generic collection types."""
        from .generics.core import emit_generic_instances
        emit_generic_instances(self)

    def _emit_enums(self):
        """Emit enum definitions."""
        from .enums import emit_enum_decls
        emit_enum_decls(self)

    def _emit_declarations(self):
        """Emit classes, functions, and other top-level declarations."""
        from ...ast_nodes import VarDeclStmt
        from .classes import emit_class_decl
        from .functions import emit_function_decl
        for decl in self.analyzed.program.declarations:
            if isinstance(decl, ClassDecl):
                if not decl.generic_params:
                    emit_class_decl(self, decl)
            elif isinstance(decl, FunctionDecl):
                emit_function_decl(self, decl)
            elif isinstance(decl, VarDeclStmt):
                # Top-level variable → global variable in C
                c_type = type_to_c(decl.type) if decl.type else "int"
                if decl.initializer:
                    from .expressions import lower_expr
                    from .statements import _quick_text
                    init_text = _quick_text(lower_expr(self, decl.initializer))
                    self.module.raw_sections.append(
                        f"static {c_type} {decl.name} = {init_text};")
                else:
                    self.module.raw_sections.append(
                        f"static {c_type} {decl.name};")
            elif isinstance(decl, PreprocessorDirective):
                text = decl.text.strip()
                if text.startswith("#include"):
                    import re
                    m = re.search(r'[<"]([^>"]+)[>"]', text)
                    if m:
                        self.module.includes.append(m.group(1))
                    else:
                        self.module.includes.append(text)
                else:
                    self.module.raw_sections.append(text)

    def _emit_fn_ptr_typedefs(self):
        """Emit function pointer typedefs accumulated during code generation."""
        from .types import get_fn_ptr_typedefs
        for td in get_fn_ptr_typedefs():
            self.module.forward_decls.append(td)

    def _emit_helpers(self):
        """Register all used runtime helpers as IRHelperDecl entries."""
        from .helpers import collect_helpers
        collect_helpers(self)


    def _emit_tuple_structs(self):
        """Scan declarations for tuple types and emit struct definitions."""
        # mangled_name → list[TypeExpr] (generic_args)
        seen_tuples: dict[str, list[TypeExpr]] = {}
        # Scan all declarations for tuple return types and parameters
        for decl in self.analyzed.program.declarations:
            if isinstance(decl, FunctionDecl):
                self._collect_tuple_types(decl.return_type, seen_tuples)
                for p in decl.params:
                    self._collect_tuple_types(p.type, seen_tuples)
            elif isinstance(decl, ClassDecl):
                for member in decl.members:
                    from ...ast_nodes import MethodDecl as MD
                    if isinstance(member, MD):
                        self._collect_tuple_types(member.return_type, seen_tuples)
        # Also scan node_types for any tuple types used
        for _, t in self.analyzed.node_types.items():
            self._collect_tuple_types(t, seen_tuples)

        for mangled, args in seen_tuples.items():
            fields = []
            for i, arg in enumerate(args):
                fields.append(IRStructField(
                    c_type=CType(text=type_to_c(arg)), name=f"_{i}"))
            self.module.struct_defs.append(IRStructDef(name=mangled, fields=fields))
            self.module.forward_decls.append(
                f"typedef struct {mangled} {mangled};")

    def _collect_tuple_types(self, t: TypeExpr | None, seen: dict):
        """Recursively collect tuple types from a type expression."""
        if t is None:
            return
        if t.base == "Tuple" and t.generic_args:
            from .types import mangle_tuple_type
            mangled = mangle_tuple_type(t)
            if mangled not in seen:
                seen[mangled] = list(t.generic_args)
        for arg in t.generic_args:
            self._collect_tuple_types(arg, seen)


def generate_ir(analyzed: AnalyzedProgram, *,
                debug: bool = False, source_file: str = "") -> IRModule:
    """Generate an IR module from an analyzed program.

    This is the main entry point for the IR generation pipeline.
    """
    gen = IRGenerator(analyzed, debug=debug, source_file=source_file)
    return gen.generate()


def _uses_trycatch(decl) -> bool:
    """Check if a declaration uses try/catch (simple scan)."""
    from ...ast_nodes import TryCatchStmt, ThrowStmt, Block
    if isinstance(decl, (ClassDecl, FunctionDecl)):
        return _block_uses_trycatch(getattr(decl, 'body', None))
    return False


def _block_uses_trycatch(block) -> bool:
    from ...ast_nodes import TryCatchStmt, ThrowStmt, Block
    if block is None:
        return False
    if isinstance(block, Block):
        for s in block.statements:
            if isinstance(s, (TryCatchStmt, ThrowStmt)):
                return True
    return False
