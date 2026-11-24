#define _POSIX_C_SOURCE 200809L
#include "Platform.h"
#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
    assert((argc == 2 || argc == 3) && btrcShimInit());
    BtrcShimWindow *window = btrcShimWindowCreate(argc == 3 ? argv[2] : "btrc input and pixels", 160, 100);
    assert(window && btrcShimWindowShow(window));
    setbuf(stdout, NULL);
    assert(fcntl(STDIN_FILENO, F_SETFL, O_NONBLOCK) == 0);
    bool keyed = false;
    unsigned long long end = btrcShimTicksNS() + 20000000000ULL;
    while (btrcShimTicksNS() < end) {
        BtrcShimEvent event;
        if (btrcShimWaitEvent(&event, 10)) {
            if (event.type == BTRC_SHIM_EVENT_KEY_DOWN) { keyed = true; }
            if (event.type == BTRC_SHIM_EVENT_WINDOW_SHOWN) { puts("shown"); }
            if (event.type == BTRC_SHIM_EVENT_QUIT) { fprintf(stderr, "%s\n", btrcShimError()); break; }
        }
        char command;
        if (read(STDIN_FILENO, &command, 1) != 1) { continue; }
        if (command == 'q') { btrcShimWindowDestroy(window); return 0; }
        if (command == 'k') {
            puts(keyed ? "key" : "waiting");
            keyed = false;
        } else if (command == 'g') {
            assert(btrcWaylandWindowAttachGPU(window->native, 0, 0));
            puts("attached");
        } else if (command == 'r') {
            if (!btrcShimHasClipboardText()) { puts("absent"); continue; }
            char *text = btrcShimGetClipboardText();
            if (!text) { puts("unavailable"); continue; }
            FILE *file = fopen(argv[1], "wb");
            assert(file && fwrite(text, 1, strlen(text), file) == strlen(text) && !fclose(file));
            btrcShimFree(text);
            puts("read");
        } else if (command == 'w') {
            FILE *file = fopen(argv[1], "rb");
            assert(file && !fseek(file, 0, SEEK_END));
            long length = ftell(file);
            assert(length >= 0 && !fseek(file, 0, SEEK_SET));
            char *text = malloc((size_t)length + 1);
            assert(text && fread(text, 1, length, file) == (size_t)length && !fclose(file));
            text[length] = 0;
            assert(btrcShimSetClipboardText(text));
            free(text);
            puts("written");
        } else { assert(0); }
    }
    return 1;
}
