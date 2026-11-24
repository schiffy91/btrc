#include "EditBuffer.h"
#include <stdlib.h>
#include <string.h>

struct BtrcEditHistory {
    char *text;
    BtrcGraphemes clusters;
    size_t anchor, caret;
    struct BtrcEditHistory *next;
};

static void clear(BtrcEditHistory **stack) {
    while (*stack) {
        BtrcEditHistory *entry = *stack;
        *stack = entry->next;
        free(entry->text);
        btrcGraphemeDestroy(&entry->clusters);
        free(entry);
    }
}

void btrcEditDestroy(BtrcEditBuffer *edit) {
    clear(&edit->undo);
    clear(&edit->redo);
    free(edit->text);
    btrcGraphemeDestroy(&edit->clusters);
    *edit = (BtrcEditBuffer){0};
}

static char *copy(const char *text, size_t length) {
    char *result = malloc(length + 1);
    if (result) { memcpy(result, text, length); result[length] = 0; }
    return result;
}

bool btrcEditReset(BtrcEditBuffer *edit, const char *text) {
    size_t length = strlen(text);
    BtrcGraphemes graphemes = {0};
    if (btrcGraphemeBoundaries(text, length, &graphemes) != BTRC_GRAPHEME_OK) { return false; }
    char *value = copy(text, length);
    if (!value) { btrcGraphemeDestroy(&graphemes); return false; }
    btrcEditDestroy(edit);
    *edit = (BtrcEditBuffer){.text=value, .clusters=graphemes, .caret=length, .anchor=length};
    return true;
}

void btrcEditSelect(BtrcEditBuffer *edit, size_t anchor, size_t caret) {
    edit->anchor = btrcGraphemeFloor(&edit->clusters, anchor);
    edit->caret = btrcGraphemeFloor(&edit->clusters, caret);
}

static size_t edge(const BtrcEditBuffer *edit, bool right) {
    return (edit->anchor > edit->caret) == right ? edit->anchor : edit->caret;
}

static size_t adjacent(const BtrcEditBuffer *edit, bool forward) {
    if (forward) { return btrcGraphemeCeil(&edit->clusters, edit->caret + 1); }
    return edit->caret ? btrcGraphemeFloor(&edit->clusters, edit->caret - 1) : 0;
}

void btrcEditMove(BtrcEditBuffer *edit, bool forward, bool extend) {
    if (!extend && edit->anchor != edit->caret) { edit->caret = edge(edit, forward); }
    else { edit->caret = adjacent(edit, forward); }
    if (!extend) { edit->anchor = edit->caret; }
}

char *btrcEditSelection(const BtrcEditBuffer *edit) {
    size_t begin = edge(edit, false), end = edge(edit, true);
    return copy(edit->text + begin, end - begin);
}

static char *replaceRange(const BtrcEditBuffer *edit, size_t begin, size_t end, const char *text) {
    size_t insert = strlen(text);
    size_t suffix = edit->clusters.byteOffsets[edit->clusters.count] - end;
    if (insert >= SIZE_MAX - begin - suffix) { return NULL; }
    char *value = malloc(begin + insert + suffix + 1);
    if (value) {
        memcpy(value, edit->text, begin);
        memcpy(value + begin, text, insert);
        memcpy(value + begin + insert, edit->text + end, suffix + 1);
    }
    return value;
}

char *btrcEditDraft(const BtrcEditBuffer *edit, const char *preedit) {
    return replaceRange(edit, edge(edit, false), edge(edit, true), preedit);
}

/* Retain the most recent native undo states within a memory budget. The
 * active text has independent ownership, including after undo or redo. */
static void trim(BtrcEditHistory **stack) {
    size_t bytes = 0;
    for (size_t i = 0; *stack; i++, stack = &(*stack)->next) {
        BtrcEditHistory *entry = *stack;
        bytes += sizeof(*entry) + (entry->clusters.count + 1) * sizeof(uint32_t)
            + 1 + entry->clusters.byteOffsets[entry->clusters.count];
        if (i >= 64 || bytes > 4 * 1024 * 1024) { clear(stack); return; }
    }
}

static bool apply(BtrcEditBuffer *edit, size_t begin, size_t end, const char *text) {
    if (begin == end && !*text) { return true; }
    char *value = replaceRange(edit, begin, end, text);
    if (!value) { return false; }
    BtrcGraphemes graphemes = {0};
    if (btrcGraphemeBoundaries(value, strlen(value), &graphemes) != BTRC_GRAPHEME_OK) { free(value); return false; }
    BtrcEditHistory *previous = malloc(sizeof *previous);
    if (!previous) { free(value); btrcGraphemeDestroy(&graphemes); return false; }
    *previous = (BtrcEditHistory){edit->text, edit->clusters, edit->anchor, edit->caret, edit->undo};
    edit->undo = previous;
    clear(&edit->redo);
    trim(&edit->undo);
    edit->text = value;
    edit->clusters = graphemes;
    edit->anchor = edit->caret = btrcGraphemeCeil(&graphemes, begin + strlen(text));
    return true;
}

bool btrcEditReplace(BtrcEditBuffer *edit, const char *text) {
    return apply(edit, edge(edit, false), edge(edit, true), text);
}

bool btrcEditDelete(BtrcEditBuffer *edit, bool forward) {
    size_t begin = edge(edit, false), end = edge(edit, true);
    if (begin == end) {
        if (forward) { end = adjacent(edit, true); } else { begin = adjacent(edit, false); }
    }
    return apply(edit, begin, end, "");
}

bool btrcEditUndo(BtrcEditBuffer *edit, bool redo) {
    BtrcEditHistory **source = redo ? &edit->redo : &edit->undo;
    BtrcEditHistory **target = redo ? &edit->undo : &edit->redo;
    BtrcEditHistory *entry = *source;
    if (!entry) { return false; }
    BtrcEditHistory current = {edit->text, edit->clusters, edit->anchor, edit->caret, *target};
    *source = entry->next;
    edit->text = entry->text;
    edit->clusters = entry->clusters;
    edit->anchor = entry->anchor;
    edit->caret = entry->caret;
    *entry = current;
    *target = entry;
    trim(target);
    return true;
}
