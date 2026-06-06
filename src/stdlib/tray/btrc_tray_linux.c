/*
 * btrc native system tray — Linux backend (StatusNotifierItem over D-Bus).
 *
 * Implements the de-facto Wayland / freedesktop systray: the KDE
 * StatusNotifierItem spec (org.kde.StatusNotifierItem) plus the Canonical
 * dbusmenu spec (com.canonical.dbusmenu). This is what GNOME (AppIndicator),
 * KDE/Plasma, Sway/Waybar, etc. consume — there is no Wayland protocol for
 * legacy XEmbed trays, so SNI-over-D-Bus is the portable answer.
 *
 * Dependency policy: uses ONLY libdbus-1 (the reference D-Bus library), a base
 * system component present on every Linux desktop — no third-party tray libs
 * (no libappindicator, no Qt/GTK). We speak the wire protocol directly:
 * register the item with the StatusNotifierWatcher, export the SNI + dbusmenu
 * objects, answer Properties/GetLayout/Event, and pump the bus.
 *
 * When an item is activated, its command string is recorded for the btrc side
 * (SystemTray.pump in tray.btrc) to run via the UnixShell stdlib.
 *
 * Build:  <transpiled>.c btrc_tray_linux.c $(pkg-config --cflags --libs dbus-1)
 */
#include "btrc_tray.h"

#include <dbus/dbus.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define BTRC_TRAY_MAX_ITEMS 64
#define SNI_OBJ   "/StatusNotifierItem"
#define MENU_OBJ  "/MenuBar"

typedef struct {
    char* label;
    char* command;
    bool  enabled;
    bool  separator;
} btrc_item;

typedef struct {
    DBusConnection* conn;
    char            bus_name[128];   /* org.kde.StatusNotifierItem-PID-ID */
    char*           title;
    char*           tooltip;
    char*           icon_path;       /* absolute file path or themed name */
    btrc_item       items[BTRC_TRAY_MAX_ITEMS];
    int             item_count;
    char*           pending_command; /* last activated command (C-owned) */
    char*           returned_command;
    bool            should_quit;
    bool            registered;
    int             revision;        /* dbusmenu layout revision */
} btrc_tray;

/* ---------- small helpers ---------- */

static char* dupstr(const char* s) {
    if (!s) { return NULL; }
    size_t n = strlen(s) + 1;
    char* p = (char*)malloc(n);
    if (p) { memcpy(p, s, n); }
    return p;
}

static void append_variant_string(DBusMessageIter* iter, const char* val) {
    DBusMessageIter v;
    dbus_message_iter_open_container(iter, DBUS_TYPE_VARIANT, "s", &v);
    const char* s = val ? val : "";
    dbus_message_iter_append_basic(&v, DBUS_TYPE_STRING, &s);
    dbus_message_iter_close_container(iter, &v);
}

static void append_variant_object(DBusMessageIter* iter, const char* path) {
    DBusMessageIter v;
    dbus_message_iter_open_container(iter, DBUS_TYPE_VARIANT, "o", &v);
    const char* s = path ? path : "/";
    dbus_message_iter_append_basic(&v, DBUS_TYPE_OBJECT_PATH, &s);
    dbus_message_iter_close_container(iter, &v);
}

static void append_variant_bool(DBusMessageIter* iter, dbus_bool_t val) {
    DBusMessageIter v;
    dbus_message_iter_open_container(iter, DBUS_TYPE_VARIANT, "b", &v);
    dbus_message_iter_append_basic(&v, DBUS_TYPE_BOOLEAN, &val);
    dbus_message_iter_close_container(iter, &v);
}

/* dict entry: { "key": variant("string") } appended into an a{sv} iter. */
static void dict_str(DBusMessageIter* arr, const char* key, const char* val) {
    DBusMessageIter e;
    dbus_message_iter_open_container(arr, DBUS_TYPE_DICT_ENTRY, NULL, &e);
    dbus_message_iter_append_basic(&e, DBUS_TYPE_STRING, &key);
    append_variant_string(&e, val);
    dbus_message_iter_close_container(arr, &e);
}

static void dict_bool(DBusMessageIter* arr, const char* key, dbus_bool_t val) {
    DBusMessageIter e;
    dbus_message_iter_open_container(arr, DBUS_TYPE_DICT_ENTRY, NULL, &e);
    dbus_message_iter_append_basic(&e, DBUS_TYPE_STRING, &key);
    append_variant_bool(&e, val);
    dbus_message_iter_close_container(arr, &e);
}

/* ---------- StatusNotifierItem property replies ---------- */

/* org.freedesktop.DBus.Properties.GetAll for org.kde.StatusNotifierItem. */
static DBusMessage* sni_get_all(btrc_tray* t, DBusMessage* msg) {
    DBusMessage* reply = dbus_message_new_method_return(msg);
    DBusMessageIter it, arr;
    dbus_message_iter_init_append(reply, &it);
    dbus_message_iter_open_container(&it, DBUS_TYPE_ARRAY, "{sv}", &arr);
    dict_str(&arr, "Category", "ApplicationStatus");
    dict_str(&arr, "Id", t->title ? t->title : "btrc");
    dict_str(&arr, "Title", t->title ? t->title : "btrc");
    dict_str(&arr, "Status", "Active");
    /* IconName: a themed name or, for an absolute path, the basename without
     * extension also works with most hosts; we expose IconName best-effort. */
    dict_str(&arr, "IconName", t->icon_path ? t->icon_path : "application-x-executable");
    dict_str(&arr, "ToolTip", t->tooltip ? t->tooltip : "");
    dict_bool(&arr, "ItemIsMenu", TRUE);
    /* Menu object path is exposed via Get("Menu"); also include here. */
    {
        DBusMessageIter e;
        const char* key = "Menu";
        const char* path = MENU_OBJ;
        dbus_message_iter_open_container(&arr, DBUS_TYPE_DICT_ENTRY, NULL, &e);
        dbus_message_iter_append_basic(&e, DBUS_TYPE_STRING, &key);
        append_variant_object(&e, path);
        dbus_message_iter_close_container(&arr, &e);
    }
    dbus_message_iter_close_container(&it, &arr);
    return reply;
}

/* org.freedesktop.DBus.Properties.Get(interface, name). */
static DBusMessage* sni_get(btrc_tray* t, DBusMessage* msg, const char* name) {
    DBusMessage* reply = dbus_message_new_method_return(msg);
    DBusMessageIter it;
    dbus_message_iter_init_append(reply, &it);
    if (strcmp(name, "Menu") == 0) {
        append_variant_object(&it, MENU_OBJ);
    } else if (strcmp(name, "Category") == 0) {
        append_variant_string(&it, "ApplicationStatus");
    } else if (strcmp(name, "Id") == 0 || strcmp(name, "Title") == 0) {
        append_variant_string(&it, t->title ? t->title : "btrc");
    } else if (strcmp(name, "Status") == 0) {
        append_variant_string(&it, "Active");
    } else if (strcmp(name, "IconName") == 0) {
        append_variant_string(&it, t->icon_path ? t->icon_path : "application-x-executable");
    } else if (strcmp(name, "ToolTip") == 0) {
        append_variant_string(&it, t->tooltip ? t->tooltip : "");
    } else if (strcmp(name, "ItemIsMenu") == 0) {
        append_variant_bool(&it, TRUE);
    } else {
        append_variant_string(&it, "");
    }
    return reply;
}

/* ---------- com.canonical.dbusmenu replies ---------- */

/* One menu node: (ia{sv}av). For the root we nest the item children. */
static void append_menu_item(DBusMessageIter* parent, btrc_tray* t, int index) {
    btrc_item* mi = &t->items[index];
    DBusMessageIter node, props, kids;
    /* dbusmenu ids: 0 is the root; children are 1-based. */
    dbus_int32_t id = index + 1;
    dbus_message_iter_open_container(parent, DBUS_TYPE_STRUCT, NULL, &node);
    dbus_message_iter_append_basic(&node, DBUS_TYPE_INT32, &id);
    dbus_message_iter_open_container(&node, DBUS_TYPE_ARRAY, "{sv}", &props);
    if (mi->separator) {
        dict_str(&props, "type", "separator");
    } else {
        dict_str(&props, "label", mi->label ? mi->label : "");
        dict_bool(&props, "enabled", mi->enabled ? TRUE : FALSE);
        dict_bool(&props, "visible", TRUE);
    }
    dbus_message_iter_close_container(&node, &props);
    /* No grandchildren (flat menu). */
    dbus_message_iter_open_container(&node, DBUS_TYPE_ARRAY, "v", &kids);
    dbus_message_iter_close_container(&node, &kids);
    dbus_message_iter_close_container(parent, &node);
}

/* GetLayout(parentId, depth, props) -> (u(ia{sv}av)). */
static DBusMessage* menu_get_layout(btrc_tray* t, DBusMessage* msg) {
    DBusMessage* reply = dbus_message_new_method_return(msg);
    DBusMessageIter it, root, rprops, rkids;
    dbus_message_iter_init_append(reply, &it);
    dbus_uint32_t rev = (dbus_uint32_t)t->revision;
    dbus_message_iter_append_basic(&it, DBUS_TYPE_UINT32, &rev);
    /* Root node id 0 with children = our items. */
    dbus_message_iter_open_container(&it, DBUS_TYPE_STRUCT, NULL, &root);
    dbus_int32_t rid = 0;
    dbus_message_iter_append_basic(&root, DBUS_TYPE_INT32, &rid);
    dbus_message_iter_open_container(&root, DBUS_TYPE_ARRAY, "{sv}", &rprops);
    dict_str(&rprops, "children-display", "submenu");
    dbus_message_iter_close_container(&root, &rprops);
    dbus_message_iter_open_container(&root, DBUS_TYPE_ARRAY, "v", &rkids);
    for (int i = 0; i < t->item_count; i++) {
        DBusMessageIter v;
        dbus_message_iter_open_container(&rkids, DBUS_TYPE_VARIANT, "(ia{sv}av)", &v);
        append_menu_item(&v, t, i);
        dbus_message_iter_close_container(&rkids, &v);
    }
    dbus_message_iter_close_container(&root, &rkids);
    dbus_message_iter_close_container(&it, &root);
    return reply;
}

/* GetGroupProperties(ids, props) -> a(ia{sv}). */
static DBusMessage* menu_get_group_properties(btrc_tray* t, DBusMessage* msg) {
    DBusMessage* reply = dbus_message_new_method_return(msg);
    DBusMessageIter it, arr;
    dbus_message_iter_init_append(reply, &it);
    dbus_message_iter_open_container(&it, DBUS_TYPE_ARRAY, "(ia{sv})", &arr);
    for (int i = 0; i < t->item_count; i++) {
        append_menu_item(&arr, t, i);
    }
    dbus_message_iter_close_container(&it, &arr);
    return reply;
}

/* Event(id, eventId, data, timestamp): a "clicked" event activates an item. */
static void menu_handle_event(btrc_tray* t, DBusMessage* msg) {
    DBusMessageIter it;
    if (!dbus_message_iter_init(msg, &it)) { return; }
    if (dbus_message_iter_get_arg_type(&it) != DBUS_TYPE_INT32) { return; }
    dbus_int32_t id = 0;
    dbus_message_iter_get_basic(&it, &id);
    dbus_message_iter_next(&it);
    const char* event = NULL;
    if (dbus_message_iter_get_arg_type(&it) == DBUS_TYPE_STRING) {
        dbus_message_iter_get_basic(&it, &event);
    }
    if (event && strcmp(event, "clicked") == 0) {
        int index = (int)id - 1;  /* ids are 1-based */
        if (index >= 0 && index < t->item_count && !t->items[index].separator) {
            const char* cmd = t->items[index].command;
            if (cmd) {
                if (t->pending_command) { free(t->pending_command); }
                t->pending_command = dupstr(cmd);
            }
        }
    }
}

/* ---------- D-Bus message dispatch ---------- */

static DBusHandlerResult on_message(DBusConnection* conn, DBusMessage* msg, void* user) {
    btrc_tray* t = (btrc_tray*)user;
    const char* iface = dbus_message_get_interface(msg);
    const char* member = dbus_message_get_member(msg);
    const char* path = dbus_message_get_path(msg);
    if (!iface || !member) { return DBUS_HANDLER_RESULT_NOT_YET_HANDLED; }

    DBusMessage* reply = NULL;

    /* Introspection: a minimal stub keeps strict hosts happy. */
    if (strcmp(iface, "org.freedesktop.DBus.Introspectable") == 0 &&
        strcmp(member, "Introspect") == 0) {
        reply = dbus_message_new_method_return(msg);
        const char* xml = "<node/>";
        dbus_message_append_args(reply, DBUS_TYPE_STRING, &xml, DBUS_TYPE_INVALID);
    }
    /* Properties for the SNI object. */
    else if (path && strcmp(path, SNI_OBJ) == 0 &&
             strcmp(iface, "org.freedesktop.DBus.Properties") == 0) {
        if (strcmp(member, "GetAll") == 0) {
            reply = sni_get_all(t, msg);
        } else if (strcmp(member, "Get") == 0) {
            const char* in_iface = NULL; const char* name = NULL;
            dbus_message_get_args(msg, NULL,
                DBUS_TYPE_STRING, &in_iface, DBUS_TYPE_STRING, &name, DBUS_TYPE_INVALID);
            reply = sni_get(t, msg, name ? name : "");
        }
    }
    /* SNI activation methods. */
    else if (path && strcmp(path, SNI_OBJ) == 0 &&
             strcmp(iface, "org.kde.StatusNotifierItem") == 0) {
        /* Activate/SecondaryActivate/ContextMenu/Scroll: just ack; the menu is
         * served separately by dbusmenu. */
        reply = dbus_message_new_method_return(msg);
    }
    /* dbusmenu object. */
    else if (path && strcmp(path, MENU_OBJ) == 0 &&
             strcmp(iface, "com.canonical.dbusmenu") == 0) {
        if (strcmp(member, "GetLayout") == 0) {
            reply = menu_get_layout(t, msg);
        } else if (strcmp(member, "GetGroupProperties") == 0) {
            reply = menu_get_group_properties(t, msg);
        } else if (strcmp(member, "AboutToShow") == 0) {
            reply = dbus_message_new_method_return(msg);
            dbus_bool_t need_update = FALSE;
            dbus_message_append_args(reply, DBUS_TYPE_BOOLEAN, &need_update, DBUS_TYPE_INVALID);
        } else if (strcmp(member, "Event") == 0) {
            menu_handle_event(t, msg);
            reply = dbus_message_new_method_return(msg);
        } else if (strcmp(member, "GetProperty") == 0) {
            reply = dbus_message_new_method_return(msg);
            DBusMessageIter it;
            dbus_message_iter_init_append(reply, &it);
            append_variant_string(&it, "");
        }
    }

    if (reply) {
        dbus_connection_send(conn, reply, NULL);
        dbus_message_unref(reply);
        return DBUS_HANDLER_RESULT_HANDLED;
    }
    return DBUS_HANDLER_RESULT_NOT_YET_HANDLED;
}

/* Register our item with the StatusNotifierWatcher. */
static bool register_with_watcher(btrc_tray* t) {
    DBusMessage* msg = dbus_message_new_method_call(
        "org.kde.StatusNotifierWatcher",
        "/StatusNotifierWatcher",
        "org.kde.StatusNotifierWatcher",
        "RegisterStatusNotifierItem");
    if (!msg) { return false; }
    const char* service = t->bus_name;
    dbus_message_append_args(msg, DBUS_TYPE_STRING, &service, DBUS_TYPE_INVALID);
    DBusError err; dbus_error_init(&err);
    DBusMessage* reply = dbus_connection_send_with_reply_and_block(t->conn, msg, 2000, &err);
    dbus_message_unref(msg);
    bool ok = !dbus_error_is_set(&err);
    if (reply) { dbus_message_unref(reply); }
    if (dbus_error_is_set(&err)) { dbus_error_free(&err); }
    return ok;
}

/* ---------- public API ---------- */

void* btrc_tray_create(char* title) {
    DBusError err; dbus_error_init(&err);
    DBusConnection* conn = dbus_bus_get(DBUS_BUS_SESSION, &err);
    if (dbus_error_is_set(&err) || !conn) {
        if (dbus_error_is_set(&err)) { dbus_error_free(&err); }
        return NULL;   /* no session bus → headless */
    }
    btrc_tray* t = (btrc_tray*)calloc(1, sizeof(btrc_tray));
    if (!t) { return NULL; }
    t->conn = conn;
    t->title = dupstr(title ? title : "btrc");
    t->tooltip = dupstr("");
    t->icon_path = NULL;
    t->item_count = 0;
    t->pending_command = NULL;
    t->should_quit = false;
    t->registered = false;
    t->revision = 1;
    /* Per-instance well-known name required by the SNI spec. */
    snprintf(t->bus_name, sizeof(t->bus_name),
             "org.kde.StatusNotifierItem-%d-1", (int)getpid());
    dbus_bus_request_name(conn, t->bus_name,
                          DBUS_NAME_FLAG_REPLACE_EXISTING, &err);
    if (dbus_error_is_set(&err)) { dbus_error_free(&err); }
    return (void*)t;
}

void btrc_tray_set_icon(void* tray, char* icon_path) {
    if (!tray) { return; }
    btrc_tray* t = (btrc_tray*)tray;
    free(t->icon_path);
    t->icon_path = (icon_path && icon_path[0]) ? dupstr(icon_path) : NULL;
}

void btrc_tray_set_tooltip(void* tray, char* tooltip) {
    if (!tray) { return; }
    btrc_tray* t = (btrc_tray*)tray;
    free(t->tooltip);
    t->tooltip = dupstr(tooltip ? tooltip : "");
}

int btrc_tray_add_item(void* tray, char* label, char* command, bool enabled) {
    if (!tray) { return -1; }
    btrc_tray* t = (btrc_tray*)tray;
    if (t->item_count >= BTRC_TRAY_MAX_ITEMS) { return -1; }
    btrc_item* mi = &t->items[t->item_count];
    mi->label = dupstr(label ? label : "");
    mi->command = dupstr(command ? command : "");
    mi->enabled = enabled;
    mi->separator = false;
    return t->item_count++;
}

void btrc_tray_add_separator(void* tray) {
    if (!tray) { return; }
    btrc_tray* t = (btrc_tray*)tray;
    if (t->item_count >= BTRC_TRAY_MAX_ITEMS) { return; }
    btrc_item* mi = &t->items[t->item_count++];
    mi->label = NULL;
    mi->command = NULL;
    mi->enabled = false;
    mi->separator = true;
}

void btrc_tray_set_menu(void* tray) {
    if (!tray) { return; }
    btrc_tray* t = (btrc_tray*)tray;
    t->revision++;
}

bool btrc_tray_show(void* tray) {
    if (!tray) { return false; }
    btrc_tray* t = (btrc_tray*)tray;
    static const DBusObjectPathVTable vtable = { .message_function = on_message };
    if (!dbus_connection_register_object_path(t->conn, SNI_OBJ, &vtable, t)) {
        return false;
    }
    if (!dbus_connection_register_object_path(t->conn, MENU_OBJ, &vtable, t)) {
        return false;
    }
    t->registered = register_with_watcher(t);
    /* Even if no watcher is running yet, the object is exported and a watcher
     * that appears later can pick it up; report success if the bus is live. */
    return true;
}

bool btrc_tray_run_iteration(void* tray, int timeout_ms) {
    if (!tray) { return false; }
    btrc_tray* t = (btrc_tray*)tray;
    if (t->should_quit) { return false; }
    int to = (timeout_ms < 0) ? 200 : timeout_ms;
    dbus_connection_read_write_dispatch(t->conn, to);
    return !t->should_quit;
}

char* btrc_tray_take_command(void* tray) {
    if (!tray) { return NULL; }
    btrc_tray* t = (btrc_tray*)tray;
    free(t->returned_command);
    t->returned_command = t->pending_command;
    t->pending_command = NULL;
    return t->returned_command;
}

bool btrc_tray_should_quit(void* tray) {
    if (!tray) { return true; }
    return ((btrc_tray*)tray)->should_quit;
}

void btrc_tray_request_quit(void* tray) {
    if (!tray) { return; }
    ((btrc_tray*)tray)->should_quit = true;
}

void btrc_tray_destroy(void* tray) {
    if (!tray) { return; }
    btrc_tray* t = (btrc_tray*)tray;
    if (t->conn) {
        dbus_connection_unregister_object_path(t->conn, SNI_OBJ);
        dbus_connection_unregister_object_path(t->conn, MENU_OBJ);
        /* Session bus is shared/owned by libdbus; just unref our ref. */
        dbus_connection_unref(t->conn);
    }
    for (int i = 0; i < t->item_count; i++) {
        free(t->items[i].label);
        free(t->items[i].command);
    }
    free(t->title);
    free(t->tooltip);
    free(t->icon_path);
    free(t->pending_command);
    free(t->returned_command);
    free(t);
}
