#ifndef BTRC_CONFORMANCE_PROBE_H
#define BTRC_CONFORMANCE_PROBE_H
/* Test-only input for the GUI conformance suite: what a person does to one
 * window, named by its title. The suite itself uses nothing but the public
 * GUI facade; this is the one thing it cannot do through it.
 *
 * Coordinates are content-local logical points from the top left. Input is
 * queued, never delivered inline: the application's next turns deliver it.
 * Every function returns 1 when the input was queued and 0 when no open
 * window has that title or the platform refused the input. */
enum ConformanceKey {
    CONFORMANCE_KEY_RETURN = 1,
    CONFORMANCE_KEY_ESCAPE = 2,
    CONFORMANCE_KEY_TAB = 3,
    CONFORMANCE_KEY_LEFT = 4,
    CONFORMANCE_KEY_RIGHT = 5,
    CONFORMANCE_KEY_UP = 6,
    CONFORMANCE_KEY_DOWN = 7,
    CONFORMANCE_KEY_BACKSPACE = 8,
    CONFORMANCE_KEY_SELECT_ALL = 9
};
int conformanceProbeMove(const char *title, double x, double y);
int conformanceProbePress(const char *title, double x, double y);
int conformanceProbeRelease(const char *title, double x, double y);
int conformanceProbeWheel(const char *title, double x, double y, double deltaX, double deltaY);
/* One press and release of a key from the enumeration above. */
int conformanceProbeKey(const char *title, int key);
/* Committed text for the focused control, as an input method delivers it. */
int conformanceProbeText(const char *title, const char *text);
/* The window manager's close request, not IWindow.close. */
int conformanceProbeClose(const char *title);
/* The host's own native loop, one bounded step that never waits. The suite
 * takes it before each turn it gives the application. A platform whose
 * application drains its own input in its turn needs nothing here. */
void conformanceProbeService(void);
#endif
