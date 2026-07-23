"""Owned build and consumption policy for precompiled stdlib archives.

``StdlibArchive`` is the single application service for transforming an IR
module into a reusable archive, authenticating an existing archive, and
partitioning archive-owned declarations out of a program module.
"""

from __future__ import annotations

import hashlib

from .artifacts.cache.compiler_cache import ToolchainFingerprint
from .artifacts.publication.publisher import ArtifactPublisher
from .artifacts.publication.storage import ArtifactStorage
from .artifacts.stdlib.publisher import StdlibArchivePublisher
from .ir.emitter import CEmitter
from .ir.nodes import IRInclude, IRMacroDef
from .ir.optimizer import optimize
from .ir.runtime_dependencies import refresh_runtime_dependencies
from .stdlib_archive_validation import (
    ArchiveVersionError,
    StdlibArchiveManifest,
)
from .stdlib_shared_state import SharedStateArchivePolicy

HEADER_NAME, IMPL_NAME = StdlibArchiveManifest.ARTIFACT_NAMES
MANIFEST_NAME = "btrc_stdlib.manifest"
MANIFEST_SCHEMA = StdlibArchiveManifest.SCHEMA
_MANIFEST_LIST_FIELDS = StdlibArchiveManifest.LIST_FIELDS


class StdlibArchive:
    """Own archive transformation, publication, validation, and partitioning."""

    def __init__(
        self,
        publisher: StdlibArchivePublisher | None = None,
        fingerprint: ToolchainFingerprint | None = None,
        shared_state: SharedStateArchivePolicy | None = None,
        emitter: CEmitter | None = None,
    ) -> None:
        self.publisher = publisher or StdlibArchivePublisher(ArtifactPublisher(ArtifactStorage()))
        self.fingerprint = fingerprint or ToolchainFingerprint()
        self.shared_state = shared_state or SharedStateArchivePolicy()
        self.emitter = emitter or CEmitter()
        self.manifest = StdlibArchiveManifest(
            self.publisher,
            self.fingerprint,
            manifest_name=MANIFEST_NAME,
        )

    def transform_module(self, module) -> tuple[list[str], dict[str, str]]:
        """Rewrite one complete IR module for external archive linkage."""

        module.validate_declarations()
        module.helper_decls, archive_owned_helpers = self.shared_state.complete_helpers(module.helper_decls)
        archive_exports = {
            function.name
            for function in module.function_defs
            if self._is_generic_symbol(function.name) or function.archive_export
        }

        for function in module.function_defs:
            if function.is_static and function.name in archive_exports:
                function.is_static = False
        for declaration in module.function_decls:
            if declaration.is_static and declaration.name in archive_exports:
                declaration.is_static = False

        shared_present = []
        shared_declarations = {}
        for helper in module.helper_decls:
            if helper.name in archive_owned_helpers:
                if helper.name in self.shared_state.ARCHIVE_API_NAMES:
                    shared_declarations[helper.name] = self.shared_state.derive_archive_api_declarations(
                        helper.c_source,
                        helper.name,
                    )
                    helper.c_source = self.shared_state.derive_archive_api_implementation(
                        helper.c_source,
                        helper.name,
                    )
                else:
                    shared_declarations[helper.name] = self.shared_state.derive_shared_declarations(helper.c_source)
                    helper.c_source = self.shared_state.derive_shared_implementation(helper.c_source)
                shared_present.append(helper.name)
            else:
                shared_declarations[helper.name] = self.shared_state.inline_toplevel_functions(helper.c_source)
        return shared_present, shared_declarations

    def build(self, out_dir: str, module, stdlib_source: str) -> dict:
        """Build and transactionally publish one complete stdlib archive."""

        optimize(module, dce=False)
        shared, shared_declarations = self.transform_module(module)
        header = self.emitter.emit_header(module, shared_declarations)
        implementation = self.emitter.emit_impl(module, HEADER_NAME, set(shared))
        manifest = self.create_manifest(
            module,
            shared,
            stdlib_source,
            {HEADER_NAME: header, IMPL_NAME: implementation},
        )
        self.publisher.publish(
            out_dir,
            HEADER_NAME,
            header,
            IMPL_NAME,
            implementation,
            MANIFEST_NAME,
            manifest,
        )
        return manifest

    def load(self, stdlib_dir: str, stdlib_source: str) -> dict:
        """Load and validate an archive against the canonical whole stdlib."""

        return self.manifest.load(stdlib_dir, stdlib_source)

    def reject_user_overrides(self, program, manifest: dict) -> None:
        self.manifest.reject_user_overrides(program, manifest)

    def partition(
        self,
        module,
        manifest: dict,
        header_include: str = HEADER_NAME,
    ):
        """Remove archive-owned elements and insert its public C header."""

        module.validate_declarations()
        types = set(manifest["types"])
        functions = set(manifest["functions"])
        drop_named = types | functions
        function_declarations = set(manifest["function_declarations"])
        archive_macros = {self._macro_record_key(record) for record in manifest["macros"]}
        helpers = set(manifest.get("helpers", [])) | set(manifest["shared_helpers"])

        module.enum_defs = [entry for entry in module.enum_defs if entry.name not in types]
        module.typedef_defs = [entry for entry in module.typedef_defs if entry.name not in types]
        module.tagged_union_defs = [entry for entry in module.tagged_union_defs if entry.name not in types]
        module.struct_defs = [entry for entry in module.struct_defs if entry.name not in types]
        module.function_defs = [entry for entry in module.function_defs if entry.name not in functions]
        module.struct_forwards = [entry for entry in module.struct_forwards if entry.name not in types]
        module.function_pointer_typedefs = [
            entry for entry in module.function_pointer_typedefs if entry.name not in types
        ]
        module.function_decls = [
            entry
            for entry in module.function_decls
            if entry.name not in drop_named and entry.name not in function_declarations
        ]
        module.preprocessor_decls = [
            declaration
            for declaration in module.preprocessor_decls
            if not (isinstance(declaration, IRMacroDef) and self._macro_key(declaration) in archive_macros)
        ]
        global_names = set(manifest["global_decl_names"])
        module.global_decls = [entry for entry in module.global_decls if entry.name not in global_names]
        module.helper_decls = [helper for helper in module.helper_decls if helper.name not in helpers]

        archive_include = IRInclude(header=header_include, is_system=False)
        first_include = next(
            (
                index
                for index, declaration in enumerate(module.preprocessor_decls)
                if isinstance(declaration, IRInclude)
            ),
            len(module.preprocessor_decls),
        )
        module.preprocessor_decls.insert(first_include, archive_include)
        module.refresh_type_declarations()
        refresh_runtime_dependencies(module)
        return module

    def create_manifest(
        self,
        module,
        shared_helpers: list[str],
        stdlib_source: str,
        artifacts: dict[str, str] | None = None,
    ) -> dict:
        """Describe every top-level element supplied by an archive."""

        module.validate_declarations()
        artifacts = artifacts or {HEADER_NAME: "", IMPL_NAME: ""}
        return {
            "artifacts": {
                name: hashlib.sha256(content.encode("utf-8")).hexdigest() for name, content in artifacts.items()
            },
            "schema": MANIFEST_SCHEMA,
            "stdlib_source": self.manifest.source_hash(stdlib_source),
            "toolchain": self.fingerprint.digest("full"),
            "types": sorted(
                {entry.name for entry in module.enum_defs if entry.name is not None}
                | {entry.name for entry in module.struct_forwards}
                | {entry.name for entry in module.function_pointer_typedefs}
                | {entry.name for entry in module.struct_defs}
                | {entry.name for entry in module.typedef_defs}
                | {entry.name for entry in module.tagged_union_defs}
            ),
            "functions": sorted(function.name for function in module.function_defs if not function.is_static),
            "function_declarations": sorted(
                declaration.name for declaration in module.function_decls if not declaration.is_static
            ),
            "macros": [
                self._macro_record(declaration)
                for declaration in module.preprocessor_decls
                if isinstance(declaration, IRMacroDef)
            ],
            "helpers": sorted(helper.name for helper in module.helper_decls),
            "global_decl_names": sorted(declaration.name for declaration in module.global_decls),
            "shared_helpers": sorted(shared_helpers),
        }

    def _is_generic_symbol(self, name: str) -> bool:
        return name.startswith("btrc_")

    def _macro_record(self, macro) -> dict:
        return {
            "name": macro.name,
            "params": None if macro.params is None else list(macro.params),
            "replacement": macro.replacement,
        }

    def _macro_key(self, macro) -> tuple:
        return (
            macro.name,
            None if macro.params is None else tuple(macro.params),
            macro.replacement,
        )

    def _macro_record_key(self, record: dict) -> tuple:
        return (
            record["name"],
            None if record["params"] is None else tuple(record["params"]),
            record["replacement"],
        )


__all__ = [
    "HEADER_NAME",
    "IMPL_NAME",
    "MANIFEST_NAME",
    "MANIFEST_SCHEMA",
    "ArchiveVersionError",
    "StdlibArchive",
]
