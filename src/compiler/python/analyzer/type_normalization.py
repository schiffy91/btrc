"""Order-independent normalization of registered declaration types."""

from dataclasses import replace

from ..ast_nodes import (
    ClassDecl,
    FieldDecl,
    FunctionDecl,
    InterfaceDecl,
    MethodDecl,
    PropertyDecl,
    RichEnumDecl,
    StructDecl,
    TypedefDecl,
    VarDeclStmt,
)


class TypeNormalizationMixin:
    def _upgrade_class_type(self, type_expr, shadowed_names=None):
        """Auto-upgrade class references without capturing type parameters.

        A lexical generic parameter shadows a top-level declaration with the
        same spelling. This matters in composed programs: a user ``class T``
        must not turn every stdlib ``Vector<T>`` template parameter into a
        pointer to that unrelated class.
        """
        if type_expr is None:
            return type_expr
        if shadowed_names is None:
            shadowed_names = set()
            if self.current_class is not None:
                shadowed_names.update(self.current_class.generic_params)
            if self.current_method is not None:
                shadowed_names.update(self.current_method.generic_params)
        else:
            shadowed_names = set(shadowed_names)

        auto_upgraded = getattr(type_expr, "auto_upgraded", False)
        upgraded_args = type_expr.generic_args
        if type_expr.generic_args:
            upgraded_args = [self._upgrade_class_type(argument, shadowed_names) for argument in type_expr.generic_args]
            if upgraded_args != type_expr.generic_args:
                type_expr = replace(type_expr, generic_args=upgraded_args)

        if type_expr.base not in self.class_table or type_expr.base in shadowed_names:
            return type_expr

        # An ``auto_upgraded`` stamp marks pointers synthesized here, so
        # re-analyzing a shared AST (LSP unit caches) stays idempotent instead
        # of reporting its own upgrade as a redundant pointer.
        if type_expr.pointer_depth > 0 and not type_expr.is_nullable and not auto_upgraded:
            self._error(
                f"Redundant pointer for class type '{type_expr.base}' — "
                f"classes are always heap-allocated. "
                f"Use '{type_expr.base}' instead of '{type_expr.base}*'",
                type_expr.line,
                type_expr.col,
            )
        upgraded = replace(
            type_expr,
            generic_args=upgraded_args,
            pointer_depth=1,
        )
        upgraded.auto_upgraded = True
        return upgraded

    def _normalize_registered_types(self, program):
        """Resolve class reference types on every declaration signature.

        Method bodies may legally precede the class whose fields they read.
        Type inference consults the registered declaration table, so those
        fields and signatures must already have the same normalized types that
        later monomorphization sees.  Normalizing opportunistically while each
        owning declaration was analyzed made code generation depend on import
        and declaration order: an early ``Vector<Item>`` field access mangled
        calls without ``Item``'s synthesized pointer suffix, while the field's
        eventual generic instance was emitted as ``Vector<Item*>``.

        The normal per-declaration analysis remains idempotent and still owns
        generic-instance collection and body validation; this pass establishes
        only the order-independent type context they consume.
        """
        for decl in self._decls_with_file(program):
            if isinstance(decl, FunctionDecl):
                for param in decl.params:
                    param.type = self._upgrade_class_type(param.type)
                decl.return_type = self._upgrade_class_type(decl.return_type)
            elif isinstance(decl, ClassDecl):
                class_params = set(decl.generic_params)
                for member in decl.members:
                    if isinstance(member, (FieldDecl, PropertyDecl)):
                        member.type = self._upgrade_class_type(member.type, class_params)
                    elif isinstance(member, MethodDecl):
                        shadowed = class_params | set(member.generic_params)
                        for param in member.params:
                            param.type = self._upgrade_class_type(param.type, shadowed)
                        member.return_type = self._upgrade_class_type(member.return_type, shadowed)
            elif isinstance(decl, InterfaceDecl):
                interface_params = set(decl.generic_params)
                for method in decl.methods:
                    for param in method.params:
                        param.type = self._upgrade_class_type(param.type, interface_params)
                    method.return_type = self._upgrade_class_type(method.return_type, interface_params)
            elif isinstance(decl, TypedefDecl):
                decl.original = self._upgrade_class_type(decl.original)
                self.typedef_table[decl.alias] = decl.original
            elif isinstance(decl, StructDecl):
                for field in decl.fields:
                    field.type = self._upgrade_class_type(field.type)
            elif isinstance(decl, RichEnumDecl):
                for variant in decl.variants:
                    for parameter in variant.params:
                        parameter.type = self._upgrade_class_type(parameter.type)
            elif isinstance(decl, VarDeclStmt) and decl.type is not None:
                decl.type = self._upgrade_class_type(decl.type)
                symbol = self.global_scope.symbols.get(decl.name)
                if symbol is not None:
                    symbol.type = decl.type
