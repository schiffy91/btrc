/* Adapt the shared desktop-portal picker to a native xdg-foreign export. */
#include "Platform.h"
#include "../PortalParent.h"

BtrcDialogParent *btrcDialogParentOpen(BtrcShimWindow *parent) {
    return parent ? (BtrcDialogParent *)btrcWaylandWindowExport(parent->native) : NULL;
}

const char *btrcDialogParentIdentifier(BtrcDialogParent *parent) {
    return btrcWaylandExportIdentifier((BtrcWaylandExport *)parent);
}

void btrcDialogParentRelease(BtrcDialogParent *parent) {
    btrcWaylandExportRelease((BtrcWaylandExport *)parent);
}
