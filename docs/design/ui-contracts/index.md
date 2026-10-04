# Portable UI contract drafts

These documents are proposals under PLAN.md D27, not approved APIs or evidence
that providers implement them. Claude owns approval and integration. The UI2
drafts are reviewed together in `CL-UIA-13` against the real UI1 shells;
`CX-UIA-21` then writes the approved interface diff. macOS and Linux providers
land atomically with that diff through `CL-UIA-14`.

| Draft | Packet | Review boundary |
| --- | --- | --- |
| [Control events](ui2-control-events.md) | CX-UIA-18 | Text, keyed selection, range interaction and scrolling; E01–E03, E33–E34 |
| `ui2-executor.md` (sibling draft) | CX-UIA-19 | Worker publication, bounded queues, fair dispatch and the host-owned loop; E04, E24, E30, E40 |
| `ui2-lifecycle.md` (sibling draft) | CX-UIA-20 | Close transactions, ordered mutation, interaction eligibility and final release; E29, E31, E35, E39, E42, E46 |

The siblings may arrive in separate PRs. Their operation spellings and shared
event rules must be reconciled before any portable interface changes. IView,
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
