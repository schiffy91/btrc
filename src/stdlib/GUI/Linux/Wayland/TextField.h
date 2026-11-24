#ifndef BTRC_WAYLAND_TEXT_FIELD_H
#define BTRC_WAYLAND_TEXT_FIELD_H
#include "ButtonHost.h"
#include "EditBuffer.h"
typedef struct BtrcWaylandTextField BtrcWaylandTextField;
BtrcShimControl *btrcWaylandAdoptTextField(unsigned id, BtrcWaylandTextField *field);
void btrcWaylandFieldModelChanged(BtrcShimControl *control);
BtrcWaylandTextField *btrcWaylandFieldState(BtrcShimControl *control);
void btrcWaylandFieldDestroy(BtrcWaylandTextField *field);
void btrcWaylandFieldSetFont(BtrcWaylandTextField *field, double size);
int btrcWaylandFieldMeasure(BtrcWaylandTextField *field, bool horizontal);
void btrcWaylandFieldPaint(BtrcWaylandTextField *field, const BtrcWaylandControlCanvas *canvas);
struct BtrcEditContext;
bool btrcWaylandFieldContext(BtrcWaylandTextField *field, struct BtrcEditContext *context);
bool btrcWaylandFieldDeleteAround(BtrcWaylandTextField *field, BtrcShimWindow *window,
    unsigned id, unsigned before, unsigned after);
const BtrcEditBuffer *btrcWaylandFieldBuffer(const BtrcWaylandTextField *field);
const char *btrcWaylandFieldPlaceholder(const BtrcWaylandTextField *field);
bool btrcWaylandFieldSelectRange(BtrcWaylandTextField *field, BtrcShimWindow *window,
    unsigned id, size_t anchorByte, size_t caretByte);
bool btrcWaylandFieldReplaceRange(BtrcWaylandTextField *field, BtrcShimWindow *window,
    unsigned id, size_t begin, size_t end, const char *text);
void btrcWaylandFieldPoint(BtrcWaylandTextField *field, double x, bool extend);
bool btrcWaylandFieldEvent(BtrcWaylandTextField *field, BtrcShimWindow *window,
    unsigned id, const BtrcShimEvent *input, bool *handled);
#endif
