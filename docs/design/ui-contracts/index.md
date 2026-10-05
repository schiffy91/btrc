# Portable UI contract drafts

These documents are proposals under PLAN.md D27, not approved APIs or evidence
that providers implement them. Claude owns approval and integration. The UI2
drafts are reviewed together in `CL-UIA-13` against the real UI1 shells;
`CX-UIA-21` then writes the approved interface diff. macOS and Linux providers
land atomically with that diff through `CL-UIA-14`.

| Draft | Packet | Review boundary |
| --- | --- | --- |
| [Control events](ui2-control-events.md) | CX-UIA-18 | Text, keyed selection, range interaction and scrolling; E01–E03, E33–E34 |
| [Executor](ui2-executor.md) | CX-UIA-19 | Worker publication, bounded queues, fair dispatch and the host-owned loop; E04, E24, E30, E40 |
| [Lifecycle](ui2-lifecycle.md) | CX-UIA-20 | Close transactions, ordered mutation, interaction eligibility and final release; E29, E31, E35, E39, E42, E46 |

The three drafts landed together in batch 20. `CL-UIA-13` reconciles their
operation spellings and shared event rules (two known conflicts: whether a
terminal result's capacity is reserved per interaction, and what text
eligibility loss cancels) before any portable interface changes.

The Stage 34 pre-drafts for UI4–UI9 live beside these in
[`../native-ui-contracts/`](../native-ui-contracts/), as their packets name it:
[UI4 controls](../native-ui-contracts/ui4-controls.md) (CX-UIB-01),
[UI5 layout](../native-ui-contracts/ui5-layout.md) and
[UI8 accessibility](../native-ui-contracts/ui8-accessibility.md) (CX-UIB-02),
[UI6 collections](../native-ui-contracts/ui6-collections.md) (CX-UIB-03),
[UI7 services](../native-ui-contracts/ui7-services.md) (CX-UIB-04),
[UI9 GPU and scheduling](../native-ui-contracts/ui9-gpu.md) and
[runtime probes](../native-ui-contracts/runtime-probes.md) (CX-UIB-05), with the
[collection data-model spike](../native-ui-contracts/spikes/collections-data-model.md) (CX-UIB-06);
`CL-UIB-02` reviews them. The per-platform native-shell notes for Win32, UIKit
(with iPadOS) and Android Views are in
[`../native-ui-shells/`](../native-ui-shells/) (CX-UIA-13), which `CL-UIA-12`
reviews. IView,
IWindow and App.btrc remain a single approved writer chain; these separate
Markdown drafts do not claim those files.

Five platform families participate: macOS, Linux, Windows, iOS (including
iPadOS) and Android, each through the reference and self-hosted frontends.
Windows, iOS and Android mappings remain provisional until their real shells
exist and `CL-UIA-22` re-checks UI2/UI3. iPad is an `ios` evidence row with
`provenance.device_class`, not a sixth provider or a new denominator.

The [native-UI acceptance backlog](../native-ui-parity.md) supplies the E-case
definitions. Proposed operation ids in a draft do not modify the frozen UI0
catalog, prove an E-case, or authorize a production interface edit. Approved
changes need the catalog amendments and release handling assigned to their
landing packet.

Read the current [Codex UI lanes](../../workstreams/codex-ui-lanes.md) and
[packet assignments](../../workstreams/codex.md) before implementation. Neither
a successful docs-tier CI run nor integration of a draft constitutes contract
approval.
