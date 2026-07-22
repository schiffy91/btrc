"""Fail-closed callability checks after ordinary call resolution."""

from ..ast_nodes import FieldAccessExpr, Identifier, LambdaExpr


class CallTargetContractsMixin:
    def _validate_callable_target(self, call) -> None:
        callee = call.callee
        if isinstance(callee, LambdaExpr):
            return
        if isinstance(callee, Identifier):
            self._validate_identifier_callable(callee)
            return
        if isinstance(callee, FieldAccessExpr):
            abstract_owner = self._abstract_method_owner(callee)
            if abstract_owner is not None:
                self.context.error(
                    f"Abstract method '{abstract_owner}.{callee.field}' cannot be called without runtime dispatch",
                    call.line,
                    call.col,
                )
                return
            if self._known_field_callable(callee):
                return
            inferred = self._infer_type(callee)
            if inferred is not None and self._function_pointer_signature(inferred) is None:
                self.context.error(
                    f"Expression of type '{self._format_type(inferred)}' is not callable",
                    call.line,
                    call.col,
                )
            return
        inferred = self._infer_type(callee)
        if inferred is not None and self._function_pointer_signature(inferred) is None:
            self.context.error(
                f"Expression of type '{self._format_type(inferred)}' is not callable",
                call.line,
                call.col,
            )

    def _validate_identifier_callable(self, identifier) -> None:
        name = identifier.name
        symbol = self.scope.lookup(name)
        if symbol is not None and symbol.kind != "function":
            if self._function_pointer_signature(symbol.type) is not None:
                return
            rendered = self._format_type(symbol.type) if symbol.type else "unknown"
            self.context.error(
                f"Resolved value '{name}' of type '{rendered}' is not callable",
                identifier.line,
                identifier.col,
            )
            return
        if name in self.declarations.function_table or name in self.declarations.class_table:
            return
        if symbol is not None:
            return
        if name in self.declarations.enum_table or name in self.declarations.rich_enum_table:
            self.context.error(f"Type '{name}' is not directly callable", identifier.line, identifier.col)
            return
        if name in self.declarations.enum_member_owners:
            self.context.error(f"Enum member '{name}' is not callable", identifier.line, identifier.col)

    def _known_field_callable(self, callee) -> bool:
        if isinstance(callee.obj, Identifier):
            owner = callee.obj.name
            rich = self.declarations.rich_enum_table.get(owner)
            if rich and any(variant.name == callee.field for variant in rich.variants):
                return True
            cls = self.declarations.class_table.get(owner)
            if cls:
                method = cls.methods.get(callee.field)
                if method is not None:
                    return True
                field = cls.static_fields.get(callee.field)
                return bool(field and self._function_pointer_signature(field.type) is not None)
        receiver = self._infer_type(callee.obj)
        if (
            receiver
            and receiver.base not in self.declarations.class_table
            and receiver.base in {"Array", "List", "Map", "Set", "Vector"}
        ):
            # Collection types are recognized before the stdlib declarations
            # are merged into analyzer-only programs.  Their shared size()
            # method remains callable in that structural view.
            if callee.field == "size":
                return True
        if receiver and receiver.base in self.declarations.class_table:
            cls = self.declarations.class_table[receiver.base]
            if callee.field in cls.methods:
                return True
            field = cls.fields.get(callee.field)
            if field is None and callee.field in cls.properties:
                field = cls.properties[callee.field]
            return bool(field and self._function_pointer_signature(field.type) is not None)
        return False

    def _abstract_method_owner(self, callee) -> str | None:
        receiver = self._infer_type(callee.obj)
        if receiver is not None and receiver.base in self.declarations.class_table:
            cls = self.declarations.class_table[receiver.base]
        elif (
            isinstance(callee.obj, Identifier)
            and self.scope.lookup(callee.obj.name) is None
            and callee.obj.name in self.declarations.class_table
        ):
            cls = self.declarations.class_table[callee.obj.name]
        else:
            return None
        method = cls.methods.get(callee.field)
        return cls.name if method is not None and method.is_abstract else None


__all__ = ["CallTargetContractsMixin"]
