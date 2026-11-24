#ifndef BTRC_WAYLAND_WIRE_H
#define BTRC_WAYLAND_WIRE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Private transport for the ordinary software window provider. The event
 * loop owns the connection; only btrcWaylandWake may run on another thread.
 * An object ID is reused only after wl_display.delete_id confirms it. */
typedef struct BtrcWaylandWire BtrcWaylandWire;
typedef struct BtrcWaylandEvent {
    BtrcWaylandWire *wire;
    const unsigned char *data;
    size_t left;
    bool valid;
} BtrcWaylandEvent;

typedef bool (*BtrcWaylandDispatch)(void *owner, uint32_t object, unsigned opcode, BtrcWaylandEvent *event);

BtrcWaylandWire *btrcWaylandConnect(void);
void btrcWaylandDisconnect(BtrcWaylandWire *wire);
const char *btrcWaylandError(const BtrcWaylandWire *wire);
uint32_t btrcWaylandObject(BtrcWaylandWire *wire, const char *interface, void *owner, BtrcWaylandDispatch dispatch, uint32_t fdEventMask);
/* Register the compositor-assigned new_id from wl_data_device.data_offer. */
bool btrcWaylandOfferObject(BtrcWaylandWire *wire, uint32_t device, uint32_t id, void *owner, BtrcWaylandDispatch dispatch);
void btrcWaylandRetire(BtrcWaylandWire *wire, uint32_t object);
/* u = word, i = signed word, s = NUL-terminated string, h = Unix descriptor.
 * Request ownership of h is a close-on-exec duplicate. */
bool btrcWaylandSend(BtrcWaylandWire *wire, uint32_t object, unsigned opcode, const char *signature, ...);
bool btrcWaylandFlush(BtrcWaylandWire *wire);
/* -1 on disconnect/protocol failure, 0 on timeout, 1 on dispatched events,
 * 2 when another thread woke the loop. */
int btrcWaylandPoll(BtrcWaylandWire *wire, int timeoutMs);
bool btrcWaylandWake(BtrcWaylandWire *wire);
uint32_t btrcWaylandUint(BtrcWaylandEvent *event);
int32_t btrcWaylandInt(BtrcWaylandEvent *event);
const char *btrcWaylandString(BtrcWaylandEvent *event);
const void *btrcWaylandArray(BtrcWaylandEvent *event, uint32_t *size);
int btrcWaylandFd(BtrcWaylandEvent *event);
bool btrcWaylandRoundtrip(BtrcWaylandWire *wire, int timeoutMs);
long long btrcWaylandMilliseconds(void);

#endif
