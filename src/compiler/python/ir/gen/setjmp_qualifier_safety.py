"""Reject implicit setjmp qualifiers that would be lost through aliases."""

from __future__ import annotations

import dataclasses

from ..nodes import (
    IRAddressOf,
    IRBlock,
    IRDoWhile,
    IRFieldAccess,
    IRFor,
    IRGlobalDecl,
    IRIf,
    IRIndex,
    IRSizeof,
    IRStmtExpr,
    IRSwitch,
    IRVar,
    IRVarDecl,
    IRWhile,
)
from ..storage_provenance import direct_storage_root
from .errors import CodegenError
from .setjmp_storage_names import compiler_storage_name


class _QualifierSafety:
    def __init__(self, parameters, inferred: set[int], globals_by_name):
        self._parameters = parameters
        self._inferred = inferred
        self._globals = globals_by_name

    def block(self, block: IRBlock | None, inherited=()) -> None:
        if block is None:
            return
        visible = list(inherited)
        for statement in block.stmts:
            self._statement(statement, visible)

    def _resolve(self, name: str, visible):
        for declaration in reversed(visible):
            if declaration.name == name:
                return declaration
        for parameter in self._parameters:
            if parameter.name == name:
                return parameter
        return self._globals.get(name)

    def _reject(self, name: str, declaration) -> None:
        if id(declaration) not in self._inferred:
            return
        raise CodegenError(
            f"storage object '{name}' is modified across try/throw and requires "
            "volatile storage; its address or array decay requires "
            "unsupported layered pointer qualifiers"
        )

    def _expression(self, value: object, visible, *, parent=None, field_name="") -> None:
        if value is None:
            return
        if isinstance(value, IRStmtExpr):
            local = list(visible)
            for statement in value.stmts:
                self._statement(statement, local)
            self._expression(value.result, local)
            return
        if isinstance(value, IRAddressOf) and value.source_expression and not isinstance(parent, IRSizeof):
            root = direct_storage_root(value.expr)
            declaration = self._resolve(root, visible) if root else None
            if declaration is not None and declaration.is_volatile and not compiler_storage_name(root):
                self._reject(root, declaration)
        if isinstance(value, IRVar):
            declaration = self._resolve(value.name, visible)
            array_root = value.array_storage_root if value.array_storage_known else value.name
            array_declaration = self._resolve(array_root, visible)
            if (
                isinstance(array_declaration, (IRVarDecl, IRGlobalDecl))
                and array_declaration.is_volatile
                and not compiler_storage_name(value.name)
                and (
                    value.array_storage_known
                    or array_declaration.array_size is not None
                    or array_declaration.is_unsized_array
                )
                and not isinstance(parent, IRSizeof)
                and not (isinstance(parent, IRIndex) and field_name == "obj")
            ):
                self._reject(array_root, array_declaration)
            return
        if (
            isinstance(value, IRFieldAccess)
            and value.array_storage_known
            and value.array_storage_root
            and not isinstance(parent, IRSizeof)
            and not (isinstance(parent, IRIndex) and field_name == "obj")
        ):
            declaration = self._resolve(value.array_storage_root, visible)
            if (
                declaration is not None
                and declaration.is_volatile
                and not compiler_storage_name(value.array_storage_root)
            ):
                self._reject(value.array_storage_root, declaration)
        if dataclasses.is_dataclass(value):
            for field in dataclasses.fields(value):
                child = getattr(value, field.name)
                if isinstance(child, (list, tuple)):
                    for item in child:
                        self._expression(item, visible, parent=value, field_name=field.name)
                else:
                    self._expression(child, visible, parent=value, field_name=field.name)

    def _declaration(self, declaration: IRVarDecl, visible) -> None:
        self._expression(declaration.array_size, visible)
        visible.append(declaration)
        self._expression(declaration.init, visible)

    def _statement(self, statement, visible) -> None:
        if isinstance(statement, IRVarDecl):
            self._declaration(statement, visible)
        elif isinstance(statement, IRIf):
            self._expression(statement.condition, visible)
            self.block(statement.then_block, visible)
            self.block(statement.else_block, visible)
        elif isinstance(statement, (IRWhile, IRDoWhile)):
            self._expression(statement.condition, visible)
            self.block(statement.body, visible)
        elif isinstance(statement, IRFor):
            local = list(visible)
            if isinstance(statement.init, IRVarDecl):
                self._declaration(statement.init, local)
            else:
                self._expression(statement.init, local)
            self._expression(statement.condition, local)
            self._expression(statement.update, local)
            self.block(statement.body, local)
        elif isinstance(statement, IRSwitch):
            self._expression(statement.value, visible)
            for case in statement.cases:
                local = list(visible)
                self._expression(case.value, local)
                for child in case.body:
                    self._statement(child, local)
        elif isinstance(statement, IRBlock):
            self.block(statement, visible)
        else:
            self._expression(statement, visible)


def reject_inferred_volatile_aliases(function, inferred: set[int], globals_by_name) -> None:
    """Fail before C emission when an implicit qualifier cannot be preserved."""

    _QualifierSafety(function.params, inferred, globals_by_name).block(function.body)


def reject_volatile_global_aliases(module) -> dict[str, IRGlobalDecl]:
    """Validate global initializers and return their C-name lookup."""

    globals_by_name = {declaration.name: declaration for declaration in module.global_decls}
    safety = _QualifierSafety((), set(), globals_by_name)
    for declaration in module.global_decls:
        safety._expression(declaration.array_size, ())
        safety._expression(declaration.init, ())
    return globals_by_name


__all__ = ["reject_inferred_volatile_aliases", "reject_volatile_global_aliases"]
