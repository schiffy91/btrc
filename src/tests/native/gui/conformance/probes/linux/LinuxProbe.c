/* The conformance probe for Linux: real input, sent through the display
 * server to the window with a given title (GtkProbe.c). The provider's shim
 * names its windows for the probe (GUI/Linux/GtkShim.h, "automation"). */
#include "../ConformanceProbe.h"
#include "GtkProbe.h"

unsigned int btrcGtkWindowNamed(const char *title);

int conformanceProbeMove(const char *title, double x, double y) {
    unsigned int window = btrcGtkWindowNamed(title);
    return window ? gtkProbeMove(window, title, x, y) : 0;
}

int conformanceProbePress(const char *title, double x, double y) {
    unsigned int window = btrcGtkWindowNamed(title);
    return window ? gtkProbeButton(window, title, x, y, 1) : 0;
}

int conformanceProbeRelease(const char *title, double x, double y) {
    unsigned int window = btrcGtkWindowNamed(title);
    return window ? gtkProbeButton(window, title, x, y, 0) : 0;
}

int conformanceProbeWheel(const char *title, double x, double y, double deltaX, double deltaY) {
    unsigned int window = btrcGtkWindowNamed(title);
    return window ? gtkProbeWheel(window, title, x, y, deltaX, deltaY) : 0;
}

int conformanceProbeKey(const char *title, int key) {
    unsigned int window = btrcGtkWindowNamed(title);
    if (!window || key < CONFORMANCE_KEY_RETURN || key > CONFORMANCE_KEY_SELECT_ALL) { return 0; }
    return gtkProbeKey(window, title, key);
}

int conformanceProbeText(const char *title, const char *text) {
    unsigned int window = btrcGtkWindowNamed(title);
    return window ? gtkProbeText(window, title, text) : 0;
}

int conformanceProbeClose(const char *title) {
    unsigned int window = btrcGtkWindowNamed(title);
    return window ? gtkProbeClose(window, title) : 0;
}

/* The provider's turn iterates GLib's main context itself. */
void conformanceProbeService(void) {}
