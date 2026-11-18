/* The shell fixture's probe for Linux: real input through the display server,
 * by way of the conformance suite's probe for the GTK provider
 * (../../../conformance/probes/linux/GtkProbe.c), and the provider shim's
 * automation hooks (GUI/Linux/GtkShim.h) for what it observes. */
#include "ShellProbe.h"
#include "../../../conformance/probes/ConformanceProbe.h"
#include "../../../conformance/probes/linux/GtkProbe.h"
#include <assert.h>
#include <stdio.h>

#define SHELL_TITLE "BTRC native shell"

unsigned int btrcGtkWindowNamed(const char *title);
int btrcGtkAutomationWindows(void);
int btrcGtkAutomationTextFocused(unsigned int window);

static unsigned int window(void) {
    unsigned int id = btrcGtkWindowNamed(SHELL_TITLE);
    assert(id != 0);
    return id;
}

void shellProbeClick(double x, double y) {
    unsigned int id = window();
    int pressed = gtkProbeButton(id, SHELL_TITLE, x, y, 1);
    int released = gtkProbeButton(id, SHELL_TITLE, x, y, 0);
    assert(pressed && released);
    (void)pressed;
    (void)released;
}

static void key(int which) {
    int sent = gtkProbeKey(window(), SHELL_TITLE, which);
    assert(sent);
    (void)sent;
}

void shellProbeTab(void) { key(CONFORMANCE_KEY_TAB); }
void shellProbeEnter(void) { key(CONFORMANCE_KEY_RETURN); }

void shellProbeText(void) {
    int sent = gtkProbeText(window(), SHELL_TITLE, "draft");
    assert(sent);
    (void)sent;
}

void shellProbeScroll(void) {
    int sent = gtkProbeWheel(window(), SHELL_TITLE, 100.0, 120.0, 0.0, -3.0);
    assert(sent);
    (void)sent;
}

void shellProbeClose(void) {
    int sent = gtkProbeClose(window(), SHELL_TITLE);
    assert(sent);
    (void)sent;
}

int shellProbeFocus(void) { return btrcGtkAutomationTextFocused(window()) ? 1 : 0; }
int shellProbeNativeCount(void) { return btrcGtkAutomationWindows(); }
int shellProbePrivateCount(void) { return 0; }
void shellProbeDrain(void) {}
void shellProbeObserve(void) { assert(shellProbeNativeCount() == 1); }

void shellProbeDump(void) {
    printf("{\"probe\":\"linux-gtk\",\"accessibility\":\"not observed\",\"native_windows\":%d,\"focused_editor\":%d}\n",
           shellProbeNativeCount(), shellProbeFocus());
}
