/* An independent input device on the private labwc display. */
#include "../conformance/probes/shim/RealInput.h"
#include "../conformance/probes/ConformanceProbe.h"
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>

static void typed(void) { }

int main(int argc, char **argv) {
    assert(getenv("BTRC_UI_PRIVATE_SESSION") && !strcmp(getenv("BTRC_UI_PRIVATE_SESSION"), "1"));
    const RealInput *input = realInputWayland();
    const char *title = "btrc input and pixels";
    assert(input);
    if (argc == 3 && !strcmp(argv[1], "close-title")) { return input->close(argv[2]) ? 0 : 1; }
    if (argc == 2 && !strcmp(argv[1], "close")) { return input->close(title) ? 0 : 1; }
    if (argc == 2 && !strcmp(argv[1], "keyboard")) {
        int command;
        while ((command = getchar()) != EOF) {
            assert(command == 'k' && input->activate(title) && input->key(CONFORMANCE_KEY_RETURN));
            puts("sent");
            fflush(stdout);
        }
        return 0;
    }
    if (argc == 2 && !strcmp(argv[1], "repeat")) { return input->activate(title) && realInputWaylandHoldReturn() ? 0 : 1; }
    if (argc == 2 && !strcmp(argv[1], "mouse")) {
        char command;
        int x, y;
        while (scanf(" %c %d %d", &command, &x, &y) == 3) {
            assert(input->move(x, y));
            if (command == 'd') { assert(input->button(true)); }
            else if (command == 'u') { assert(input->button(false)); }
            else if (command == 'w') { assert(input->wheel(0, 1)); }
            else if (command == 'v') { assert(input->wheel(0, -1)); }
            else if (command == 'j') { assert(input->key(CONFORMANCE_KEY_DOWN)); }
            else if (command == 'e') { assert(input->key(CONFORMANCE_KEY_ESCAPE)); }
            else if (command == 'l') { assert(input->key(CONFORMANCE_KEY_LEFT)); }
            else if (command == 'r') { assert(input->key(CONFORMANCE_KEY_RIGHT)); }
            else { assert(command == 'm'); }
            puts("sent");
            fflush(stdout);
        }
        return 0;
    }
    if (argc == 2 && !strcmp(argv[1], "motion")) {
        int x, y;
        while (scanf("%d %d", &x, &y) == 2) {
            if (!input->move(x, y)) { return 1; }
            puts("moved");
            fflush(stdout);
        }
        return 0;
    }
    assert(argc == 3 && input->activate(title));
    assert(input->move(atoi(argv[1]), atoi(argv[2])) && input->button(true) && input->button(false));
    assert(input->wheel(0, 1) && input->key(CONFORMANCE_KEY_RETURN));
    assert(input->key(CONFORMANCE_KEY_SELECT_ALL) && input->text("Aé🟢", typed));
    return 0;
}
