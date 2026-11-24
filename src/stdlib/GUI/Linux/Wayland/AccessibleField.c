#include "Accessibility.h"
#include "TextField.h"
#include "EditBuffer.h"

BtrcShimControl *btrcWaylandAccessibleControl(unsigned window, unsigned id, bool vertical, BtrcShimWindow **owner);

void btrcWaylandDescribeField(BtrcWaylandAccessible *out, const BtrcWaylandTextField *field) {
    const BtrcEditBuffer *edit = btrcWaylandFieldBuffer(field);
    out->name = btrcWaylandFieldPlaceholder(field);
    out->text = edit->text;
    out->anchor = (int)edit->anchor;
    out->caret = (int)edit->caret;
}

static BtrcWaylandTextField *lookup(unsigned window, unsigned id, BtrcShimWindow **owner) {
    return btrcWaylandFieldState(btrcWaylandAccessibleControl(window, id, false, owner));
}

bool btrcWaylandAccessibleSelect(unsigned window, unsigned id, int anchor, int caret) {
    BtrcShimWindow *owner = NULL;
    if (anchor < 0 || caret < 0) { return false; }
    BtrcWaylandTextField *field = lookup(window, id, &owner);
    return field && btrcWaylandFieldSelectRange(field, owner, id, (size_t)anchor, (size_t)caret);
}

bool btrcWaylandAccessibleReplace(unsigned window, unsigned id, int start, int end, const char *value) {
    BtrcShimWindow *owner = NULL;
    if (start < 0 || start > end || !value) { return false; }
    BtrcWaylandTextField *field = lookup(window, id, &owner);
    return field && btrcWaylandFieldReplaceRange(field, owner, id, (size_t)start, (size_t)end, value);
}
