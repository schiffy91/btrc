/* The shell fixture's probe for Linux: real input through the display server,
 * by way of the conformance suite's probe for the GTK provider
 * (../../../conformance/probes/shim/ShimProbe.c), and the provider shim's
 * automation hooks (GUI/Shim/Shim.h) for what it observes. */
#include "ShellProbe.h"
#include "../../../conformance/probes/ConformanceProbe.h"
#include "../../../conformance/probes/shim/ShimProbe.h"
#include <assert.h>
#include <stdio.h>

#define SHELL_TITLE "BTRC native shell"

unsigned int btrcShimWindowNamed(const char *title);
int btrcShimAutomationWindows(void);
int btrcShimAutomationTextFocused(unsigned int window);

static unsigned int window(void) {
    unsigned int id = btrcShimWindowNamed(SHELL_TITLE);
    assert(id != 0);
    return id;
}

void shellProbeClick(double x, double y) {
    unsigned int id = window();
    int pressed = shimProbeButton(id, SHELL_TITLE, x, y, 1);
    int released = shimProbeButton(id, SHELL_TITLE, x, y, 0);
    assert(pressed && released);
    (void)pressed;
    (void)released;
}

static void key(int which) {
    int sent = shimProbeKey(window(), SHELL_TITLE, which);
    assert(sent);
    (void)sent;
}

void shellProbeTab(void) { key(CONFORMANCE_KEY_TAB); }
void shellProbeEnter(void) { key(CONFORMANCE_KEY_RETURN); }

void shellProbeText(void) {
    int sent = shimProbeText(window(), SHELL_TITLE, "draft");
    assert(sent);
    (void)sent;
}

void shellProbeScroll(void) {
    int sent = shimProbeWheel(window(), SHELL_TITLE, 100.0, 120.0, 0.0, -3.0);
    assert(sent);
    (void)sent;
}

void shellProbeClose(void) {
    int sent = shimProbeClose(window(), SHELL_TITLE);
    assert(sent);
    (void)sent;
}

int shellProbeFocus(void) { return btrcShimAutomationTextFocused(window()) ? 1 : 0; }
int shellProbeNativeCount(void) { return btrcShimAutomationWindows(); }
int shellProbePrivateCount(void) { return 0; }
void shellProbeDrain(void) {}
void shellProbeObserve(void) { assert(shellProbeNativeCount() == 1); }

void shellProbeDump(void) {
    printf("{\"probe\":\"linux-gtk\",\"accessibility\":\"not observed\",\"native_windows\":%d,\"focused_editor\":%d}\n",
           shellProbeNativeCount(), shellProbeFocus());
}
