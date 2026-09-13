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
    NativeCxxClass,
    NativeCxxMethod,
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
    callback: bool = False
    resource_type: str = ""
    by_value: bool = False

    @property
    def managed(self):
        return bool(self.object_type or self.resource_type)


@dataclass(frozen=True)
class NativeRecordInput:
    name: str
    native_spelling: str
    fields: tuple[NativeRecordInputField, ...]
    by_value: bool = False

    @property
    def input_name(self):
        return f"{self.name}Input"


@dataclass(frozen=True)
class NativeStringViewProjection:
    native_spelling: str
    data: str
    length: str
    length_spelling: str
    null_maximum: bool


@dataclass(frozen=True)
class NativeRecordOutput:
    parameter_index: int
    record: NativeRecordInput
    null_fields: tuple[str, ...]

    @property
    def output_name(self):
        return f"{self.record.name}Output"


@dataclass(frozen=True)
class NativeRealtimeOperation:
    name: str
    function: str
    owner_index: int
    parameters: tuple[ast.Param, ...]
    return_type: ast.TypeExpr


@dataclass(frozen=True)
class NativeCallbackTableMethod:
    name: str
    field: str
    parameters: tuple[ast.TypeExpr, ...]
    return_type: ast.TypeExpr
    native_parameters: tuple[str, ...]
    native_return: str


@dataclass(frozen=True)
class NativeCallbackTableProjection:
    """A generated SDK callback table whose one receiver claim lives per native table."""

    resource: str
    interface: str
    native_type: str
    context: str
    context_index: int
    methods: tuple[NativeCallbackTableMethod, ...]
    label: str = ""
    reopen: str = ""
    release: str = ""


@dataclass(frozen=True)
class NativeRealtimeRegistration:
    name: str
    invocation: str
    resource: str
    function: str
    owner_index: int
    size_index: int
    native_parameters: tuple[str, ...]
    operations: tuple[NativeRealtimeOperation, ...]
    status_type: ast.TypeExpr


@dataclass(frozen=True)
class NativeCallbackProjection:
    interface: str
    parameter_index: int
    context_index: int
    callback_context_index: int
    parameters: tuple[ast.TypeExpr, ...]
    return_type: ast.TypeExpr
    native_parameters: tuple[str, ...] = ()
    native_return: str = ""
    unregister: NativeObjectiveCMethod | NativeFunction | None = None
    activation_failure: str = ""
    method_name: str = "invoke"
    native_method: NativeObjectiveCMethod | None = None
    one_shot: bool = False
    owned_arguments: tuple[int, ...] = ()
    field: str = ""
    record: str = ""
    context_fields: tuple[str, ...] = ()
    callback_context_indices: tuple[int, ...] = ()
    string_arguments: tuple[tuple[int, NativeStringViewProjection], ...] = ()
    realtime: NativeRealtimeRegistration | None = None

    def is_context(self, index):
        return index == self.callback_context_index or index in self.callback_context_indices


@dataclass(frozen=True)
class NativeDelegateProjection:
    interface: str
    parameter_index: int
    unregister: NativeObjectiveCMethod
    activation_failure: str
    getter: NativeObjectiveCMethod
    protocol: str
    methods: tuple[NativeCallbackProjection, ...]
    one_shot: bool = False

    @property
    def context_index(self):
        return -1


@dataclass(frozen=True)
class NativeActionProjection:
    interface: str
    parameter_index: int
    unregister: NativeObjectiveCMethod
    activation_failure: str
    getter: NativeObjectiveCMethod
    action_setter: NativeObjectiveCMethod
    action_getter: NativeObjectiveCMethod
    methods: tuple[NativeCallbackProjection, ...]
    one_shot: bool = False

    @property
    def context_index(self):
        return -1


@dataclass(frozen=True)
class NativeOutputOffset:
    parameter_index: int
    input_index: int
    length_index: int
    field: str


@dataclass(frozen=True)
class NativeSizedResourceOutput:
    size_index: int
    size_type: ast.TypeExpr
    native_function: str


@dataclass(frozen=True)
class NativeInitializer:
    success: str
    copied_input: int = -1
    length: int = -1


@dataclass(frozen=True)
class NativeCopiedInput:
    owner_index: int
    input_index: int
    length_index: int
    resource: str


@dataclass(frozen=True)
class NativeOwnedOutput:
    parameter_index: int
    result_name: str
    resource: str
    status_type: ast.TypeExpr
    offset: NativeOutputOffset | None = None
    sized_resource: NativeSizedResourceOutput | None = None
    initializer: NativeInitializer | None = None

    def hides(self, index):
        return (
            index == self.parameter_index
            or bool(self.offset and index == self.offset.parameter_index)
            or bool(self.sized_resource and index == self.sized_resource.size_index)
        )


@dataclass(frozen=True)
class NativeCopiedResult:
    kind: str
    owner_index: int
    length_function: str = ""
    length_arguments: tuple[int, ...] = ()


@dataclass(frozen=True)
class NativeRecordPath:
    steps: tuple[tuple[str, bool], ...]
    value_type: ast.TypeExpr
    enum_identity: str = ""


@dataclass(frozen=True)
class NativeRecordSnapshot:
    result_name: str
    fields: tuple[NativeRecordInputField, ...]
    paths: tuple[NativeRecordPath, ...]
    byte_field: str = ""
    byte_paths: tuple[NativeRecordPath, ...] = ()
    guard_path: NativeRecordPath | None = None
    guard_constant: str = ""
    strings: tuple[tuple[str, NativeRecordPath], ...] = ()
    byte_span: bool = False


@dataclass(frozen=True)
class NativeCxxProjection:
    method: NativeCxxMethod
    receiver: str
    root_owner: str
    result_record: NativeRecordInput | None = None
    factory_result: str = ""
    success: str = ""
    status_field: str = ""


@dataclass(frozen=True)
class NativeCallContract:
    """Checks at a native call boundary, including calls through function values."""

    nonnull_parameters: tuple[bool, ...] = ()
    nonnull_return: bool = False
    read_only_borrows: tuple[bool, ...] = ()
    realtime_safe: bool = False
    record_inputs: tuple[NativeRecordInput | None, ...] = ()
    record_types: tuple[NativeRecordInput, ...] = ()
    resource_parameters: tuple[str, ...] = ()
    resource_result: str = ""
    callbacks: tuple[NativeCallbackProjection | NativeDelegateProjection | NativeActionProjection, ...] = ()
    objective_c_method: NativeObjectiveCMethod | None = None
    executor: str = ""
    record_output: NativeRecordOutput | None = None
    borrowed_result_owner: int = -1
    owned_output: NativeOwnedOutput | None = None
    bound_parameter: int = -1
    bound_constant: str = ""
    variadic_arguments: tuple[str, ...] = ()
    copied_result: NativeCopiedResult | None = None
    record_snapshot: NativeRecordSnapshot | None = None
    copied_input: NativeCopiedInput | None = None
    cxx_method: NativeCxxProjection | None = None
    callback_table: NativeCallbackTableProjection | None = None

    @property
    def returns_owned(self):
        return bool(
            self.resource_result
            or self.record_output
            or self.owned_output
            or self.copied_result
            or self.record_snapshot
            or (self.cxx_method and self.cxx_method.factory_result)
            or any(callback.one_shot for callback in self.callbacks)
            or any(getattr(callback, "realtime", None) is not None for callback in self.callbacks)
        )

    def adapter_symbol(self, name):
        return (
            f"__btrc_native_{name}"
            if self.nonnull_return
            or any(self.nonnull_parameters)
            or any(self.record_inputs)
            or any(self.resource_parameters)
            or self.resource_result
            or self.callbacks
            or self.record_output
            or self.owned_output
            or self.bound_parameter >= 0
            or self.copied_result
            or self.record_snapshot
            or self.copied_input
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
        resource=None,
        resource_query_type="",
        private_fields=False,
        invocation="",
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
        value.resource = resource
        value.resource_query_type = resource_query_type
        value.private_fields = private_fields
        value.invocation = invocation
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
            self.resource,
            self.resource_query_type,
            self.private_fields,
            self.invocation,
        )


class NativeDeclarationImporter:
    """Import selected C declarations into the normal typed compiler pipeline.

    Compatible C values retain their SDK spelling. Checked resources and
    Objective-C objects use normal managed cleanup through generated adapters.
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
        self._resources = {}
        self._resource_types = {}
        self._resource_records = {}
        self._resource_operations = set()
        self._callback_operations = set()
        self._callback_exports = {}
        self._owned_results = set()
        self._borrowed_results = {}
        self._resource_borrows = set()
        self._callbacks = {}
        self._main_thread_globals = set()
        self._static_globals = set()
        self._resource_parameters = {}
        self._resource_results = {}
        self._record_private_fields = {}
        self._record_resource_fields = {}
        self._string_views = {}
        self._used_string_views = set()

    def resolve(self, plan: NativeLinkPlan) -> tuple:
        if not plan.bindings:
            return ()
        self._callback_operations = {
            operation
            for binding in plan.bindings
            for callback in binding.callbacks
            for operation in (
                (callback.slot_getter, callback.action_setter, callback.action_getter, *callback.methods)
                if callback.slot_getter
                else (callback.unregister,)
            )
            if operation
        }
        for binding in plan.bindings:
            for callback in binding.callbacks:
                if callback.realtime is not None:
                    self._callback_operations.update(
                        parameter.split(".", 1)[0] for _, parameter in callback.realtime.operations
                    )
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
            self._callbacks = {callback.parameter: callback for callback in binding.callbacks}
            self._main_thread_globals = set(binding.main_thread_globals)
            self._static_globals = set(binding.static_globals)
            self._resource_parameters = dict(binding.resource_parameters)
            self._resource_results = dict(binding.resource_results)
            self._owned_outputs = dict(binding.owned_outputs)
            self._initializers = {value.function: value for value in binding.initializers}
            self._resource_initializers = {value.resource: value for value in binding.initializers}
            self._copied_inputs = {parameter: (owner, length) for parameter, owner, length in binding.copied_inputs}
            self._attached_resources = set()
            self._copied_results = {
                function: (kind, owner, length, arguments)
                for function, kind, owner, length, arguments in binding.copied_results
            }
            self._owned_output_resources = dict(binding.owned_output_resources)
            self._variadic_calls = {shape.parameter: shape for shape in binding.variadic_calls}
            self._output_offsets = {key: (input, length, field) for key, input, length, field in binding.output_offsets}
            self._origin = NativeHeaderSource(binding.module, binding.header, language=binding.language)
            if binding.language not in ("c", "objective-c"):
                raise IncludeResolutionError(f"{binding.module}: Objective-C/C++ call adapters are not implemented")
            arguments = [
                reader,
                *(f"--symbol={name}" for name in binding.symbols),
                *(
                    f"--record-path={path}"
                    for path in sorted(
                        {
                            f"{snapshot.owner}.{path}"
                            for snapshot in binding.record_snapshots
                            for path in (
                                *[path for _, path in snapshot.fields],
                                *snapshot.byte_plane[1:],
                                *snapshot.guard[:1],
                                *[path for _, path in snapshot.strings],
                                *snapshot.byte_span[1:],
                            )
                        }
                    )
                ),
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
                self._callback_exports = {declaration.name: declaration for declaration in header.exports}
                self._prepare_resources(binding, header)
                self._prepare_resource_conversions(binding, header)
                self._merge_interfaces(header.interfaces)
                self._layouts = {record.identity: record for record in header.records}
                self._binding_layouts.setdefault(binding.module, {}).update(self._layouts)
                self._prepare_record_fields(binding)
                self._prepare_string_views(binding)
                for record in header.records:
                    identity = self._layout_identity(record)
                    previous = self._layout_identities.setdefault(record.identity, identity)
                    if previous != identity:
                        raise NativeImportError(f"conflicting native layout {record.name!r}")
                for declaration in header.exports:
                    self._import(declaration)
                self._project_realtime_callbacks(binding)
                self._project_callback_tables(binding)
                self._project_record_snapshots(binding)
                if self._variadic_calls:
                    raise NativeImportError("variadic-calls names an unknown function or parameter")
                if self._borrows:
                    raise NativeImportError(
                        f"read-only-borrows names unknown function parameter: {sorted(self._borrows)[0]}"
                    )
                if self._realtime:
                    raise NativeImportError(
                        f"realtime-safe names a non-function declaration: {sorted(self._realtime)[0]}"
                    )
                if (
                    self._owned_results
                    or self._resource_borrows
                    or self._borrowed_results
                    or self._owned_outputs
                    or self._output_offsets
                ):
                    raise NativeImportError("resource ownership names an unknown or non-resource result/parameter")
                if self._callbacks:
                    raise NativeImportError(
                        f"callbacks names an unknown function parameter: {next(iter(self._callbacks))}"
                    )
                if self._main_thread_globals:
                    raise NativeImportError("main-thread-globals names a non-object-global declaration")
                if self._static_globals:
                    raise NativeImportError("static-globals names a non-resource-global declaration")
                if self._resource_parameters or self._resource_results:
                    raise NativeImportError("resource projections name an unknown native position")
                if self._copied_results:
                    raise NativeImportError("copied-results names an unknown or non-function result")
                if self._initializers:
                    raise NativeImportError("initializers names an unknown or non-function declaration")
                if self._copied_inputs:
                    raise NativeImportError("copied-inputs names an unknown SDK setter")
                if self._string_views.keys() - self._used_string_views:
                    raise NativeImportError("string-views requires a mapped C one-shot callback argument")
            except (OSError, subprocess.TimeoutExpired, NativeImportError) as error:
                raise IncludeResolutionError(f"{binding.module}: {error}") from error
        try:
            if any(name in self._resource_operations for _, name in self._declarations):
                raise NativeImportError("resource lifetime operations are reserved across native bindings")
            self._project_record_inputs(plan)
            self._coalesce()
            self._validate_selector_storage()
        except NativeImportError as error:
            raise IncludeResolutionError(str(error)) from error
        return (*self._declarations.values(), *self._input_classes)

    def _prepare_record_fields(self, binding):
        self._record_private_fields = {}
        for name in binding.owned_records:
            declaration = self._callback_exports.get(name)
            native = (
                declaration.underlying
                if isinstance(declaration, NativeTypedef)
                else declaration.record_type
                if isinstance(declaration, NativeRecordDeclaration)
                else None
            )
            record = self._unqualified_native(native) if native is not None else None
            if not isinstance(record, NativeRecordType) or record.identity not in self._layouts:
                continue
            for field in self._layouts[record.identity].fields:
                resource = self._resource_name(field.field_type)
                if not resource:
                    continue
                if (
                    field.field_type.qualifiers.is_const
                    or self._unqualified_native(field.field_type).qualifiers.is_const
                ):
                    raise NativeImportError("owning resource fields require assignable storage")
                projected = NativeRecordInputField(
                    field.name, self._resource_call_type(field.field_type), resource_type=resource
                )
                self._record_resource_fields[(binding.module, record.identity, field.name)] = projected
                self._record_private_fields.setdefault(record.identity, set()).add(field.name)
        for callback in binding.callbacks:
            if not callback.field:
                continue
            if callback.realtime is not None:
                selected = self._callback_exports.get(callback.realtime.record)
                record = self._unqualified_native(selected.underlying) if isinstance(selected, NativeTypedef) else None
                if not isinstance(record, NativeRecordType) or record.identity not in self._layouts:
                    raise NativeImportError("realtime callback record requires a complete selected SDK struct typedef")
                self._record_private_fields.setdefault(record.identity, set()).update(
                    (callback.field, *callback.contexts)
                )
                continue
            function, parameter = callback.parameter.rsplit(".", 1)
            declaration = self._callback_exports.get(function)
            if not isinstance(declaration, NativeFunction):
                raise NativeImportError("callback field requires a selected native function")
            for index, semantics in enumerate(declaration.parameter_semantics):
                if semantics.name != parameter:
                    continue
                record = self._unqualified_native(declaration.signature.parameters[index])
                if isinstance(record, NativeRecordType):
                    self._record_private_fields.setdefault(record.identity, set()).update(
                        (callback.field, *callback.contexts)
                    )
        for declaration in self._callback_exports.values():
            if not isinstance(declaration, NativeFunction):
                continue
            if self._record_contains_resources(declaration.signature.return_type):
                raise NativeImportError("resource-bearing record results require a checked output ownership mapping")
            for native, parameter in zip(
                declaration.signature.parameters, declaration.parameter_semantics, strict=True
            ):
                if self._record_contains_resources(native) and f"{declaration.name}.{parameter.name}" not in (
                    *binding.record_inputs,
                    *binding.record_outputs,
                    *dict(binding.owned_outputs),
                ):
                    raise NativeImportError("resource-bearing record parameters require record-inputs")

    def _record_contains_resources(self, native, active=()):
        if self._resource_name(native):
            return False
        native = self._unqualified_native(native)
        while isinstance(native, (NativePointer, NativeArrayType)):
            native = self._unqualified_native(native.pointee if isinstance(native, NativePointer) else native.element)
        if (
            not isinstance(native, NativeRecordType)
            or native.identity in active
            or native.identity not in self._layouts
        ):
            return False
        return any(
            self._resource_name(field.field_type)
            or self._record_contains_resources(field.field_type, (*active, native.identity))
            for field in self._layouts[native.identity].fields
        )

    def _prepare_string_views(self, binding):
        self._string_views = {}
        self._used_string_views = set()
        for view in binding.string_views:
            declaration = self._callback_exports.get(view.name)
            native = (
                declaration.underlying
                if isinstance(declaration, NativeTypedef)
                else declaration.record_type
                if isinstance(declaration, NativeRecordDeclaration)
                else None
            )
            if native is None:
                raise NativeImportError("string-views requires a complete selected struct")
            record = self._unqualified_native(native)
            layout = self._layouts.get(record.identity) if isinstance(record, NativeRecordType) else None
            if layout is None or layout.record_kind != "struct" or len(layout.fields) != 2:
                raise NativeImportError("string-views requires a complete two-field struct")
            fields = {field.name: field.field_type for field in layout.fields}
            if set(fields) != {view.data, view.length} or any(
                field.is_anonymous or field.is_bitfield for field in layout.fields
            ):
                raise NativeImportError("string-view data/length must name its two ordinary fields")
            data = self._unqualified_native(fields[view.data])
            element = self._unqualified_native(data.pointee) if isinstance(data, NativePointer) else None
            length = self._unqualified_native(fields[view.length])
            if not isinstance(element, NativeBuiltin) or element.name != "char":
                raise NativeImportError("string-view data requires a char pointer")
            if (
                not isinstance(length, NativeBuiltin)
                or length.signedness != "unsigned"
                or length.name
                not in {"unsigned char", "unsigned short", "unsigned int", "unsigned long", "unsigned long long"}
            ):
                raise NativeImportError("string-view length requires an unsigned integer byte count")
            for field in fields.values():
                while True:
                    if field.qualifiers.is_volatile or field.qualifiers.is_restrict:
                        raise NativeImportError("string-view fields cannot be volatile or restrict-qualified")
                    if isinstance(field, (NativeAlias, NativeQualifiedType)):
                        field = field.underlying
                    elif isinstance(field, NativePointer):
                        field = field.pointee
                    else:
                        break
            spelling = f"struct {record.tag_name}" if record.tag_name else view.name
            projection = NativeStringViewProjection(
                spelling, view.data, view.length, length.name, view.null_length == "zero-or-max"
            )
            previous = self._string_views.get(record.identity)
            if previous and previous != projection:
                raise NativeImportError("conflicting string-view mappings for the same native record")
            self._string_views[record.identity] = projection

    def _realtime_scalar(self, native):
        scalar = self._unqualified_native(native)
        if isinstance(scalar, NativeEnumType):
            scalar = self._unqualified_native(scalar.underlying)
        return isinstance(scalar, NativeBuiltin) and scalar.name in {
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
        }

    def _realtime_pod(self, native, seen=()):
        if self._resource_name(native):
            return False
        value = self._unqualified_native(native)
        if isinstance(value, (NativeBuiltin, NativeEnumType)):
            return True
        if isinstance(value, NativePointer):
            return self._realtime_pod(value.pointee, seen)
        if isinstance(value, NativeArrayType):
            return (
                value.count is not None
                and value.count.isdecimal()
                and int(value.count) > 0
                and self._realtime_pod(value.element, seen)
            )
        if isinstance(value, NativeRecordType):
            if value.identity in seen:
                return True
            record = self._layouts.get(value.identity)
            return record is not None and all(
                self._realtime_pod(field.field_type, (*seen, value.identity)) for field in record.fields
            )
        return False

    def _realtime_parameter(self, native):
        value = self._unqualified_native(native)
        if isinstance(value, (NativeBuiltin, NativeEnumType)):
            return self._call_type(native, parameter=True)
        if isinstance(value, NativePointer):
            pointee = self._unqualified_native(value.pointee)
            if isinstance(pointee, (NativeBuiltin, NativeEnumType, NativeRecordType)) and self._realtime_pod(native):
                return self._call_type(native, parameter=True)
        raise NativeImportError("realtime callback arguments require SDK scalar or POD data-pointer types")

    def _realtime_native_spelling(self, native):
        if isinstance(native, NativeQualifiedType):
            return self._realtime_native_spelling(native.underlying)
        prefix = "const " if native.qualifiers.is_const else ""
        if isinstance(native, NativePointer):
            return self._realtime_native_spelling(native.pointee) + "*" + (" const" if prefix else "")
        if isinstance(native, NativeRecordType) and native.tag_name:
            return prefix + "struct " + native.tag_name
        return prefix + self._block_type_spelling(native)

    def _project_realtime_callbacks(self, binding):
        for selected in binding.callbacks:
            shape = selected.realtime
            if shape is None:
                continue
            function, parameter = selected.parameter.split(".", 1)
            native = self._callback_exports.get(function)
            if (
                not isinstance(native, NativeFunction)
                or native.signature.variadic
                or not self._realtime_scalar(native.signature.return_type)
            ):
                raise NativeImportError("realtime registration requires a selected fixed-arity status function")
            names = self._parameter_names(native.parameter_semantics)
            if (
                any(names.count(name) != 1 for name in (parameter, shape.owner, shape.size))
                or len({parameter, shape.owner, shape.size}) != 3
            ):
                raise NativeImportError("realtime registration requires distinct callback, owner and size parameters")
            index, owner_index, size_index = names.index(parameter), names.index(shape.owner), names.index(shape.size)
            storage = self._unqualified_native(native.signature.parameters[index])
            pointee = self._unqualified_native(storage.pointee) if isinstance(storage, NativePointer) else None
            size = self._unqualified_native(native.signature.parameters[size_index])
            resource = self._resource_name(native.signature.parameters[owner_index])
            if not isinstance(pointee, NativeBuiltin) or pointee.name != "void" or not pointee.qualifiers.is_const:
                raise NativeImportError("realtime callback record requires const void* SDK input storage")
            if not isinstance(size, NativeBuiltin) or size.signedness != "unsigned" or not self._realtime_scalar(size):
                raise NativeImportError("realtime callback record requires an unsigned SDK size parameter")
            if not resource or self._resources[resource].ownership != "unique":
                raise NativeImportError("realtime callback owner requires a declared unique resource")
            if len(selected.contexts) != 1 or len(selected.context_indices) != 1:
                raise NativeImportError("realtime callback requires one compiler-owned context slot")
            record = self._unqualified_native(self._callback_exports[shape.record].underlying)
            fields = {field.name: field.field_type for field in self._layouts[record.identity].fields}
            if (
                len(fields) != 2
                or selected.field not in fields
                or selected.contexts[0] not in fields
                or selected.field == selected.contexts[0]
            ):
                raise NativeImportError("realtime callback field/context must identify distinct SDK fields")
            callback_pointer = self._unqualified_native(fields[selected.field])
            signature = (
                self._unqualified_native(callback_pointer.pointee)
                if isinstance(callback_pointer, NativePointer)
                else None
            )
            context = self._unqualified_native(fields[selected.contexts[0]])
            context_type = self._unqualified_native(context.pointee) if isinstance(context, NativePointer) else None
            if (
                not isinstance(signature, NativeFunctionType)
                or signature.variadic
                or not self._realtime_scalar(signature.return_type)
            ):
                raise NativeImportError("realtime callback requires a fixed-arity scalar-result function pointer")
            context_index = selected.context_indices[0]
            if (
                context_index >= len(signature.parameters)
                or not isinstance(context_type, NativeBuiltin)
                or context_type.name != "void"
                or context_type.qualifiers.is_const
            ):
                raise NativeImportError("realtime callback context requires unqualified void* SDK storage")
            callback_context = self._unqualified_native(signature.parameters[context_index])
            callback_pointee = (
                self._unqualified_native(callback_context.pointee)
                if isinstance(callback_context, NativePointer)
                else None
            )
            if (
                not isinstance(callback_pointee, NativeBuiltin)
                or callback_pointee.name != "void"
                or callback_pointee.qualifiers.is_const
            ):
                raise NativeImportError("realtime callback context-index must identify an unqualified void* argument")
            operations = []
            for method, key in shape.operations:
                operation_name, owner_name = key.split(".", 1)
                operation = self._callback_exports.get(operation_name)
                if (
                    not isinstance(operation, NativeFunction)
                    or operation.signature.variadic
                    or operation_name not in self._realtime
                ):
                    raise NativeImportError(
                        "callback operation requires an explicitly realtime-safe fixed-arity SDK function"
                    )
                operation_names = self._parameter_names(operation.parameter_semantics)
                if operation_names.count(owner_name) != 1:
                    raise NativeImportError("callback operation owner names an unknown SDK parameter")
                position = operation_names.index(owner_name)
                if (
                    self._resource_name(operation.signature.parameters[position]) != resource
                    or key not in self._resource_borrows
                    or not self._resource_pointer_accepts(
                        operation.signature.parameters[position], self._resource_types[resource]
                    )
                ):
                    raise NativeImportError(
                        "callback operation requires a borrowed parameter of its registration owner"
                    )
                if not self._realtime_scalar(operation.signature.return_type) or any(
                    item.cf_consumed or item.ns_consumed for item in operation.parameter_semantics
                ):
                    raise NativeImportError("callback operations require non-consuming scalar-result calls")
                parameters = tuple(
                    ast.Param(type=self._realtime_parameter(value), name=operation_names[slot])
                    for slot, value in enumerate(operation.signature.parameters)
                    if slot != position
                )
                operations.append(
                    NativeRealtimeOperation(
                        method, operation_name, position, parameters, self._call_type(operation.signature.return_type)
                    )
                )
                self._resource_borrows.remove(key)
                self._realtime.remove(operation_name)
            unregister = self._callback_exports.get(selected.unregister)
            if (
                not isinstance(unregister, NativeFunction)
                or unregister.signature.variadic
                or len(unregister.signature.parameters) != 1
                or not self._realtime_scalar(unregister.signature.return_type)
            ):
                raise NativeImportError("realtime unregister requires one borrowed owner and a scalar status")
            unregister_key = f"{unregister.name}.{self._parameter_names(unregister.parameter_semantics)[0]}"
            if (
                self._resource_name(unregister.signature.parameters[0]) != resource
                or unregister_key not in self._resource_borrows
                or not self._resource_pointer_accepts(
                    unregister.signature.parameters[0], self._resource_types[resource]
                )
                or any(item.cf_consumed or item.ns_consumed for item in unregister.parameter_semantics)
            ):
                raise NativeImportError("realtime unregister must borrow its registration owner without consumption")
            self._resource_borrows.remove(unregister_key)
            arguments = tuple(
                self._realtime_parameter(value) if slot != context_index else ast.TypeExpr(base="void", pointer_depth=1)
                for slot, value in enumerate(signature.parameters)
            )
            result = self._call_type(signature.return_type)
            invocation = NativeRealtimeRegistration(
                shape.name,
                shape.invocation,
                resource,
                function,
                owner_index,
                size_index,
                tuple(self._realtime_native_spelling(value) for value in native.signature.parameters),
                tuple(operations),
                self._call_type(native.signature.return_type),
            )
            projection = NativeCallbackProjection(
                selected.interface,
                index,
                -1,
                context_index,
                arguments,
                result,
                unregister=unregister,
                activation_failure=selected.activation_failure,
                field=selected.field,
                record=shape.record,
                context_fields=selected.contexts,
                callback_context_indices=selected.context_indices,
                realtime=invocation,
            )
            payload = [
                ast.Param(type=value, name=f"argument{slot}")
                for slot, value in enumerate(arguments)
                if slot != context_index
            ]
            self._add(
                selected.interface,
                ast.InterfaceDecl(
                    name=selected.interface,
                    methods=[
                        ast.MethodSig(
                            name="invoke",
                            return_type=result,
                            params=[ast.Param(type=ast.TypeExpr(base=shape.invocation), name="invocation"), *payload],
                        )
                    ],
                ),
                ("realtime-callback", selected, self._type_identity(signature)),
            )
            origin = NativeHeaderSource(
                str(self._origin), self._origin.header, language="", invocation=shape.invocation
            )
            members = [
                ast.FieldDecl(access="private", name="_context", type=ast.TypeExpr(base="void", pointer_depth=1))
            ]
            for operation in operations:
                method = ast.MethodDecl(
                    access="public",
                    name=operation.name,
                    return_type=operation.return_type,
                    params=list(operation.parameters),
                )
                method.source_file = NativeHeaderSource(
                    str(self._origin),
                    self._origin.header,
                    language="",
                    call_contract=NativeCallContract(realtime_safe=True),
                )
                origin.methods[operation.name] = method.source_file.call_contract
                members.append(method)
            self._input_classes.append(
                ast.ClassDecl(name=shape.invocation, is_abstract=True, members=members, source_file=origin)
            )
            visible = [slot for slot in range(len(names)) if slot not in {index, size_index}]
            parameters = [
                ast.Param(
                    type=self._resource_call_type(native.signature.parameters[slot])
                    if slot == owner_index
                    else self._call_type(native.signature.parameters[slot], parameter=True),
                    name=names[slot],
                )
                for slot in visible
            ]
            fallback = ast.TypeExpr(
                base="__realtime_fn_ptr", generic_args=[result, *[parameter.type for parameter in payload]]
            )
            occupied = set(names)
            for name, value in (
                ("receiver", ast.TypeExpr(base=selected.interface)),
                ("denied", fallback),
                ("scope", ast.TypeExpr(base="CallbackScope")),
            ):
                while name in occupied:
                    name += "_"
                occupied.add(name)
                parameters.append(ast.Param(type=value, name=name))
            alias = ast.FunctionDecl(name=shape.name, return_type=ast.TypeExpr(base="CallbackState"), params=parameters)
            self._add(
                shape.name,
                alias,
                ("realtime-registration", selected),
                call_contract=NativeCallContract(callbacks=(projection,)),
            )
            self._callbacks.pop(selected.parameter)

    def _table_function_type(self, field_type, what):
        pointer = self._unqualified_native(field_type)
        signature = self._unqualified_native(pointer.pointee) if isinstance(pointer, NativePointer) else None
        if not isinstance(signature, NativeFunctionType) or signature.variadic:
            raise NativeImportError(f"callback table {what} requires a fixed-arity function pointer field")
        return signature

    def _table_context_argument(self, native, what):
        pointer = self._unqualified_native(native)
        pointee = self._unqualified_native(pointer.pointee) if isinstance(pointer, NativePointer) else None
        if not isinstance(pointee, NativeBuiltin) or pointee.name != "void" or pointee.qualifiers.is_const:
            raise NativeImportError(f"callback table {what} requires an unqualified void* context")

    def _table_record_pointer(self, native, identity, what):
        pointer = self._unqualified_native(native)
        pointee = self._unqualified_native(pointer.pointee) if isinstance(pointer, NativePointer) else None
        if (
            not isinstance(pointee, NativeRecordType)
            or pointee.identity != identity
            or self._native_is_const(pointer.pointee)
        ):
            raise NativeImportError(f"callback table {what} requires a mutable pointer to the table record")

    def _table_text_pointer(self, native, what):
        pointer = self._unqualified_native(native)
        pointee = self._unqualified_native(pointer.pointee) if isinstance(pointer, NativePointer) else None
        if (
            not isinstance(pointee, NativeBuiltin)
            or pointee.name != "char"
            or not self._native_is_const(pointer.pointee)
        ):
            raise NativeImportError(f"callback table {what} requires const char* text")

    def _project_callback_tables(self, binding):
        for resource in binding.resources:
            table = resource.table
            if table is None:
                continue
            pointer = self._resource_types[resource.name]
            record = self._unqualified_native(pointer.pointee)
            layout = self._layouts.get(record.identity) if isinstance(record, NativeRecordType) else None
            if resource.ownership != "unique" or resource.storage or layout is None or layout.record_kind != "struct":
                raise NativeImportError("callback table requires a unique pointer resource over a complete SDK struct")
            if any(field.is_anonymous or field.is_bitfield for field in layout.fields):
                raise NativeImportError("callback table fields must be ordinary named SDK fields")
            fields = {field.name: field.field_type for field in layout.fields}
            mapped = [table.context, *(field for _, field in table.methods)]
            mapped.extend(field for field in (table.label, table.reopen, table.release) if field)
            if set(mapped) != set(fields) or len(mapped) != len(fields):
                raise NativeImportError("callback table must map every SDK field exactly once")
            for name in mapped:
                storage = fields[name]
                while True:
                    if storage.qualifiers.is_const or storage.qualifiers.is_volatile or storage.qualifiers.is_restrict:
                        raise NativeImportError("callback table fields require assignable unqualified storage")
                    if not isinstance(storage, (NativeAlias, NativeQualifiedType)):
                        break
                    storage = storage.underlying
            self._table_context_argument(fields[table.context], "context field")
            methods = []
            for method, field in table.methods:
                signature = self._table_function_type(fields[field], f"method {method}")
                if table.context_index >= len(signature.parameters):
                    raise NativeImportError("callback table context-index is outside a method signature")
                self._table_context_argument(signature.parameters[table.context_index], f"method {method}")
                result = self._unqualified_native(signature.return_type)
                if not (isinstance(result, NativeBuiltin) and result.name == "void") and not self._realtime_scalar(
                    signature.return_type
                ):
                    raise NativeImportError("callback table methods require scalar or void results")
                parameters = []
                for slot, value in enumerate(signature.parameters):
                    if slot == table.context_index:
                        continue
                    try:
                        parameters.append(self._realtime_parameter(value))
                    except NativeImportError as error:
                        raise NativeImportError(
                            "callback table method arguments require SDK scalar or POD data-pointer types"
                        ) from error
                methods.append(
                    NativeCallbackTableMethod(
                        method,
                        field,
                        tuple(parameters),
                        self._call_type(signature.return_type),
                        tuple(self._realtime_native_spelling(value) for value in signature.parameters),
                        self._realtime_native_spelling(signature.return_type),
                    )
                )
            if table.label:
                signature = self._table_function_type(fields[table.label], "label")
                if len(signature.parameters) != 1:
                    raise NativeImportError("callback table label requires exactly the context argument")
                self._table_context_argument(signature.parameters[0], "label")
                self._table_text_pointer(signature.return_type, "label result")
            if table.reopen:
                signature = self._table_function_type(fields[table.reopen], "reopen")
                if len(signature.parameters) != 2:
                    raise NativeImportError("callback table reopen requires context and name arguments")
                self._table_context_argument(signature.parameters[0], "reopen")
                self._table_text_pointer(signature.parameters[1], "reopen name")
                self._table_record_pointer(signature.return_type, record.identity, "reopen result")
            if table.release:
                signature = self._table_function_type(fields[table.release], "release")
                result = self._unqualified_native(signature.return_type)
                if len(signature.parameters) != 1 or not isinstance(result, NativeBuiltin) or result.name != "void":
                    raise NativeImportError("callback table release requires one table argument and void result")
                self._table_record_pointer(signature.parameters[0], record.identity, "release")
            interface_methods = [
                ast.MethodSig(
                    name=method.name,
                    return_type=method.return_type,
                    params=[
                        ast.Param(type=value, name=f"argument{slot}") for slot, value in enumerate(method.parameters)
                    ],
                )
                for method in methods
            ]
            self._add(
                table.interface,
                ast.InterfaceDecl(name=table.interface, methods=interface_methods),
                ("callback-table", resource.name, self._type_identity(pointer)),
            )
            native_type = self._declarations[(str(self._origin), resource.name)].source_file.type_spelling
            projection = NativeCallbackTableProjection(
                resource.name,
                table.interface,
                native_type.removesuffix("*").strip() if native_type else resource.name,
                table.context,
                table.context_index,
                tuple(methods),
                table.label,
                table.reopen,
                table.release,
            )
            parameters = [ast.Param(type=ast.TypeExpr(base=table.interface), name="receiver")]
            if table.label:
                parameters.append(ast.Param(type=ast.TypeExpr(base="string"), name="label"))
            factory = ast.FunctionDecl(
                name=table.name,
                return_type=ast.TypeExpr(base=resource.name),
                params=parameters,
                body=None,
            )
            contract = NativeCallContract(
                tuple(True for _ in parameters),
                True,
                tuple(False for _ in parameters),
                False,
                resource_parameters=tuple("" for _ in parameters),
                resource_result=resource.name,
                callback_table=projection,
            )
            self._add(table.name, factory, ("callback-table-factory", resource.name), call_contract=contract)

    def _project_callbacks(self, declaration):
        projections = []
        names = [parameter.name for parameter in declaration.parameter_semantics]
        prefix = declaration.name + "."
        known = {prefix + name for name in names}
        for key in self._callbacks:
            if key.startswith(prefix) and key not in known:
                raise NativeImportError(f"callbacks names an unknown function parameter: {key}")
        for index, name in enumerate(names):
            selected = self._callbacks.get(f"{declaration.name}.{name}")
            if selected is not None and selected.realtime is not None:
                continue
            binding = self._callbacks.pop(f"{declaration.name}.{name}", None)
            if binding is None:
                continue
            if binding.action_setter:
                projections.append(self._project_action(declaration, binding, index))
                continue
            if binding.methods:
                projections.append(self._project_delegate(declaration, binding, index))
                continue
            native = self._unqualified_native(declaration.signature.parameters[index])
            record_name = ""
            record_contexts = []
            if binding.field:
                if not isinstance(native, NativeRecordType) or native.identity not in self._layouts:
                    raise NativeImportError("callback field requires a complete by-value record parameter")
                layout = self._layouts[native.identity]
                fields = {field.name: field.field_type for field in layout.fields}
                if layout.record_kind != "struct" or any(
                    name not in fields for name in (binding.field, *binding.contexts)
                ):
                    raise NativeImportError("callback field/context must identify fields of the native struct")
                if binding.field in binding.contexts:
                    raise NativeImportError("callback field and context must be distinct")
                for storage in (fields[name] for name in (binding.field, *binding.contexts)):
                    while True:
                        if (
                            storage.qualifiers.is_const
                            or storage.qualifiers.is_volatile
                            or storage.qualifiers.is_restrict
                        ):
                            raise NativeImportError("callback fields require assignable unqualified storage")
                        if not isinstance(storage, (NativeAlias, NativeQualifiedType)):
                            break
                        storage = storage.underlying
                record_name = self._call_type(declaration.signature.parameters[index]).base
                record_contexts = [fields[name] for name in binding.contexts]
                native = self._unqualified_native(fields[binding.field])
            is_block = isinstance(native, NativeObjectiveCBlock)
            if is_block != isinstance(declaration, NativeObjectiveCMethod):
                raise NativeImportError(
                    f"callback {binding.parameter}: Objective-C method callbacks require block parameters"
                )
            context_index = -1
            callback_context_indices = binding.context_indices
            callback_context_index = callback_context_indices[0] if callback_context_indices else -1
            if is_block:
                qualified = declaration.signature.parameters[index]
                while True:
                    if qualified.qualifiers.is_volatile or qualified.qualifiers.is_restrict:
                        raise NativeImportError("unsupported Objective-C block qualifiers")
                    if qualified.qualifiers.nullability not in {"unannotated", "nullable", "nonnull"}:
                        raise NativeImportError("unsupported Objective-C block nullability")
                    if not isinstance(qualified, (NativeAlias, NativeQualifiedType)):
                        break
                    qualified = qualified.underlying
                if binding.contexts or binding.context_indices:
                    raise NativeImportError(
                        f"callback {binding.parameter}: block context is compiler-owned; omit context/context-index"
                    )
                signature = self._unqualified_native(native.signature)
            else:
                if not binding.field and names.count(binding.contexts[0]) != 1:
                    raise NativeImportError(f"callback {binding.parameter}: context must identify one native parameter")
                context_index = -1 if binding.field else names.index(binding.contexts[0])
                signature = self._unqualified_native(native.pointee) if isinstance(native, NativePointer) else None
            if not isinstance(signature, NativeFunctionType) or signature.variadic:
                raise NativeImportError(f"callback {binding.parameter}: expected a nonvariadic function pointer")
            if is_block:
                callback_context_index = len(signature.parameters)
                callback_context_indices = (callback_context_index,)
            if not is_block and any(position >= len(signature.parameters) for position in callback_context_indices):
                raise NativeImportError(f"callback {binding.parameter}: context-index is outside the native signature")
            for context in (
                [
                    *(record_contexts if binding.field else [declaration.signature.parameters[context_index]]),
                    *(signature.parameters[position] for position in callback_context_indices),
                ]
                if not is_block
                else ()
            ):
                pointer = self._unqualified_native(context)
                pointee = self._unqualified_native(pointer.pointee) if isinstance(pointer, NativePointer) else None
                if not isinstance(pointee, NativeBuiltin) or pointee.name != "void" or pointee.qualifiers.is_const:
                    raise NativeImportError(
                        f"callback {binding.parameter}: context must be an unqualified void pointer"
                    )
            for position in binding.owned_arguments:
                if position >= len(signature.parameters) or position in callback_context_indices:
                    raise NativeImportError("callback owned-arguments must identify resource payload parameters")
                if not self._resource_name(signature.parameters[position]):
                    raise NativeImportError("callback owned-arguments requires a declared native resource")
            projected = []
            string_arguments = []
            for position, parameter in enumerate(signature.parameters):
                if position in callback_context_indices:
                    projected.append(ast.TypeExpr(base="void", pointer_depth=1))
                    continue
                scalar = self._unqualified_native(parameter)
                if isinstance(scalar, NativeRecordType) and scalar.identity in self._string_views:
                    if is_block or binding.lifetime != "one-shot":
                        raise NativeImportError("string-views currently requires a C one-shot callback")
                    string_arguments.append((position, self._string_views[scalar.identity]))
                    self._used_string_views.add(scalar.identity)
                    projected.append(ast.TypeExpr(base="string"))
                    continue
                if position in binding.owned_arguments:
                    projected.append(self._resource_call_type(parameter))
                    continue
                if is_block and isinstance(scalar, NativeObjectiveCObject):
                    projected.append(self._objective_c_type(parameter, parameter=True))
                    continue
                if not isinstance(scalar, (NativeBuiltin, NativeEnumType)):
                    raise NativeImportError(
                        f"callback {binding.parameter}: non-scalar arguments require a borrow mapping"
                    )
                projected.append(
                    self._objective_c_scalar(parameter) if is_block else self._call_type(parameter, parameter=True)
                )
            object_result = is_block and isinstance(
                self._unqualified_native(signature.return_type), NativeObjectiveCObject
            )
            if object_result and binding.lifetime != "stored":
                raise NativeImportError("object callback results require a stored Objective-C block")
            if not object_result and not isinstance(
                self._unqualified_native(signature.return_type), (NativeBuiltin, NativeEnumType)
            ):
                raise NativeImportError(
                    f"callback {binding.parameter}: non-scalar results require an ownership mapping"
                )
            if is_block:
                projected.append(ast.TypeExpr(base="void", pointer_depth=1))
            result = (
                self._objective_c_type(signature.return_type)
                if object_result
                else self._objective_c_scalar(signature.return_type)
                if is_block
                else self._call_type(signature.return_type)
            )
            unregister = None
            if binding.lifetime == "one-shot":
                native_result = self._unqualified_native(declaration.signature.return_type)
                if is_block and declaration.parameter_semantics[index].no_escape:
                    raise NativeImportError("one-shot requires an escaping Objective-C block")
                if result.base != "void":
                    raise NativeImportError(
                        "one-shot currently requires void native and callback results"
                        if is_block
                        else "one-shot currently requires void callback results"
                    )
                if is_block:
                    if not isinstance(native_result, NativeBuiltin) or native_result.name != "void":
                        raise NativeImportError("one-shot currently requires void native and callback results")
                else:
                    self._require_completion_value(declaration.signature.return_type)
            if binding.lifetime == "stored":
                unregister = self._callback_exports.get(binding.unregister)
                if not is_block or declaration.parameter_semantics[index].no_escape:
                    raise NativeImportError("stored callback requires an escaping Objective-C block")
                if (
                    not isinstance(unregister, NativeObjectiveCMethod)
                    or len(unregister.signature.parameters) > 1
                    or unregister.signature.variadic
                ):
                    raise NativeImportError(
                        "stored callback unregister requires a method with at most one token argument"
                    )
                cancellation_result = self._unqualified_native(unregister.signature.return_type)
                if (
                    not isinstance(cancellation_result, NativeBuiltin)
                    or cancellation_result.name != "void"
                    or unregister.consumes_self
                    or any(
                        parameter.cf_consumed or parameter.ns_consumed for parameter in unregister.parameter_semantics
                    )
                ):
                    raise NativeImportError("stored callback unregister requires a non-consuming void result")
                token = self._unqualified_native(declaration.signature.return_type)
                token_name = declaration.receiver if declaration.related_result else getattr(token, "name", "")
                if not isinstance(token, NativeObjectiveCObject):
                    raise NativeImportError("stored callback requires a native object cancellation token")
                if unregister.signature.parameters:
                    self._objective_c_type(unregister.signature.parameters[0], parameter=True)
                    argument = self._unqualified_native(unregister.signature.parameters[0])
                    if (
                        declaration.class_method != unregister.class_method
                        or declaration.receiver != unregister.receiver
                        or not isinstance(argument, NativeObjectiveCObject)
                        or argument.class_object
                        or argument.protocols
                        or argument.type_arguments
                        or argument.name not in {token_name, "id", ""}
                    ):
                        raise NativeImportError(
                            "stored callback unregister must accept the token on its registration receiver"
                        )
                elif unregister.class_method or not declaration.class_method or token_name != unregister.receiver:
                    raise NativeImportError("stored callback requires a factory returning its unregister receiver")
            method = ast.MethodSig(
                name="invoke",
                return_type=result,
                params=[
                    ast.Param(type=parameter, name=f"argument{position}")
                    for position, parameter in enumerate(
                        parameter for index, parameter in enumerate(projected) if index not in callback_context_indices
                    )
                ],
            )
            self._add(
                binding.interface,
                ast.InterfaceDecl(name=binding.interface, methods=[method]),
                (
                    "callback-interface",
                    self._type_identity(signature.return_type),
                    tuple(
                        self._type_identity(parameter)
                        for position, parameter in enumerate(signature.parameters)
                        if position not in callback_context_indices
                    ),
                ),
            )
            projections.append(
                NativeCallbackProjection(
                    binding.interface,
                    index,
                    context_index,
                    callback_context_index,
                    tuple(projected),
                    result,
                    tuple(self._block_type_spelling(parameter) for parameter in signature.parameters)
                    if is_block
                    else (),
                    self._block_type_spelling(signature.return_type) if is_block else "",
                    unregister,
                    binding.activation_failure,
                    one_shot=binding.lifetime == "one-shot",
                    owned_arguments=binding.owned_arguments,
                    field=binding.field,
                    record=record_name,
                    context_fields=binding.contexts if binding.field else (),
                    callback_context_indices=callback_context_indices,
                    string_arguments=tuple(string_arguments),
                )
            )
        occupied = [
            index
            for projection in projections
            for index in (projection.parameter_index, projection.context_index)
            if index >= 0
        ]
        if len(set(occupied)) != len(occupied):
            raise NativeImportError(
                f"{declaration.name}: callback and context parameters must be distinct and unshared"
            )
        return tuple(projections)

    def _project_action(self, declaration, binding, index):
        getter = self._callback_exports.get(binding.slot_getter)
        setter = self._callback_exports.get(binding.action_setter)
        action_getter = self._callback_exports.get(binding.action_getter)
        operations = ((declaration, 1), (getter, 0), (setter, 1), (action_getter, 0))
        if (
            index != 0
            or any(
                not isinstance(operation, NativeObjectiveCMethod)
                or operation.class_method
                or operation.protocol_owner
                or operation.optional
                or operation.receiver != declaration.receiver
                or operation.signature.variadic
                or len(operation.signature.parameters) != arity
                or operation.consumes_self
                or operation.returns_inner_pointer
                or operation.returned_ownership != "unspecified"
                or any(parameter.cf_consumed or parameter.ns_consumed for parameter in operation.parameter_semantics)
                for operation, arity in operations
            )
            or len({operation.name for operation, _ in operations}) != 4
        ):
            raise NativeImportError("action binding requires distinct non-consuming instance target/action accessors")
        if any(
            self._objective_c_scalar(operation.signature.return_type).base != "void"
            for operation in (declaration, setter)
        ):
            raise NativeImportError("action setters must return void")
        for native in (declaration.signature.parameters[0], getter.signature.return_type):
            value = self._unqualified_native(native)
            if (
                not isinstance(value, NativeObjectiveCObject)
                or value.name not in {"", "id"}
                or value.protocols
                or value.class_object
                or value.type_arguments
                or self._call_nullability(native) != "nullable"
            ):
                raise NativeImportError("action target requires nullable id setter and getter")
            self._objective_c_type(native, cancellation_token=True)
        for native in (setter.signature.parameters[0], action_getter.signature.return_type):
            value = self._unqualified_native(native)
            if (
                not isinstance(value, NativePointer)
                or not isinstance(value.pointee, NativeBuiltin)
                or value.pointee.name != "SEL"
                or self._call_nullability(native) != "nullable"
            ):
                raise NativeImportError("action selector requires nullable SEL setter and getter")
        result = ast.TypeExpr(base="void")
        self._add(
            binding.interface,
            ast.InterfaceDecl(
                name=binding.interface, methods=[ast.MethodSig(name="invoke", return_type=result, params=[])]
            ),
            ("action-interface",),
        )
        invocation = NativeCallbackProjection(
            binding.interface, index, -1, 0, (ast.TypeExpr(base="void", pointer_depth=1),), result, native_return="void"
        )
        return NativeActionProjection(
            binding.interface,
            index,
            declaration,
            binding.activation_failure,
            getter,
            setter,
            action_getter,
            (invocation,),
        )

    def _project_delegate(self, declaration, binding, index):
        getter = self._callback_exports.get(binding.slot_getter)
        if (
            not isinstance(declaration, NativeObjectiveCMethod)
            or declaration.class_method
            or index != 0
            or len(declaration.signature.parameters) != 1
            or self._objective_c_scalar(declaration.signature.return_type).base != "void"
            or not isinstance(getter, NativeObjectiveCMethod)
            or getter.class_method
            or getter.optional
            or getter.signature.parameters
            or getter.signature.variadic
            or getter.receiver != declaration.receiver
            or getter.consumes_self
            or getter.returns_inner_pointer
            or getter.returned_ownership != "unspecified"
        ):
            raise NativeImportError("delegate slot requires an instance void setter and matching non-consuming getter")
        argument = self._unqualified_native(declaration.signature.parameters[0])
        result = self._unqualified_native(getter.signature.return_type)
        if (
            not isinstance(argument, NativeObjectiveCObject)
            or argument.name not in {"", "id"}
            or argument.class_object
            or argument.type_arguments
            or len(argument.protocols) != 1
            or not isinstance(result, NativeObjectiveCObject)
            or (result.name, result.protocols, result.class_object, result.type_arguments)
            != (argument.name, argument.protocols, argument.class_object, argument.type_arguments)
            or not self._objective_c_type(declaration.signature.parameters[0], cancellation_token=True).is_nullable
            or not self._objective_c_type(getter.signature.return_type, cancellation_token=True).is_nullable
        ):
            raise NativeImportError("delegate slot requires matching nullable id<Protocol> setter and getter")
        methods = []
        names = set()
        protocol = argument.protocols[0]
        signatures = []
        identities = []
        for symbol in binding.methods:
            method = self._callback_exports.get(symbol)
            if (
                not isinstance(method, NativeObjectiveCMethod)
                or not method.protocol_owner
                or method.receiver != protocol
                or method.class_method
                or method.signature.variadic
                or method.consumes_self
                or method.returns_inner_pointer
                or method.returned_ownership != "unspecified"
                or any(parameter.cf_consumed or parameter.ns_consumed for parameter in method.parameter_semantics)
            ):
                raise NativeImportError(
                    f"delegate method requires a non-consuming instance method of {protocol}: {symbol}"
                )
            name = method.selector.split(":", 1)[0]
            if name in names:
                raise NativeImportError(f"ambiguous delegate method projection: {name}")
            names.add(name)
            return_type = self._objective_c_scalar(method.signature.return_type)
            parameters = tuple(
                self._objective_c_type(parameter, parameter=True) for parameter in method.signature.parameters
            )
            signatures.append(
                ast.MethodSig(
                    name=name,
                    return_type=return_type,
                    params=[
                        ast.Param(type=value, name=f"argument{position}") for position, value in enumerate(parameters)
                    ],
                )
            )
            identities.append((name, self._type_identity(method.signature)))
            methods.append(
                NativeCallbackProjection(
                    binding.interface,
                    index,
                    -1,
                    len(parameters),
                    (*parameters, ast.TypeExpr(base="void", pointer_depth=1)),
                    return_type,
                    tuple(self._block_type_spelling(parameter) for parameter in method.signature.parameters),
                    self._block_type_spelling(method.signature.return_type),
                    method_name=name,
                    native_method=method,
                )
            )
        self._add(
            binding.interface,
            ast.InterfaceDecl(name=binding.interface, methods=signatures),
            ("delegate-interface", tuple(identities)),
        )
        return NativeDelegateProjection(
            binding.interface, index, declaration, binding.activation_failure, getter, protocol, tuple(methods)
        )

    def _block_type_spelling(self, native):
        while isinstance(native, NativeQualifiedType):
            native = native.underlying
        if isinstance(native, (NativeBuiltin, NativeAlias)):
            return native.name
        if isinstance(native, NativeObjectiveCObject):
            return f"{native.name}*" if native.name and native.name != "id" else "id"
        if isinstance(native, NativeEnumType) and native.name:
            return f"enum {native.name}"
        raise NativeImportError("anonymous native block scalar requires a named SDK type")

    def _prepare_cxx_resources(self, binding, header):
        """Authenticate opaque C++ owners before projecting any callable surface.

        Published document owners have no mutation entry point. Value views
        carry their originating owner, rather than acquiring a new native
        lifetime or deriving ownership from the immediately preceding view.
        """
        exports = {declaration.name: declaration for declaration in header.exports}
        resources = {resource.name: resource for resource in binding.resources}
        classes = {}
        self._layouts = {record.identity: record for record in header.records}
        for resource in binding.resources:
            declaration = exports.get(resource.name)
            if not isinstance(declaration, NativeCxxClass) or not declaration.record_type.complete:
                raise NativeImportError(f"C++ resource {resource.name}: expected a complete selected SDK class")
            if not declaration.public_destructor:
                raise NativeImportError(f"C++ resource {resource.name}: a public nondeleted destructor is required")
            if resource.ownership == "unique":
                if not declaration.default_constructor:
                    raise NativeImportError("C++ unique resource requires an available public default constructor")
                if resource.constructor != "default" or resource.release != "delete":
                    raise NativeImportError("C++ unique resource requires checked default/delete lifetime")
            elif resource.ownership == "owner-bound-value":
                if not declaration.trivially_copyable or not declaration.trivially_destructible:
                    raise NativeImportError("C++ owner-bound values require trivial copy and destruction")
                if resource.owner not in resources or resources[resource.owner].ownership != "unique":
                    raise NativeImportError("C++ value requires a selected unique originating owner")
            else:
                raise NativeImportError("unsupported C++ resource lifetime")
            if declaration.record_type.identity in classes:
                raise NativeImportError("one SDK C++ class cannot declare multiple managed resources")
            classes[declaration.record_type.identity] = resource
            self._add(
                resource.alias,
                ast.ClassDecl(
                    name=resource.alias,
                    is_abstract=True,
                    members=[
                        ast.MethodDecl(name="close", return_type=ast.TypeExpr(base="void"), access="public"),
                        ast.MethodDecl(name="isOpen", return_type=ast.TypeExpr(base="bool"), access="public"),
                    ]
                    if resource.ownership == "unique"
                    else [],
                ),
                ("c++-resource", declaration, resource),
                type_spelling="void*",
                resource=resource,
            )
        factories = {factory.function: factory for factory in binding.initializers}
        selected = {
            f"{resource.name}::{method}": resource for resource in binding.resources for method in resource.methods
        }
        selected.update({name: resources[factory.resource] for name, factory in factories.items()})
        copies = {function: (kind, owner) for function, kind, owner, _, _ in binding.copied_results}
        for name, resource in selected.items():
            method = exports.get(name)
            if not isinstance(method, NativeCxxMethod) or method.receiver != resource.name:
                raise NativeImportError(f"C++ method {name}: expected its selected SDK receiver")
            factory = factories.get(name)
            if method.signature.variadic or any(
                item.cf_consumed or item.ns_consumed for item in method.parameter_semantics
            ):
                raise NativeImportError("C++ methods require fixed, non-consuming SDK parameters")
            if not factory and not method.const_method:
                raise NativeImportError("published C++ owners and views expose only const traversal methods")
            root = resource if resource.ownership == "unique" else resources[resource.owner]
            parameters, borrows = [], []
            names = self._parameter_names(method.parameter_semantics)
            for index, native in enumerate(method.signature.parameters):
                path = f"{method.name.removesuffix('()')}.{names[index]}"
                pointer = self._unqualified_native(native)
                if isinstance(pointer, NativePointer):
                    pointee = self._unqualified_native(pointer.pointee)
                    if (
                        not self._native_is_const(pointer.pointee)
                        or not isinstance(pointee, NativeBuiltin)
                        or pointee.name not in {"void", "char", "unsigned char"}
                        or path not in binding.read_only_borrows
                    ):
                        raise NativeImportError("C++ pointer inputs require explicit read-only byte borrows")
                    projected = ast.TypeExpr(base=pointee.name, pointer_depth=1, is_const=True)
                    self._borrows.discard(path)
                    borrows.append(True)
                else:
                    projected = replace(self._objective_c_scalar(native), is_const=False)
                    borrows.append(False)
                parameters.append(ast.Param(name=names[index], type=projected))
            native_result = self._unqualified_native(method.signature.return_type)
            record = None
            result_resource = ""
            copied = None
            if factory:
                if resource.ownership != "unique" or method.const_method:
                    raise NativeImportError("C++ factory requires its private mutable document receiver")
                record = self._cxx_result_record(native_result, binding, exports, factory.result + "Status")
                status_native = next(
                    (
                        field.field_type
                        for field in self._layouts[native_result.identity].fields
                        if field.name == factory.status_field
                    ),
                    None,
                )
                success = exports.get(factory.success)
                status_enum = self._unqualified_native(status_native) if status_native else None
                if (
                    not isinstance(status_enum, NativeEnumType)
                    or not isinstance(success, NativeConstant)
                    or success.enum_identity != status_enum.identity
                ):
                    raise NativeImportError("C++ initializer success must belong to exactly the SDK status field enum")
                return_type = ast.TypeExpr(base=factory.result)
                self._cxx_value_class(
                    factory.result,
                    (
                        NativeRecordInputField("called", ast.TypeExpr(base="bool")),
                        NativeRecordInputField("status", ast.TypeExpr(base=record.name)),
                        NativeRecordInputField(
                            "value", ast.TypeExpr(base=resource.alias, is_nullable=True, pointer_depth=1)
                        ),
                    ),
                )
            elif isinstance(native_result, NativeRecordType):
                target = classes.get(native_result.identity)
                if target is None or target.ownership != "owner-bound-value" or target.owner != root.name:
                    raise NativeImportError("C++ returned views must retain exactly the same originating owner")
                result_resource = target.alias
                return_type = ast.TypeExpr(base=target.alias)
            elif isinstance(native_result, NativePointer):
                key = name.removesuffix("()")
                pointee = self._unqualified_native(native_result.pointee)
                if (
                    copies.pop(key, None) != ("string", "self")
                    or not self._native_is_const(native_result.pointee)
                    or not isinstance(pointee, NativeBuiltin)
                    or pointee.name != "char"
                ):
                    raise NativeImportError("C++ pointer results require checked receiver-owned string copying")
                copied = NativeCopiedResult("string", -1)
                return_type = ast.TypeExpr(base="string", is_nullable=True, pointer_depth=1)
            else:
                return_type = replace(self._objective_c_scalar(method.signature.return_type), is_const=False)
            projection = NativeCxxProjection(
                method,
                resource.alias,
                root.alias,
                record,
                factory.result if factory else "",
                factory.success if factory else "",
                factory.status_field if factory else "",
            )
            contract = NativeCallContract(
                read_only_borrows=tuple(borrows),
                resource_result=result_resource,
                copied_result=copied,
                cxx_method=projection,
            )
            owner = self._declarations[(str(self._origin), resource.alias)]
            if method.method_name in owner.source_file.methods:
                raise NativeImportError("ambiguous C++ method source projection")
            owner.source_file.methods[method.method_name] = contract
            owner.members.append(
                ast.MethodDecl(
                    access="class" if factory else "public",
                    name=method.method_name,
                    return_type=return_type,
                    params=parameters,
                )
            )
        if copies:
            raise NativeImportError("C++ copied-results names a method without a copied pointer result")

    def _cxx_value_class(self, name, fields):
        if any(key[1] == name for key in self._declarations) or any(item.name == name for item in self._input_classes):
            raise NativeImportError(f"conflicting C++ copied result class {name!r}")
        self._input_classes.append(
            ast.ClassDecl(
                name=name,
                source_file=str(self._origin),
                members=[ast.FieldDecl(access="public", name=field.name, type=field.value_type) for field in fields],
            )
        )

    def _cxx_result_record(self, native, binding, exports, name):
        if not isinstance(native, NativeRecordType) or native.opaque or native.identity not in self._layouts:
            raise NativeImportError("C++ factory result requires an explicitly selected scalar SDK record")
        selected = next(
            (
                exports[item]
                for item in binding.owned_records
                if isinstance(exports.get(item), NativeCxxClass)
                and exports[item].record_type.identity == native.identity
            ),
            None,
        )
        if selected is None or not selected.trivially_copyable or not selected.trivially_destructible:
            raise NativeImportError("C++ factory result requires a trivial selected scalar SDK record")
        layout = self._layouts[native.identity]
        if not layout.fields:
            raise NativeImportError("C++ factory result requires nonempty public scalar fields")
        fields = tuple(
            NativeRecordInputField(field.name, replace(self._objective_c_scalar(field.field_type), is_const=False))
            for field in layout.fields
        )
        self._cxx_value_class(name, fields)
        return NativeRecordInput(name, selected.name, fields, by_value=True)

    def _prepare_resources(self, binding, header):
        self._resources = {resource.name: resource for resource in binding.resources}
        self._resource_types = {}
        self._resource_records = {}
        self._owned_results = set(binding.owned_results)
        self._borrowed_results = dict(binding.borrowed_results)
        self._resource_borrows = set(binding.borrowed_parameters)
        exports = {declaration.name: declaration for declaration in header.exports}
        for resource in binding.resources:
            declaration = exports.get(resource.name)
            if isinstance(declaration, NativeTypedef):
                native = declaration.underlying
                spelling = resource.name
            elif resource.ownership == "unique" and isinstance(declaration, NativeRecordDeclaration):
                native = declaration.record_type
                spelling = f"{native.record_kind} {native.tag_name}"
            else:
                raise NativeImportError(
                    f"resource {resource.name}: expected a selected pointer typedef or unique record"
                )
            pointer = self._unqualified_native(native)
            record_spelling = ""
            if resource.ownership == "unique" and isinstance(pointer, NativeRecordType):
                if pointer.identity in self._resource_records:
                    raise NativeImportError("one SDK record cannot declare multiple unique owners")
                self._resource_records[pointer.identity] = resource.name
                pointer = NativePointer(pointee=native, qualifiers=NativeQualifiers(nullability="unannotated"))
                record_spelling = spelling + "*"
            if not isinstance(pointer, NativePointer) or not (
                isinstance(self._unqualified_native(pointer.pointee), NativeRecordType)
                or (
                    resource.ownership == "reference-counted"
                    and isinstance(self._unqualified_native(pointer.pointee), NativeBuiltin)
                    and self._unqualified_native(pointer.pointee).name == "void"
                )
            ):
                raise NativeImportError(f"resource {resource.name}: expected a record-pointer typedef")
            self._resource_types[resource.name] = pointer
            if resource.storage and (
                self._native_is_const(pointer.pointee)
                or self._unqualified_native(pointer.pointee).identity
                not in {record.identity for record in header.records}
            ):
                raise NativeImportError("inline resource storage requires a complete mutable SDK record")
            if resource.ownership == "unique" and (
                binding.owned_records
                or binding.record_inputs
                or binding.record_outputs
                or any(
                    callback.owned_arguments or (callback.lifetime != "call" and callback.realtime is None)
                    for callback in binding.callbacks
                )
            ):
                raise NativeImportError("unique resource records and completion payloads require owning projections")
            close_type = ast.TypeExpr(base="void")
            resource_identity = self._type_identity(pointer)
            for operation in (
                (resource.release,) if resource.ownership == "unique" else (resource.retain, resource.release)
            ):
                function = exports.get(operation)
                if (
                    not isinstance(function, NativeFunction)
                    or function.signature.variadic
                    or len(function.signature.parameters) != 1
                ):
                    raise NativeImportError(
                        f"resource {resource.name}: lifetime operation {operation} requires one pointer parameter"
                    )
                if not self._resource_pointer_accepts(function.signature.parameters[0], pointer):
                    raise NativeImportError(f"resource {resource.name}: incompatible lifetime parameter in {operation}")
                result = self._unqualified_native(function.signature.return_type)
                returns_void = isinstance(result, NativeBuiltin) and result.name == "void"
                status_release = resource.ownership == "unique" and bool(resource.release_consumption)
                if status_release:
                    scalar = (
                        self._unqualified_native(result.underlying) if isinstance(result, NativeEnumType) else result
                    )
                    if not isinstance(scalar, NativeBuiltin) or scalar.name not in {
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
                    }:
                        raise NativeImportError(
                            f"resource {resource.name}: status policy requires an integral or enum destructor result"
                        )
                    close_type = self._type(function.signature.return_type)
                elif not returns_void and (
                    operation == resource.release or not self._resource_pointer_accepts(result, pointer)
                ):
                    raise NativeImportError(f"resource {resource.name}: unsupported lifetime result in {operation}")
                if resource.ownership == "unique":
                    resource_identity = (resource_identity, self._type_identity(function.signature))
                if function.returned_ownership not in ("unspecified", "cf_retained") or any(
                    parameter.ns_consumed or (parameter.cf_consumed and operation != resource.release)
                    for parameter in function.parameter_semantics
                ):
                    raise NativeImportError(f"resource {resource.name}: conflicting lifetime ownership in {operation}")
                self._resource_operations.add(operation)
            self._add(
                resource.name,
                ast.ClassDecl(
                    name=resource.name,
                    is_abstract=True,
                    members=[
                        ast.MethodDecl(name="close", return_type=close_type, access="public"),
                        ast.MethodDecl(name="isOpen", return_type=ast.TypeExpr(base="bool"), access="public"),
                    ]
                    if resource.ownership == "unique"
                    else [],
                ),
                resource_identity,
                type_spelling=record_spelling,
                resource=resource,
            )

    def _prepare_resource_conversions(self, binding, header):
        exports = {declaration.name: declaration for declaration in header.exports}
        for resource in binding.resources:
            if resource.ownership != "reference-counted":
                continue
            origin = self._declarations[(str(self._origin), resource.name)].source_file
            origin.native_ancestors = tuple(
                other.name
                for other in binding.resources
                if other.name != resource.name
                and other.ownership == "reference-counted"
                and (other.retain, other.release) == (resource.retain, resource.release)
                and self._resource_pointer_accepts(
                    self._resource_types[other.name], self._resource_types[resource.name]
                )
            )
            if not resource.type_query:
                continue
            query, tag = exports.get(resource.type_query), exports.get(resource.type_tag)
            if (
                not isinstance(query, NativeFunction)
                or not isinstance(tag, NativeFunction)
                or query.signature.variadic
                or tag.signature.variadic
                or len(query.signature.parameters) != 1
                or tag.signature.parameters
                or self._type_identity(query.signature.return_type) != self._type_identity(tag.signature.return_type)
            ):
                raise NativeImportError(
                    "resource type-query/type-tag require one-parameter/zero-parameter functions with the same scalar result"
                )
            result = self._unqualified_native(query.signature.return_type)
            if isinstance(result, NativeEnumType):
                result = self._unqualified_native(result.underlying)
            if not isinstance(result, NativeBuiltin) or result.name not in {
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
            }:
                raise NativeImportError("resource type discriminator must return an integral SDK type")
            source = self._resource_name(query.signature.parameters[0])
            if (
                not source
                or self._resources[source].ownership != "reference-counted"
                or (self._resources[source].retain, self._resources[source].release)
                != (resource.retain, resource.release)
                or not self._resource_pointer_accepts(
                    query.signature.parameters[0], self._resource_types[resource.name]
                )
                or f"{query.name}.{self._parameter_names(query.parameter_semantics)[0]}" not in self._resource_borrows
            ):
                raise NativeImportError("resource type-query requires a compatible borrowed reference-counted source")
            origin.resource_query_type = source

    def _project_resource_position(self, key, native, *, result=False, consume=True):
        mappings = self._resource_results if result else self._resource_parameters
        selected = mappings.pop(key, None) if consume else mappings.get(key)
        inferred = self._resource_name(native)
        if selected is None:
            return inferred
        resource = self._resources[selected]
        pointer = self._unqualified_native(native)
        if (
            resource.ownership != "reference-counted"
            or inferred
            or not isinstance(pointer, NativePointer)
            or not isinstance(self._unqualified_native(pointer.pointee), NativeBuiltin)
            or self._unqualified_native(pointer.pointee).name != "void"
            or not self._resource_pointer_accepts(native, self._resource_types[selected])
        ):
            raise NativeImportError(
                "resource projection requires an unprojected compatible erased pointer and reference-counted resource"
            )
        return selected

    def _require_completion_value(self, native):
        value = self._unqualified_native(native)
        if isinstance(value, (NativeBuiltin, NativeEnumType)):
            return
        if isinstance(value, NativeRecordType) and value.complete and not value.opaque:
            layout = self._layouts[value.identity]
            if layout.record_kind == "struct" and layout.fields:
                for field in layout.fields:
                    self._require_completion_value(field.field_type)
                return
        raise NativeImportError("C one-shot native result requires a pointer-free scalar or record value")

    def _resource_pointer_accepts(self, target, source):
        target = self._unqualified_native(target)
        source = self._unqualified_native(source)
        if not isinstance(target, NativePointer) or not isinstance(source, NativePointer):
            return False
        target_value = self._unqualified_native(target.pointee)
        source_value = self._unqualified_native(source.pointee)
        if self._native_is_const(source.pointee) and not self._native_is_const(target.pointee):
            return False
        return (isinstance(target_value, NativeBuiltin) and target_value.name == "void") or (
            isinstance(target_value, NativeRecordType)
            and isinstance(source_value, NativeRecordType)
            and target_value.identity == source_value.identity
        )

    def _native_is_const(self, value):
        while True:
            if value.qualifiers.is_const:
                return True
            if not isinstance(value, (NativeAlias, NativeQualifiedType)):
                return False
            value = value.underlying

    def _resource_name(self, native):
        while isinstance(native, (NativeAlias, NativeQualifiedType)):
            if (
                isinstance(native, NativeAlias)
                and native.name in self._resources
                and isinstance(self._unqualified_native(native), NativePointer)
            ):
                return native.name
            native = native.underlying
        if isinstance(native, NativePointer):
            pointee = self._unqualified_native(native.pointee)
            if isinstance(pointee, NativeRecordType):
                return self._resource_records.get(pointee.identity, "")
        elif isinstance(native, NativeRecordType) and native.identity in self._resource_records:
            raise NativeImportError("unique record resource requires pointer use, not by-value storage")
        return ""

    def _resource_call_type(self, native, name=None):
        name = name or self._resource_name(native)
        if not name:
            return self._call_type(native)
        current = native
        while isinstance(current, (NativeAlias, NativeQualifiedType, NativePointer)):
            if current.qualifiers.is_volatile or current.qualifiers.is_restrict:
                raise NativeImportError("resource qualifiers require managed native lowering")
            current = current.pointee if isinstance(current, NativePointer) else current.underlying
        nullable = self._call_nullability(native) != "nonnull"
        return ast.TypeExpr(base=name, is_nullable=nullable, pointer_depth=int(nullable))

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

    def _snapshot_unqualified(self, native):
        while isinstance(native, (NativeAlias, NativeQualifiedType)):
            if native.qualifiers.is_volatile or native.qualifiers.is_restrict:
                raise NativeImportError("record snapshot paths cannot be volatile or restrict-qualified")
            native = native.underlying
        if native.qualifiers.is_volatile or native.qualifiers.is_restrict:
            raise NativeImportError("record snapshot paths cannot be volatile or restrict-qualified")
        return native

    def _snapshot_path(self, owner, path, kind="scalar", guarded=False):
        native = self._resource_types[owner]
        steps = []
        visited = set()
        for name in path.split("."):
            native = self._snapshot_unqualified(native)
            pointer = isinstance(native, NativePointer)
            record = self._snapshot_unqualified(native.pointee) if pointer else native
            if not isinstance(record, NativeRecordType) or record.identity not in self._layouts:
                raise NativeImportError("record snapshot path requires a complete SDK record")
            if record.identity in visited:
                raise NativeImportError("record snapshot path cannot traverse cyclic SDK records")
            visited.add(record.identity)
            layout = self._layouts[record.identity]
            fields = [field for field in layout.fields if field.name == name]
            if (
                layout.record_kind not in ({"struct", "union"} if guarded else {"struct"})
                or len(fields) != 1
                or fields[0].is_anonymous
                or fields[0].is_bitfield
            ):
                raise NativeImportError(f"record snapshot path names an unavailable SDK field: {path}")
            steps.append((name, pointer))
            native = fields[0].field_type
        native = self._snapshot_unqualified(native)
        scalar = self._snapshot_unqualified(native.underlying) if isinstance(native, NativeEnumType) else native
        if kind == "pointer":
            element = self._snapshot_unqualified(native.pointee) if isinstance(native, NativePointer) else None
            if (
                not isinstance(element, NativeBuiltin)
                or element.name not in {"char", "signed char", "unsigned char"}
                or element.qualifiers.is_volatile
            ):
                raise NativeImportError("record snapshot byte plane requires a byte pointer")
            value_type = ast.TypeExpr(base="unsigned char", pointer_depth=1, is_const=True)
        else:
            if not isinstance(scalar, NativeBuiltin) or scalar.name == "void":
                raise NativeImportError("record snapshot leaves must be scalar SDK fields")
            if kind in {"width", "rows", "pitch", "length"} and (
                scalar.name in {"float", "double", "bool", "_Bool"} or scalar.bits > 64
            ):
                raise NativeImportError("record snapshot plane dimensions require integral fields of at most 64 bits")
            if kind == "pitch" and scalar.signedness != "signed":
                raise NativeImportError("record snapshot pitch requires a signed integral field")
            value_type = replace(self._type(scalar), is_const=False)
        return NativeRecordPath(tuple(steps), value_type, native.identity if isinstance(native, NativeEnumType) else "")

    def _project_record_snapshots(self, binding):
        for selected in binding.record_snapshots:
            existing = {name for _, name in self._declarations} | {value.name for value in self._input_classes}
            if selected.result in existing or selected.name in existing:
                raise NativeImportError("conflicting native record snapshot name")
            if selected.owner not in self._resource_types:
                raise NativeImportError("record snapshot requires an authenticated selected native owner")
            guard_path = self._snapshot_path(selected.owner, selected.guard[0]) if selected.guard else None
            if guard_path:
                constant = self._callback_exports.get(selected.guard[1])
                if (
                    not guard_path.enum_identity
                    or not isinstance(constant, NativeConstant)
                    or constant.enum_identity != guard_path.enum_identity
                ):
                    raise NativeImportError(
                        "record snapshot guard requires a selected constant of exactly the field's SDK enum"
                    )
            paths = tuple(
                self._snapshot_path(selected.owner, path, guarded=bool(guard_path)) for _, path in selected.fields
            )
            fields = tuple(
                NativeRecordInputField(name, path.value_type)
                for (name, _), path in zip(selected.fields, paths, strict=True)
            )
            byte_paths = (
                tuple(
                    self._snapshot_path(selected.owner, path, kind, bool(guard_path))
                    for path, kind in zip(selected.byte_plane[1:], ("pointer", "width", "rows", "pitch"), strict=True)
                )
                if selected.byte_plane
                else ()
            )
            byte_field = selected.byte_plane[0] if selected.byte_plane else ""
            if selected.byte_span:
                byte_field = selected.byte_span[0]
                byte_paths = tuple(
                    self._snapshot_path(selected.owner, path, kind, bool(guard_path))
                    for path, kind in zip(selected.byte_span[1:], ("pointer", "length"), strict=True)
                )
            strings = tuple(
                (name, self._snapshot_path(selected.owner, path, "pointer", bool(guard_path)))
                for name, path in selected.strings
            )
            projection = NativeRecordSnapshot(
                selected.result,
                fields,
                paths,
                byte_field,
                byte_paths,
                guard_path,
                selected.guard[1] if guard_path else "",
                strings,
                bool(selected.byte_span),
            )
            members = [ast.FieldDecl(access="public", name=field.name, type=field.value_type) for field in fields]
            members.extend(
                ast.FieldDecl(access="public", name=name, type=ast.TypeExpr(base="string", is_nullable=True))
                for name, _ in strings
            )
            if byte_field:
                members.append(ast.FieldDecl(access="public", name=byte_field, type=ast.TypeExpr(base="Bytes")))
            self._input_classes.append(ast.ClassDecl(name=selected.result, members=members, source_file=binding.module))
            parameters = [ast.Param(name="owner", type=ast.TypeExpr(base=selected.owner))]
            if byte_field or strings:
                parameters.append(ast.Param(name="maximumBytes", type=ast.TypeExpr(base="int")))
            declaration = ast.FunctionDecl(
                name=selected.name,
                params=parameters,
                return_type=ast.TypeExpr(base=selected.result, is_nullable=True, pointer_depth=1),
                body=None,
            )
            contract = NativeCallContract(
                nonnull_parameters=(True,) + ((False,) if byte_field or strings else ()),
                resource_parameters=(selected.owner,) + (("",) if byte_field or strings else ()),
                record_snapshot=projection,
            )
            self._add(selected.name, declaration, ("record-snapshot", selected), call_contract=contract)

    def _project_record_inputs(self, plan):
        generated = set()
        outputs = {}
        for binding in plan.bindings:
            if not binding.owned_records and not binding.record_inputs and not binding.record_outputs:
                continue
            projections = {}
            object_fields = dict(binding.object_fields)
            callback_fields = {}
            for symbol in binding.symbols:
                declaration = self._declarations.get((binding.module, symbol))
                contract = declaration.source_file.call_contract if isinstance(declaration, ast.FunctionDecl) else None
                for callback in contract.callbacks if contract else ():
                    if not callback.field:
                        continue
                    if (
                        callback.record not in binding.owned_records
                        or f"{symbol}.{declaration.params[callback.parameter_index].name}" not in binding.record_inputs
                    ):
                        raise NativeImportError("callback fields require owned-records and record-inputs")
                    key = f"{callback.record}.{callback.field}"
                    previous = callback_fields.get(key)
                    if previous and (previous.interface, previous.context_fields) != (
                        callback.interface,
                        callback.context_fields,
                    ):
                        raise NativeImportError("conflicting callback field projection")
                    callback_fields[key] = callback
            for name in binding.owned_records:
                self._record_input(binding, name, projections, object_fields, callback_fields, ())
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
                        or not (original.pointer_depth == 0 or (original.pointer_depth == 1 and original.is_const))
                        or original.is_array
                    ):
                        raise NativeImportError(
                            f"{name}.{parameter.name}: record-inputs requires a const pointer to an owned record or a record value"
                        )
                    projection = replace(projections[original.base], by_value=original.pointer_depth == 0)
                    for field in projection.fields:
                        if field.callback and not any(
                            callback.field == field.name and callback.parameter_index == index
                            for callback in contract.callbacks
                        ):
                            raise NativeImportError(
                                "record callback fields require a callback mapping on every input call"
                            )
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
            self._project_record_outputs(binding, projections, outputs)

        for declaration in self._declarations.values():
            if not isinstance(declaration, ast.FunctionDecl):
                continue
            contract = declaration.source_file.call_contract
            for callback in contract.callbacks if contract else ():
                if (
                    callback.field
                    and getattr(callback, "realtime", None) is None
                    and (
                        callback.parameter_index >= len(contract.record_inputs)
                        or contract.record_inputs[callback.parameter_index] is None
                    )
                ):
                    raise NativeImportError("callback fields require owned-records and record-inputs")

    def _project_record_outputs(self, binding, projections, outputs):
        functions = set()
        for selected in binding.record_outputs:
            name, parameter = selected.split(".")
            declaration = self._declarations.get((binding.module, name))
            if not isinstance(declaration, ast.FunctionDecl) or name in functions:
                raise NativeImportError("record-outputs requires one output parameter per selected function")
            functions.add(name)
            contract = declaration.source_file.call_contract
            if contract.bound_parameter >= 0:
                raise NativeImportError("record-outputs cannot combine a selected variadic-calls shape")
            if contract.callbacks or contract.realtime_safe or contract.resource_result:
                raise NativeImportError("record-outputs cannot combine callbacks, realtime or a managed native result")
            indices = [index for index, value in enumerate(declaration.params) if value.name == parameter]
            if not indices:
                raise NativeImportError("record-outputs names an unknown parameter")
            index = indices[0]
            original = declaration.params[index].type
            if (
                original.base not in projections
                or original.pointer_depth != 1
                or original.is_const
                or original.is_array
            ):
                raise NativeImportError("record-outputs requires a mutable pointer to an owned record")
            projection = projections[original.base]
            owned = {
                value.rsplit(".", 1)[1] for value in binding.owned_output_fields if value.startswith(selected + ".")
            }
            nulls = {
                value.rsplit(".", 1)[1] for value in binding.null_output_fields if value.startswith(selected + ".")
            }
            if owned != {field.name for field in projection.fields if field.resource_type}:
                raise NativeImportError("owned-output-fields must declare every resource field exactly")
            layout = self._binding_layouts[binding.module][self._native_types[(binding.module, original.base)][0]]
            native_fields = {field.name: field.field_type for field in layout.fields}
            fields = []
            for field in projection.fields:
                if field.callback or field.record or field.object_type:
                    raise NativeImportError("record-outputs supports scalar fields and declared C resources")
                if field.resource_type:
                    fields.append(field)
                elif field.name in nulls:
                    if not isinstance(self._unqualified_native(native_fields[field.name]), NativePointer):
                        raise NativeImportError("null-output-fields requires unmanaged pointer fields")
                elif isinstance(self._unqualified_native(native_fields[field.name]), (NativeBuiltin, NativeEnumType)):
                    fields.append(field)
                else:
                    raise NativeImportError(
                        "record-outputs requires null-output-fields for pointer storage; aggregates are unsupported"
                    )
            if not nulls <= set(native_fields):
                raise NativeImportError("null-output-fields names an unknown field")
            result_type = declaration.return_type
            if result_type.base != "void" or result_type.pointer_depth or result_type.is_array:
                raise NativeImportError(
                    "record-outputs currently requires a void native result; managed tuple cleanup is not supported"
                )
            output = NativeRecordOutput(index, replace(projection, fields=tuple(fields)), tuple(sorted(nulls)))
            previous = outputs.get(output.output_name)
            if previous is not None and previous.record != output.record:
                raise NativeImportError("conflicting native output class")
            if previous is None:
                if any(key[1] == output.output_name for key in self._declarations):
                    raise NativeImportError("conflicting native output class")
                outputs[output.output_name] = output
                self._input_classes.append(
                    ast.ClassDecl(
                        name=output.output_name,
                        members=[
                            ast.FieldDecl(access="public", name=field.name, type=field.value_type) for field in fields
                        ],
                        source_file=binding.module,
                    )
                )
            del declaration.params[index]
            owner = ast.TypeExpr(base=output.output_name)
            declaration.return_type = owner
            declaration.source_file.call_contract = replace(
                contract,
                nonnull_parameters=contract.nonnull_parameters[:index] + contract.nonnull_parameters[index + 1 :],
                nonnull_return=False,
                read_only_borrows=contract.read_only_borrows[:index] + contract.read_only_borrows[index + 1 :],
                resource_parameters=contract.resource_parameters[:index] + contract.resource_parameters[index + 1 :],
                record_inputs=contract.record_inputs[:index] + contract.record_inputs[index + 1 :],
                record_output=output,
            )

    def _record_input(self, binding, name, projections, object_fields, callback_fields, active):
        if name in projections:
            return projections[name]
        if name in active:
            raise NativeImportError(f"cyclic native record input projection: {name}")
        declaration = self._declarations.get((binding.module, name))
        if not isinstance(declaration, ast.StructDecl) or declaration.is_forward:
            raise NativeImportError(f"owned-records requires a complete selected struct: {name}")
        identity = self._native_types[(binding.module, name)][0]
        layout = self._binding_layouts[binding.module][identity]
        native_fields = {field.name: field for field in layout.fields}
        imported_fields = {field.name: field for field in declaration.fields}
        fields = []
        callbacks = [callback for callback in callback_fields.values() if callback.record == name]
        hidden = {field for callback in callbacks for field in callback.context_fields}
        for field in layout.fields:
            if field.name in hidden:
                continue
            callback = callback_fields.get(f"{name}.{field.name}")
            if callback:
                fields.append(NativeRecordInputField(field.name, ast.TypeExpr(base=callback.interface), callback=True))
                continue
            resource = self._record_resource_fields.get((binding.module, identity, field.name))
            if resource:
                if f"{name}.{field.name}" in object_fields:
                    raise NativeImportError("resource field type/nullability comes from its SDK declaration")
                fields.append(resource)
                continue
            field = imported_fields[field.name]
            native = self._unqualified_native(native_fields[field.name].field_type)
            target = object_fields.pop(f"{name}.{field.name}", None)
            if isinstance(native, NativeRecordType) and field.type.base in binding.owned_records:
                target = target or field.type.base
            if field.type.is_array or (field.type.is_const and field.type.pointer_depth == 0):
                raise NativeImportError(f"{name}.{field.name}: owning input requires assignable non-array fields")
            if target is None:
                if self._record_contains_resources(native):
                    raise NativeImportError(f"{name}.{field.name}: embedded resource record requires owned-records")
                fields.append(NativeRecordInputField(field.name, field.type))
                continue
            nullable = target.endswith("?")
            target = target.removesuffix("?")
            by_value = isinstance(native, NativeRecordType)
            if not isinstance(native, NativePointer) and not by_value:
                raise NativeImportError(
                    f"{name}.{field.name}: object projection requires a pointer field or record value"
                )
            pointee = native if by_value else self._unqualified_native(native.pointee)
            if target in binding.owned_records:
                if by_value and nullable:
                    raise NativeImportError(f"{name}.{field.name}: embedded record input cannot be nullable")
                child = self._record_input(
                    binding, target, projections, object_fields, callback_fields, (*active, name)
                )
                if any(field.callback for field in child.fields):
                    raise NativeImportError("callback fields currently require a root by-value record input")
                child_identity = self._native_types[(binding.module, target)][0]
                child_layout = self._binding_layouts[binding.module][child_identity]
                prefix = ""
                if not isinstance(pointee, NativeRecordType) or pointee.identity != child_identity:
                    if by_value:
                        raise NativeImportError(f"{name}.{field.name}: incompatible projected record value")
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
                fields.append(NativeRecordInputField(field.name, value_type, child.name, prefix, by_value=by_value))
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
                or previous_origin.resource != origin.resource
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
            if isinstance(declaration, ast.ClassDecl) and origin.resource is not None:
                previous_origin.native_ancestors = tuple(
                    dict.fromkeys((*previous_origin.native_ancestors, *origin.native_ancestors))
                )
                origin.native_ancestors = previous_origin.native_ancestors
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

    def _add(
        self, name, declaration, native_type=None, type_spelling="", read_only=False, call_contract=None, resource=None
    ):
        key = (str(self._origin), name)
        if key in self._declarations:
            previous = self._declarations[key]
            if (
                self._native_types.get(key) != native_type
                or type(previous) is not type(declaration)
                or previous.source_file.type_spelling != type_spelling
                or previous.source_file.read_only != read_only
                or previous.source_file.call_contract != call_contract
                or previous.source_file.resource != resource
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
            resource=resource,
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
        if isinstance(native, NativeObjectiveCBlock):
            return (*identity, self._type_identity(native.signature))
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
                if self._managed_callback_signature(field.field_type):
                    self._record_private_fields.setdefault(native.identity, set()).add(field.name)
                if field.name in self._record_private_fields.get(native.identity, ()):
                    declaration.source_file.private_fields = True
                    continue
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

    def _managed_callback_signature(self, native):
        pointer = self._unqualified_native(native)
        signature = self._unqualified_native(pointer.pointee) if isinstance(pointer, NativePointer) else None
        return isinstance(signature, NativeFunctionType) and any(
            self._resource_name(value) for value in (signature.return_type, *signature.parameters)
        )

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
        if self._resource_name(native) or any(
            self._type_identity(native) == self._type_identity(resource_type)
            for resource_type in self._resource_types.values()
            if not isinstance(self._unqualified_native(resource_type.pointee), NativeBuiltin)
        ):
            raise NativeImportError("resource storage requires a checked managed call boundary")
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

    def _validate_copy_qualifiers(self, native):
        while True:
            if native.qualifiers.is_volatile or native.qualifiers.is_restrict:
                raise NativeImportError("copied-results/output-offsets does not support volatile or restrict storage")
            if isinstance(native, (NativeAlias, NativeQualifiedType)):
                native = native.underlying
            elif isinstance(native, NativePointer):
                native = native.pointee
            else:
                return

    def _project_copied_result(self, declaration, parameter_names):
        binding = self._copied_results.get(declaration.name)
        if binding is None:
            return None
        kind, owner, length_function, arguments = binding
        self._validate_copy_qualifiers(declaration.signature.return_type)
        pointer = self._unqualified_native(declaration.signature.return_type)
        element = self._unqualified_native(pointer.pointee) if isinstance(pointer, NativePointer) else None
        accepted = {"char"} if kind == "string" else {"char", "signed char", "unsigned char", "void"}
        if (
            not isinstance(element, NativeBuiltin)
            or element.name not in accepted
            or not self._native_is_const(pointer.pointee)
        ):
            raise NativeImportError("copied-results requires a const character/byte pointer result")
        owner_index = -1
        if owner:
            if owner not in parameter_names:
                raise NativeImportError("copied-results names an unknown owner parameter")
            owner_index = parameter_names.index(owner)
            key = f"{declaration.name}.{owner}"
            if key not in self._resource_borrows or not self._project_resource_position(
                key, declaration.signature.parameters[owner_index], consume=False
            ):
                raise NativeImportError("copied-results owner requires a borrowed native resource")
        indices = []
        if kind == "bytes":
            function = self._callback_exports.get(length_function)
            if (
                not isinstance(function, NativeFunction)
                or length_function in self._resource_operations
                or function.signature.variadic
                or any(parameter.cf_consumed or parameter.ns_consumed for parameter in function.parameter_semantics)
            ):
                raise NativeImportError("copied-results length-function requires a selected non-consuming C function")
            result = self._unqualified_native(function.signature.return_type)
            if not isinstance(result, NativeBuiltin) or result.name != "int":
                raise NativeImportError("copied-results length-function requires a signed int byte count")
            if len(arguments) != len(function.signature.parameters) or any(
                argument not in parameter_names for argument in arguments
            ):
                raise NativeImportError(
                    "copied-results length-arguments must match the length-function arity and parameters"
                )
            for target, name in zip(function.signature.parameters, arguments, strict=True):
                index = parameter_names.index(name)
                source = declaration.signature.parameters[index]
                if self._type_identity(target) != self._type_identity(source):
                    raise NativeImportError("copied-results length argument has incompatible SDK type")
                indices.append(index)
            if owner_index not in indices:
                raise NativeImportError("copied-results length-function must use the original owner")
        self._copied_results.pop(declaration.name)
        return NativeCopiedResult(kind, owner_index, length_function, tuple(indices))

    def _project_output_offset(self, declaration, parameter_names, owned_index):
        selected = [
            (key, value) for key, value in self._output_offsets.items() if key.split(".", 1)[0] == declaration.name
        ]
        if not selected:
            return None
        key, (input_name, length_name, field) = selected[0]
        output_name = key.split(".", 1)[1]
        if any(name not in parameter_names for name in (output_name, input_name, length_name)):
            raise NativeImportError("output-offsets names an unknown parameter")
        output_index, input_index, length_index = (
            parameter_names.index(name) for name in (output_name, input_name, length_name)
        )
        if owned_index in {output_index, input_index, length_index}:
            raise NativeImportError("output-offsets cannot reuse an owned resource output")
        signature = declaration.signature
        for index in (output_index, input_index, length_index):
            self._validate_copy_qualifiers(signature.parameters[index])
        output = self._unqualified_native(signature.parameters[output_index])
        pointer = self._unqualified_native(output.pointee) if isinstance(output, NativePointer) else None
        element = self._unqualified_native(pointer.pointee) if isinstance(pointer, NativePointer) else None
        source = self._unqualified_native(signature.parameters[input_index])
        source_element = self._unqualified_native(source.pointee) if isinstance(source, NativePointer) else None
        length = self._unqualified_native(signature.parameters[length_index])
        if (
            not isinstance(element, NativeBuiltin)
            or element.name != "char"
            or not self._native_is_const(pointer.pointee)
            or self._native_is_const(output.pointee)
        ):
            raise NativeImportError("output-offsets requires a mutable const-char-pointer output slot")
        if (
            not isinstance(source_element, NativeBuiltin)
            or source_element.name != "char"
            or not self._native_is_const(source.pointee)
        ):
            raise NativeImportError("output-offsets input requires a const char pointer")
        if not isinstance(length, NativeBuiltin) or length.name != "int":
            raise NativeImportError("output-offsets length requires the supported signed int byte count")
        if f"{declaration.name}.{input_name}" not in self._borrows:
            raise NativeImportError("output-offsets input requires read-only-borrows")
        self._output_offsets.pop(key)
        return NativeOutputOffset(output_index, input_index, length_index, field)

    def _project_owned_output(self, declaration, parameter_names):
        if declaration.name in self._initializers:
            return self._project_initializer(declaration, parameter_names)
        selected = [
            (key, result) for key, result in self._owned_outputs.items() if key.split(".", 1)[0] == declaration.name
        ]
        if not selected:
            return None
        key, result_name = selected[0]
        if key in self._owned_output_resources:
            return None
        parameter_name = key.split(".", 1)[1]
        if parameter_name not in parameter_names:
            raise NativeImportError("owned-outputs names an unknown parameter")
        index = parameter_names.index(parameter_name)
        pointer = self._unqualified_native(declaration.signature.parameters[index])
        if (
            not isinstance(pointer, NativePointer)
            or not isinstance(self._unqualified_native(pointer.pointee), NativePointer)
            or self._native_is_const(pointer.pointee)
        ):
            raise NativeImportError("owned-outputs requires a mutable resource pointer output slot")
        resource = self._resource_name(pointer.pointee)
        if not resource or self._resources[resource].ownership != "unique":
            raise NativeImportError("owned-outputs requires a declared unique resource")
        if self._resources[resource].storage:
            raise NativeImportError("inline resources require checked initializers, not owned pointer outputs")
        if not self._resource_pointer_accepts(
            self._resource_types[resource], pointer.pointee
        ) or not self._resource_pointer_accepts(pointer.pointee, self._resource_types[resource]):
            raise NativeImportError("owned-outputs has incompatible resource pointer qualifiers")
        native_status = self._unqualified_native(declaration.signature.return_type)
        if isinstance(native_status, NativeEnumType):
            native_status = self._unqualified_native(native_status.underlying)
        if not isinstance(native_status, NativeBuiltin) or native_status.name not in {
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
        }:
            raise NativeImportError("owned-outputs requires an integral or enum status result")
        status_type = self._type(declaration.signature.return_type)
        offset = self._project_output_offset(declaration, parameter_names, index)
        if any(name == result_name for _, name in self._declarations) or any(
            value.name == result_name for value in self._input_classes
        ):
            raise NativeImportError(f"conflicting owned-output result class {result_name!r}")
        self._input_classes.append(
            ast.ClassDecl(
                name=result_name,
                members=[
                    ast.FieldDecl(access="public", name="status", type=status_type),
                    ast.FieldDecl(
                        access="public",
                        name="value",
                        type=ast.TypeExpr(base=resource, is_nullable=True, pointer_depth=1),
                    ),
                    *(
                        [ast.FieldDecl(access="public", name=offset.field, type=ast.TypeExpr(base="int"))]
                        if offset
                        else []
                    ),
                ],
                source_file=str(self._origin),
            )
        )
        self._owned_outputs.pop(key)
        return NativeOwnedOutput(index, result_name, resource, status_type, offset)

    def _project_initializer(self, declaration, names):
        binding = self._initializers[declaration.name]
        if binding.parameter not in names:
            raise NativeImportError("initializer names an unknown storage parameter")
        index = names.index(binding.parameter)
        native = declaration.signature.parameters[index]
        resource_type = self._resource_types[binding.resource]
        if not self._resource_pointer_accepts(native, resource_type) or not self._resource_pointer_accepts(
            resource_type, native
        ):
            raise NativeImportError("initializer requires exactly its mutable inline resource pointer")
        success = self._callback_exports.get(binding.success)
        if (
            binding.success
            and not isinstance(success, NativeConstant)
            and not (isinstance(success, NativeGlobal) and success.read_only)
        ):
            raise NativeImportError("initializer success requires a selected read-only SDK constant")
        statuses = []
        for value in (
            declaration.signature.return_type,
            success.value_type if success else declaration.signature.return_type,
        ):
            value = self._unqualified_native(value)
            if isinstance(value, NativeEnumType):
                value = self._unqualified_native(value.underlying)
            if not isinstance(value, NativeBuiltin) or value.name not in {
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
            }:
                raise NativeImportError("initializer status and success require matching integral SDK types")
            statuses.append(value.name)
        if statuses[0] != statuses[1]:
            raise NativeImportError("initializer status and success require matching integral SDK types")
        copied_input, length = -1, -1
        if binding.copied_input:
            if binding.copied_input not in names or binding.length not in names:
                raise NativeImportError("initializer copied input names an unknown parameter")
            copied_input, length = names.index(binding.copied_input), names.index(binding.length)
            pointer = self._unqualified_native(declaration.signature.parameters[copied_input])
            scalar = self._unqualified_native(pointer.pointee) if isinstance(pointer, NativePointer) else None
            if (
                not isinstance(pointer, NativePointer)
                or not self._native_is_const(pointer.pointee)
                or not isinstance(scalar, NativeBuiltin)
                or scalar.name not in {"void", "char", "signed char", "unsigned char"}
            ):
                raise NativeImportError("initializer copied input requires a const byte pointer")
            self._validate_copy_qualifiers(declaration.signature.parameters[copied_input])
            native_length = self._unqualified_native(declaration.signature.parameters[length])
            if not isinstance(native_length, NativeBuiltin) or native_length.name not in {
                "unsigned int",
                "unsigned long",
                "unsigned long long",
            }:
                raise NativeImportError("initializer copied input requires an unsigned byte length")
            if f"{declaration.name}.{binding.copied_input}" not in self._borrows:
                raise NativeImportError("initializer copied input requires read-only-borrows")
        for parameter_index, parameter in enumerate(declaration.signature.parameters):
            if parameter_index in (index, copied_input):
                continue
            resource = self._resource_name(parameter)
            borrowed = resource and f"{declaration.name}.{names[parameter_index]}" in self._resource_borrows
            if not borrowed and not isinstance(self._unqualified_native(parameter), (NativeBuiltin, NativeEnumType)):
                raise NativeImportError(
                    "initializer additional parameters require SDK scalars; retained dependencies need an explicit contract"
                )
        if any(name == binding.result for _, name in self._declarations) or any(
            value.name == binding.result for value in self._input_classes
        ):
            raise NativeImportError("conflicting initializer result class")
        status_type = self._type(declaration.signature.return_type)
        self._input_classes.append(
            ast.ClassDecl(
                name=binding.result,
                members=[
                    ast.FieldDecl(access="public", name="called", type=ast.TypeExpr(base="bool")),
                    ast.FieldDecl(access="public", name="status", type=status_type),
                    ast.FieldDecl(
                        access="public",
                        name="value",
                        type=ast.TypeExpr(base=binding.resource, is_nullable=True, pointer_depth=1),
                    ),
                ],
                source_file=str(self._origin),
            )
        )
        self._initializers.pop(declaration.name)
        return NativeOwnedOutput(
            index,
            binding.result,
            binding.resource,
            status_type,
            initializer=NativeInitializer(binding.success, copied_input, length),
        )

    def _project_copied_input(self, declaration, names):
        selected = [
            (key, value) for key, value in self._copied_inputs.items() if key.split(".", 1)[0] == declaration.name
        ]
        if not selected:
            return None
        key, (owner, length) = selected[0]
        input_name = key.split(".", 1)[1]
        native_return = self._unqualified_native(declaration.signature.return_type)
        if (
            declaration.signature.variadic
            or len(names) != 3
            or any(name not in names for name in (owner, input_name, length))
            or not isinstance(native_return, NativeBuiltin)
            or native_return.name != "void"
        ):
            raise NativeImportError(
                "copied-inputs requires a void SDK setter with exactly owner, byte pointer and length"
            )
        owner_index, input_index, length_index = names.index(owner), names.index(input_name), names.index(length)
        resource = self._resource_name(declaration.signature.parameters[owner_index])
        if not resource or self._resources[resource].storage != "inline" or resource not in self._resource_initializers:
            raise NativeImportError("copied-inputs requires an initialized inline resource owner")
        if self._resource_initializers[resource].copied_input or resource in self._attached_resources:
            raise NativeImportError(
                "copied-inputs requires one write-once attachment per resource without initializer input"
            )
        pointer = self._unqualified_native(declaration.signature.parameters[input_index])
        scalar = self._unqualified_native(pointer.pointee) if isinstance(pointer, NativePointer) else None
        if (
            not isinstance(pointer, NativePointer)
            or not self._native_is_const(pointer.pointee)
            or not isinstance(scalar, NativeBuiltin)
            or scalar.name not in {"void", "char", "signed char", "unsigned char"}
        ):
            raise NativeImportError("copied-inputs requires a const byte pointer")
        self._validate_copy_qualifiers(declaration.signature.parameters[input_index])
        size = self._unqualified_native(declaration.signature.parameters[length_index])
        if not isinstance(size, NativeBuiltin) or size.name not in {
            "unsigned int",
            "unsigned long",
            "unsigned long long",
        }:
            raise NativeImportError("copied-inputs requires an unsigned byte length")
        self._attached_resources.add(resource)
        self._copied_inputs.pop(key)
        return NativeCopiedInput(owner_index, input_index, length_index, resource)

    def _import_resource_output(self, declaration, imported):
        selected = [
            (key, value)
            for key, value in self._owned_output_resources.items()
            if key.split(".", 1)[0] == declaration.name
        ]
        if not selected:
            return
        key, projection = selected[0]
        names = self._parameter_names(declaration.parameter_semantics)
        output_name = key.split(".", 1)[1]
        if output_name not in names or projection.size_parameter not in names:
            raise NativeImportError("erased owned-outputs names an unknown output or size parameter")
        index, size_index = names.index(output_name), names.index(projection.size_parameter)
        output_pointer = self._unqualified_native(declaration.signature.parameters[index])
        size_pointer = self._unqualified_native(declaration.signature.parameters[size_index])
        if (
            not isinstance(output_pointer, NativePointer)
            or self._native_is_const(output_pointer.pointee)
            or not isinstance(self._unqualified_native(output_pointer.pointee), NativeBuiltin)
            or self._unqualified_native(output_pointer.pointee).name != "void"
        ):
            raise NativeImportError("erased owned-outputs requires mutable void-pointer output storage")
        size_value = self._unqualified_native(size_pointer.pointee) if isinstance(size_pointer, NativePointer) else None
        if (
            not isinstance(size_value, NativeBuiltin)
            or self._native_is_const(size_pointer.pointee)
            or size_value.name
            not in {"unsigned char", "unsigned short", "unsigned int", "unsigned long", "unsigned long long"}
        ):
            raise NativeImportError("erased owned-outputs requires an unsigned integral mutable size pointer")
        status = self._unqualified_native(declaration.signature.return_type)
        if isinstance(status, NativeEnumType):
            status = self._unqualified_native(status.underlying)
        if not isinstance(status, NativeBuiltin) or status.name not in {
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
        }:
            raise NativeImportError("owned-outputs requires an integral or enum status result")
        contract = imported.source_file.call_contract
        if (
            contract.callbacks
            or contract.realtime_safe
            or contract.owned_output
            or contract.record_output
            or any(contract.record_inputs)
            or any(offset.split(".", 1)[0] == declaration.name for offset in self._output_offsets)
        ):
            raise NativeImportError(
                "erased owned-outputs cannot combine callbacks, realtime, record outputs or output-offsets"
            )
        resource = projection.resource
        if resource not in self._resources or self._resources[resource].ownership != "reference-counted":
            raise NativeImportError("erased owned-outputs requires a declared reference-counted resource")
        result_name = self._owned_outputs[key]
        if any(name in {result_name, projection.alias} for _, name in self._declarations) or any(
            value.name in {result_name, projection.alias} for value in self._input_classes
        ):
            raise NativeImportError("conflicting erased owned-output alias or result class")
        size_type = self._type(size_pointer.pointee)
        result_type = ast.TypeExpr(base=result_name)
        self._input_classes.append(
            ast.ClassDecl(
                name=result_name,
                members=[
                    ast.FieldDecl(access="public", name="status", type=imported.return_type),
                    ast.FieldDecl(access="public", name="size", type=size_type),
                    ast.FieldDecl(access="public", name="sizeValid", type=ast.TypeExpr(base="bool")),
                    ast.FieldDecl(
                        access="public",
                        name="value",
                        type=ast.TypeExpr(base=resource, is_nullable=True, pointer_depth=1),
                    ),
                ],
                source_file=str(self._origin),
            )
        )
        output = NativeOwnedOutput(
            index,
            result_name,
            resource,
            imported.return_type,
            sized_resource=NativeSizedResourceOutput(size_index, size_type, declaration.name),
        )
        visible = [position for position in range(len(names)) if not output.hides(position)]
        alias_contract = replace(
            contract,
            nonnull_parameters=tuple(contract.nonnull_parameters[position] for position in visible),
            read_only_borrows=tuple(contract.read_only_borrows[position] for position in visible),
            resource_parameters=tuple(contract.resource_parameters[position] for position in visible),
            owned_output=output,
        )
        alias = ast.FunctionDecl(
            name=projection.alias,
            return_type=result_type,
            params=[imported.params[position] for position in visible],
            body=None,
        )
        self._add(
            projection.alias,
            alias,
            ("sized-resource-output", declaration.name, key, projection),
            call_contract=alias_contract,
        )
        self._owned_outputs.pop(key)
        self._owned_output_resources.pop(key)

    def _project_variadic(self, declaration, parameter_names):
        selected = [
            (key, shape) for key, shape in self._variadic_calls.items() if key.startswith(declaration.name + ".")
        ]
        if not selected:
            if declaration.signature.variadic:
                raise NativeImportError("variadic native calls require a selected variadic-calls shape")
            return -1, "", (), ()
        key, shape = selected[0]
        if not declaration.signature.variadic:
            raise NativeImportError("variadic-calls requires an SDK variadic function")
        parameter = key.split(".", 1)[1]
        if parameter not in parameter_names:
            raise NativeImportError("variadic-calls names an unknown selector parameter")
        index = parameter_names.index(parameter)
        constant = self._callback_exports.get(shape.value)
        if not isinstance(constant, NativeConstant) and not (isinstance(constant, NativeGlobal) and constant.read_only):
            raise NativeImportError("variadic-calls value must be a selected read-only SDK integer constant")
        types = [declaration.signature.parameters[index], constant.value_type]
        bases = []
        for native in types:
            while isinstance(native, (NativeAlias, NativeQualifiedType, NativeEnumType)):
                native = native.underlying
            if not isinstance(native, NativeBuiltin) or native.name not in {
                "int",
                "unsigned int",
                "long",
                "unsigned long",
                "long long",
                "unsigned long long",
            }:
                raise NativeImportError("variadic-calls selector and value must be promoted integral SDK types")
            bases.append(native.name)
        if bases[0] != bases[1]:
            raise NativeImportError("variadic-calls selector and value must have the same SDK integer type")
        parameters = []
        occupied = set(parameter_names)
        for position, spelling in enumerate(shape.arguments):
            pointer = spelling.endswith("*")
            scalar = spelling[:-1].strip() if pointer else spelling
            const = scalar.startswith("const ")
            base = scalar[6:] if const else scalar
            name = f"variadicArgument{position}"
            while name in occupied:
                name += "_"
            occupied.add(name)
            parameters.append(
                ast.Param(type=ast.TypeExpr(base=base, is_const=const, pointer_depth=int(pointer)), name=name)
            )
        self._variadic_calls.pop(key)
        return index, shape.value, tuple(parameters), shape.arguments

    def _parameter_names(self, semantics):
        occupied = {parameter.name for parameter in semantics if parameter.name}
        names = []
        for index, parameter in enumerate(semantics):
            name = parameter.name
            if not name:
                name = f"argument{index}"
                while name in occupied:
                    name += "_"
                occupied.add(name)
            names.append(name)
        return tuple(names)

    def _import(self, declaration):
        if declaration.name in self._callback_operations:
            return
        if self._origin.language == "objective-c" and not isinstance(
            declaration, (NativeObjectiveCMethod, NativeConstant, NativeGlobal)
        ):
            raise NativeImportError("Objective-C header declarations require adapter lowering")
        contract = None
        if isinstance(declaration, NativeFunction):
            if declaration.name in self._resource_operations:
                return
            signature = declaration.signature
            # Emit calls through the included header's source spelling. The C
            # compiler owns SDK asm labels (including Darwin's pthread aliases);
            # redeclaring or calling the linker spelling would discard that ABI.
            resource_result = self._project_resource_position(declaration.name, signature.return_type, result=True)
            parameter_names = self._parameter_names(declaration.parameter_semantics)
            bound_parameter, bound_constant, variadic_parameters, variadic_arguments = self._project_variadic(
                declaration, parameter_names
            )
            owned_output = self._project_owned_output(declaration, parameter_names)
            copied_input = self._project_copied_input(declaration, parameter_names)
            copied_result = self._project_copied_result(declaration, parameter_names)
            borrowed_owner = self._borrowed_results.get(declaration.name)
            borrowed_owner_index = -1
            if borrowed_owner is not None:
                if not resource_result or self._resources[resource_result].ownership != "reference-counted":
                    raise NativeImportError("borrowed-results requires a reference-counted result")
                if declaration.returned_ownership not in ("unspecified", "cf_not_retained"):
                    raise NativeImportError("borrowed-results contradicts SDK retained ownership")
                for index, parameter_name in enumerate(parameter_names):
                    if parameter_name == borrowed_owner:
                        owner_resource = self._project_resource_position(
                            f"{declaration.name}.{parameter_names[index]}", signature.parameters[index], consume=False
                        )
                        if not owner_resource or self._resources[owner_resource].ownership != "reference-counted":
                            raise NativeImportError(
                                "borrowed-results owner must be a borrowed reference-counted parameter"
                            )
                        borrowed_owner_index = index
                if borrowed_owner_index < 0:
                    raise NativeImportError("borrowed-results names an unknown owner parameter")
                self._borrowed_results.pop(declaration.name)
            if (declaration.returned_ownership != "unspecified" and not resource_result) or any(
                parameter.cf_consumed or parameter.ns_consumed for parameter in declaration.parameter_semantics
            ):
                raise NativeImportError("annotated native ownership requires managed native lowering")
            if resource_result and borrowed_owner is None:
                if self._resources[resource_result].storage:
                    raise NativeImportError("inline resources require checked initializers, not owned pointer results")
                if self._resources[resource_result].ownership == "unique" and not self._resource_pointer_accepts(
                    self._resource_types[resource_result], signature.return_type
                ):
                    raise NativeImportError("unique resource result has incompatible pointer qualifiers")
                if declaration.returned_ownership not in ("unspecified", "cf_retained"):
                    raise NativeImportError(
                        "resource result contradicts owned ownership; borrowed results require an owner"
                    )
                if declaration.name not in self._owned_results and declaration.returned_ownership != "cf_retained":
                    raise NativeImportError("resource result requires owned-results or SDK retained ownership")
                self._owned_results.discard(declaration.name)
            parameters = []
            borrows = []
            resource_parameters = []
            callbacks = self._project_callbacks(declaration)
            if copied_input and (
                callbacks
                or owned_output
                or copied_result
                or resource_result
                or declaration.name in self._realtime
                or bound_parameter >= 0
            ):
                raise NativeImportError(
                    "copied-inputs cannot combine callbacks, other result mappings or realtime calls"
                )
            if copied_result and (
                callbacks
                or owned_output
                or resource_result
                or declaration.name in self._realtime
                or bound_parameter >= 0
            ):
                raise NativeImportError(
                    "copied-results does not support callbacks, other owned results, variadic, or realtime calls"
                )
            if bound_parameter >= 0 and (
                callbacks or owned_output or resource_result or declaration.name in self._realtime
            ):
                raise NativeImportError(
                    "variadic-calls does not support callbacks, owned outputs/results, or realtime calls"
                )
            if owned_output and (callbacks or declaration.name in self._realtime):
                raise NativeImportError("owned-outputs does not support callbacks or realtime calls")
            callback_parameters = {projection.parameter_index: projection for projection in callbacks}
            callback_contexts = {projection.context_index for projection in callbacks if projection.context_index >= 0}
            for index, (native, _) in enumerate(
                zip(signature.parameters, declaration.parameter_semantics, strict=True)
            ):
                name = parameter_names[index]
                key = f"{declaration.name}.{name}"
                if owned_output and owned_output.hides(index):
                    parameters.append(ast.Param(type=ast.TypeExpr(base="void", pointer_depth=1), name=name))
                    resource_parameters.append("")
                    borrows.append(False)
                    continue
                resource_parameter = self._project_resource_position(key, native)
                if resource_parameter:
                    if self._resources[resource_parameter].ownership == "unique" and not self._resource_pointer_accepts(
                        native, self._resource_types[resource_parameter]
                    ):
                        raise NativeImportError("unique resource parameter has incompatible pointer qualifiers")
                    if key not in self._resource_borrows:
                        raise NativeImportError(f"resource parameter {key} requires borrowed-parameters")
                    self._resource_borrows.remove(key)
                resource_parameters.append(resource_parameter)
                parameters.append(
                    ast.Param(
                        type=ast.TypeExpr(base=callback_parameters[index].interface)
                        if index in callback_parameters and not callback_parameters[index].field
                        else self._resource_call_type(native, resource_parameter)
                        if resource_parameter
                        else self._call_type(native, parameter=True),
                        name=name,
                    )
                )
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
            if any(borrows[index] or resource_parameters[index] for index in callback_contexts):
                raise NativeImportError("callback context cannot also declare a borrow or resource mapping")
            if bound_parameter >= 0 and (borrows[bound_parameter] or resource_parameters[bound_parameter]):
                raise NativeImportError("variadic-calls selector cannot carry a resource or borrow mapping")
            parameters.extend(variadic_parameters)
            borrows.extend(False for _ in variadic_parameters)
            resource_parameters.extend("" for _ in variadic_parameters)
            visible = [
                index
                for index in range(len(parameters))
                if index != bound_parameter
                and index not in callback_contexts
                and not (owned_output and owned_output.hides(index))
            ]
            imported = ast.FunctionDecl(
                name=declaration.name,
                return_type=ast.TypeExpr(base="bool")
                if copied_input
                else ast.TypeExpr(base=owned_output.result_name)
                if owned_output
                else ast.TypeExpr(base="string" if copied_result.kind == "string" else "Bytes", is_nullable=True)
                if copied_result
                else self._resource_call_type(signature.return_type, resource_result),
                params=[parameters[index] for index in visible],
                body=None,
            )
            contract = NativeCallContract(
                tuple(
                    index in callback_parameters
                    or (
                        index < len(signature.parameters)
                        and not (copied_input and index == copied_input.input_index)
                        and self._call_nullability(signature.parameters[index]) == "nonnull"
                    )
                    for index in visible
                ),
                self._call_nullability(signature.return_type) == "nonnull",
                tuple(borrows[index] for index in visible),
                declaration.name in self._realtime,
                resource_parameters=tuple(resource_parameters[index] for index in visible),
                resource_result=resource_result,
                callbacks=callbacks,
                borrowed_result_owner=visible.index(borrowed_owner_index) if borrowed_owner_index >= 0 else -1,
                owned_output=owned_output,
                bound_parameter=bound_parameter,
                bound_constant=bound_constant,
                variadic_arguments=variadic_arguments,
                copied_result=copied_result,
                copied_input=copied_input,
            )
            if any(callback.one_shot for callback in callbacks):
                if borrowed_owner is not None:
                    raise NativeImportError("borrowed-results does not support one-shot callback registration")
                if len(callbacks) != 1:
                    raise NativeImportError("one-shot currently requires exactly one callback")
                request_type = ast.TypeExpr(
                    base="CallbackRequest", generic_args=[ast.TypeExpr(base=callbacks[0].interface)]
                )
                imported.return_type = (
                    request_type
                    if imported.return_type.base == "void"
                    else ast.TypeExpr(base="CallbackResult", generic_args=[imported.return_type, request_type])
                )
                scope_name = "scope"
                while any(parameter.name == scope_name for parameter in imported.params):
                    scope_name += "_"
                imported.params.append(ast.Param(type=ast.TypeExpr(base="CallbackScope"), name=scope_name))
                contract = replace(
                    contract,
                    nonnull_parameters=(*contract.nonnull_parameters, True),
                    read_only_borrows=(*contract.read_only_borrows, False),
                    resource_parameters=(*contract.resource_parameters, ""),
                )
            if contract.realtime_safe and (resource_result or any(resource_parameters) or callbacks):
                raise NativeImportError("managed resource adapters are not realtime-safe")
            self._realtime.discard(declaration.name)
        elif isinstance(declaration, NativeGlobal):
            resource_global = ""
            if declaration.name in self._static_globals:
                resource_global = self._resource_name(declaration.value_type)
                if not resource_global or self._resources[resource_global].ownership != "reference-counted":
                    raise NativeImportError("static-globals requires reference-counted resource globals")
                if not declaration.read_only:
                    raise NativeImportError("static-globals requires read-only SDK storage")
                contract = NativeCallContract(
                    resource_result=resource_global,
                    nonnull_return=self._call_nullability(declaration.value_type) == "nonnull",
                )
                self._static_globals.remove(declaration.name)
            native = declaration.value_type
            while isinstance(native, (NativeAlias, NativeQualifiedType)):
                native = native.underlying
            object_global = self._origin.language == "objective-c" and isinstance(native, NativeObjectiveCObject)
            if declaration.name in self._main_thread_globals:
                if not object_global:
                    raise NativeImportError("main-thread-globals requires Objective-C object globals")
                contract = NativeCallContract(executor="main")
                self._main_thread_globals.remove(declaration.name)
            if object_global and not declaration.read_only and contract is None:
                raise NativeImportError("Mutable Objective-C object globals require managed storage lowering")
            projected = (
                self._resource_call_type(declaration.value_type)
                if resource_global
                else self._objective_c_type(declaration.value_type, read_only_slot=True)
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
                    or (
                        declaration.read_only
                        and not object_global
                        and not resource_global
                        and not isinstance(native, NativePointer)
                    ),
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
            if declaration.name in self._resources:
                return
            self._type(
                NativeAlias(
                    name=declaration.name,
                    underlying=declaration.underlying,
                    qualifiers=NativeQualifiers(nullability="unannotated"),
                )
            )
            return
        elif isinstance(declaration, NativeRecordDeclaration):
            if declaration.name in self._resources:
                return
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
            read_only=isinstance(declaration, NativeGlobal) and (declaration.read_only or contract is not None),
            call_contract=contract,
        )
        if isinstance(declaration, NativeFunction):
            self._import_resource_output(declaration, imported)

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

    def _objective_c_type(
        self, native, *, parameter=False, related_owner="", read_only_slot=False, cancellation_token=False
    ):
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
        opaque_token = cancellation_token and name in {"", "id"}
        unbounded_arguments = all(
            isinstance(argument := self._unqualified_native(value), NativeObjectiveCObject)
            and argument.name in {"", "id"}
            and not argument.class_object
            and not argument.protocols
            and not argument.type_arguments
            for value in native.type_arguments
        )
        if native.class_object or (native.protocols and not opaque_token) or not unbounded_arguments or name == "Class":
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
        initializer = (
            declaration.method_family == "init" and not declaration.class_method and declaration.related_result
        )
        if declaration.protocol_owner and declaration.receiver not in self._interfaces:
            raise NativeImportError(f"Objective-C protocol methods require a delegate binding: {declaration.name}")
        if declaration.optional:
            raise NativeImportError(f"Optional Objective-C calls require an availability check: {declaration.name}")
        if (
            declaration.signature.variadic
            or (declaration.consumes_self and not initializer)
            or declaration.returns_inner_pointer
            or any(parameter.cf_consumed or parameter.ns_consumed for parameter in declaration.parameter_semantics)
        ):
            raise NativeImportError("Objective-C instance/ownership calls require managed native lowering")
        callbacks = self._project_callbacks(declaration)
        if initializer and callbacks:
            raise NativeImportError("Objective-C initializer callbacks require an explicit publication contract")
        stored = [callback for callback in callbacks if callback.unregister is not None]
        opaque_token = bool(
            stored
            and stored[0].unregister.signature.parameters
            and self._unqualified_native(stored[0].unregister.signature.parameters[0]).name in {"", "id"}
        )
        contract = NativeCallContract(callbacks=callbacks, objective_c_method=declaration)
        projected = {callback.parameter_index: callback for callback in callbacks}
        name = declaration.selector.split(":", 1)[0]
        method = ast.MethodDecl(
            access="class" if declaration.class_method or initializer else "public",
            name=name,
            return_type=self._objective_c_type(
                declaration.signature.return_type,
                related_owner=declaration.receiver if declaration.related_result else "",
                cancellation_token=opaque_token,
            ),
            params=[
                ast.Param(
                    type=ast.TypeExpr(base=projected[index].interface)
                    if index in projected
                    else self._objective_c_type(native, parameter=True),
                    name=f"argument{index}",
                )
                for index, native in enumerate(declaration.signature.parameters)
            ],
        )
        if stored:
            if len(callbacks) != 1:
                raise NativeImportError("stored callback factory currently requires exactly one callback")
            token = (
                ast.TypeExpr(base="id")
                if isinstance(stored[0], (NativeDelegateProjection, NativeActionProjection))
                else replace(method.return_type, is_nullable=False, pointer_depth=0)
            )
            if stored[0].unregister.signature.parameters and not stored[0].unregister.class_method:
                self._objective_c_class(declaration.receiver)
                token = ast.TypeExpr(
                    base="CallbackToken", generic_args=[ast.TypeExpr(base=declaration.receiver), token]
                )
            method.return_type = ast.TypeExpr(
                base="CallbackContext", generic_args=[ast.TypeExpr(base=stored[0].interface), token]
            )
            method.params.append(ast.Param(type=ast.TypeExpr(base="CallbackScope"), name="scope"))
        elif any(callback.one_shot for callback in callbacks):
            if len(callbacks) != 1:
                raise NativeImportError("one-shot currently requires exactly one callback")
            method.return_type = ast.TypeExpr(
                base="CallbackRequest", generic_args=[ast.TypeExpr(base=callbacks[0].interface)]
            )
            method.params.append(ast.Param(type=ast.TypeExpr(base="CallbackScope"), name="scope"))
        owner = self._objective_c_class(declaration.receiver)
        previous = owner.source_file.methods.get(name)
        if previous is not None:
            if previous != contract:
                raise NativeImportError(f"ambiguous Objective-C method projection {declaration.receiver}.{name}")
            return
        owner.source_file.methods[name] = contract
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
        if nullability != "unannotated" and not isinstance(native, (NativePointer, NativeObjectiveCObject)):
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
                    if isinstance(entry, (NativeFunction, NativeObjectiveCMethod, NativeCxxMethod))
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
        elif kind == "cxx_class":
            required |= {"default_constructor", "public_destructor", "trivially_copyable", "trivially_destructible"}
        elif kind == "cxx_method":
            required |= {"identity", "owner", "receiver", "method_name", "parameter_semantics", "const_method"}
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
        optional_fields = {"source", "line", "column"}
        if kind == "enum_constant":
            optional_fields.add("enum_identity")
        if kind == "objc_method":
            optional_fields |= {"protocol_owner", "optional"}
        self._object(value, required, optional_fields)
        position = {
            "name": self._text(value["name"]),
            "source_file": self._text(value.get("source", ""), empty=True),
            "line": self._integer(value.get("line", 0)),
            "column": self._integer(value.get("column", 0)),
        }
        native_type = self._type(value["type"])
        if kind == "cxx_class":
            if (
                not isinstance(native_type, NativeRecordType)
                or not native_type.complete
                or native_type.name != position["name"]
            ):
                raise NativeImportError("C++ class requires its complete SDK record identity")
            return NativeCxxClass(
                **position,
                record_type=native_type,
                default_constructor=self._boolean(value["default_constructor"]),
                public_destructor=self._boolean(value["public_destructor"]),
                trivially_copyable=self._boolean(value["trivially_copyable"]),
                trivially_destructible=self._boolean(value["trivially_destructible"]),
            )
        if kind in {"function", "objc_method", "cxx_method"}:
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
            if kind == "cxx_method":
                receiver, method = self._text(value["receiver"]), self._text(value["method_name"])
                if (
                    position["name"] not in {f"{receiver}::{method}", f"{receiver}::{method}()"}
                    or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", method)
                    or native_type.variadic
                    or (position["name"].endswith("()") and parameters)
                ):
                    raise NativeImportError("C++ method must match its receiver and fixed signature")
                return NativeCxxMethod(
                    **position,
                    identity=self._text(value["identity"]),
                    owner=self._text(value["owner"]),
                    receiver=receiver,
                    method_name=method,
                    signature=native_type,
                    parameter_semantics=parameters,
                    const_method=self._boolean(value["const_method"]),
                )
            if kind == "objc_method":
                owner = self._text(value["owner"])
                receiver = self._text(value["receiver"])
                selector = self._text(value["selector"])
                class_method = self._boolean(value["class_method"])
                protocol_owner = self._boolean(value.get("protocol_owner", False))
                optional = self._boolean(value.get("optional", False))
                if optional and not protocol_owner:
                    raise NativeImportError("optional Objective-C method requires a protocol owner")
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
                    protocol_owner=protocol_owner,
                    optional=optional,
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
                **position,
                value_type=native_type,
                decimal_value=self._decimal(value["value"], signed=True),
                enum_identity=self._text(value.get("enum_identity", ""), empty=True),
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
