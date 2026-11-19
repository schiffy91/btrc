/* The conformance probe for the shim provider's platforms: real input, sent
 * to the window with a given title (ShimProbe.c). The provider's shim names
 * its windows for the probe (GUI/Shim/Shim.h, "automation"). */
#include "../ConformanceProbe.h"
#include "ShimProbe.h"

unsigned int btrcShimWindowNamed(const char *title);

int conformanceProbeMove(const char *title, double x, double y) {
    unsigned int window = btrcShimWindowNamed(title);
    return window ? shimProbeMove(window, title, x, y) : 0;
}

int conformanceProbePress(const char *title, double x, double y) {
    unsigned int window = btrcShimWindowNamed(title);
    return window ? shimProbeButton(window, title, x, y, 1) : 0;
}

int conformanceProbeRelease(const char *title, double x, double y) {
    unsigned int window = btrcShimWindowNamed(title);
    return window ? shimProbeButton(window, title, x, y, 0) : 0;
}

int conformanceProbeWheel(const char *title, double x, double y, double deltaX, double deltaY) {
    unsigned int window = btrcShimWindowNamed(title);
    return window ? shimProbeWheel(window, title, x, y, deltaX, deltaY) : 0;
}

int conformanceProbeKey(const char *title, int key) {
    unsigned int window = btrcShimWindowNamed(title);
    if (!window || key < CONFORMANCE_KEY_RETURN || key > CONFORMANCE_KEY_SELECT_ALL) { return 0; }
    return shimProbeKey(window, title, key);
}

int conformanceProbeText(const char *title, const char *text) {
    unsigned int window = btrcShimWindowNamed(title);
    return window ? shimProbeText(window, title, text) : 0;
}

int conformanceProbeClose(const char *title) {
    unsigned int window = btrcShimWindowNamed(title);
    return window ? shimProbeClose(window, title) : 0;
}

/* The provider's turn runs the toolkit's own loop itself. */
void conformanceProbeService(void) {}

int conformanceProbeWindowSizing(void) {
    if (shimProbeKeepsScreen()) { return CONFORMANCE_WINDOW_SIZING_SCREEN_ALWAYS; }
    return shimProbeFillsScreen() ? CONFORMANCE_WINDOW_SIZING_SCREEN_AT_FIRST : CONFORMANCE_WINDOW_SIZING_ASKED;
}
