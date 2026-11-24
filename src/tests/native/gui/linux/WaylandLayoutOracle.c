/* Compare the native client's physical key decoding to the host's XKB implementation. */
#define _POSIX_C_SOURCE 200809L
#include "Keymap.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <xkbcommon/xkbcommon.h>

int main(int argc, char **argv) {
    assert(argc == 4);
    const char *layout = argv[1];
    bool allKeys = strcmp(argv[2], "keypad") != 0;
    /* Early XKB releases used historical case rules for legacy symbols, e.g.
     * Greek final sigma. Compare Caps Lock against the Unicode-aware oracle. */
    bool oldCase = xkb_keysym_to_upper(XKB_KEY_Greek_finalsmallsigma) == XKB_KEY_Greek_finalsmallsigma;
    struct xkb_context *context = xkb_context_new(XKB_CONTEXT_NO_FLAGS);
    struct xkb_rule_names names = {.model = "pc105", .layout = layout};
    struct xkb_keymap *map = xkb_keymap_new_from_names(context, &names, XKB_KEYMAP_COMPILE_NO_FLAGS);
    assert(map);
    char *source = xkb_keymap_get_as_string(map, XKB_KEYMAP_FORMAT_TEXT_V1);
    assert(source);
    if (!strcmp(argv[2], "relocate")) {
        char *num = strstr(source, "modifier_map Mod2 { <NMLK>");
        char *levelFive = strstr(source, "modifier_map Mod3 { <LVL5>");
        assert(num && levelFive);
        num[strlen("modifier_map Mod")] = '3';
        levelFive[strlen("modifier_map Mod")] = '2';
        xkb_keymap_unref(map);
        map = xkb_keymap_new_from_string(context, source, XKB_KEYMAP_FORMAT_TEXT_V1, XKB_KEYMAP_COMPILE_NO_FLAGS);
        assert(map);
    }
    FILE *file = fopen(argv[3], "w+b");
    size_t bytes = strlen(source) + 1;
    assert(file && fwrite(source, 1, bytes, file) == bytes && !fflush(file));
    BtrcWaylandKeymap *native = btrcWaylandKeymapRead(fileno(file), bytes);
    assert(native && !fclose(file));
    free(source);
    struct xkb_state *state = xkb_state_new(map);
    assert(state);
    unsigned cases = 0;
    for (unsigned mods = 0; mods < 256; ++mods) {
        /* Control, Alt and Super carry application shortcuts. */
        if (mods & (4u | 8u | 64u)) { continue; }
        if ((mods & 2u) && oldCase && !strcmp(argv[2], "unicode")) { continue; }
        xkb_state_update_mask(state, mods & ~2u, 0, mods & 2u, 0, 0, 0);
        for (xkb_keycode_t key = xkb_keymap_min_keycode(map); key <= xkb_keymap_max_keycode(map); ++key) {
            const char *name = xkb_keymap_key_get_name(map, key);
            if (!name || (!allKeys && strncmp(name, "KP", 2))) { continue; }
            char expected[64] = "";
            int len = xkb_state_key_get_utf8(state, key, expected, sizeof(expected));
            if (len < 1 || (len == 1 && ((unsigned char)*expected < ' ' || *expected == 127))) { expected[0] = 0; }
            BtrcWaylandKey actual = btrcWaylandKey(native, key - 8, mods, 0);
            if (strcmp(actual.text, expected)) {
                fprintf(stderr, "%s %s mods=%u expected [%s] got [%s]\n", layout, name, mods, expected, actual.text);
                return 1;
            }
            ++cases;
        }
    }
    assert(cases > 300);
    printf("%u physical key and modifier combinations matched\n", cases);
    xkb_state_unref(state);
    xkb_keymap_unref(map);
    xkb_context_unref(context);
    btrcWaylandKeymapFree(native);
    return 0;
}
