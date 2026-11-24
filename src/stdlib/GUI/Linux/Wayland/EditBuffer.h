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
bool btrcEditReplaceRange(BtrcEditBuffer *edit, size_t begin, size_t end, const char *text);
bool btrcEditDelete(BtrcEditBuffer *edit, bool forward);
bool btrcEditUndo(BtrcEditBuffer *edit, bool redo);
char *btrcEditSelection(const BtrcEditBuffer *edit);
/* Wayland text-input-v3 publishes at most 4000 bytes around a selection.
 * Deletion lengths exclude the selected bytes, which remain selected. */
typedef struct BtrcEditContext {
    char text[4001];
    int cursor, anchor;
} BtrcEditContext;
bool btrcEditContext(const BtrcEditBuffer *edit, BtrcEditContext *context);
bool btrcEditDeleteAround(BtrcEditBuffer *edit, size_t before, size_t after);
char *btrcEditDraft(const BtrcEditBuffer *edit, const char *preedit);
#endif
