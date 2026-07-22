"""Variable-declaration analysis and local symbol construction."""

from ..ast_nodes import (
    BraceInitializer,
    Identifier,
    LambdaExpr,
    ListLiteral,
    MapLiteral,
    TypeExpr,
    VarDeclStmt,
)
from ..type_identity import is_semantic_scalar_void
from .core import SymbolInfo


class VariableDeclarationAnalysisMixin:
    def _analyze_var_decl(self, stmt):
        is_global = self.scope is self.global_scope
        define_binding = is_global or self._claim_local_binding(
            stmt.name,
            "variable",
            stmt.name_line or stmt.line,
            stmt.name_col or stmt.col,
        )
        explicit_type = stmt.type is not None
        if stmt.type is None:
            if stmt.initializer is None:
                self.context.error(f"'var' declaration of '{stmt.name}' requires an initializer", stmt.line, stmt.col)
                stmt.type = TypeExpr(base="int")
                if define_binding:
                    self.scope.define(stmt.name, self._var_symbol(stmt))
                return
            self._analyze_gpu_array_initializer(stmt.initializer, stmt.type)
            inferred = self._infer_type(stmt.initializer)
            if inferred is None:
                self.context.error(f"Cannot infer type for 'var' declaration of '{stmt.name}'", stmt.line, stmt.col)
                stmt.type = TypeExpr(base="int")
                if define_binding:
                    self.scope.define(stmt.name, self._var_symbol(stmt))
                return
            if is_semantic_scalar_void(inferred):
                self.context.error(
                    f"Cannot assign void expression to variable '{stmt.name}'",
                    stmt.line,
                    stmt.col,
                )
                # Keep later analysis/codegen on a concrete recovery type;
                # a local object of C type ``void`` is never valid.
                stmt.type = TypeExpr(base="int")
                if define_binding:
                    self.scope.define(stmt.name, self._var_symbol(stmt))
                return
            stmt.type = self._inferred_array_binding_type(
                inferred,
                stmt.initializer,
            )
            self._validate_volatile_reference_conversion(
                stmt.type,
                stmt.initializer,
                f"Variable '{stmt.name}'",
                stmt.line,
                stmt.col,
            )
            if stmt.type.base in self.declarations.class_table and stmt.type.pointer_depth == 0:
                stmt.type = self._upgrade_class_type(stmt.type)
            self._validate_thread_handle_copy(
                stmt.type,
                stmt.initializer,
                stmt.line,
                stmt.col,
            )
            # ARC aliasing warning: var q = p where p is a managed class-type var
            self._check_alias_warning(stmt)
            self._collect_generic_instances(stmt.type)
            self._validate_callable_storage(stmt.type, stmt.initializer, explicit_type, stmt.line, stmt.col)
            if not self._expression_produces_owned_result(stmt.initializer):
                self._validate_opaque_borrow_storage(
                    stmt.type,
                    stmt.initializer,
                    f"Variable '{stmt.name}'",
                    stmt.line,
                    stmt.col,
                )
            self._validate_variable_storage(stmt, is_global=is_global)
            if define_binding:
                self.scope.define(stmt.name, self._var_symbol(stmt))
            return

        stmt.type = self._upgrade_class_type(stmt.type)
        self._collect_generic_instances(stmt.type)
        if stmt.initializer:
            self._analyze_gpu_array_initializer(stmt.initializer, stmt.type)
            self._validate_array_object_initializer(
                stmt.type,
                stmt.initializer,
                f"Initializer for '{stmt.name}'",
                stmt.line,
                stmt.col,
            )
            self._contextualize_aggregate_initializer(
                stmt.type,
                stmt.initializer,
                f"Initializer for '{stmt.name}'",
                stmt.line,
                stmt.col,
            )
            self._validate_fixed_array_initializer(
                stmt.type,
                stmt.initializer,
                f"Initializer for '{stmt.name}'",
                stmt.line,
                stmt.col,
            )
            self._validate_callable_storage(stmt.type, stmt.initializer, explicit_type, stmt.line, stmt.col)
            if isinstance(stmt.initializer, (ListLiteral, MapLiteral, BraceInitializer)):
                self._contextualize_collection_initializer(
                    stmt.type,
                    stmt.initializer,
                    f"Initializer for '{stmt.name}'",
                    stmt.line,
                    stmt.col,
                )
            self._contextualize_generic_constructor(stmt.type, stmt.initializer)
            init_type = self._infer_type(stmt.initializer)
            self._validate_managed_string_source(
                stmt.type,
                stmt.initializer,
                f"Initializer for '{stmt.name}'",
                stmt.line,
                stmt.col,
            )
            self._validate_volatile_reference_conversion(
                stmt.type,
                stmt.initializer,
                f"Initializer for '{stmt.name}'",
                stmt.line,
                stmt.col,
            )
            if not self._expression_produces_owned_result(stmt.initializer):
                self._validate_opaque_borrow_storage(
                    stmt.type,
                    stmt.initializer,
                    f"Variable '{stmt.name}'",
                    stmt.line,
                    stmt.col,
                )
            self._validate_thread_handle_copy(
                stmt.type,
                stmt.initializer,
                stmt.line,
                stmt.col,
            )
            if is_semantic_scalar_void(init_type):
                self.context.error(f"Cannot assign void expression to variable '{stmt.name}'", stmt.line, stmt.col)
            elif init_type and stmt.type and not self._types_compatible(stmt.type, init_type):
                is_empty_literal = (
                    (isinstance(stmt.initializer, ListLiteral) and not stmt.initializer.elements)
                    or (isinstance(stmt.initializer, MapLiteral) and not stmt.initializer.entries)
                    or isinstance(stmt.initializer, BraceInitializer)
                )
                if not is_empty_literal:
                    self.context.error(
                        f"Cannot assign '{init_type.base}' to variable '{stmt.name}' of type '{stmt.type.base}'",
                        stmt.line,
                        stmt.col,
                    )
            # Stamp typed aggregate literals with the declared type so
            # monomorphization uses the declaration's element domain.
            if (
                stmt.type
                and stmt.type.generic_args
                and isinstance(stmt.initializer, (ListLiteral, MapLiteral, BraceInitializer))
            ):
                self._record_node_type(stmt.initializer, stmt.type)
                self._collect_generic_instances(stmt.type)
        self._validate_variable_storage(stmt, is_global=is_global)
        if define_binding:
            self.scope.define(stmt.name, self._var_symbol(stmt))

    def _var_symbol(self, stmt: VarDeclStmt) -> SymbolInfo:
        """SymbolInfo for a local var decl, pinned to its name token span."""
        nl = stmt.name_line or stmt.line
        nc = stmt.name_col or stmt.col
        symbol = self._local_symbol(
            stmt.name,
            self._array_value_type(stmt.type),
            "variable",
            nl,
            nc,
        )
        if isinstance(stmt.initializer, LambdaExpr):
            symbol.captures_environment = bool(stmt.initializer.captures)
        elif isinstance(stmt.initializer, Identifier):
            source = self.scope.lookup(stmt.initializer.name)
            symbol.captures_environment = bool(source and source.captures_environment)
        return symbol

    def _check_alias_warning(self, stmt: VarDeclStmt):
        """Warn when a variable aliases a managed class-typed variable."""
        if not isinstance(stmt.initializer, Identifier):
            return
        src_name = stmt.initializer.name
        src_sym = self.scope.lookup(src_name)
        if not src_sym or not src_sym.type or src_sym.type.base not in self.declarations.class_table:
            return
        self.context.warning(
            f"Aliasing managed variable '{src_name}' — "
            f"'{stmt.name}' shares the same reference without incrementing refcount. "
            f"Use 'keep {stmt.name};' if both variables should own the object",
            stmt.line,
            stmt.col,
        )


__all__ = ["VariableDeclarationAnalysisMixin"]
