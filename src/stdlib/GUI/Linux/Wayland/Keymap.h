#ifndef BTRC_WAYLAND_KEYMAP_H
#define BTRC_WAYLAND_KEYMAP_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef struct BtrcWaylandKeymap BtrcWaylandKeymap;
typedef struct {
    unsigned key;
    unsigned scancode;
    bool repeats;
    char text[5];
} BtrcWaylandKey;

BtrcWaylandKeymap *btrcWaylandKeymapRead(int fd, size_t size);
void btrcWaylandKeymapFree(BtrcWaylandKeymap *map);
BtrcWaylandKey btrcWaylandKey(BtrcWaylandKeymap *map, uint32_t evdev, uint32_t modifiers, uint32_t group);
#endif
