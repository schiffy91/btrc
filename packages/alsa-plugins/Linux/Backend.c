#include <BtrcLinuxPcmPlugin.h>
#include "Available.h"
#include "AlsaPcm.h"

const BtrcLinuxPcmPluginV1 *btrcLinuxPcmPluginV1(void) {
    static const BtrcLinuxPcmPluginV1 provider = {
        .hints = btrcLegacyHints,
        .hintCount = btrcLegacyHintCount,
        .hint = btrcLegacyHint,
        .hintsClose = btrcLegacyHintsClose,
        .openPcm = btrcLegacyOpen,
        .closePcm = btrcLegacyClose,
        .probe = btrcLegacyProbe,
        .configure = btrcLegacyConfigure,
        .wait = btrcLegacyWait,
        .prepare = btrcLegacyPrepare,
        .start = btrcLegacyStart,
        .drop = btrcLegacyDrop,
        .recover = btrcLegacyRecover,
        .startIfPrepared = btrcLegacyStartIfPrepared,
        .needsDrop = btrcLegacyNeedsDrop,
        .transfer = btrcLegacyTransfer,
    };
    return &provider;
}

int btrcAlsaPluginAvailable(void) {
    void *library = btrcLegacyLibrary();
    if (!library) { return 0; }
    dlclose(library);
    return 1;
}
