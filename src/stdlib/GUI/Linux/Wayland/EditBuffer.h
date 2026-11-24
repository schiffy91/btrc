#ifndef BTRC_WAYLAND_EDIT_BUFFER_H
#define BTRC_WAYLAND_EDIT_BUFFER_H
#include "../../Text/Grapheme.h"
#include <stdbool.h>

typedef struct BtrcEditHistory BtrcEditHistory;
typedef struct {
    char *text;
    BtrcGraphemes clusters;
    size_t anchor, caret;
    BtrcEditHistory *undo, *redo;
} BtrcEditBuffer;

/* UTF-8 byte offsets always name an extended grapheme boundary.
 * Zero initialization is valid. Replacement and undo are transactional. */
void btrcEditDestroy(BtrcEditBuffer *edit);
bool btrcEditReset(BtrcEditBuffer *edit, const char *text);
void btrcEditSelect(BtrcEditBuffer *edit, size_t anchor, size_t caret);
void btrcEditMove(BtrcEditBuffer *edit, bool forward, bool extend);
bool btrcEditReplace(BtrcEditBuffer *edit, const char *text);
bool btrcEditDelete(BtrcEditBuffer *edit, bool forward);
bool btrcEditUndo(BtrcEditBuffer *edit, bool redo);
char *btrcEditSelection(const BtrcEditBuffer *edit);
char *btrcEditDraft(const BtrcEditBuffer *edit, const char *preedit);
#endif
