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
bytes/modes. Python AST parsing passed. No local test, compiler, native
simulator, runtime acquisition or hosted run has executed for this packet yet.
The next focused qualification uses the original28 local unittest methods as
an authentic baseline, then the same28 on the current-main port and the
relevant unchanged current workflow contracts. Those local process/transport
checks remain explicitly `not-ios`; the original50 native matrix is a separate
allocation after runtime admission. Full integration gates remain root-owned.

The ordinary parked checkout/index, acquisition packet and root-owned PLAN
remain unchanged. No publication or dispatch is included in this preparation.
