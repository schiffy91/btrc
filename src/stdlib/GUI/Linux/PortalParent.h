#ifndef BTRC_GUI_LINUX_PORTAL_PARENT_H
#define BTRC_GUI_LINUX_PORTAL_PARENT_H
#include "../Shim/Shim.h"

/* The desktop must be able to import the parent until its dialog finishes. */
typedef struct BtrcDialogParent BtrcDialogParent;
BtrcDialogParent *btrcDialogParentOpen(BtrcShimWindow *parent);
const char *btrcDialogParentIdentifier(BtrcDialogParent *parent);
void btrcDialogParentRelease(BtrcDialogParent *parent);
#endif
