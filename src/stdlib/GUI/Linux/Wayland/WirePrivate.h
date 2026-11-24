#ifndef BTRC_WAYLAND_WIRE_PRIVATE_H
#define BTRC_WAYLAND_WIRE_PRIVATE_H
#include "Wire.h"
#include <stdarg.h>

typedef struct BtrcWaylandGPUWire BtrcWaylandGPUWire;
/* The upper 16 header bits are a byte length, including the eight-byte
 * header. All wire arguments occupy a multiple of four bytes. */
#define SERVER_ID_BASE UINT32_C(0xff000000)
enum { MAX_OFFERS = 65536, MAX_MESSAGE = 65532, MAX_QUEUED_BYTES = 4 * 1024 * 1024, MAX_QUEUED_FDS = 64 };

typedef struct {
    const char *interface;
    BtrcWaylandDispatch dispatch;
    void *owner;
    uint32_t fdEvents;
    uint32_t nextFree;
    uint32_t offerDevice;
    bool allocated;
    bool retired;
} Object;

typedef struct Request {
    struct Request *next;
    size_t size;
    size_t sent;
    int fd;
    unsigned char data[];
} Request;

struct BtrcWaylandWire {
    int socket;
    int wake;
    int auxiliary;
    int accessibility;
    BtrcWaylandGPUWire *gpu;
    char error[256];
    Object *objects;
    Object *offers;
    size_t offerCapacity;
    uint32_t used;
    uint32_t capacity;
    uint32_t freeObject;
    Request *first;
    Request *last;
    size_t queued;
    unsigned char input[2 * MAX_MESSAGE];
    size_t length;
    int fds[MAX_QUEUED_FDS];
    size_t fdCount;
};

bool btrcWaylandWireFail(BtrcWaylandWire *wire, const char *error);
bool btrcWaylandDispatchObject(BtrcWaylandWire *wire, uint32_t id, unsigned opcode, const unsigned char *bytes, size_t size);
bool btrcWaylandEnableGPUWire(BtrcWaylandWire *wire);
void btrcWaylandGPUWireClose(BtrcWaylandGPUWire *gpu);
uint32_t btrcWaylandGPUObject(BtrcWaylandGPUWire *gpu, const char *interface);
void btrcWaylandGPURetire(BtrcWaylandGPUWire *gpu, uint32_t id);
bool btrcWaylandGPUSend(BtrcWaylandGPUWire *gpu, uint32_t id, unsigned opcode, const char *signature, va_list args);
bool btrcWaylandGPUFlush(BtrcWaylandGPUWire *gpu);
int btrcWaylandGPUPoll(BtrcWaylandGPUWire *gpu, int timeout);
void *btrcWaylandGPUDisplay(BtrcWaylandGPUWire *gpu);
void *btrcWaylandGPUProxy(BtrcWaylandGPUWire *gpu, uint32_t id);
#endif
