/* The first-party ABI between Library.DBus and optional Linux X11
 * session-bus activation providers. A statically linked package or an
 * ELF-preloaded shared object may supply btrcLinuxDBusX11AutolaunchV1. */
#ifndef BTRC_LINUX_DBUS_X11_AUTOLAUNCH_V1_H
#define BTRC_LINUX_DBUS_X11_AUTOLAUNCH_V1_H

#include <stddef.h>

typedef struct BtrcLinuxDBusX11AutolaunchV1 {
    size_t (*launch)(const char* machineId, char* output, size_t capacity);
} BtrcLinuxDBusX11AutolaunchV1;

#endif
