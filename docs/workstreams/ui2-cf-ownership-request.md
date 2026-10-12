# UI2 Core Foundation ownership composition prerequisite

Private source base `bac92b20830e5adde31c638a7dd95cb917da8721`.
This packet owns only WORKSTREAMS and this report. It changes no provider,
fixture, manifest, compiler, runtime, generated data, assertion or deadline.

## Observed failure and retained scope

The unchanged current-tree diagnostic completed 42 reference pytest cases and
failed both plain/sanitized NativePanel cases during PACKAGE processing with
`resource lifetime operations are reserved across native bindings`. Neither
failed case produced its generated C or native executable. The remaining 38
reference cases and all 82 selfhost cases were unrun; no fresh selfhost build
started. The separate generated-source failure for the LSP catalog also remains
failed, so this diagnostic cannot establish overall qualification.

Evidence directory:
`~/.cache/btrc/plan-consolidation-2026-10-07/ui2-macos-current-bac92b20-diagnostic-attempt-1`.
Result SHA-256 `c92ad62539458b6349a3e05c35a385a0c98456f3a7e07f1b69da26161e32a0fc`.
The independent failure audit records 377 pinned files, 4,658 source files,
11,577 workspace files, 102 logs and 51 closed process groups; source/tools
remained unchanged. Its exact hash is retained in the companion evidence receipt.
This packet reads that terminal proof; it runs no new compile or native test.

## Three distinct ownership contributors

1. `src/stdlib/GUI/btrc.toml:561-633` declares the SystemText CF resources as
   reference-counted, with CFRetain/CFRelease as managed lifetime operations.
   `MacOSSystemText.btrc` retains them in nullable managed fields and uses owned
   results plus borrowed SDK-call parameters. That is intentional ownership.
2. `GUI/btrc.toml:761-765` separately selects CFRelease as an ordinary function
   for `MacOSRunLoop`. `MacOSRunLoop.btrc:106,115,175,280-282` creates raw timer
   and source handles, invalidates them, directly releases them, then clears the
   corresponding POD fields. These are real production lifetime calls.
3. The generic `native_project` fixture in
   `src/tests/python/native_import_fixtures.py:63-73` also writes an ordinary
   CFRelease selection for its Foundation module. Both retained NativePanel
   project manifests have SHA-256
   `d566b5df7e689c7a5948b2de03491c59a2888b3e66c3e414036b533d032cf9d2`
   and contain that row. `test_native_gui_appkit.py:274-317` replaces Main's
   source and adds the Panel probe without removing Foundation's binding.
   This contributor is distinct from RunLoop. Removing only that fixture row
   would not repair the production RunLoop/SystemText ownership conflict.

The diagnostic does not print which ordinary declaration first triggered the
final reservation check. It proves the PACKAGE conflict; the three contributors
above are established by actual source and retained project manifests.

## Existing model and exact unsupported boundary

Reference importer `src/compiler/python/frontend/native_imports.py:911-913` and
selfhost `src/compiler/btrc/frontend/NativeImports.btrc:3290` reject any ordinary
imported declaration whose name is also a managed lifetime operation. The check
is global across selected bindings. This guard is not removed by the request.

The supported resource model creates managed class projections
(`native_imports.py:2440-2560`), consumes declared owned results, and admits typed
borrowed parameters for individual SDK calls (`:4205-4270`; selfhost counterpart
`:1919-1955`). It supplies no general raw-handle borrow accessor. Managed-resource
casts to or from unrelated values/pointers are explicitly rejected by
`analyzer/expressions.py:1123-1138` and
`analyzer/validation/Expressions.btrc:1322`. Callback projection rejects an
unmapped non-scalar argument (`native_imports.py:1824-1826`, selfhost
`NativeImports.btrc:735`). Mapping an owned callback argument is a different
ownership contract and cannot stand in for a borrowed timer identity.

RunLoop's current shape relies on all of the following:

- `MacOSRunLoopWakeState` is calloc'd POD. Workers use its source/loop handles
  under the native mutex; no worker looks up or retains/releases the UI registry.
- Source and timer ownership, registration, invalidation and final release are
  UI-thread operations. Timer callback identity is compared with the current
  raw timer before changing deadline state.
- The UI owner keeps POD storage alive through worker retirement. Source closure
  seals ingress before callback drain. Slot reuse waits for that drain; the
  OwnedClosure disposer requires closed state and a retired slot before free.
- `RunLoopLifetime.btrc` exercises 300 failed factory acquisitions, 300 closes
  from inside a delivered callback, and 100 actual worker/close races.
  `RunLoopDeadline`, `RunLoopAttachment`, and `RunLoopWake` preserve deadline,
  attachment and wake behavior. All original oracles remain required.

Declaring the source/timer as managed resources is therefore not a manifest-only
fix: the existing design also needs an expressible borrowed native view in its
POD state and timer callback, tied to the UI owner's lifetime and close barrier.
Nulling a raw field does not release it; storing an untracked pointer extracted
from a managed value would evade ownership. Changing CoreText back to manual
release, renaming CFRelease in a shim, or marking invalidate as the destructor
would respectively discard the ownership contract, bypass reservation, or leak
the original retained CF claim. None is proposed.

## Compiler-owned request

```text
REQUEST(CL-REQ-UI2-CF-BORROW): Express the existing UI-owned Core Foundation run-loop handle and scoped native borrow boundary alongside managed CoreText resources.
Repro: On exact bac92b20, run the unchanged NativePanel plain/sanitized selection with its real SDK imports; both actual reference cases fail PACKAGE reservation before C/native. Retained result and audit above are the baseline. Reduce to the managed CoreText binding plus ordinary RunLoop CFRelease binding and independently to the Foundation fixture contributor; do not rely on optimizer removal of unused declarations.
Expected / actual: Safe composed CF ownership must be representable without exposing a managed destructor as an ordinary callable. Current importers reserve CFRelease globally; current managed projections cannot provide the POD/borrowed callback boundary this provider uses.
Blocks: The remaining current-tree UI2 native matrix and full composed provider qualification.
Workaround in this branch: none. No release alias/shim, raw cast, ownership metadata omission, guard relaxation, skipped fixture, or copied lifetime owner.
```

The smallest bounded compiler-owned investigation is the paired native resource
projection/admission and analyzer boundary, not a GUI API or worker-pool redesign:

1. Define and prove a typed non-owning native handle projection whose lifetime
   is bounded by the retained UI owner/closed-ingress barrier, including the
   callback timer argument. No free pointer conversion or destruction authority
   may escape, and worker signal calls must not acquire/drop UI managed owners.
2. Reuse the existing ownership and callback stage owners in both frontends.
   If existing metadata cannot describe that lifetime, the integrator must name
   the minimal shared-schema/lowering change explicitly before implementation;
   this report does not grant a provider-side bypass or assert broad impossibility.
3. Add paired positive composition controls and negative direct-managed-release,
   pointer-escape, callback-after-invalidation and use-after-owner-close controls.
   Retain the present lifetime reservation/managed-cast rejection guarantees.
4. Only then adapt the existing RunLoop owner and its final manifest fragment,
   retain CoreText's ownership semantics, and remove irrelevant Foundation
   fixture imports only as a separately justified fixture cleanup. Re-run the
   original lifetime/deadline/wake tests plus NativePanel in both frontends and
   sanitizers, then the unchanged 164-case/240-native-scenario matrix. The stale
   generated gate remains an independent integrator prerequisite.

No statement here grants native success, physical input, external accessibility,
full UI2 acceptance or permission to edit compiler-owned files in a Codex packet.

## Resolution (Claude, integration batch 4, 2026-10-13)

Steps 1 to 3 are implemented in both compilers as **unmanaged handles**
(`src/language/package-manifest.md`, "Unmanaged handles"). The binding that
holds raw run-loop handles declares them:

```toml
[native.bindings.unmanaged-handles.CFRunLoopTimerRef]
release = "CFRelease"
[native.bindings.unmanaged-handles.CFRunLoopSourceRef]
release = "CFRelease"
```

The handle must be a selected typedef of a record pointer, and the release a
selected `void (const void*)` function. Selecting the release in that binding
no longer trips the reservation, but the operation stays reserved: the analyzer
admits only a direct call whose single argument's type resolves to a declared
handle's record pointer. A managed CoreText value, a cast, a second argument
or taking the function as a value is rejected, and a typedef that is a managed
resource elsewhere cannot be declared unmanaged. Every other ordinary selection
of a lifetime operation is still rejected in either binding order.
`src/tests/python/test_native_unmanaged_handles.py` holds the positive
composition (both binding orders, plain and sanitized) and the negative
controls, in both compilers.

Step 4 is Codex's: add the fragment above to the RunLoop binding in
`src/stdlib/GUI/btrc.toml` (a `fragment:` commit), then re-run the RunLoop
lifetime, deadline and wake tests, NativePanel and the UI2 matrix named above.
Callback-after-invalidation and use-after-owner-close stay the RunLoop owner's
own tests: the handle is raw data, so its lifetime is the owner's close barrier,
exactly as before.
