#pragma once

#include <dbus/dbus.h>
#include <stddef.h>

/* BlueZ is driven over the system bus. libdbus is bound directly except
 * where a call reports through DBusError, which carries bitfields the typed
 * importer cannot lower, or passes a basic value through a typed `void*`. */
static inline DBusConnection* btrcBlueZOpen(void) {
	DBusError error;
	dbus_error_init(&error);
	DBusConnection* connection = dbus_bus_get_private(DBUS_BUS_SYSTEM, &error);
	if (dbus_error_is_set(&error)) { dbus_error_free(&error); return NULL; }
	return connection;
}

/* Send a call and wait for its reply; NULL when the call failed. */
static inline DBusMessage* btrcBlueZCall(DBusConnection* connection, DBusMessage* message, int timeoutMilliseconds) {
	DBusError error;
	dbus_error_init(&error);
	DBusMessage* reply = dbus_connection_send_with_reply_and_block(connection, message, timeoutMilliseconds, &error);
	if (dbus_error_is_set(&error)) {
		dbus_error_free(&error);
		if (reply != NULL) { dbus_message_unref(reply); }
		return NULL;
	}
	return reply;
}

/* The connection's socket, to wait on; -1 when it has none. */
static inline int btrcBlueZDescriptor(DBusConnection* connection) {
	int descriptor = -1;
	return dbus_connection_get_unix_fd(connection, &descriptor) ? descriptor : -1;
}

static inline dbus_bool_t btrcBlueZAppendString(DBusMessageIter* iter, int type, const char* value) { return dbus_message_iter_append_basic(iter, type, &value); }
static inline dbus_bool_t btrcBlueZAppendUInt32(DBusMessageIter* iter, unsigned int value) { dbus_uint32_t wire = value; return dbus_message_iter_append_basic(iter, DBUS_TYPE_UINT32, &wire); }
static inline dbus_bool_t btrcBlueZAppendBool(DBusMessageIter* iter, int value) { dbus_bool_t wire = value ? TRUE : FALSE; return dbus_message_iter_append_basic(iter, DBUS_TYPE_BOOLEAN, &wire); }

/* A string or object path argument; empty when the argument is neither. */
static inline const char* btrcBlueZReadString(DBusMessageIter* iter) {
	const char* value = NULL;
	int type = dbus_message_iter_get_arg_type(iter);
	if (type == DBUS_TYPE_STRING || type == DBUS_TYPE_OBJECT_PATH) { dbus_message_iter_get_basic(iter, &value); }
	return value == NULL ? "" : value;
}

static inline int btrcBlueZReadBool(DBusMessageIter* iter) {
	dbus_bool_t value = FALSE;
	if (dbus_message_iter_get_arg_type(iter) == DBUS_TYPE_BOOLEAN) { dbus_message_iter_get_basic(iter, &value); }
	return value ? 1 : 0;
}
