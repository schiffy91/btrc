#pragma once

#include <dbus/dbus.h>
#include <stddef.h>

/* Only two kinds of adapter remain; every other libdbus call, including the
 * header getters, is bound directly.
 *
 * DBusError carries bitfields the typed importer cannot lower, so the four
 * calls that report through one keep it C-side and return a plain result. */
static inline DBusConnection* btrcDBusOpenSessionBus(void) {
	DBusError error;
	dbus_error_init(&error);
	DBusConnection* connection = dbus_bus_get_private(DBUS_BUS_SESSION, &error);
	if (dbus_error_is_set(&error)) { dbus_error_free(&error); return NULL; }
	return connection;
}

static inline dbus_bool_t btrcDBusOwnName(DBusConnection* connection, const char* name) {
	DBusError error;
	dbus_error_init(&error);
	int result = dbus_bus_request_name(connection, name, DBUS_NAME_FLAG_DO_NOT_QUEUE, &error);
	dbus_bool_t failed = dbus_error_is_set(&error);
	if (failed) { dbus_error_free(&error); }
	return !failed && (result == DBUS_REQUEST_NAME_REPLY_PRIMARY_OWNER || result == DBUS_REQUEST_NAME_REPLY_ALREADY_OWNER);
}

static inline dbus_bool_t btrcDBusCallSucceeds(DBusConnection* connection, DBusMessage* message, int timeoutMilliseconds) {
	DBusError error;
	dbus_error_init(&error);
	DBusMessage* reply = dbus_connection_send_with_reply_and_block(connection, message, timeoutMilliseconds, &error);
	dbus_bool_t failed = dbus_error_is_set(&error);
	if (failed) { dbus_error_free(&error); }
	if (reply != NULL) { dbus_message_unref(reply); }
	return reply != NULL && !failed;
}

static inline dbus_bool_t btrcDBusAddMatch(DBusConnection* connection, const char* rule) {
	DBusError error;
	dbus_error_init(&error);
	dbus_bus_add_match(connection, rule, &error);
	dbus_bool_t failed = dbus_error_is_set(&error);
	if (failed) { dbus_error_free(&error); }
	return !failed;
}

/* libdbus reads and writes basic values through a typed `void*` address;
 * BTRC passes them by value, so these marshal one basic value each. */
static inline dbus_bool_t btrcDBusAppendString(DBusMessageIter* iter, int type, const char* value) { return dbus_message_iter_append_basic(iter, type, &value); }
static inline dbus_bool_t btrcDBusAppendInt32(DBusMessageIter* iter, int value) { dbus_int32_t wire = value; return dbus_message_iter_append_basic(iter, DBUS_TYPE_INT32, &wire); }
static inline dbus_bool_t btrcDBusAppendUInt32(DBusMessageIter* iter, unsigned int value) { dbus_uint32_t wire = value; return dbus_message_iter_append_basic(iter, DBUS_TYPE_UINT32, &wire); }
static inline dbus_bool_t btrcDBusAppendBool(DBusMessageIter* iter, dbus_bool_t value) { dbus_bool_t wire = value ? TRUE : FALSE; return dbus_message_iter_append_basic(iter, DBUS_TYPE_BOOLEAN, &wire); }
static inline const char* btrcDBusReadString(DBusMessageIter* iter) { const char* value = NULL; if (dbus_message_iter_get_arg_type(iter) == DBUS_TYPE_STRING) { dbus_message_iter_get_basic(iter, &value); } return value == NULL ? "" : value; }
static inline int btrcDBusReadInt32(DBusMessageIter* iter) { dbus_int32_t value = 0; if (dbus_message_iter_get_arg_type(iter) == DBUS_TYPE_INT32) { dbus_message_iter_get_basic(iter, &value); } return value; }
