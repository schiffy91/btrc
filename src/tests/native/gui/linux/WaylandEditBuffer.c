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
    assert(btrcEditReset(&edit, "Xéfoo日Y"));
    btrcEditSelect(&edit, 6, 3);
    BtrcEditContext context;
    assert(btrcEditContext(&edit, &context) && !strcmp(context.text, edit.text) && context.anchor == 6 && context.cursor == 3);
    assert(btrcEditDeleteAround(&edit, 1, 3) && !strcmp(edit.text, "Xéfoo日Y"));
    assert(btrcEditDeleteAround(&edit, 2, 3) && !strcmp(edit.text, "XfooY") && edit.anchor == 4 && edit.caret == 1);
    assert(btrcEditUndo(&edit, false) && edit.anchor == 6 && edit.caret == 3);
    assert(!btrcEditReplaceRange(&edit, 2, 3, "bad") && !strcmp(edit.text, "Xéfoo日Y"));
    assert(btrcEditReplaceRange(&edit, 0, 1, "hello") && !strcmp(edit.text, "helloéfoo日Y"));
    assert(btrcEditUndo(&edit, false) && edit.anchor == 6 && edit.caret == 3);
    char large[6001];
    for (int i = 0; i < 2000; ++i) { memcpy(large + i * 3, "日", 3); }
    large[6000] = 0;
    assert(btrcEditReset(&edit, large));
    btrcEditSelect(&edit, 1500, 4500);
    assert(btrcEditContext(&edit, &context) && strlen(context.text) <= 4000);
    assert(context.cursor - context.anchor == 3000 && (context.anchor % 3) == 0 && (strlen(context.text) % 3) == 0);
    btrcEditSelect(&edit, 0, 6000);
    assert(!btrcEditContext(&edit, &context));
    btrcEditDestroy(&edit);
    return 0;
}
