"""Formatting for C type, alias, and aggregate declarations."""

from .emitter_stmts import _volatile_type
from .nodes import (
    IREnumDef,
    IRFunctionDecl,
    IRFunctionPointerTypedef,
    IRStructDef,
    IRStructForward,
    IRTaggedUnionDef,
    IRTypedefDef,
)


class _TypeEmitterMixin:
    def _emit_type_declaration(self, declaration):
        """Format one already-ordered typed declaration."""

        if isinstance(declaration, IREnumDef):
            self._emit_enum_def(declaration)
        elif isinstance(declaration, IRFunctionPointerTypedef):
            self._emit_function_pointer_typedef(declaration)
            self._line("")
        elif isinstance(declaration, IRTypedefDef):
            self._emit_typedef(declaration)
        elif isinstance(declaration, IRTaggedUnionDef):
            self._emit_tagged_union(declaration)
        elif isinstance(declaration, IRStructDef):
            self._emit_struct(declaration)
        else:
            raise TypeError(f"unsupported typed declaration {type(declaration).__name__}")

    def _emit_enum_def(self, enum: IREnumDef):
        self._line("typedef enum {" if enum.name is not None else "enum {")
        self._indent += 1
        for index, value in enumerate(enum.values):
            comma = "," if index < len(enum.values) - 1 else ""
            suffix = f" = {self._expr(value.value)}" if value.value is not None else ""
            self._line(f"{value.name}{suffix}{comma}")
        self._indent -= 1
        self._line(f"}} {enum.name};" if enum.name is not None else "};")
        self._line("")

    def _emit_struct_forward(self, declaration: IRStructForward):
        self._line(f"typedef struct {declaration.name} {declaration.name};")

    def _emit_function_pointer_typedef(
        self,
        declaration: IRFunctionPointerTypedef,
    ):
        params = ", ".join(map(str, declaration.param_types)) or "void"
        self._line(f"typedef {declaration.return_type} (*{declaration.name})({params});")

    @staticmethod
    def _function_signature(declaration: IRFunctionDecl) -> str:
        params = (
            ", ".join(
                f"{_volatile_type(str(param.c_type), param.is_volatile)} {param.name}" for param in declaration.params
            )
            or "void"
        )
        storage = "static " if declaration.is_static else ""
        return f"{storage}{declaration.return_type} {declaration.name}({params})"

    def _emit_function_decl(self, declaration: IRFunctionDecl):
        self._line(f"{self._function_signature(declaration)};")

    def _emit_typedef(self, typedef: IRTypedefDef):
        self._line(f"typedef {typedef.target_type} {typedef.name};")
        self._line("")

    def _emit_tagged_union(self, tagged: IRTaggedUnionDef):
        payload_variants = [variant for variant in tagged.variants if variant.fields]
        for variant in payload_variants:
            data_name = f"{tagged.name}_{variant.name}_Data"
            self._line(f"typedef struct {data_name} {{")
            self._indent += 1
            for field in variant.fields:
                self._line(f"{field.c_type} {field.name};")
            self._indent -= 1
            self._line(f"}} {data_name};")
            self._line("")

        self._line(f"struct {tagged.name} {{")
        self._indent += 1
        self._line(f"{tagged.tag_type} tag;")
        if payload_variants:
            self._line("union {")
            self._indent += 1
            for variant in payload_variants:
                data_name = f"{tagged.name}_{variant.name}_Data"
                self._line(f"{data_name} {variant.name};")
            self._indent -= 1
            self._line("} data;")
        self._indent -= 1
        self._line("};")
        self._line("")

    def _emit_struct(self, struct: IRStructDef):
        if struct.pack_alignment is not None:
            self._line(f"#pragma pack(push, {struct.pack_alignment})")
        self._line(f"struct {struct.name} {{")
        self._indent += 1
        for field in struct.fields:
            suffix = f"[{self._expr(field.array_size)}]" if field.array_size is not None else ""
            self._line(f"{field.c_type} {field.name}{suffix};")
        self._indent -= 1
        self._line("};")
        if struct.pack_alignment is not None:
            self._line("#pragma pack(pop)")
        self._line("")
