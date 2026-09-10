"""Decode native header semantics without erasing qualifiers or ownership."""

from __future__ import annotations

import json
import re

from ..abi.native_generated import (
    NativeAlias,
    NativeArrayType,
    NativeBuiltin,
    NativeConstant,
    NativeEnumType,
    NativeField,
    NativeFunction,
    NativeFunctionType,
    NativeHeader,
    NativeParameterSemantics,
    NativePointer,
    NativeQualifiedType,
    NativeQualifiers,
    NativeRecordDeclaration,
    NativeRecordLayout,
    NativeRecordType,
    NativeTypedef,
)


class NativeImportError(ValueError):
    """The native reader returned unsupported or inconsistent semantics."""


class NativeHeaderCodec:
    """Own the checked boundary from experimental Clang JSON to shared types."""

    SCHEMA = "btrc.native-declarations.experimental"
    _QUALIFIERS = frozenset({"const", "volatile", "restrict", "nullability"})
    _DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)\Z")
    _SIGNED_DECIMAL = re.compile(r"(?:0|-?[1-9][0-9]*)\Z")
    _NULLABILITY = frozenset({"unannotated", "nonnull", "nullable", "nullable_result", "unspecified"})
    _OWNERSHIP = frozenset(
        {"unspecified", "cf_retained", "cf_not_retained", "ns_retained", "ns_not_retained", "ns_autoreleased"}
    )

    @staticmethod
    def _object(value, fields, optional=()):
        if not isinstance(value, dict) or not set(fields) <= set(value) or set(value) - set(fields) - set(optional):
            raise NativeImportError("native object fields do not match the semantic schema")
        return value

    @staticmethod
    def _text(value, *, empty=False):
        if not isinstance(value, str) or "\0" in value or (not empty and not value):
            raise NativeImportError("expected native text")
        return value

    @staticmethod
    def _boolean(value):
        if type(value) is not bool:
            raise NativeImportError("expected native boolean")
        return value

    @staticmethod
    def _integer(value):
        if type(value) is not int or not 0 <= value <= 2147483647:
            raise NativeImportError("expected nonnegative native int32")
        return value

    @classmethod
    def _decimal(cls, value, *, signed=False):
        if not isinstance(value, str) or (cls._SIGNED_DECIMAL if signed else cls._DECIMAL).fullmatch(value) is None:
            raise NativeImportError("expected canonical native decimal text")
        return value

    @staticmethod
    def _array(value):
        if not isinstance(value, list):
            raise NativeImportError("expected native array")
        return value

    @classmethod
    def _choice(cls, value, choices):
        value = cls._text(value)
        if value not in choices:
            raise NativeImportError(f"unsupported native semantic value: {value}")
        return value

    def decode(self, source: str, *, expected_target: str | None = None) -> NativeHeader:
        try:
            value = json.loads(source)
            self._object(
                value, {"schema", "target", "clang", "big_endian", "character_bits", "declarations", "records"}
            )
            if value["schema"] != self.SCHEMA:
                raise NativeImportError("unsupported native header schema")
            target = self._text(value["target"])
            if expected_target is not None and target != expected_target:
                raise NativeImportError("native header target does not match the requested target")
            header = NativeHeader(
                target_triple=target,
                compiler_version=self._text(value["clang"]),
                big_endian=self._boolean(value["big_endian"]),
                character_bits=self._integer(value["character_bits"]),
                exports=[self._declaration(entry) for entry in self._array(value["declarations"])],
                records=[self._record(entry) for entry in self._array(value["records"])],
            )
            if header.character_bits == 0:
                raise NativeImportError("native character width must be positive")
            names = [entry.name for entry in header.exports]
            identities = [record.identity for record in header.records]
            if len(set(names)) != len(names) or len(set(identities)) != len(identities):
                raise NativeImportError("duplicate native declaration or record identity")
            layouts = set(identities)
            for entry in header.exports:
                native_type = (
                    entry.signature
                    if isinstance(entry, NativeFunction)
                    else entry.underlying
                    if isinstance(entry, NativeTypedef)
                    else entry.value_type
                    if isinstance(entry, NativeConstant)
                    else entry.record_type
                )
                self._verify_layout_references(native_type, layouts)
            for record in header.records:
                for field in record.fields:
                    self._verify_layout_references(field.field_type, layouts)
            return header
        except (json.JSONDecodeError, RecursionError) as error:
            raise NativeImportError(f"invalid native header document: {error}") from error

    def _type(self, value):
        if not isinstance(value, dict):
            raise NativeImportError("expected native type object")
        kind = self._text(value.get("kind"))
        fields = {
            "builtin": ({"name"}, {"bits", "alignment_bits", "signed"}),
            "pointer": ({"pointee"}, set()),
            "typedef": ({"name", "underlying"}, set()),
            "record": ({"name", "identity", "complete", "opaque"}, set()),
            "enum": ({"name", "identity", "underlying"}, set()),
            "function": ({"return_type", "parameters", "variadic", "calling_convention"}, set()),
            "array": ({"element", "count"}, set()),
            "qualified": ({"underlying"}, set()),
        }
        if kind not in fields:
            raise NativeImportError(f"unsupported native type: {kind}")
        required, optional = fields[kind]
        self._object(value, required | self._QUALIFIERS | {"kind"}, optional)
        qualifiers = NativeQualifiers(
            is_const=self._boolean(value["const"]),
            is_volatile=self._boolean(value["volatile"]),
            is_restrict=self._boolean(value["restrict"]),
            nullability=self._choice(value["nullability"], self._NULLABILITY),
        )
        if kind == "builtin":
            name = self._text(value["name"])
            if name == "void":
                if set(value) & {"bits", "alignment_bits", "signed"}:
                    raise NativeImportError("void must not have native storage or signedness")
                return NativeBuiltin(
                    name=name, bits=0, alignment_bits=0, signedness="not_integer", qualifiers=qualifiers
                )
            bits = self._integer(value.get("bits"))
            alignment = self._integer(value.get("alignment_bits"))
            if bits == 0 or alignment == 0:
                raise NativeImportError("native scalar storage must be positive")
            signedness = (
                ("signed" if self._boolean(value["signed"]) else "unsigned") if "signed" in value else "not_integer"
            )
            return NativeBuiltin(
                name=name, bits=bits, alignment_bits=alignment, signedness=signedness, qualifiers=qualifiers
            )
        if kind == "pointer":
            return NativePointer(pointee=self._type(value["pointee"]), qualifiers=qualifiers)
        if kind == "typedef":
            return NativeAlias(
                name=self._text(value["name"]), underlying=self._type(value["underlying"]), qualifiers=qualifiers
            )
        if kind == "record":
            complete = self._boolean(value["complete"])
            opaque = self._boolean(value["opaque"])
            if not opaque and not complete:
                raise NativeImportError("incomplete native record used by value")
            return NativeRecordType(
                name=self._text(value["name"], empty=True),
                identity=self._text(value["identity"]),
                complete=complete,
                opaque=opaque,
                qualifiers=qualifiers,
            )
        if kind == "enum":
            return NativeEnumType(
                name=self._text(value["name"], empty=True),
                identity=self._text(value["identity"]),
                underlying=self._type(value["underlying"]),
                qualifiers=qualifiers,
            )
        if kind == "function":
            return NativeFunctionType(
                return_type=self._type(value["return_type"]),
                parameters=[self._type(parameter) for parameter in self._array(value["parameters"])],
                variadic=self._boolean(value["variadic"]),
                calling_convention=self._choice(value["calling_convention"], {"c"}),
                qualifiers=qualifiers,
            )
        if kind == "array":
            return NativeArrayType(
                element=self._type(value["element"]),
                count=None if value["count"] is None else self._decimal(value["count"]),
                qualifiers=qualifiers,
            )
        return NativeQualifiedType(underlying=self._type(value["underlying"]), qualifiers=qualifiers)

    def _declaration(self, value):
        if not isinstance(value, dict):
            raise NativeImportError("expected native declaration object")
        kind = self._text(value.get("kind"))
        required = {"kind", "name", "type"}
        if kind == "function":
            required |= {"link_name", "returned_ownership", "parameter_semantics"}
        elif kind == "enum_constant":
            required |= {"value"}
        elif kind not in {"typedef", "record"}:
            raise NativeImportError(f"unsupported native declaration: {kind}")
        self._object(value, required, {"source", "line", "column"})
        position = {
            "name": self._text(value["name"]),
            "source_file": self._text(value.get("source", ""), empty=True),
            "line": self._integer(value.get("line", 0)),
            "column": self._integer(value.get("column", 0)),
        }
        native_type = self._type(value["type"])
        if kind == "function":
            parameters = []
            for parameter in self._array(value["parameter_semantics"]):
                self._object(parameter, {"name", "cf_consumed", "ns_consumed"})
                parameters.append(
                    NativeParameterSemantics(
                        name=self._text(parameter["name"], empty=True),
                        cf_consumed=self._boolean(parameter["cf_consumed"]),
                        ns_consumed=self._boolean(parameter["ns_consumed"]),
                    )
                )
            if not isinstance(native_type, NativeFunctionType) or len(parameters) != len(native_type.parameters):
                raise NativeImportError("native function semantics do not match its signature")
            return NativeFunction(
                **position,
                signature=native_type,
                link_name=self._text(value["link_name"]),
                parameter_semantics=parameters,
                returned_ownership=self._choice(value["returned_ownership"], self._OWNERSHIP),
            )
        if kind == "typedef":
            return NativeTypedef(**position, underlying=native_type)
        if kind == "enum_constant":
            return NativeConstant(
                **position, value_type=native_type, decimal_value=self._decimal(value["value"], signed=True)
            )
        return NativeRecordDeclaration(**position, record_type=native_type)

    def _record(self, value):
        self._object(value, {"identity", "name", "kind", "size_bits", "alignment_bits", "fields"})
        size = self._decimal(value["size_bits"])
        alignment = self._decimal(value["alignment_bits"])
        if int(alignment) == 0:
            raise NativeImportError("native record alignment must be positive")
        fields = []
        for entry in self._array(value["fields"]):
            self._object(entry, {"name", "type", "offset_bits", "anonymous"}, {"width_bits"})
            offset = self._decimal(entry["offset_bits"])
            width = self._decimal(entry["width_bits"]) if "width_bits" in entry else "0"
            if int(offset) + int(width) > int(size):
                raise NativeImportError("native field extends beyond its record")
            fields.append(
                NativeField(
                    name=self._text(entry["name"], empty=True),
                    field_type=self._type(entry["type"]),
                    offset_bits=offset,
                    is_anonymous=self._boolean(entry["anonymous"]),
                    is_bitfield="width_bits" in entry,
                    width_bits=width,
                )
            )
        return NativeRecordLayout(
            identity=self._text(value["identity"]),
            name=self._text(value["name"], empty=True),
            record_kind=self._choice(value["kind"], {"struct", "union"}),
            size_bits=size,
            alignment_bits=alignment,
            fields=fields,
        )

    def _verify_layout_references(self, native_type, layouts):
        if isinstance(native_type, NativeRecordType):
            if not native_type.opaque and native_type.identity not in layouts:
                raise NativeImportError("native record layout is missing")
        elif isinstance(native_type, (NativeAlias, NativeQualifiedType, NativeEnumType)):
            self._verify_layout_references(native_type.underlying, layouts)
        elif isinstance(native_type, NativePointer):
            self._verify_layout_references(native_type.pointee, layouts)
        elif isinstance(native_type, NativeArrayType):
            self._verify_layout_references(native_type.element, layouts)
        elif isinstance(native_type, NativeFunctionType):
            self._verify_layout_references(native_type.return_type, layouts)
            for parameter in native_type.parameters:
                self._verify_layout_references(parameter, layouts)
