"""Decode native header semantics without erasing qualifiers or ownership."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, replace

from ..abi.native_generated import (
    NativeAlias,
    NativeArrayType,
    NativeBuiltin,
    NativeConstant,
    NativeEnumType,
    NativeField,
    NativeFunction,
    NativeFunctionType,
    NativeGlobal,
    NativeHeader,
    NativeObjectiveCBlock,
    NativeObjectiveCInterface,
    NativeObjectiveCMethod,
    NativeObjectiveCObject,
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


@dataclass(frozen=True)
class NativeRecordInputField:
    name: str
    value_type: ast.TypeExpr
    record: str = ""
    prefix: str = ""
    object_type: str = ""


@dataclass(frozen=True)
class NativeRecordInput:
    name: str
    native_spelling: str
    fields: tuple[NativeRecordInputField, ...]

    @property
    def input_name(self):
        return f"{self.name}Input"


@dataclass(frozen=True)
class NativeCallContract:
    """Checks at a native call boundary, including calls through function values."""

    nonnull_parameters: tuple[bool, ...] = ()
    nonnull_return: bool = False
    read_only_borrows: tuple[bool, ...] = ()
    realtime_safe: bool = False
    record_inputs: tuple[NativeRecordInput | None, ...] = ()
    record_types: tuple[NativeRecordInput, ...] = ()

    def adapter_symbol(self, name):
        return (
            f"__btrc_native_{name}"
            if self.nonnull_return or any(self.nonnull_parameters) or any(self.record_inputs)
            else name
        )


class NativeHeaderSource(str):
    """Module provenance plus the SDK header that owns the native declaration."""

    def __new__(
        cls,
        module: str,
        header: str,
        type_spelling: str = "",
        read_only: bool = False,
        call_contract=None,
        field_contracts=None,
        coalesced=False,
        language="c",
        methods=None,
        native_ancestors=(),
        headers=None,
    ):
        value = super().__new__(cls, module)
        value.header = header
        value.type_spelling = type_spelling
        value.read_only = read_only
        value.call_contract = call_contract
        value.field_contracts = {} if field_contracts is None else field_contracts
        value.coalesced = coalesced
        value.language = language
        value.methods = {} if methods is None else methods
        value.native_ancestors = native_ancestors
        value.headers = (header,) if headers is None else headers
        return value

    def __getnewargs__(self):
        return (
            str(self),
            self.header,
            self.type_spelling,
            self.read_only,
            self.call_contract,
            self.field_contracts,
            self.coalesced,
            self.language,
            self.methods,
            self.native_ancestors,
            self.headers,
        )


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
        self._expanded_records = set()
        self._borrows = set()
        self._realtime = set()
        self._layout_identities = {}
        self._interfaces = {}
        self._interface_names = {}
        self._binding_layouts = {}
        self._input_classes = []
        self._requires_selector = False

    def resolve(self, plan: NativeLinkPlan) -> tuple:
        if not plan.bindings:
            return ()
        reader = os.environ.get("BTRC_NATIVE_HEADER_READER")
        if not reader:
            plan.require_resolved_bindings()
        target = os.environ.get("BTRC_NATIVE_TARGET", "")
        sysroot = os.environ.get("BTRC_NATIVE_SYSROOT", "")
        architecture = plan.target.architecture
        if plan.target.operating_system == "macos":
            architecture = "arm64" if architecture == "aarch64" else "x86_64"
            pattern = rf"{architecture}-apple-macosx[0-9]+\.[0-9]+\.[0-9]+"
        elif plan.target.operating_system == "linux":
            pattern = rf"{architecture}-(?:unknown-)?linux-gnu"
        else:
            pattern = "(?!)"
        if not re.fullmatch(pattern, target):
            raise IncludeResolutionError(
                "native imports require an explicit matching macOS or Linux GNU BTRC_NATIVE_TARGET triple"
            )
        if not os.path.isdir(sysroot):
            raise IncludeResolutionError("native imports require an explicit available BTRC_NATIVE_SYSROOT")
        for binding in plan.bindings:
            self._borrows = set(binding.read_only_borrows)
            self._realtime = set(binding.realtime_safe)
            self._origin = NativeHeaderSource(binding.module, binding.header, language=binding.language)
            if binding.language not in ("c", "objective-c"):
                raise IncludeResolutionError(f"{binding.module}: Objective-C/C++ call adapters are not implemented")
            arguments = [
                reader,
                *(f"--symbol={name}" for name in binding.symbols),
                *(
                    f"--pkg-config={name}"
                    for name in sorted(
                        {
                            item.value
                            for item in plan.declarations
                            if item.kind == "pkg-config" and item.selected_for(plan.target)
                        }
                    )
                ),
                binding.header,
                "--",
                "-x",
                binding.language,
                f"-std={binding.standard}",
                f"--target={target}",
                "-isysroot",
                sysroot,
            ]
            if binding.language == "objective-c":
                if plan.target.operating_system != "macos":
                    raise IncludeResolutionError("Objective-C adapters currently require the macOS runtime")
                arguments.extend(("-fblocks", "-fobjc-arc"))
            if plan.target.operating_system == "linux":
                arguments.extend(("-isystem", os.path.join(sysroot, "usr", "include")))
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
                self._merge_interfaces(header.interfaces)
                self._layouts = {record.identity: record for record in header.records}
                self._binding_layouts.setdefault(binding.module, {}).update(self._layouts)
                for record in header.records:
                    identity = self._layout_identity(record)
                    previous = self._layout_identities.setdefault(record.identity, identity)
                    if previous != identity:
                        raise NativeImportError(f"conflicting native layout {record.name!r}")
                for declaration in header.exports:
                    self._import(declaration)
                if self._borrows:
                    raise NativeImportError(
                        f"read-only-borrows names unknown function parameter: {sorted(self._borrows)[0]}"
                    )
                if self._realtime:
                    raise NativeImportError(
                        f"realtime-safe names a non-function declaration: {sorted(self._realtime)[0]}"
                    )
            except (OSError, subprocess.TimeoutExpired, NativeImportError) as error:
                raise IncludeResolutionError(f"{binding.module}: {error}") from error
        try:
            self._project_record_inputs(plan)
            self._coalesce()
            self._validate_selector_storage()
        except NativeImportError as error:
            raise IncludeResolutionError(str(error)) from error
        return (*self._declarations.values(), *self._input_classes)

    def _validate_selector_storage(self):
        if not self._requires_selector:
            return
        for (module, name), declaration in self._declarations.items():
            if name != "SEL" or not isinstance(declaration, ast.TypedefDecl) or declaration.source_file.language != "c":
                continue
            target = declaration.original
            record = self._declarations.get((module, target.base))
            if (
                target.pointer_depth == 1
                and not target.is_const
                and isinstance(record, ast.StructDecl)
                and record.is_forward
            ):
                return
        raise NativeImportError("Objective-C selectors require an imported opaque C SEL typedef from the SDK")

    def _unqualified_native(self, value):
        while isinstance(value, (NativeAlias, NativeQualifiedType)):
            value = value.underlying
        return value

    def _project_record_inputs(self, plan):
        generated = set()
        for binding in plan.bindings:
            if not binding.owned_records and not binding.record_inputs:
                continue
            projections = {}
            object_fields = dict(binding.object_fields)
            for name in binding.owned_records:
                self._record_input(binding, name, projections, object_fields, ())
            if object_fields:
                raise NativeImportError(
                    f"{binding.module}: unknown projected object field {next(iter(object_fields))!r}"
                )
            for projection in projections.values():
                if projection.input_name in generated or any(
                    key[1] == projection.input_name for key in self._declarations
                ):
                    raise NativeImportError(f"conflicting native input class {projection.input_name!r}")
                generated.add(projection.input_name)
                self._input_classes.append(
                    ast.ClassDecl(
                        name=projection.input_name,
                        members=[
                            ast.FieldDecl(access="public", name=field.name, type=field.value_type)
                            for field in projection.fields
                        ],
                        source_file=binding.module,
                    )
                )
            by_function = {}
            for selected in binding.record_inputs:
                function, parameter = selected.split(".")
                by_function.setdefault(function, set()).add(parameter)
            for name, selected in by_function.items():
                declaration = self._declarations.get((binding.module, name))
                if not isinstance(declaration, ast.FunctionDecl):
                    raise NativeImportError(f"record-inputs requires a function: {name!r}")
                contract = declaration.source_file.call_contract
                if contract.realtime_safe:
                    raise NativeImportError("owning record input adapters are not realtime-safe")
                inputs = []
                nonnull = list(contract.nonnull_parameters)
                for index, parameter in enumerate(declaration.params):
                    if parameter.name not in selected:
                        inputs.append(None)
                        continue
                    selected.remove(parameter.name)
                    original = parameter.type
                    if (
                        original.base not in projections
                        or original.pointer_depth != 1
                        or not original.is_const
                        or original.is_array
                    ):
                        raise NativeImportError(
                            f"{name}.{parameter.name}: record-inputs requires a const pointer to an owned record"
                        )
                    projection = projections[original.base]
                    inputs.append(projection)
                    parameter.type = ast.TypeExpr(
                        base=projection.input_name,
                        is_nullable=original.is_nullable,
                        pointer_depth=int(original.is_nullable),
                    )
                    nonnull[index] = not original.is_nullable
                if selected:
                    raise NativeImportError(f"{name}: record-inputs names an unknown parameter")
                declaration.source_file.call_contract = replace(
                    contract,
                    nonnull_parameters=tuple(nonnull),
                    record_inputs=tuple(inputs),
                    record_types=tuple(projections[name] for name in sorted(projections)),
                )

    def _record_input(self, binding, name, projections, object_fields, active):
        if name in projections:
            return projections[name]
        if name in active:
            raise NativeImportError(f"cyclic native record input projection: {name}")
        declaration = self._declarations.get((binding.module, name))
        if not isinstance(declaration, ast.StructDecl) or declaration.is_forward or not declaration.fields:
            raise NativeImportError(f"owned-records requires a complete selected struct: {name}")
        identity = self._native_types[(binding.module, name)][0]
        layout = self._binding_layouts[binding.module][identity]
        native_fields = {field.name: field for field in layout.fields}
        fields = []
        for field in declaration.fields:
            target = object_fields.pop(f"{name}.{field.name}", None)
            if target is None:
                if field.type.is_array or (field.type.is_const and field.type.pointer_depth == 0):
                    raise NativeImportError(f"{name}.{field.name}: owning input requires assignable non-array fields")
                fields.append(NativeRecordInputField(field.name, field.type))
                continue
            nullable = target.endswith("?")
            target = target.removesuffix("?")
            native = self._unqualified_native(native_fields[field.name].field_type)
            if not isinstance(native, NativePointer):
                raise NativeImportError(f"{name}.{field.name}: object projection requires a pointer field")
            pointee = self._unqualified_native(native.pointee)
            if target in binding.owned_records:
                child = self._record_input(binding, target, projections, object_fields, (*active, name))
                child_identity = self._native_types[(binding.module, target)][0]
                child_layout = self._binding_layouts[binding.module][child_identity]
                prefix = ""
                if not isinstance(pointee, NativeRecordType) or pointee.identity != child_identity:
                    first = child_layout.fields[0]
                    first_type = self._unqualified_native(first.field_type)
                    if (
                        not isinstance(pointee, NativeRecordType)
                        or not isinstance(first_type, NativeRecordType)
                        or first.offset_bits != "0"
                        or first_type.identity != pointee.identity
                    ):
                        raise NativeImportError(f"{name}.{field.name}: incompatible projected record pointer")
                    prefix = first.name
                value_type = ast.TypeExpr(base=child.input_name, is_nullable=nullable, pointer_depth=int(nullable))
                fields.append(NativeRecordInputField(field.name, value_type, child.name, prefix))
            else:
                selected = any(
                    isinstance(owner, ast.ClassDecl)
                    and owner.name == target
                    and owner.source_file.language == "objective-c"
                    for owner in self._declarations.values()
                )
                if not isinstance(pointee, NativeBuiltin) or pointee.name != "void" or not selected:
                    raise NativeImportError(
                        f"{name}.{field.name}: expected an erased pointer to a selected Objective-C object"
                    )
                value_type = ast.TypeExpr(base=target, is_nullable=nullable, pointer_depth=int(nullable))
                fields.append(NativeRecordInputField(field.name, value_type, object_type=target))
        result = NativeRecordInput(name, declaration.source_file.type_spelling, tuple(fields))
        projections[name] = result
        return result

    def _layout_identity(self, record):
        return (
            record.record_kind,
            record.size_bits,
            record.alignment_bits,
            tuple(
                (
                    field.name,
                    self._type_identity(field.field_type),
                    field.offset_bits,
                    field.is_anonymous,
                    field.is_bitfield,
                    field.width_bits,
                )
                for field in record.fields
            ),
        )

    def _merge_interfaces(self, interfaces):
        for entry in interfaces:
            previous = self._interfaces.get(entry.name)
            if self._interface_names.get(entry.identity, entry.name) != entry.name or (
                previous is not None
                and (
                    previous.identity != entry.identity or (previous.complete and entry.complete and previous != entry)
                )
            ):
                raise NativeImportError(f"conflicting Objective-C interface {entry.name!r}")
            self._interface_names[entry.identity] = entry.name
            if previous is None or entry.complete:
                self._interfaces[entry.name] = entry

    def _coalesce(self):
        """Keep all visibility owners, but select one checked semantic declaration."""
        selected = {}
        for key, declaration in self._declarations.items():
            name = key[1]
            if isinstance(declaration, ast.ClassDecl) and declaration.source_file.language == "objective-c":
                current = self._interfaces.get(name)
                ancestors = []
                while current is not None and current.superclass:
                    current = self._interfaces[self._interface_names[current.superclass]]
                    ancestors.append(current.name)
                if name != "id":
                    ancestors.append("id")
                declaration.source_file.native_ancestors = tuple(ancestors)
            if name not in selected:
                selected[name] = key
                continue
            previous_key = selected[name]
            previous = self._declarations[previous_key]
            origin = declaration.source_file
            previous_origin = previous.source_file
            shared_c_record = (
                isinstance(previous, ast.StructDecl)
                and isinstance(declaration, ast.StructDecl)
                and bool(previous.fields)
                and bool(declaration.fields)
                and {previous_origin.language, origin.language} == {"c", "objective-c"}
            )
            if (
                type(previous) is not type(declaration)
                or self._native_types[previous_key] != self._native_types[key]
                or previous_origin.type_spelling != origin.type_spelling
                or previous_origin.read_only != origin.read_only
                or previous_origin.call_contract != origin.call_contract
                or (previous_origin.language != origin.language and not shared_c_record)
                or (
                    isinstance(declaration, ast.StructDecl)
                    and previous.fields
                    and declaration.fields
                    and previous_origin.field_contracts != origin.field_contracts
                )
            ):
                raise IncludeResolutionError(
                    f"{origin}: conflicting native declaration {name!r} also imported by {previous_origin}"
                )
            if shared_c_record:
                # Layout identity was checked across SDK reads above. When C
                # also owns the complete record, use that SDK type in both
                # translation units, not an Objective-C-only value projection.
                if origin.language == "c":
                    previous_origin.coalesced = True
                    selected[name] = key
                else:
                    origin.coalesced = True
                continue
            if isinstance(declaration, ast.ClassDecl) and origin.language == "objective-c":
                self._merge_objective_c_methods(previous, declaration)
                origin.coalesced = True
                continue
            # Prefer selected record fields to an opaque parameter type,
            # retaining both modules' pre-analysis visibility owners.
            if isinstance(declaration, ast.StructDecl) and (
                (previous.is_forward and not declaration.is_forward) or (not previous.fields and declaration.fields)
            ):
                previous_origin.coalesced = True
                selected[name] = key
            else:
                origin.coalesced = True

    def _merge_objective_c_methods(self, previous, declaration):
        origin = declaration.source_file
        selected = previous.source_file
        for name, method in origin.methods.items():
            if name in selected.methods and selected.methods[name] != method:
                raise IncludeResolutionError(
                    f"{origin}: conflicting native declaration {declaration.name!r}, method {name!r}, also imported by {selected}"
                )
        previous.members.extend(member for member in declaration.members if member.name not in selected.methods)
        selected.methods.update(origin.methods)
        selected.headers = tuple(dict.fromkeys((*selected.headers, *origin.headers)))

    def _add(self, name, declaration, native_type=None, type_spelling="", read_only=False, call_contract=None):
        key = (str(self._origin), name)
        if key in self._declarations:
            previous = self._declarations[key]
            if (
                self._native_types.get(key) != native_type
                or type(previous) is not type(declaration)
                or previous.source_file.type_spelling != type_spelling
                or previous.source_file.read_only != read_only
                or previous.source_file.call_contract != call_contract
            ):
                raise NativeImportError(f"conflicting native declaration {name!r}")
            return
        declaration.source_file = NativeHeaderSource(
            str(self._origin),
            self._origin.header,
            type_spelling,
            read_only,
            call_contract,
            language=self._origin.language,
        )
        self._declarations[key] = declaration
        self._native_types[key] = native_type

    def _qualify(self, projected, native, *, call_boundary=False):
        qualifiers = native.qualifiers
        if (
            qualifiers.is_restrict
            or qualifiers.is_volatile
            or (not call_boundary and qualifiers.nullability != "unannotated")
        ):
            raise NativeImportError("native qualifier requires native-type lowering; refusing a lossy projection")
        qualified_type = native
        while isinstance(qualified_type, (NativeAlias, NativeQualifiedType)):
            qualified_type = qualified_type.underlying
        handle_record = (
            self._without_spelling_wrappers(qualified_type.pointee)
            if isinstance(qualified_type, NativePointer)
            else None
        )
        # Preserve the SDK typedef: const qualifies its handle slot, not the
        # opaque pointee. Unnamed/layered native pointers remain unsupported.
        handle_alias = (
            isinstance(native, NativeAlias)
            and projected.base == native.name
            and projected.pointer_depth == 0
            and isinstance(handle_record, NativeRecordType)
            and not handle_record.complete
        )
        if (
            qualifiers.is_const
            and not handle_alias
            and not isinstance(qualified_type, (NativeBuiltin, NativeRecordType, NativeEnumType))
        ):
            raise NativeImportError("pointer/alias const requires native-type lowering; refusing a lossy projection")
        return replace(projected, is_const=projected.is_const or qualifiers.is_const)

    def _type_identity(self, native):
        # Typedef and spelling layers do not create new C types. Peel only
        # layers that add no qualifiers; retain all pointer/record identities
        # and qualification boundaries rather than comparing storage size.
        while (
            isinstance(native, (NativeAlias, NativeQualifiedType)) and native.qualifiers == native.underlying.qualifiers
        ):
            native = native.underlying
        identity = (type(native), native.qualifiers)
        if isinstance(native, NativeBuiltin):
            return (*identity, native.name, native.bits, native.alignment_bits, native.signedness)
        if isinstance(native, NativeRecordType):
            # Opaque describes this use of the record, not a distinct C type.
            return (*identity, native.identity, native.record_kind)
        if isinstance(native, NativeObjectiveCObject):
            return (
                *identity,
                native.identity,
                native.name,
                native.class_object,
                tuple(native.protocols),
                tuple(self._type_identity(argument) for argument in native.type_arguments),
            )
        if isinstance(native, NativePointer):
            return (*identity, self._type_identity(native.pointee))
        if isinstance(native, NativeAlias):
            return (*identity, native.name, self._type_identity(native.underlying))
        if isinstance(native, NativeQualifiedType):
            return (*identity, self._type_identity(native.underlying))
        if isinstance(native, NativeFunctionType):
            return (
                *identity,
                native.variadic,
                native.calling_convention,
                self._type_identity(native.return_type),
                tuple(self._type_identity(parameter) for parameter in native.parameters),
            )
        if isinstance(native, NativeArrayType):
            return (*identity, native.count, self._type_identity(native.element))
        if isinstance(native, NativeEnumType):
            return (*identity, native.identity, self._type_identity(native.underlying))
        raise NativeImportError("unsupported native type identity")

    def _record(self, native, alias=""):
        key = (str(self._origin), native.identity)
        if key not in self._records:
            name = native.name or alias
            if not name:
                raise NativeImportError("anonymous native record requires a named typedef")
            # A complete SDK type can own storage even when imported through
            # a pointer. Its fields remain unavailable until explicitly read;
            # the included header, not a mirrored record, owns sizeof/alignment.
            declaration = ast.StructDecl(name=name, fields=[], is_forward=not native.complete)
            spelling = f"{native.record_kind} {native.tag_name}" if native.tag_name else name
            self._add(name, declaration, (native.identity, native.record_kind), spelling)
            self._records[key] = declaration
        declaration = self._records[key]
        if not native.opaque and key not in self._expanded_records:
            layout = self._layouts[native.identity]
            if layout.record_kind != "struct" or layout.record_kind != native.record_kind:
                raise NativeImportError("native union values require native-type lowering")
            # Register the owner before walking fields so recursive pointers
            # share its identity without recursively copying its layout.
            declaration.is_forward = False
            self._expanded_records.add(key)
            for field in layout.fields:
                if field.is_anonymous or field.is_bitfield or not field.name:
                    raise NativeImportError("anonymous fields and bitfields require native-type lowering")
                if self._origin.language == "objective-c":
                    value_type = self._objective_c_value(field.field_type)
                    if value_type.is_const:
                        raise NativeImportError("Objective-C const record fields require initialization-only lowering")
                    declaration.fields.append(ast.FieldDef(name=field.name, type=value_type))
                    continue
                callback = self._callback_field(field.field_type)
                if callback is None:
                    projected = self._field_type(field.field_type)
                else:
                    projected, contract = callback
                    if any(contract.nonnull_parameters):
                        declaration.source_file.field_contracts[field.name] = contract
                declaration.fields.append(ast.FieldDef(name=field.name, type=projected))
        return ast.TypeExpr(base=declaration.name)

    def _callback_field(self, native):
        pointer = native
        while isinstance(pointer, (NativeAlias, NativeQualifiedType)):
            pointer = pointer.underlying
        if not isinstance(pointer, NativePointer):
            return None
        signature = pointer.pointee
        while isinstance(signature, (NativeAlias, NativeQualifiedType)):
            signature = signature.underlying
        if not isinstance(signature, NativeFunctionType):
            return None
        if self._call_nullability(native) == "nonnull":
            raise NativeImportError("nested native non-null contracts require native-type lowering")
        if signature.variadic:
            raise NativeImportError("variadic native callbacks require adapter lowering")
        if self._call_nullability(signature.return_type) == "nonnull":
            raise NativeImportError("native callback non-null results require adapter lowering")
        contract = NativeCallContract(
            tuple(self._call_nullability(value) == "nonnull" for value in signature.parameters)
        )
        projected = ast.TypeExpr(
            base="__fn_ptr",
            generic_args=[
                self._type(self._without_call_nullability(signature.return_type)),
                *(self._type(self._without_call_nullability(value, parameter=True)) for value in signature.parameters),
            ],
        )
        # Incoming callback arguments may have stronger guarantees than BTRC
        # requires. Keep that direction on the field: a read cannot erase it.
        current = native
        while True:
            projected = self._qualify(projected, current, call_boundary=True)
            if not isinstance(current, (NativeAlias, NativeQualifiedType)):
                break
            current = current.underlying
        return self._qualify(projected, signature), contract

    def _field_type(self, native):
        native = self._without_spelling_wrappers(self._without_nested_nullable(native))
        if isinstance(native, NativeArrayType):
            if native.count is None or not 0 < int(native.count) <= 2147483647:
                raise NativeImportError("native array field requires a positive representable fixed bound")
            element = self._field_type(native.element)
            if element.is_array:
                raise NativeImportError("multidimensional native array fields require native-type lowering")
            return self._qualify(
                replace(element, is_array=True, array_size=ast.IntLiteral(value=int(native.count), raw=native.count)),
                native,
            )
        return self._type(native)

    def _without_spelling_wrappers(self, native):
        while isinstance(native, NativeQualifiedType):
            if native.qualifiers != native.underlying.qualifiers:
                raise NativeImportError("qualified native wrapper requires native-type lowering")
            native = native.underlying
        return native

    def _type(self, native):
        native = self._without_spelling_wrappers(native)
        if isinstance(native, NativeBuiltin):
            if native.name not in {
                "void",
                "bool",
                "_Bool",
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
            projected = ast.TypeExpr(base="bool" if native.name in {"bool", "_Bool"} else native.name)
        elif isinstance(native, NativeAlias):
            original = (
                self._qualify(self._record(native.underlying, native.name), native.underlying)
                if isinstance(native.underlying, NativeRecordType)
                else self._enum(native.underlying, native.name)
                if isinstance(native.underlying, NativeEnumType)
                else self._type(native.underlying)
            )
            if original.base != native.name:
                self._add(
                    native.name,
                    ast.TypedefDecl(original=original, alias=native.name),
                    self._type_identity(native.underlying),
                )
            projected = ast.TypeExpr(base=native.name)
        elif isinstance(native, NativeEnumType):
            projected = self._enum(native)
        elif isinstance(native, NativePointer):
            pointee = self._without_spelling_wrappers(native.pointee)
            if isinstance(pointee, NativeFunctionType):
                function = pointee
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
        else:
            raise NativeImportError(f"{type(native).__name__} requires native-type lowering")
        return self._qualify(projected, native)

    def _enum(self, native, alias=""):
        underlying = self._type(native.underlying)
        name = native.name or alias
        if not name:
            return self._qualify(underlying, native)
        self._add(
            name,
            ast.TypedefDecl(original=underlying, alias=name),
            ("native-enum", native.identity, self._type_identity(native.underlying)),
            type_spelling=f"enum {native.name}" if native.name else alias,
        )
        return self._qualify(ast.TypeExpr(base=name), native)

    def _import(self, declaration):
        if self._origin.language == "objective-c" and not isinstance(
            declaration, (NativeObjectiveCMethod, NativeConstant, NativeGlobal)
        ):
            raise NativeImportError("Objective-C header declarations require adapter lowering")
        contract = None
        if isinstance(declaration, NativeFunction):
            signature = declaration.signature
            if signature.variadic:
                raise NativeImportError("variadic native calls require adapter lowering")
            # Emit calls through the included header's source spelling. The C
            # compiler owns SDK asm labels (including Darwin's pthread aliases);
            # redeclaring or calling the linker spelling would discard that ABI.
            if declaration.returned_ownership != "unspecified" or any(
                parameter.cf_consumed or parameter.ns_consumed for parameter in declaration.parameter_semantics
            ):
                raise NativeImportError("annotated native ownership requires managed native lowering")
            parameters = []
            borrows = []
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
                parameters.append(ast.Param(type=self._call_type(native, parameter=True), name=name))
                key = f"{declaration.name}.{semantics.name}"
                borrowed = key in self._borrows
                if borrowed:
                    projected = parameters[-1].type
                    # A declaration is a trusted lifetime promise, not permission
                    # to mutate managed storage or borrow pointer-containing graphs.
                    scalar = native
                    while isinstance(scalar, (NativeAlias, NativeQualifiedType)):
                        scalar = scalar.underlying
                    if isinstance(scalar, NativePointer):
                        scalar = scalar.pointee
                    while isinstance(scalar, (NativeAlias, NativeQualifiedType)):
                        scalar = scalar.underlying
                    if projected.pointer_depth != 1 or not projected.is_const or not isinstance(scalar, NativeBuiltin):
                        raise NativeImportError("read-only-borrows requires a const scalar pointer parameter")
                    self._borrows.remove(key)
                borrows.append(borrowed)
            imported = ast.FunctionDecl(
                name=declaration.name, return_type=self._call_type(signature.return_type), params=parameters, body=None
            )
            contract = NativeCallContract(
                tuple(self._call_nullability(value) == "nonnull" for value in signature.parameters),
                self._call_nullability(signature.return_type) == "nonnull",
                tuple(borrows),
                declaration.name in self._realtime,
            )
            self._realtime.discard(declaration.name)
        elif isinstance(declaration, NativeGlobal):
            native = declaration.value_type
            while isinstance(native, (NativeAlias, NativeQualifiedType)):
                native = native.underlying
            object_global = self._origin.language == "objective-c" and isinstance(native, NativeObjectiveCObject)
            if object_global and not declaration.read_only:
                raise NativeImportError("Mutable Objective-C object globals require managed storage lowering")
            projected = (
                self._objective_c_type(declaration.value_type, read_only_slot=True)
                if object_global
                else self._objective_c_scalar(declaration.value_type)
                if self._origin.language == "objective-c"
                else self._type(declaration.value_type)
            )
            imported = ast.VarDeclStmt(
                type=replace(
                    projected,
                    is_extern=True,
                    is_const=projected.is_const
                    or (declaration.read_only and not object_global and not isinstance(native, NativePointer)),
                ),
                name=declaration.name,
                initializer=None,
            )
        elif isinstance(declaration, NativeConstant):
            native = declaration.value_type
            while isinstance(native, (NativeAlias, NativeQualifiedType, NativeEnumType)):
                native = native.underlying
            raw = declaration.decimal_value + (
                "U" if isinstance(native, NativeBuiltin) and native.signedness == "unsigned" else ""
            )
            imported = ast.VarDeclStmt(
                type=replace(
                    self._objective_c_scalar(declaration.value_type)
                    if self._origin.language == "objective-c"
                    else self._type(declaration.value_type),
                    is_const=True,
                ),
                name=declaration.name,
                initializer=ast.IntLiteral(value=int(declaration.decimal_value), raw=raw),
            )
        elif isinstance(declaration, NativeTypedef):
            self._type(
                NativeAlias(
                    name=declaration.name,
                    underlying=declaration.underlying,
                    qualifiers=NativeQualifiers(nullability="unannotated"),
                )
            )
            return
        elif isinstance(declaration, NativeRecordDeclaration):
            self._type(declaration.record_type)
            return
        elif isinstance(declaration, NativeObjectiveCMethod):
            self._import_objective_c_method(declaration)
            return
        else:
            raise NativeImportError("selected native records require native-type lowering")
        self._add(
            declaration.name,
            imported,
            self._declaration_identity(declaration),
            read_only=isinstance(declaration, NativeGlobal) and declaration.read_only,
            call_contract=contract,
        )

    def _objective_c_scalar(self, native):
        """Project scalar ABI values without leaking Objective-C SDK typedefs into C."""
        const = False
        while isinstance(native, (NativeAlias, NativeQualifiedType, NativeEnumType)):
            if native.qualifiers.is_volatile or native.qualifiers.is_restrict:
                raise NativeImportError("Objective-C scalar qualifiers require native-type lowering")
            const |= native.qualifiers.is_const
            native = native.underlying
        if not isinstance(native, NativeBuiltin):
            raise NativeImportError("Objective-C objects, pointers and aggregates require managed native lowering")
        if native.name in ("bool", "_Bool"):
            return self._qualify(ast.TypeExpr(base="bool", is_const=const), native)
        projected = self._type(native)
        return replace(projected, is_const=const or projected.is_const)

    def _objective_c_class(self, name):
        key = (str(self._origin), name)
        if key not in self._declarations:
            self._add(name, ast.ClassDecl(name=name, is_abstract=True), ("objective-c-class", name))
        owner = self._declarations[key]
        if not isinstance(owner, ast.ClassDecl) or owner.source_file.language != "objective-c":
            raise NativeImportError(f"conflicting native declaration {name!r}")
        return owner

    def _objective_c_value(self, native):
        original = native
        constant = False
        while isinstance(native, (NativeAlias, NativeQualifiedType)):
            if native.qualifiers.is_volatile or native.qualifiers.is_restrict:
                raise NativeImportError("Objective-C value qualifiers require native-type lowering")
            constant |= native.qualifiers.is_const
            native = native.underlying
        if not isinstance(native, NativeRecordType):
            return self._objective_c_scalar(original)
        if not native.complete or native.opaque or not self._layouts[native.identity].fields:
            raise NativeImportError("Objective-C record values require complete nonempty fields")
        projected = self._qualify(self._record(native), native)
        return replace(projected, is_const=constant or projected.is_const)

    def _objective_c_type(self, native, *, parameter=False, related_owner="", read_only_slot=False):
        original = native
        nullability = "unannotated"
        qualified = False
        while True:
            qualified |= (
                (native.qualifiers.is_const and not read_only_slot)
                or native.qualifiers.is_volatile
                or native.qualifiers.is_restrict
            )
            annotation = native.qualifiers.nullability
            if annotation != "unannotated":
                if nullability not in ("unannotated", annotation):
                    raise NativeImportError("conflicting Objective-C nullability")
                nullability = annotation
            if not isinstance(native, (NativeAlias, NativeQualifiedType)):
                break
            native = native.underlying
        if (
            isinstance(native, NativePointer)
            and isinstance(native.pointee, NativeBuiltin)
            and native.pointee.name == "SEL"
        ):
            if (
                qualified
                or native.pointee.qualifiers != NativeQualifiers(nullability="unannotated")
                or nullability not in ("unannotated", "nullable", "nonnull")
            ):
                raise NativeImportError("unsupported Objective-C selector qualifiers")
            # Clang models ObjC SEL as a builtin pointee. The SDK's C binding
            # owns its opaque pointer typedef; never substitute id or void*.
            self._requires_selector = True
            nullable = nullability != "nonnull"
            return ast.TypeExpr(base="SEL", is_nullable=nullable, pointer_depth=int(nullable))
        if parameter and isinstance(native, NativePointer):
            if qualified or nullability not in ("unannotated", "nullable", "nonnull"):
                raise NativeImportError("unsupported Objective-C pointer qualifiers")
            projected = self._objective_c_scalar(native.pointee)
            return replace(projected, pointer_depth=1, is_nullable=nullability != "nonnull")
        if not isinstance(native, NativeObjectiveCObject):
            return self._objective_c_value(original)
        name = related_owner or native.name
        if native.class_object or native.protocols or native.type_arguments or name == "Class":
            raise NativeImportError("Objective-C protocol/generic/dynamic objects require managed native lowering")
        # Unqualified id is a managed object with no statically callable methods,
        # not a void pointer and not an assertion that it inherits NSObject.
        if not name:
            name = "id"
        if nullability not in ("unannotated", "nullable", "nonnull") or qualified:
            raise NativeImportError("unsupported Objective-C object qualifiers")
        if not related_owner and name in self._interfaces and self._interfaces[name].identity != native.identity:
            raise NativeImportError(f"conflicting Objective-C object identity {name!r}")
        self._objective_c_class(name)
        nullable = nullability != "nonnull"
        return ast.TypeExpr(base=name, is_nullable=nullable, pointer_depth=int(nullable))

    def _import_objective_c_method(self, declaration):
        if (
            declaration.signature.variadic
            or declaration.consumes_self
            or declaration.returns_inner_pointer
            or any(parameter.cf_consumed or parameter.ns_consumed for parameter in declaration.parameter_semantics)
        ):
            raise NativeImportError("Objective-C instance/ownership calls require managed native lowering")
        name = declaration.selector.split(":", 1)[0]
        method = ast.MethodDecl(
            access="class" if declaration.class_method else "public",
            name=name,
            return_type=self._objective_c_type(
                declaration.signature.return_type,
                related_owner=declaration.receiver if declaration.related_result else "",
            ),
            params=[
                ast.Param(type=self._objective_c_type(native, parameter=True), name=f"argument{index}")
                for index, native in enumerate(declaration.signature.parameters)
            ],
        )
        owner = self._objective_c_class(declaration.receiver)
        previous = owner.source_file.methods.get(name)
        if previous is not None:
            if previous != declaration:
                raise NativeImportError(f"ambiguous Objective-C method projection {declaration.receiver}.{name}")
            return
        owner.source_file.methods[name] = declaration
        owner.members.append(method)

    def _declaration_identity(self, declaration):
        if isinstance(declaration, NativeFunction):
            return (
                type(declaration),
                declaration.link_name,
                self._type_identity(declaration.signature),
                declaration.returned_ownership,
                tuple(
                    (parameter.cf_consumed, parameter.ns_consumed, parameter.no_escape)
                    for parameter in declaration.parameter_semantics
                ),
            )
        if isinstance(declaration, NativeGlobal):
            return type(declaration), self._type_identity(declaration.value_type), declaration.read_only
        return type(declaration), self._type_identity(declaration.value_type), declaration.decimal_value

    def _call_nullability(self, native):
        nullability = "unannotated"
        while True:
            annotation = native.qualifiers.nullability
            if annotation != "unannotated":
                if annotation not in {"nullable", "nonnull"} or nullability not in {"unannotated", annotation}:
                    raise NativeImportError("conflicting/unsupported native nullability requires native-type lowering")
                nullability = annotation
            if not isinstance(native, (NativeAlias, NativeQualifiedType)):
                break
            native = native.underlying
        if nullability != "unannotated" and not isinstance(native, NativePointer):
            raise NativeImportError("native nullability on non-pointer requires native-type lowering")
        return nullability

    def _without_call_nullability(self, native, *, parameter=False):
        # Top-level parameter restrict qualifies the callee's local pointer,
        # not the compatible function type. Keep the original SDK declaration
        # at the call site; do not erase nested/pointee qualifiers or apply this
        # rule to returns, globals, or typedef declarations.
        if (
            parameter
            and native.qualifiers.is_restrict
            and not isinstance(native, (NativeAlias, NativeQualifiedType, NativePointer))
        ):
            raise NativeImportError("native restrict parameter must be a pointer")
        qualifiers = replace(
            native.qualifiers,
            nullability="unannotated",
            is_restrict=False if parameter else native.qualifiers.is_restrict,
        )
        if isinstance(native, (NativeAlias, NativeQualifiedType)):
            return replace(
                native,
                qualifiers=qualifiers,
                underlying=self._without_call_nullability(native.underlying, parameter=parameter),
            )
        if isinstance(native, NativePointer):
            return replace(native, qualifiers=qualifiers, pointee=self._without_nested_nullable(native.pointee))
        if isinstance(native, NativeFunctionType):
            return replace(
                native,
                qualifiers=qualifiers,
                return_type=self._without_nested_nullable(native.return_type),
                parameters=[self._without_nested_nullable(item, parameter=True) for item in native.parameters],
            )
        return replace(native, qualifiers=qualifiers)

    def _without_nested_nullable(self, native, *, parameter=False):
        # BTRC raw pointers already permit null. A nested nullable output slot
        # or callback value therefore has exactly that value domain, with no
        # extra indirection and no non-null assumption. Keep the original SDK
        # declaration at the C boundary. Nested non-null is different: it needs
        # directional output/callback validation and must not be projected away.
        if self._call_nullability(native) == "nonnull":
            raise NativeImportError("nested native non-null contracts require native-type lowering")
        return self._without_call_nullability(native, parameter=parameter)

    def _call_type(self, native, *, parameter=False):
        nullability = self._call_nullability(native)
        projected = self._type(self._without_call_nullability(native, parameter=parameter))
        if nullability == "nullable":
            if projected.is_nullable:
                raise NativeImportError("nested native nullability requires native-type lowering")
            projected = replace(
                projected,
                is_nullable=True,
                pointer_depth=projected.pointer_depth
                if projected.base == "__fn_ptr"
                else max(1, projected.pointer_depth),
            )
        return projected


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
                value,
                {"schema", "target", "clang", "big_endian", "character_bits", "declarations", "records"},
                {"interfaces"},
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
                interfaces=[self._interface(entry) for entry in self._array(value.get("interfaces", []))],
            )
            self._verify_interfaces(header.interfaces)
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
                    if isinstance(entry, (NativeFunction, NativeObjectiveCMethod))
                    else entry.underlying
                    if isinstance(entry, NativeTypedef)
                    else entry.value_type
                    if isinstance(entry, (NativeConstant, NativeGlobal))
                    else entry.record_type
                )
                self._verify_layout_references(native_type, layouts)
            for record in header.records:
                for field in record.fields:
                    self._verify_layout_references(field.field_type, layouts)
            return header
        except (json.JSONDecodeError, RecursionError) as error:
            raise NativeImportError(f"invalid native header document: {error}") from error

    def _interface(self, value):
        self._object(value, {"name", "identity", "complete", "superclass"})
        result = NativeObjectiveCInterface(
            name=self._text(value["name"]),
            identity=self._text(value["identity"]),
            complete=self._boolean(value["complete"]),
            superclass=self._text(value["superclass"], empty=True),
        )
        if not result.complete and result.superclass:
            raise NativeImportError("incomplete Objective-C interface has a superclass")
        return result

    def _verify_interfaces(self, interfaces):
        by_identity = {entry.identity: entry for entry in interfaces}
        if len(by_identity) != len(interfaces) or len({entry.name for entry in interfaces}) != len(interfaces):
            raise NativeImportError("duplicate Objective-C interface name or identity")
        for entry in interfaces:
            visited = {entry.identity}
            parent = entry.superclass
            while parent:
                if parent not in by_identity:
                    raise NativeImportError("missing Objective-C superclass declaration")
                if parent in visited:
                    raise NativeImportError("cyclic Objective-C inheritance")
                visited.add(parent)
                ancestor = by_identity[parent]
                if not ancestor.complete:
                    raise NativeImportError("incomplete Objective-C superclass declaration")
                parent = ancestor.superclass

    def _type(self, value):
        if not isinstance(value, dict):
            raise NativeImportError("expected native type object")
        kind = self._text(value.get("kind"))
        fields = {
            "builtin": ({"name"}, {"bits", "alignment_bits", "signed"}),
            "pointer": ({"pointee"}, set()),
            "typedef": ({"name", "underlying"}, set()),
            "record": ({"name", "tag_name", "identity", "record_kind", "complete", "opaque"}, set()),
            "enum": ({"name", "identity", "underlying"}, set()),
            "function": ({"return_type", "parameters", "variadic", "calling_convention"}, set()),
            "array": ({"element", "count"}, set()),
            "qualified": ({"underlying"}, set()),
            "objc_object": ({"name", "identity", "class_object", "protocols", "type_arguments"}, set()),
            "objc_block": ({"signature"}, set()),
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
                tag_name=self._text(value["tag_name"], empty=True),
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
        if kind == "objc_object":
            name = self._text(value["name"], empty=True)
            identity = self._text(value["identity"], empty=True)
            if bool(name) != bool(identity):
                raise NativeImportError("Objective-C interface name and identity must agree")
            protocols = [self._text(protocol) for protocol in self._array(value["protocols"])]
            if len(set(protocols)) != len(protocols):
                raise NativeImportError("duplicate Objective-C protocol")
            return NativeObjectiveCObject(
                name=name,
                identity=identity,
                class_object=self._boolean(value["class_object"]),
                protocols=protocols,
                type_arguments=[self._type(argument) for argument in self._array(value["type_arguments"])],
                qualifiers=qualifiers,
            )
        if kind == "objc_block":
            signature = self._type(value["signature"])
            function = signature
            while isinstance(function, (NativeAlias, NativeQualifiedType)):
                function = function.underlying
            if not isinstance(function, NativeFunctionType):
                raise NativeImportError("Objective-C block requires a function signature")
            return NativeObjectiveCBlock(signature=signature, qualifiers=qualifiers)
        return NativeQualifiedType(underlying=self._type(value["underlying"]), qualifiers=qualifiers)

    def _declaration(self, value):
        if not isinstance(value, dict):
            raise NativeImportError("expected native declaration object")
        kind = self._text(value.get("kind"))
        required = {"kind", "name", "type"}
        if kind == "function":
            required |= {"link_name", "returned_ownership", "parameter_semantics"}
        elif kind == "objc_method":
            required |= {
                "identity",
                "owner",
                "receiver",
                "selector",
                "class_method",
                "returned_ownership",
                "parameter_semantics",
                "method_family",
                "consumes_self",
                "related_result",
                "returns_inner_pointer",
            }
        elif kind == "enum_constant":
            required |= {"value"}
        elif kind == "global":
            required |= {"read_only"}
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
        if kind in {"function", "objc_method"}:
            parameters = []
            for parameter in self._array(value["parameter_semantics"]):
                self._object(parameter, {"name", "cf_consumed", "ns_consumed", "no_escape"})
                parameters.append(
                    NativeParameterSemantics(
                        name=self._text(parameter["name"], empty=True),
                        cf_consumed=self._boolean(parameter["cf_consumed"]),
                        ns_consumed=self._boolean(parameter["ns_consumed"]),
                        no_escape=self._boolean(parameter["no_escape"]),
                    )
                )
            if not isinstance(native_type, NativeFunctionType) or len(parameters) != len(native_type.parameters):
                raise NativeImportError("native function semantics do not match its signature")
            if kind == "objc_method":
                owner = self._text(value["owner"])
                receiver = self._text(value["receiver"])
                selector = self._text(value["selector"])
                class_method = self._boolean(value["class_method"])
                if position["name"] != f"{'+' if class_method else '-'}[{receiver} {selector}]" or selector.count(
                    ":"
                ) != len(parameters):
                    raise NativeImportError("Objective-C selector does not match its receiver or signature")
                return NativeObjectiveCMethod(
                    **position,
                    identity=self._text(value["identity"]),
                    owner=owner,
                    receiver=receiver,
                    selector=selector,
                    class_method=class_method,
                    signature=native_type,
                    parameter_semantics=parameters,
                    returned_ownership=self._choice(value["returned_ownership"], self._OWNERSHIP),
                    method_family=self._choice(
                        value["method_family"],
                        {
                            "none",
                            "alloc",
                            "init",
                            "initialize",
                            "copy",
                            "mutable_copy",
                            "new",
                            "autorelease",
                            "dealloc",
                            "finalize",
                            "release",
                            "retain",
                            "retain_count",
                            "self",
                            "perform_selector",
                        },
                    ),
                    consumes_self=self._boolean(value["consumes_self"]),
                    related_result=self._boolean(value["related_result"]),
                    returns_inner_pointer=self._boolean(value["returns_inner_pointer"]),
                )
            return NativeFunction(
                **position,
                signature=native_type,
                link_name=self._text(value["link_name"]),
                parameter_semantics=parameters,
                returned_ownership=self._choice(value["returned_ownership"], self._OWNERSHIP),
            )
        if kind == "typedef":
            return NativeTypedef(**position, underlying=native_type)
        if kind == "global":
            return NativeGlobal(**position, value_type=native_type, read_only=self._boolean(value["read_only"]))
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
        elif isinstance(native_type, NativeObjectiveCObject):
            for argument in native_type.type_arguments:
                self._verify_layout_references(argument, layouts)
        elif isinstance(native_type, NativeObjectiveCBlock):
            self._verify_layout_references(native_type.signature, layouts)
        elif isinstance(native_type, NativeFunctionType):
            self._verify_layout_references(native_type.return_type, layouts)
            for parameter in native_type.parameters:
                self._verify_layout_references(parameter, layouts)
