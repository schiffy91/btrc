# CX-UIA-21: approved UI2 interface implementation

Owned paths are the interface, facade, completion-hook, portable fixture and
catalog paths in `docs/design/ui-contracts/ui2-approved.md` (Landing), as listed
in the draft PR. Provider implementations remain in the stacked CX-UIA-22/23
packets and land atomically with this interface.

Base: `87dd60d7`. Implement the approved record; do not restart its design review.
No compiler prerequisite blocks the approved interface. The interface by itself
does not qualify the existing platform providers.

Acceptance: exact approved source surface, portable E-case fixtures, completion
hook contract/regression, formatting and catalog validation. Combined macOS/Linux
provider and repository acceptance remains mandatory before main landing.
No implementation or test pass is claimed by this claim commit.
