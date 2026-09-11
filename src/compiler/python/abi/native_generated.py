"""Native header semantic data for BTRC.

Auto-generated from src/language/native_abi.asdl by tools/compiler_codegen/ast.py.
DO NOT EDIT BY HAND.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as _dc_field
from typing import Optional, Union


@dataclass(kw_only=True)
class NativeHeader:
    target_triple: str = ""
    compiler_version: str = ""
    big_endian: bool = False
    character_bits: int = 0
    exports: list[native_declaration] = _dc_field(default_factory=list)
    records: list[NativeRecordLayout] = _dc_field(default_factory=list)
    interfaces: list[NativeObjectiveCInterface] = _dc_field(default_factory=list)


@dataclass(kw_only=True)
class NativeFunction:
    name: str = ""
    link_name: str = ""
    signature: native_type
    parameter_semantics: list[NativeParameterSemantics] = _dc_field(default_factory=list)
    returned_ownership: str = ""
    source_file: str = _dc_field(default=None, compare=False)
    line: int = _dc_field(default=0, compare=False)
    column: int = 0


@dataclass(kw_only=True)
class NativeObjectiveCMethod:
    name: str = ""
    identity: str = ""
    owner: str = ""
    receiver: str = ""
    selector: str = ""
    class_method: bool = False
    signature: native_type
    parameter_semantics: list[NativeParameterSemantics] = _dc_field(default_factory=list)
    returned_ownership: str = ""
    method_family: str = ""
    consumes_self: bool = False
    related_result: bool = False
    returns_inner_pointer: bool = False
    source_file: str = _dc_field(default=None, compare=False)
    line: int = _dc_field(default=0, compare=False)
    column: int = 0


@dataclass(kw_only=True)
class NativeTypedef:
    name: str = ""
    underlying: native_type
    source_file: str = _dc_field(default=None, compare=False)
    line: int = _dc_field(default=0, compare=False)
    column: int = 0


@dataclass(kw_only=True)
class NativeConstant:
    name: str = ""
    value_type: native_type
    decimal_value: str = ""
    source_file: str = _dc_field(default=None, compare=False)
    line: int = _dc_field(default=0, compare=False)
    column: int = 0


@dataclass(kw_only=True)
class NativeGlobal:
    name: str = ""
    value_type: native_type
    read_only: bool = False
    source_file: str = _dc_field(default=None, compare=False)
    line: int = _dc_field(default=0, compare=False)
    column: int = 0


@dataclass(kw_only=True)
class NativeRecordDeclaration:
    name: str = ""
    record_type: native_type
    source_file: str = _dc_field(default=None, compare=False)
    line: int = _dc_field(default=0, compare=False)
    column: int = 0


@dataclass(kw_only=True)
class NativeBuiltin:
    name: str = ""
    bits: int = 0
    alignment_bits: int = 0
    signedness: str = ""
    qualifiers: NativeQualifiers


@dataclass(kw_only=True)
class NativePointer:
    pointee: native_type
    qualifiers: NativeQualifiers


@dataclass(kw_only=True)
class NativeAlias:
    name: str = ""
    underlying: native_type
    qualifiers: NativeQualifiers


@dataclass(kw_only=True)
class NativeRecordType:
    name: str = ""
    tag_name: str = ""
    identity: str = ""
    record_kind: str = ""
    complete: bool = False
    opaque: bool = False
    qualifiers: NativeQualifiers


@dataclass(kw_only=True)
class NativeEnumType:
    name: str = ""
    identity: str = ""
    underlying: native_type
    qualifiers: NativeQualifiers


@dataclass(kw_only=True)
class NativeFunctionType:
    return_type: native_type
    parameters: list[native_type] = _dc_field(default_factory=list)
    variadic: bool = False
    calling_convention: str = ""
    qualifiers: NativeQualifiers


@dataclass(kw_only=True)
class NativeArrayType:
    element: native_type
    count: Optional[str] = None
    qualifiers: NativeQualifiers


@dataclass(kw_only=True)
class NativeQualifiedType:
    underlying: native_type
    qualifiers: NativeQualifiers


@dataclass(kw_only=True)
class NativeObjectiveCObject:
    name: str = ""
    identity: str = ""
    class_object: bool = False
    protocols: list[str] = _dc_field(default_factory=list)
    type_arguments: list[native_type] = _dc_field(default_factory=list)
    qualifiers: NativeQualifiers


@dataclass(kw_only=True)
class NativeObjectiveCBlock:
    signature: native_type
    qualifiers: NativeQualifiers


@dataclass(kw_only=True)
class NativeQualifiers:
    is_const: bool = False
    is_volatile: bool = False
    is_restrict: bool = False
    nullability: str = ""


@dataclass(kw_only=True)
class NativeParameterSemantics:
    name: str = ""
    cf_consumed: bool = False
    ns_consumed: bool = False
    no_escape: bool = False


@dataclass(kw_only=True)
class NativeObjectiveCInterface:
    name: str = ""
    identity: str = ""
    complete: bool = False
    superclass: str = ""


@dataclass(kw_only=True)
class NativeRecordLayout:
    identity: str = ""
    name: str = ""
    record_kind: str = ""
    size_bits: str = ""
    alignment_bits: str = ""
    fields: list[NativeField] = _dc_field(default_factory=list)


@dataclass(kw_only=True)
class NativeField:
    name: str = ""
    field_type: native_type
    offset_bits: str = ""
    is_anonymous: bool = False
    is_bitfield: bool = False
    width_bits: str = ""


# --- Union type aliases for sum types ---

native_declaration = Union[NativeFunction, NativeObjectiveCMethod, NativeTypedef, NativeConstant, NativeGlobal, NativeRecordDeclaration]
native_type = Union[NativeBuiltin, NativePointer, NativeAlias, NativeRecordType, NativeEnumType, NativeFunctionType, NativeArrayType, NativeQualifiedType, NativeObjectiveCObject, NativeObjectiveCBlock]


# --- Product type aliases ---
# These alias lowercase ASDL names to the PascalCase class names

native_header = NativeHeader
native_qualifiers = NativeQualifiers
native_parameter = NativeParameterSemantics
native_interface = NativeObjectiveCInterface
native_record = NativeRecordLayout
native_field = NativeField
