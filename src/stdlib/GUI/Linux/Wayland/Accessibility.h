#ifndef BTRC_WAYLAND_ACCESSIBILITY_H
#define BTRC_WAYLAND_ACCESSIBILITY_H
#include <stdbool.h>
#include <stdint.h>

typedef struct BtrcWaylandAccessible {
    unsigned window, control, role;
    unsigned state;
    const char *name, *description;
    int x, y, width, height;
} BtrcWaylandAccessible;

/* UI thread only. References remain valid until the next application event. */
bool btrcWaylandAccessibleChild(unsigned window, int index, BtrcWaylandAccessible *out);
bool btrcWaylandAccessibleAction(unsigned window, unsigned control, bool focusOnly);
void btrcWaylandAccessibilityChanged(void);
unsigned long long btrcWaylandAccessibilityRevision(void);
void btrcWaylandAccessibilityInstall(int (*service)(int *, int *));
#endif
