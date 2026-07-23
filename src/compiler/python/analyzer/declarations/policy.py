"""Owned declaration-name, parameter, and inheritance policy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...hosted_abi import HOSTED_MACROS
from .c_names import (
    C11_RESERVED_NAMES,
    c_file_scope_reserved_identifier,
    c_reserved_identifier,
    compiler_reserved_prefix,
    trusted_native_binding,
)
from .callables import CallableDeclarationPolicy
from .hosted import HostedDeclarationPolicy
from .signature_types import SignatureTypePolicy

if TYPE_CHECKING:
    from ..analysis_context import AnalysisContext
    from .registry import DeclarationRegistry


class DeclarationPolicy:
    """Own semantic rules applied to source declarations."""

    def __init__(
        self,
        context: AnalysisContext,
        registry: DeclarationRegistry,
    ) -> None:
        self.context = context
        self.registry = registry
        self.callables = CallableDeclarationPolicy(context, registry)
        self.hosted = HostedDeclarationPolicy(context, registry)
        self.signatures = SignatureTypePolicy(context, registry)

    def validate_name(
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
        if not name:
            return True
        if self.registry.source_macros.declared(name):
            self.context.error(
                f"{subject} name '{name}' collides with source macro '{name}'",
                line,
                col,
            )
            return False
        if name in HOSTED_MACROS and not (c_name_generated or trusted_hosted):
            self.context.error(
                f"{subject} name '{name}' collides with an automatically included C macro",
                line,
                col,
            )
            return False
        if name in C11_RESERVED_NAMES:
            self.context.error(f"{subject} name '{name}' is reserved by C11", line, col)
            return False
        reserved_prefix = compiler_reserved_prefix(name)
        if reserved_prefix:
            if trusted_prototype and trusted_native_binding(
                name,
                self.context.current_source_file,
            ):
                return True
            self.context.error(
                f"{subject} name '{name}' uses the compiler-reserved '{reserved_prefix}' prefix",
                line,
                col,
            )
            return False
        if c_reserved_identifier(name) and not (allow_magic and self.callables.is_magic_method_name(name)):
            self.context.error(f"{subject} name '{name}' is reserved by C11", line, col)
            return False
        if file_scope and c_file_scope_reserved_identifier(name):
            self.context.error(
                f"{subject} name '{name}' is reserved by C11 at file scope",
                line,
                col,
            )
            return False
        return True

    def validate_parameter_names(self, parameters, owner) -> None:
        seen = set()
        for parameter in parameters:
            line = parameter.name_line or parameter.line
            col = parameter.name_col or parameter.col
            self.validate_name(
                parameter.name,
                "Parameter",
                line,
                col,
                c_name_generated=True,
            )
            if parameter.name in seen:
                self.context.error(
                    f"Duplicate parameter name '{parameter.name}' in {owner}",
                    line,
                    col,
                )
            seen.add(parameter.name)

    def validate_generic_parameter_names(
        self,
        names,
        owner,
        line=0,
        col=0,
    ) -> None:
        seen = set()
        for name in names:
            self.validate_name(name, "Generic parameter", line, col)
            if name in seen:
                self.context.error(
                    f"Duplicate generic parameter name '{name}' in {owner}",
                    line,
                    col,
                )
            seen.add(name)

    def validate_default_parameters(self, parameters, line, col) -> None:
        seen_default = False
        for parameter in parameters:
            if parameter.default is not None:
                seen_default = True
            elif seen_default:
                self.context.error(
                    f"Non-default parameter '{parameter.name}' follows default parameter",
                    parameter.line or line,
                    parameter.col or col,
                )
                break

    def validate_inherited_member_names(self, child, parent) -> None:
        own_fields = {name for name, owner in child.field_owners.items() if owner == child.name}
        own_methods = {
            name for name, owner in child.method_owners.items() if owner == child.name and name != child.name
        }
        own_properties = {name for name, owner in child.property_owners.items() if owner == child.name}
        conflicts = (
            (own_fields & parent.properties.keys())
            | (own_methods & parent.properties.keys())
            | (own_properties & (parent.fields.keys() | parent.methods.keys()))
        )
        for name in sorted(conflicts):
            member = child.fields.get(name) or child.methods.get(name) or child.properties.get(name)
            self.context.error(
                f"Member '{name}' in class '{child.name}' conflicts with an inherited member of a different kind",
                getattr(member, "line", 0),
                getattr(member, "col", 0),
            )
        parent_storage = {name for name, _member in parent.instance_storage}
        for storage_name, member in child.instance_storage:
            if storage_name in parent_storage:
                self.context.error(
                    f"Instance storage '{storage_name}' in class '{child.name}' conflicts with inherited storage",
                    getattr(member, "line", 0),
                    getattr(member, "col", 0),
                )


__all__ = ["DeclarationPolicy"]
