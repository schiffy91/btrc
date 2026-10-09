# Preserved iOS simulator host on current main

Packet: CX-HARMONIZE-IOS-HOST-PORT.

This packet ports the exact eleven owned paths from preserved local revision
`1844837b2ca9f9e4bcea9decc26a9eed51eba42d` (PR34 follow-up to `f49c5fe1`)
onto main `36b647f079ed7338e51b119a11046eb222dd4877`. The ten new
`tools/target_hosts/ios/` files have no counterpart on that base; the workflow
still matches the original port's merge base. The port changes no fixture,
executor behavior, timeout, compiler, runtime provider or native ABI.

The scope is a standalone simulator host for trusted, child-free handwritten
C11 fixtures. It is not compiler-generated-program, arbitrary descendant,
UIKit operation, physical-device or full corpus acceptance. The existing
limitations on direct exit/status transport, PID ownership and child containment
remain in the original README. No compiler rebuild is required to exercise the
original host matrix, because it does not invoke either BTRC frontend.

The original matrix remains twelve fixture cases through spawn and installed
app modes on both iPhone and iPad, plus one repeat in each app mode: 50 actual
executions. Exact bytes/status/signal/timeout, fresh-container markers and
owned-device cleanup remain mandatory. Launch stays bounded at 30 seconds;
ordinary fixture execution stays at 15 seconds and the forced-timeout fixture
at 0.5 seconds. Compiler/signing calls retain their 120-second bounds, simulator
bootstatus 300 seconds, and the hosted job 90 minutes.

The source retains Xcode 27A266a admission and the iOS 17.0 deployment target.
Runtime selection numerically chooses the oldest available installed iOS >=17.
D8 requires using iOS17 if Xcode27 can install it, otherwise the oldest
installable runtime. An installed-runtime inventory alone does not establish
installability. The held `5efb6a9d` component-acquisition packet is separate and
unchanged. Its eventual evidence cannot transfer installed state between
throwaway hosted machines; original-50 acceptance needs the admitted runtime
available on the actual host that executes those cases. Generic download,
capacity, transport or authentication failure is not incompatibility proof.

Historical evidence is retained without promoting it: original184 passed all
50 on the acceptance Mac under Xcode27A266a and iOS26.4/23E254a, with both owned
simulators shut down. The earlier f49 hosted run37579929097 completed zero of
50 after launch-identity/cleanup failures. Neither result qualifies this new
source combination or closes D8's runtime-selection evidence.

Preparation authenticated all eleven donor file hashes and preserved their
bytes and Git executable modes. Python AST parsing passed. Focused local gate
38412 then passed the exact original 28 process/transport methods on preserved
1844837b, the same 28 on candidate55daaf9b, and four unchanged current workflow
contracts. Actual collection, JUnit and the workflow skip ledger matched every
expected identity, with zero failures, errors or skips. The gate took 37.19s.

Evidence remains at `ios-host-port-55daaf9b-attempt-1` beneath the local
`plan-consolidation-2026-10-07` evidence root. Result SHA-256:
`c7213525cf4e8ed0fc002320ba229fab359ebf8dca37731b1b7c8e6ede973ac7`.
Independent audit SHA-256:
`c87cb379b508145b4e05b12275a13a85652977bc9b7222de92993049021308e5`.
The audit rehashed all 55 input/tool pins, both source archives, all 4,370
baseline and 4,518 candidate source entries and Git executable modes, all
26 command logs, and the exact test reports. All 13 owned process groups were
absent and their leaders reaped zero; final source and tools were unchanged.
Archive extraction explicitly restores canonical Git executable modes rather
than retaining archive-specific group-write permission bits; source bytes and
archive hashes were unchanged. This correction preceded all test execution.

These are local trusted C process/transport checks, explicitly `not-ios`.
No simulator was booted and no runtime was acquired. The original 50 native
simulator executions on the integrated source and D8 oldest-installable-runtime
admission remain outstanding, as do final root-owned integration gates.

The ordinary parked checkout/index, acquisition packet and root-owned PLAN
remain unchanged. No publication or dispatch is included in this preparation.
