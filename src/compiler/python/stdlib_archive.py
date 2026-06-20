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
  archive/program boundary — the destroyed-pointer guard and try/catch stacks.
  We emit those once in the archive (extern) and declare them in the header. The
  string temp-pool is an accumulate-until-exit arena (never flushed), so a per-TU
  copy is behaviourally identical and is intentionally left duplicated.
"""

from __future__ import annotations

import json
import os
import re

from .cache_keys import toolchain_hash
from .stdlib_shared_state import (
    SHARED_STATE_HELPER_NAMES,
    derive_shared_decls,
    derive_shared_impl,
    externize_toplevel,
)

HEADER_NAME = "btrc_stdlib.h"
IMPL_NAME = "btrc_stdlib.c"
MANIFEST_NAME = "btrc_stdlib.manifest"


class ArchiveVersionError(Exception):
    """The archive was built by a different compiler than the one loading it.

    Partitioning a program against a foreign archive silently drops symbols by
    *name* even when their definitions differ, so a stale archive must be
    refused and regenerated (--build-stdlib) rather than used.
    """

# Helpers whose process-global mutable state must be a single instance shared by
# the archive and every program that links it. The header extern decls and the
# single-instance .c definitions are *derived* from each helper's real
# ``c_source`` (see stdlib_shared_state) rather than hardcoded, so a change to
# the helper text can never drift out of sync with the program TUs.

_FWD_TYPEDEF_RE = re.compile(r"typedef\s+struct\s+(\w+)\s+\1\s*;")
_FWD_FUNC_RE = re.compile(r"\b(\w+)\s*\(")


def _forward_decl_name(fwd: str) -> str | None:
    """Best-effort: the symbol a forward declaration introduces.

    Handles the two shapes IR gen emits — ``typedef struct X X;`` and function
    prototypes ``[static] RET NAME(params);`` — returning ``X`` / ``NAME``.
    """
    m = _FWD_TYPEDEF_RE.search(fwd)
    if m:
        return m.group(1)
    # Function prototype: the identifier immediately before the parameter list.
    m = _FWD_FUNC_RE.search(fwd)
    if m:
        return m.group(1)
    return None


def _is_generic_symbol(name: str) -> bool:
    """Monomorphized generic instances are mangled ``btrc_Base_arg...``."""
    return name.startswith("btrc_")


# Re-exported for callers that referenced the archive's externizer directly.
_externize_toplevel = externize_toplevel


def transform_archive_module(module) -> tuple[list[str], dict[str, str]]:
    """Rewrite an IR module in place for use as a precompiled archive.

    * Flip the stdlib's own concrete generic instance methods from ``static`` to
      extern (definitions and forward-decl prototypes) so programs can link them.
    * Emit shared-state helpers (the destroyed-pointer guard) as a single extern
      definition.

    Returns ``(shared_names, shared_decls)`` where ``shared_names`` lists the
    shared-state helpers actually present (so the manifest/header only advertise
    state the archive really defines) and ``shared_decls`` maps each to the
    header (extern) declarations derived from its real source — captured *before*
    each helper's ``c_source`` is rewritten to its single-instance .c definition.
    """
    # Generic instance method *definitions* -> extern.
    for func in module.function_defs:
        if func.is_static and _is_generic_symbol(func.name):
            func.is_static = False

    # Generic instance *prototypes* (raw strings in forward_decls) -> extern.
    new_fwd = []
    for fwd in module.forward_decls:
        name = _forward_decl_name(fwd)
        if name and _is_generic_symbol(name) and fwd.lstrip().startswith("static"):
            new_fwd.append(_externize_toplevel(fwd.lstrip()))
        else:
            new_fwd.append(fwd)
    module.forward_decls = new_fwd

    # Raw sections hold generic-instance method prototypes and a few cross-TU
    # function definitions (cycle-collector visitors), all emitted `static`.
    # Export them so programs can link the archive's copies. #define sections and
    # the type-macro section have no top-level `static`, so this is a no-op there.
    module.raw_sections = [
        s if s.startswith("#define") else _externize_toplevel(s)
        for s in module.raw_sections
    ]

    # Shared-state helpers -> single extern definition. Derive the matching
    # header decls from the *original* source first, then rewrite the helper to
    # its single-instance .c definition.
    shared_present = []
    shared_decls = {}
    for helper in module.helper_decls:
        if helper.name in SHARED_STATE_HELPER_NAMES:
            shared_decls[helper.name] = derive_shared_decls(helper.c_source)
            helper.c_source = derive_shared_impl(helper.c_source)
            shared_present.append(helper.name)
    return shared_present, shared_decls


def _build_manifest(module, shared_helpers: list[str]) -> dict:
    """Identify every top-level element the archive provides, so a program can
    drop its own copy. Named elements key by name; pre-rendered raw sections key
    by exact text (deterministic across compilations of the same source).
    """
    return {
        "toolchain": toolchain_hash("full"),
        "types": sorted(
            {e.name for e in module.enum_defs}
            | {s.name for s in module.struct_defs}
        ),
        "functions": sorted(f.name for f in module.function_defs if not f.is_static),
        "helpers": sorted(h.name for h in module.helper_decls),
        "forward_decls": list(module.forward_decls),
        "vtables": list(module.vtable_defs),
        "globals": list(module.global_vars),
        "raw_sections": [s for s in module.raw_sections if not s.startswith("#define")],
        "shared_helpers": sorted(shared_helpers),
    }


def build_archive(out_dir: str, module) -> dict:
    """Transform ``module`` and write the header, impl, and manifest into
    ``out_dir``. Returns the manifest dict.
    """
    from .ir.emitter import CEmitter

    os.makedirs(out_dir, exist_ok=True)
    shared, shared_decls = transform_archive_module(module)

    header = CEmitter().emit_header(module, shared_decls)
    impl = CEmitter().emit_impl(module, HEADER_NAME, set(shared))
    manifest = _build_manifest(module, shared)

    with open(os.path.join(out_dir, HEADER_NAME), "w") as f:
        f.write(header)
    with open(os.path.join(out_dir, IMPL_NAME), "w") as f:
        f.write(impl)
    with open(os.path.join(out_dir, MANIFEST_NAME), "w") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
    return manifest


def load_manifest(stdlib_dir: str) -> dict:
    """Load and validate an archive manifest.

    Refuses (raises ArchiveVersionError) when the manifest was written by a
    different compiler version — the caller must rebuild with --build-stdlib.
    """
    with open(os.path.join(stdlib_dir, MANIFEST_NAME)) as f:
        manifest = json.load(f)
    current = toolchain_hash("full")
    stamped = manifest.get("toolchain")
    if stamped != current:
        raise ArchiveVersionError(
            f"stdlib archive in '{stdlib_dir}' was built by a different "
            f"compiler version (archive: {stamped or 'unstamped'}, current: "
            f"{current}); regenerate it with --build-stdlib"
        )
    return manifest


def partition_for_archive(module, manifest: dict,
                          header_include: str = HEADER_NAME):
    """Drop every element the archive already provides, in place, and prepend the
    header include. What remains is program-only: user code plus any generic
    instances the stdlib never instantiated (kept local and ``static``).
    """
    types = set(manifest["types"])
    funcs = set(manifest["functions"])
    drop_named = types | funcs
    fwd_set = set(manifest["forward_decls"])
    vt_set = set(manifest["vtables"])
    gl_set = set(manifest["globals"])
    raw_set = set(manifest["raw_sections"])
    helpers = set(manifest.get("helpers", [])) | set(manifest["shared_helpers"])

    module.enum_defs = [e for e in module.enum_defs if e.name not in types]
    module.struct_defs = [s for s in module.struct_defs if s.name not in types]
    module.function_defs = [f for f in module.function_defs if f.name not in funcs]
    module.forward_decls = [
        fd for fd in module.forward_decls
        if (_forward_decl_name(fd) not in drop_named) and (fd not in fwd_set)
    ]
    module.vtable_defs = [v for v in module.vtable_defs if v not in vt_set]
    module.global_vars = [g for g in module.global_vars if g not in gl_set]
    # The archive's raw sections were externized (their leading `static` stripped)
    # when the manifest was built; a program's copy is still `static`, so compare
    # the normalized form. #defines are kept (re-including them is harmless).
    module.raw_sections = [
        s for s in module.raw_sections
        if s.startswith("#define") or _externize_toplevel(s) not in raw_set
    ]
    # Every runtime helper the archive provides comes from the header; drop the
    # program's own copies. Helpers the stdlib never used (not in the manifest)
    # stay local.
    module.helper_decls = [h for h in module.helper_decls if h.name not in helpers]

    module.includes = [f'#include "{header_include}"'] + module.includes
    return module
