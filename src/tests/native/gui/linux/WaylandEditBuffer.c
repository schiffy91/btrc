#include "../../../../stdlib/GUI/Linux/Wayland/EditBuffer.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>

int main(void) {
    BtrcEditBuffer edit = {0};
    const char *family = "👩‍👩‍👧‍👦";
    const char *mixed = "Aé👩‍👩‍👧‍👦Z";
    assert(btrcEditReset(&edit, mixed));
    assert(edit.clusters.count == 4);
    btrcEditMove(&edit, false, false);
    btrcEditMove(&edit, false, true);
    char *selection = btrcEditSelection(&edit);
    assert(selection && !strcmp(selection, family));
    free(selection);
    char *draft = btrcEditDraft(&edit, "文");
    assert(draft && !strcmp(draft, "Aé文Z") && !strcmp(edit.text, mixed));
    free(draft);
    assert(btrcEditReplace(&edit, "文") && !strcmp(edit.text, "Aé文Z"));
    assert(btrcEditUndo(&edit, false) && !strcmp(edit.text, mixed));
    assert(btrcEditUndo(&edit, true) && !strcmp(edit.text, "Aé文Z"));
    assert(btrcEditDelete(&edit, false) && !strcmp(edit.text, "AéZ"));
    assert(btrcEditDelete(&edit, false) && !strcmp(edit.text, "AZ"));
    assert(btrcEditDelete(&edit, true) && !strcmp(edit.text, "A"));
    assert(!btrcEditReplace(&edit, "\xff") && !strcmp(edit.text, "A"));
    assert(!btrcEditReset(&edit, "\xff") && !strcmp(edit.text, "A"));
    assert(btrcEditReset(&edit, "new") && !btrcEditUndo(&edit, false));
    btrcEditSelect(&edit, 0, SIZE_MAX);
    assert(btrcEditReplace(&edit, "") && !strcmp(edit.text, ""));
    assert(btrcEditReset(&edit, "e"));
    assert(btrcEditReplace(&edit, "́") && edit.clusters.count == 1 && edit.caret == 3);
    for (int i = 0; i < 80; ++i) { assert(btrcEditReplace(&edit, "X")); }
    int count = 0;
    while (btrcEditUndo(&edit, false)) { ++count; }
    assert(count == 64);
    assert(btrcEditReplace(&edit, "z") && !btrcEditUndo(&edit, true));
    btrcEditDestroy(&edit);
    return 0;
}
