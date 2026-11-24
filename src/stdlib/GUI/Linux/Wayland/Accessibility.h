#ifndef BTRC_WAYLAND_ACCESSIBILITY_H
#define BTRC_WAYLAND_ACCESSIBILITY_H
#include <stdbool.h>
#include <stdint.h>

typedef struct BtrcWaylandAccessible {
    unsigned window, control, role;
    unsigned state;
    const char *name, *description, *text;
    int anchor, caret;
    int x, y, width, height;
} BtrcWaylandAccessible;

/* UI thread only. References remain valid until the next application event. */
bool btrcWaylandAccessibleChild(unsigned window, int index, BtrcWaylandAccessible *out);
bool btrcWaylandAccessibleAction(unsigned window, unsigned control, bool focusOnly);
bool btrcWaylandAccessibleSelect(unsigned window, unsigned id, int anchor, int caret);
bool btrcWaylandAccessibleReplace(unsigned window, unsigned id, int start, int end, const char *value);
void btrcWaylandAccessibilityChanged(void);
unsigned long long btrcWaylandAccessibilityRevision(void);
void btrcWaylandAccessibilityInstall(int (*service)(void));
#endif
