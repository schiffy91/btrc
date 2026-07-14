"""Translation-unit root for the structured IR."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .top_nodes import (
    IREnumDef,
    IRFunctionDecl,
    IRFunctionPointerTypedef,
    IRGlobalDecl,
    IRHelperDecl,
    IRInclude,
    IRMacroDef,
    IRStructDef,
    IRStructForward,
    IRTaggedUnionDef,
    IRTypedefDef,
)

if TYPE_CHECKING:
    from .nodes import (
        IRFunctionDef,
        IRGpuKernel,
    )


@dataclass
class IRModule:
    """One C translation unit before formatting."""

    preprocessor_decls: list[IRInclude | IRMacroDef] = field(default_factory=list)
    freestanding: bool = False
    runtime_roots: set[str] = field(default_factory=set)
    needs_runtime: bool = False
    debug: bool = False
    debug_cfile: str = ""
    struct_forwards: list[IRStructForward] = field(default_factory=list)
    function_pointer_typedefs: list[IRFunctionPointerTypedef] = field(default_factory=list)
    function_decls: list[IRFunctionDecl] = field(default_factory=list)
    helper_decls: list[IRHelperDecl] = field(default_factory=list)
    enum_defs: list[IREnumDef] = field(default_factory=list)
    typedef_defs: list[IRTypedefDef] = field(default_factory=list)
    tagged_union_defs: list[IRTaggedUnionDef] = field(default_factory=list)
    struct_defs: list[IRStructDef] = field(default_factory=list)
    ordered_type_declarations: list[
        IREnumDef | IRFunctionPointerTypedef | IRTypedefDef | IRTaggedUnionDef | IRStructDef
    ] = field(default_factory=list, init=False, repr=False, compare=False)
    global_decls: list[IRGlobalDecl] = field(default_factory=list)
    function_defs: list[IRFunctionDef] = field(default_factory=list)
    gpu_kernels: list[IRGpuKernel] = field(default_factory=list)
    _generated_runtime_preprocessor: list[IRInclude | IRMacroDef] = field(
        default_factory=list,
        repr=False,
        compare=False,
    )
    _freestanding_system_includes_lowered: bool = field(
        default=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        self.refresh_type_declarations()

    def refresh_type_declarations(self) -> None:
        """Refresh the stable strict-C order of typed type declarations."""

        self._validate_declaration_schema()
        from .declaration_order import plan_type_declarations

        self.ordered_type_declarations = plan_type_declarations(self)

    def validate_declarations(self) -> None:
        """Reject malformed declarations and a stale derived type order."""

        self._validate_declaration_schema()
        from .declaration_order import plan_type_declarations

        planned = plan_type_declarations(self)
        ordered = self.ordered_type_declarations
        if (
            not isinstance(ordered, list)
            or len(ordered) != len(planned)
            or any(actual is not expected for actual, expected in zip(ordered, planned))
        ):
            raise ValueError(
                "IRModule.ordered_type_declarations is stale; "
                "call refresh_type_declarations() after mutating type declarations"
            )

    def _validate_declaration_schema(self) -> None:
        """Reject raw strings or the wrong typed declaration category."""

        from .nodes import IRFunctionDef, IRGpuKernel

        for field_name in ("freestanding", "needs_runtime", "debug"):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"IRModule.{field_name} requires bool")

        if not isinstance(self.runtime_roots, set) or any(
            not isinstance(root, str) or not root for root in self.runtime_roots
        ):
            raise TypeError("IRModule.runtime_roots requires a set of non-empty strings")

        declaration_fields = (
            ("struct_forwards", IRStructForward),
            ("function_pointer_typedefs", IRFunctionPointerTypedef),
            ("function_decls", IRFunctionDecl),
            ("helper_decls", IRHelperDecl),
            ("enum_defs", IREnumDef),
            ("typedef_defs", IRTypedefDef),
            ("tagged_union_defs", IRTaggedUnionDef),
            ("struct_defs", IRStructDef),
            ("global_decls", IRGlobalDecl),
            ("function_defs", IRFunctionDef),
            ("gpu_kernels", IRGpuKernel),
        )
        for field_name, expected_type in declaration_fields:
            declarations = getattr(self, field_name)
            if not isinstance(declarations, list):
                raise TypeError(f"IRModule.{field_name} requires a list")
            for declaration in declarations:
                if not isinstance(declaration, expected_type):
                    raise TypeError(
                        f"IRModule.{field_name} requires {expected_type.__name__}, got {type(declaration).__name__}"
                    )
        if not isinstance(self.preprocessor_decls, list):
            raise TypeError("IRModule.preprocessor_decls requires a list")
        for declaration in self.preprocessor_decls:
            if not isinstance(declaration, (IRInclude, IRMacroDef)):
                raise TypeError(
                    f"IRModule.preprocessor_decls requires IRInclude or IRMacroDef, got {type(declaration).__name__}"
                )
            if isinstance(declaration, IRMacroDef):
                declaration.validate()
