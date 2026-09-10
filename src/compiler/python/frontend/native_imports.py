"""Decode native header semantics without erasing qualifiers or ownership."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import replace

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
from ..syntax.ast import generated as ast
from .packages import IncludeResolutionError, NativeLinkPlan


class NativeImportError(ValueError):
    """The native reader returned unsupported or inconsistent semantics."""


class NativeHeaderSource(str):
    """Module provenance plus the SDK header that owns the native declaration."""

    def __new__(cls, module: str, header: str, type_spelling: str = ""):
        value = super().__new__(cls, module)
        value.header = header
        value.type_spelling = type_spelling
        return value

    def __getnewargs__(self):
        return str(self), self.header, self.type_spelling


class NativeDeclarationImporter:
    """Import selected C declarations into the normal typed compiler pipeline.

    This first consumer supports only lossless source-type projections. Managed
    ownership and richer native types must be implemented before broad migration.
    """

    def __init__(self):
        self._declarations = {}
        self._native_types = {}
        self._origin = None
        self._layouts = {}
        self._records = {}

    def resolve(self, plan: NativeLinkPlan) -> tuple:
        if not plan.bindings:
            return ()
        reader = os.environ.get("BTRC_NATIVE_HEADER_READER")
        if not reader:
            plan.require_resolved_bindings()
        target = os.environ.get("BTRC_NATIVE_TARGET", "")
        sysroot = os.environ.get("BTRC_NATIVE_SYSROOT", "")
        architecture = "arm64" if plan.target.architecture == "aarch64" else "x86_64"
        if plan.target.operating_system != "macos" or not re.fullmatch(
            rf"{architecture}-apple-macosx[0-9]+\.[0-9]+\.[0-9]+", target
        ):
            raise IncludeResolutionError(
                "experimental native imports require an explicit matching macOS BTRC_NATIVE_TARGET triple"
            )
        if not os.path.isdir(sysroot):
            raise IncludeResolutionError("native imports require an explicit available BTRC_NATIVE_SYSROOT")
        for binding in plan.bindings:
            self._origin = NativeHeaderSource(binding.module, binding.header)
            if binding.language != "c":
                raise IncludeResolutionError(f"{binding.module}: Objective-C/C++ call adapters are not implemented")
            arguments = [
                reader,
                *(f"--symbol={name}" for name in binding.symbols),
                binding.header,
                "--",
                "-x",
                "c",
                f"-std={binding.standard}",
                f"--target={target}",
                "-isysroot",
                sysroot,
            ]
            for declaration in plan.declarations:
                if not declaration.selected_for(plan.target):
                    continue
                if declaration.kind == "include-directory":
                    arguments.extend(("-I", declaration.value))
                elif declaration.kind == "define":
                    arguments.append(
                        f"-D{declaration.value}={declaration.detail}"
                        if declaration.detail
                        else f"-D{declaration.value}"
                    )
            try:
                result = subprocess.run(arguments, capture_output=True, text=True, timeout=60, check=False)
                if result.returncode:
                    raise NativeImportError(result.stderr.strip() or "native header reader failed")
                header = NativeHeaderCodec().decode(result.stdout, expected_target=target)
                self._layouts = {record.identity: record for record in header.records}
                for declaration in header.exports:
                    self._import(declaration)
            except (OSError, subprocess.TimeoutExpired, NativeImportError) as error:
                raise IncludeResolutionError(f"{binding.module}: {error}") from error
        return tuple(self._declarations.values())

    def _add(self, name, declaration, native_type=None, type_spelling=""):
        key = (str(self._origin), name)
        if key in self._declarations:
            if self._native_types.get(key) != native_type:
                raise NativeImportError(f"conflicting native declaration {name!r}")
            return
        declaration.source_file = NativeHeaderSource(str(self._origin), self._origin.header, type_spelling)
        self._declarations[key] = declaration
        self._native_types[key] = native_type

    def _qualify(self, projected, native):
        qualifiers = native.qualifiers
        if qualifiers.is_restrict or qualifiers.is_volatile or qualifiers.nullability != "unannotated":
            raise NativeImportError("native qualifier requires native-type lowering; refusing a lossy projection")
        if qualifiers.is_const and isinstance(native, (NativePointer, NativeAlias)):
            raise NativeImportError("pointer/alias const requires native-type lowering; refusing a lossy projection")
        return replace(projected, is_const=projected.is_const or qualifiers.is_const)

    def _record(self, native, alias=""):
        key = (str(self._origin), native.identity)
        if key not in self._records:
            name = native.name or alias
            if not name:
                raise NativeImportError("anonymous native record requires a named typedef")
            declaration = ast.StructDecl(name=name, fields=[], is_forward=True)
            spelling = f"{native.record_kind} {native.name}" if native.name else alias
            self._add(name, declaration, (native.identity, native.record_kind), spelling)
            self._records[key] = declaration
        declaration = self._records[key]
        if not native.opaque and declaration.is_forward:
            layout = self._layouts[native.identity]
            if layout.record_kind != "struct" or layout.record_kind != native.record_kind:
                raise NativeImportError("native union values require native-type lowering")
            # Register the owner before walking fields so recursive pointers
            # share its identity without recursively copying its layout.
            declaration.is_forward = False
            for field in layout.fields:
                if field.is_anonymous or field.is_bitfield or not field.name:
                    raise NativeImportError("anonymous fields and bitfields require native-type lowering")
                declaration.fields.append(ast.FieldDef(name=field.name, type=self._type(field.field_type)))
        return ast.TypeExpr(base=declaration.name)

    def _type(self, native):
        if isinstance(native, NativeBuiltin):
            if native.name not in {
                "void",
                "char",
                "signed char",
                "unsigned char",
                "short",
                "unsigned short",
                "int",
                "unsigned int",
                "long",
                "unsigned long",
                "long long",
                "unsigned long long",
                "float",
                "double",
            }:
                raise NativeImportError(f"unsupported native scalar {native.name!r}")
            projected = ast.TypeExpr(base=native.name)
        elif isinstance(native, NativeAlias):
            original = (
                self._qualify(self._record(native.underlying, native.name), native.underlying)
                if isinstance(native.underlying, NativeRecordType)
                else self._type(native.underlying)
            )
            if original.base != native.name:
                self._add(native.name, ast.TypedefDecl(original=original, alias=native.name), native.underlying)
            projected = ast.TypeExpr(base=native.name)
        elif isinstance(native, NativePointer):
            if isinstance(native.pointee, NativeFunctionType):
                function = native.pointee
                if function.variadic:
                    raise NativeImportError("variadic native callbacks require adapter lowering")
                projected = ast.TypeExpr(
                    base="__fn_ptr",
                    generic_args=[self._type(function.return_type), *(self._type(t) for t in function.parameters)],
                )
                projected = self._qualify(projected, function)
            else:
                pointee = self._type(native.pointee)
                projected = replace(pointee, pointer_depth=pointee.pointer_depth + 1)
        elif isinstance(native, NativeRecordType):
            projected = self._record(native)
        elif isinstance(native, NativeQualifiedType):
            projected = self._type(native.underlying)
            if native.qualifiers != native.underlying.qualifiers:
                raise NativeImportError("qualified native wrapper requires native-type lowering")
        else:
            raise NativeImportError(f"{type(native).__name__} requires native-type lowering")
        return self._qualify(projected, native)

    def _import(self, declaration):
        if isinstance(declaration, NativeFunction):
            signature = declaration.signature
            if signature.variadic or declaration.link_name != declaration.name:
                raise NativeImportError("variadic/renamed native calls require adapter lowering")
            if declaration.returned_ownership != "unspecified" or any(
                parameter.cf_consumed or parameter.ns_consumed for parameter in declaration.parameter_semantics
            ):
                raise NativeImportError("annotated native ownership requires managed native lowering")
            parameters = []
            names = {parameter.name for parameter in declaration.parameter_semantics if parameter.name}
            for index, (native, semantics) in enumerate(
                zip(signature.parameters, declaration.parameter_semantics, strict=True)
            ):
                name = semantics.name
                if not name:
                    name = f"argument{index}"
                    while name in names:
                        name += "_"
                    names.add(name)
                parameters.append(ast.Param(type=self._type(native), name=name))
            imported = ast.FunctionDecl(
                name=declaration.name, return_type=self._type(signature.return_type), params=parameters, body=None
            )
        elif isinstance(declaration, NativeConstant):
            imported = ast.VarDeclStmt(
                type=replace(self._type(declaration.value_type), is_const=True),
                name=declaration.name,
                initializer=ast.IntLiteral(value=int(declaration.decimal_value), raw=declaration.decimal_value),
            )
        elif isinstance(declaration, NativeTypedef):
            self._type(
                NativeAlias(name=declaration.name, underlying=declaration.underlying, qualifiers=NativeQualifiers())
            )
            return
        elif isinstance(declaration, NativeRecordDeclaration):
            self._type(declaration.record_type)
            return
        else:
            raise NativeImportError("selected native records require native-type lowering")
        self._add(declaration.name, imported, declaration)


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
    def _unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise NativeImportError(f"duplicate native object key: {key}")
            result[key] = value
        return result

    @staticmethod
    def _layout_integer(value):
        if len(value) > 20 or (len(value) == 20 and value > "18446744073709551615"):
            raise NativeImportError("native layout exceeds uint64")
        return int(value)

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
            value = json.loads(source, object_pairs_hook=self._unique_object)
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
            "record": ({"name", "identity", "record_kind", "complete", "opaque"}, set()),
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
                record_kind=self._choice(value["record_kind"], {"struct", "union"}),
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
        size_value = self._layout_integer(size)
        if self._layout_integer(alignment) == 0:
            raise NativeImportError("native record alignment must be positive")
        fields = []
        for entry in self._array(value["fields"]):
            self._object(entry, {"name", "type", "offset_bits", "anonymous"}, {"width_bits"})
            offset = self._decimal(entry["offset_bits"])
            width = self._decimal(entry["width_bits"]) if "width_bits" in entry else "0"
            if self._layout_integer(offset) + self._layout_integer(width) > size_value:
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
