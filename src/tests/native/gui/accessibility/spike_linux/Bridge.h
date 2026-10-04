#pragma once
#include "../../../../../stdlib/Tray/Linux/DBus.h"
#include <stdlib.h>
/* Same DBusError bitfield boundary as Tray/Linux, now opening the actual
 * accessibility bus supplied by org.a11y.Bus.GetAddress. No tree lives in C. */
static inline DBusConnection* spikeOpenBus(void) {
    const char *address = getenv("BTRC_A11Y_ADDRESS");
    if (!address || !*address) return NULL;
    DBusError error;
    dbus_error_init(&error);
    DBusConnection *connection = dbus_connection_open_private(address, &error);
    if (dbus_error_is_set(&error)) { dbus_error_free(&error); return NULL; }
    if (!connection) return NULL;
    if (!dbus_bus_register(connection, &error)) {
        if (dbus_error_is_set(&error)) dbus_error_free(&error);
        dbus_connection_close(connection); dbus_connection_unref(connection); return NULL;
    }
    return connection;
}
