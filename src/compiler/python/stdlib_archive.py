"""Precompiled-stdlib support: build the stdlib once into a linkable archive
(header + impl + manifest), then compile programs that *reference* it instead of
inlining the whole stdlib into every translation unit.

Two compiler modes use this:

* ``--build-stdlib <dir>`` runs the stdlib through the normal pipeline *without*
  dead-code elimination (an archive is a complete library, not a program) and
  writes ``btrc_stdlib.h`` (declarations), ``btrc_stdlib.c`` (definitions), and
  ``btrc_stdlib.manifest`` (the set of symbols the archive provides).

* ``--stdlib <dir>`` compiles a program as usual, then *partitions out* every
  top-level element the manifest already provides, leaving program-only C that
  ``#include "btrc_stdlib.h"`` and links the archive.

Linkage notes:
* Class methods and free functions are already extern, so they live in the
  archive and programs call them directly. Generic instance methods are emitted
  ``static`` by IR gen; for the archive we flip the stdlib's own concrete
  instances to extern (and strip ``static`` from their prototypes) so programs
  can link them. A program's *own* generic instantiations (e.g. ``Vector<Foo>``
  for a user type the stdlib never used) are not in the manifest, so they stay
  local and ``static`` — no duplicate symbols.
* Runtime helpers are ``static``/``static inline`` (file-local), so duplicating
  them per-TU causes no link conflict. The only ones that must be a *single*
  instance are those with process-global mutable state that crosses the
  archive/program boundary — every pointer/index/capacity member of the
  destroyed-pointer guard, cycle-suspect queue, try/catch cleanup stacks, and
  managed-string registry. We emit those once in the archive (extern) and
  declare them in the header. A managed string can cross the archive boundary,
  so its registry lock, buckets, counters, and lookup functions must never be
  duplicated per translation unit.
"""

from __future__ import annotations

import hashlib

from . import stdlib_archive_validation as _archive_validation
from .cache_keys import toolchain_hash
from .stdlib_archive_helpers import (
    ARCHIVE_HELPER_API_NAMES,
    derive_archive_api_decls,
    derive_archive_api_impl,
)
from .stdlib_archive_publish import publish_stdlib_archive
from .stdlib_shared_state import (
    complete_shared_helpers,
    derive_shared_decls,
    derive_shared_impl,
    externize_toplevel,
    inline_toplevel_functions,
)

HEADER_NAME, IMPL_NAME = _archive_validation.ARCHIVE_ARTIFACT_NAMES
MANIFEST_NAME = "btrc_stdlib.manifest"
ArchiveVersionError = _archive_validation.ArchiveVersionError
MANIFEST_SCHEMA = _archive_validation.MANIFEST_SCHEMA
_MANIFEST_LIST_FIELDS = _archive_validation.MANIFEST_LIST_FIELDS
_stdlib_source_hash = _archive_validation.stdlib_source_hash
reject_user_overrides = _archive_validation.reject_user_overrides
# Helpers whose process-global mutable state must be a single instance shared by
# the archive and every program that links it. The header extern decls and the
# single-instance .c definitions are *derived* from each helper's real
# ``c_source`` (see stdlib_shared_state) rather than hardcoded, so a change to
# the helper text can never drift out of sync with the program TUs.


def _is_generic_symbol(name: str) -> bool:
    """Monomorphized generic instances are mangled ``btrc_Base_arg...``."""
    return name.startswith("btrc_")


def _macro_record(macro) -> dict:
    return {
        "name": macro.name,
        "params": None if macro.params is None else list(macro.params),
        "replacement": macro.replacement,
    }


def _macro_key(macro) -> tuple:
    return (
        macro.name,
        None if macro.params is None else tuple(macro.params),
        macro.replacement,
    )


def _macro_record_key(record: dict) -> tuple:
    return (
        record["name"],
        None if record["params"] is None else tuple(record["params"]),
        record["replacement"],
    )


# Re-exported for callers that referenced the archive's externizer directly.
_externize_toplevel = externize_toplevel


def transform_archive_module(module) -> tuple[list[str], dict[str, str]]:
    """Rewrite an IR module in place for use as a precompiled archive.

    * Flip the stdlib's own concrete generic instance methods and structured
      archive callbacks from ``static`` to extern (definitions and prototypes)
      so programs can link them.
    * Emit each complete shared-state helper group as one set of extern
      definitions.

    Returns ``(shared_names, shared_decls)`` where ``shared_names`` lists the
    shared-state helpers actually present (so the manifest/header only advertise
    state the archive really defines) and ``shared_decls`` maps each to the
    header (extern) declarations derived from its real source — captured *before*
    each helper's ``c_source`` is rewritten to its single-instance .c definition.
    """
    module.validate_declarations()
    module.helper_decls, archive_owned_helpers = complete_shared_helpers(module.helper_decls)
    archive_exports = {
        func.name for func in module.function_defs if _is_generic_symbol(func.name) or func.archive_export
    }

    # Generic instance methods and archive callback definitions -> extern.
    for func in module.function_defs:
        if func.is_static and func.name in archive_exports:
            func.is_static = False

    # The matching typed prototypes must expose the same linkage.
    for declaration in module.function_decls:
        if declaration.is_static and declaration.name in archive_exports:
            declaration.is_static = False

    # Shared-state helpers -> single extern definition. Derive the matching
    # header decls from the *original* source first, then rewrite the helper to
    # its single-instance .c definition.
    shared_present = []
    shared_decls = {}
    for helper in module.helper_decls:
        if helper.name in archive_owned_helpers:
            if helper.name in ARCHIVE_HELPER_API_NAMES:
                shared_decls[helper.name] = derive_archive_api_decls(
                    helper.c_source,
                    helper.name,
                )
                helper.c_source = derive_archive_api_impl(
                    helper.c_source,
                    helper.name,
                )
            else:
                shared_decls[helper.name] = derive_shared_decls(helper.c_source)
                helper.c_source = derive_shared_impl(helper.c_source)
            shared_present.append(helper.name)
        else:
            shared_decls[helper.name] = inline_toplevel_functions(helper.c_source)
    return shared_present, shared_decls


def _build_manifest(
    module,
    shared_helpers: list[str],
    stdlib_source: str,
    artifacts: dict[str, str] | None = None,
) -> dict:
    """Identify every top-level element the archive provides, so a program can
    drop its own copy. Named elements key by name; macro records preserve their
    structured signature and replacement tokens.
    """
    from .ir.nodes import IRMacroDef

    module.validate_declarations()
    artifacts = artifacts or {HEADER_NAME: "", IMPL_NAME: ""}
    return {
        "artifacts": {name: hashlib.sha256(content.encode("utf-8")).hexdigest() for name, content in artifacts.items()},
        "schema": MANIFEST_SCHEMA,
        "stdlib_source": _stdlib_source_hash(stdlib_source),
        "toolchain": toolchain_hash("full"),
        "types": sorted(
            {e.name for e in module.enum_defs if e.name is not None}
            | {f.name for f in module.struct_forwards}
            | {f.name for f in module.function_pointer_typedefs}
            | {s.name for s in module.struct_defs}
            | {t.name for t in module.typedef_defs}
            | {t.name for t in module.tagged_union_defs}
        ),
        "functions": sorted(f.name for f in module.function_defs if not f.is_static),
        "function_declarations": sorted(
            declaration.name for declaration in module.function_decls if not declaration.is_static
        ),
        "macros": [
            _macro_record(declaration)
            for declaration in module.preprocessor_decls
            if isinstance(declaration, IRMacroDef)
        ],
        "helpers": sorted(h.name for h in module.helper_decls),
        "global_decl_names": sorted(g.name for g in module.global_decls),
        "shared_helpers": sorted(shared_helpers),
    }


def build_archive(out_dir: str, module, stdlib_source: str) -> dict:
    """Transform ``module`` and write the header, impl, and manifest into
    ``out_dir``. Returns the manifest dict.
    """
    from .ir.emitter import CEmitter
    from .ir.optimizer import optimize

    optimize(module, dce=False)
    shared, shared_decls = transform_archive_module(module)

    header = CEmitter().emit_header(module, shared_decls)
    impl = CEmitter().emit_impl(module, HEADER_NAME, set(shared))
    manifest = _build_manifest(
        module,
        shared,
        stdlib_source,
        {HEADER_NAME: header, IMPL_NAME: impl},
    )

    publish_stdlib_archive(
        out_dir,
        HEADER_NAME,
        header,
        IMPL_NAME,
        impl,
        MANIFEST_NAME,
        manifest,
    )
    return manifest


def load_manifest(stdlib_dir: str, stdlib_source: str) -> dict:
    """Load and validate an archive against the canonical whole stdlib."""
    return _archive_validation.load_manifest(
        stdlib_dir,
        stdlib_source,
        MANIFEST_NAME,
    )


def partition_for_archive(module, manifest: dict, header_include: str = HEADER_NAME):
    """Drop every element the archive already provides, in place, and insert the
    header before the first remaining include. What remains is program-only:
    user code plus generic instances the stdlib never instantiated (kept local
    and ``static``).
    """
    module.validate_declarations()
    types = set(manifest["types"])
    funcs = set(manifest["functions"])
    drop_named = types | funcs
    function_declarations = set(manifest["function_declarations"])
    archive_macros = {_macro_record_key(record) for record in manifest["macros"]}
    helpers = set(manifest.get("helpers", [])) | set(manifest["shared_helpers"])

    module.enum_defs = [e for e in module.enum_defs if e.name not in types]
    module.typedef_defs = [t for t in module.typedef_defs if t.name not in types]
    module.tagged_union_defs = [t for t in module.tagged_union_defs if t.name not in types]
    module.struct_defs = [s for s in module.struct_defs if s.name not in types]
    module.function_defs = [f for f in module.function_defs if f.name not in funcs]
    module.struct_forwards = [declaration for declaration in module.struct_forwards if declaration.name not in types]
    module.function_pointer_typedefs = [
        declaration for declaration in module.function_pointer_typedefs if declaration.name not in types
    ]
    module.function_decls = [
        declaration
        for declaration in module.function_decls
        if (declaration.name not in drop_named and declaration.name not in function_declarations)
    ]
    from .ir.nodes import IRInclude, IRMacroDef

    module.preprocessor_decls = [
        declaration
        for declaration in module.preprocessor_decls
        if not (isinstance(declaration, IRMacroDef) and _macro_key(declaration) in archive_macros)
    ]
    global_decl_names = set(manifest["global_decl_names"])
    module.global_decls = [g for g in module.global_decls if g.name not in global_decl_names]
    # Every runtime helper the archive provides comes from the header; drop the
    # program's own copies. Helpers the stdlib never used (not in the manifest)
    # stay local.
    module.helper_decls = [h for h in module.helper_decls if h.name not in helpers]

    archive_include = IRInclude(header=header_include, is_system=False)
    first_include = next(
        (index for index, declaration in enumerate(module.preprocessor_decls) if isinstance(declaration, IRInclude)),
        len(module.preprocessor_decls),
    )
    module.preprocessor_decls.insert(first_include, archive_include)
    module.refresh_type_declarations()
    from .ir.runtime_dependencies import refresh_runtime_dependencies

    refresh_runtime_dependencies(module)
    return module
