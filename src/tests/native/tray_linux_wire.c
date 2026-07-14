#include "btrc_tray_linux.c"

static int failed = 0;

static void check(int condition, const char* message) {
    if (!condition) {
        fprintf(stderr, "FAIL: %s\n", message);
        failed = 1;
    }
}

int main(void) {
    btrc_tray tray = {0};
    tray.item_count = 1;
    tray.items[0].label = "Open";
    tray.items[0].command = "open";
    tray.items[0].enabled = false;
    tray.title = "Test";
    tray.tooltip = "Tooltip";

    DBusMessage* request = dbus_message_new_method_call(
        "org.example.Test", MENU_OBJ,
        "com.canonical.dbusmenu", "GetGroupProperties");
    check(request != NULL, "request allocation");
    if (request) { dbus_message_set_serial(request, 1); }
    DBusMessage* reply = request ? menu_get_group_properties(&tray, request) : NULL;
    check(reply != NULL, "group-properties reply allocation");
    if (reply) {
        check(strcmp(dbus_message_get_signature(reply), "a(ia{sv})") == 0,
              "GetGroupProperties has the declared wire signature");
        dbus_message_unref(reply);
    }
    if (request) { dbus_message_unref(request); }

    request = dbus_message_new_method_call(
        "org.example.Test", SNI_OBJ,
        "org.freedesktop.DBus.Properties", "Get");
    check(request != NULL, "tooltip request allocation");
    if (request) {
        dbus_message_set_serial(request, 2);
        reply = sni_get(&tray, request, "ToolTip");
        check(reply != NULL, "tooltip reply allocation");
        if (reply) {
            DBusMessageIter outer, value;
            check(dbus_message_iter_init(reply, &outer), "tooltip reply value");
            check(dbus_message_iter_get_arg_type(&outer) == DBUS_TYPE_VARIANT,
                  "tooltip property is a variant");
            dbus_message_iter_recurse(&outer, &value);
            char* signature = dbus_message_iter_get_signature(&value);
            check(signature && strcmp(signature, "(sa(iiay)ss)") == 0,
                  "tooltip uses the StatusNotifierItem struct signature");
            dbus_free(signature);
            dbus_message_unref(reply);
        }
        dbus_message_unref(request);
    }

    request = dbus_message_new_method_call(
        "org.example.Test", SNI_OBJ,
        "org.freedesktop.DBus.Properties", "Get");
    check(request != NULL, "unknown-property request allocation");
    if (request) {
        dbus_message_set_serial(request, 3);
        reply = sni_get(&tray, request, "NotAProperty");
        check(reply != NULL, "unknown-property reply allocation");
        if (reply) {
            check(dbus_message_get_type(reply) == DBUS_MESSAGE_TYPE_ERROR,
                  "unknown property returns a D-Bus error");
            check(strcmp(dbus_message_get_error_name(reply),
                         "org.freedesktop.DBus.Error.UnknownProperty") == 0,
                  "unknown property uses the standard error name");
            dbus_message_unref(reply);
        }
        dbus_message_unref(request);
    }

    DBusMessage* event = dbus_message_new_method_call(
        "org.example.Test", MENU_OBJ, "com.canonical.dbusmenu", "Event");
    dbus_int32_t id = 1;
    const char* clicked = "clicked";
    check(event != NULL, "event allocation");
    if (event) {
        check(dbus_message_append_args(
                  event,
                  DBUS_TYPE_INT32, &id,
                  DBUS_TYPE_STRING, &clicked,
                  DBUS_TYPE_INVALID),
              "event arguments");
        menu_handle_event(&tray, event);
        check(tray.pending_command == NULL, "disabled item cannot be activated");
        tray.items[0].enabled = true;
        menu_handle_event(&tray, event);
        check(tray.pending_command && strcmp(tray.pending_command, "open") == 0,
              "enabled item returns its command");
        dbus_message_unref(event);
    }
    free(tray.pending_command);

    btrc_tray wake_tray = {
        .bus_fd = -1,
        .wake_read_fd = -1,
        .wake_write_fd = -1,
    };
    atomic_init(&wake_tray.should_quit, false);
    check(create_wake_pipe(&wake_tray), "quit wake pipe creation");
    if (wake_tray.wake_read_fd >= 0) {
        btrc_tray_request_quit(&wake_tray);
        struct pollfd wake_descriptor = {
            .fd = wake_tray.wake_read_fd,
            .events = POLLIN,
        };
        check(poll(&wake_descriptor, 1, 1000) == 1,
              "quit wakes a blocking Linux event loop");
        check(atomic_load_explicit(
                  &wake_tray.should_quit, memory_order_acquire),
              "quit state is published before the wake");
        close_wake_pipe(&wake_tray);
    }
    return failed;
}
