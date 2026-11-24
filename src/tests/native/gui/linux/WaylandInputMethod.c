/* Independent input-method process speaking the compositor's IM-side v2
 * protocol. The product uses the client-side text-input-v3 protocol. */
#include <wayland-client.h>
#include <assert.h>
#include <stdio.h>
#include <string.h>

static const struct wl_message requests[] = {
    {"commit_string", "s", NULL}, {"set_preedit_string", "sii", NULL},
    {"delete_surrounding_text", "uu", NULL}, {"commit", "u", NULL},
};
static const struct wl_message events[] = {
    {"activate", "", NULL}, {"deactivate", "", NULL}, {"surrounding_text", "suu", NULL},
    {"text_change_cause", "u", NULL}, {"content_type", "uu", NULL},
    {"done", "", NULL}, {"unavailable", "", NULL},
};
static const struct wl_interface methodType = {"zwp_input_method_v2", 1, 4, requests, 7, events};
static const struct wl_interface *types[] = {&wl_seat_interface, &methodType};
static const struct wl_message get[] = {{"get_input_method", "on", types}};
static const struct wl_interface managerType = {"zwp_input_method_manager_v2", 1, 1, get, 0, NULL};

static struct wl_proxy *manager;
static struct wl_seat *seat;
static int active;
static unsigned serial;
static char context[4001];
static unsigned cursor, anchor;

static void global(void *data, struct wl_registry *registry, uint32_t name, const char *interface, uint32_t version) {
    (void)data; (void)version;
    if (!strcmp(interface, managerType.name)) { manager = wl_registry_bind(registry, name, &managerType, 1); }
    if (!strcmp(interface, "wl_seat") && !seat) { seat = wl_registry_bind(registry, name, &wl_seat_interface, 1); }
}
static void removed(void *data, struct wl_registry *registry, uint32_t name) { (void)data; (void)registry; (void)name; }
static const struct wl_registry_listener registryListener = {global, removed};

static int methodEvent(const void *impl, void *target, uint32_t opcode, const struct wl_message *message, union wl_argument *args) {
    (void)impl; (void)target; (void)message; (void)args;
    if (opcode == 0) { active = 1; }
    if (opcode == 1) { active = 0; }
    if (opcode == 2) {
        assert(strlen(args[0].s) < sizeof context);
        strcpy(context, args[0].s);
        cursor = args[1].u; anchor = args[2].u;
    }
    if (opcode == 5) { ++serial; if (active) { active = 2; } }
    assert(opcode != 6);
    return 0;
}

int main(int argc, char **argv) {
    struct wl_display *d = wl_display_connect(NULL);
    assert(d);
    struct wl_registry *r = wl_display_get_registry(d);
    wl_registry_add_listener(r, &registryListener, NULL);
    assert(wl_display_roundtrip(d) >= 0);
    if (!manager) { puts("IM unavailable"); return 77; }
    assert(seat);
    struct wl_proxy *im = wl_proxy_marshal_flags(manager, 0, &methodType, 1, 0, seat, NULL);
    assert(im && wl_proxy_add_dispatcher(im, methodEvent, NULL, NULL) == 0);
    assert(wl_display_roundtrip(d) >= 0);
    puts("IM ready");
    fflush(stdout);
    while (active != 2) { assert(wl_display_dispatch(d) >= 0); }
    if (argc == 2 && !strcmp(argv[1], "field")) {
        while (strcmp(context, "Native BTRC")) { assert(wl_display_dispatch(d) >= 0); }
        assert(cursor == strlen(context) && anchor == cursor);
        puts("surrounding confirmed"); fflush(stdout);
        assert(getchar() == '\n');
        wl_proxy_marshal_flags(im, 1, NULL, 1, 0, "draft", 5, 5);
        wl_proxy_marshal_flags(im, 3, NULL, 1, 0, serial);
        assert(wl_display_roundtrip(d) >= 0);
        puts("preedit sent"); fflush(stdout);
        assert(getchar() == '\n');
        wl_proxy_marshal_flags(im, 2, NULL, 1, 0, 4u, 0u);
        wl_proxy_marshal_flags(im, 0, NULL, 1, 0, "Wayland");
        wl_proxy_marshal_flags(im, 3, NULL, 1, 0, serial);
        do { assert(wl_display_dispatch(d) >= 0); } while (strcmp(context, "Native Wayland"));
        assert(cursor == strlen(context) && anchor == cursor);
        puts("committed text confirmed"); fflush(stdout);
        wl_display_disconnect(d);
        return 0;
    }
    wl_proxy_marshal_flags(im, 1, NULL, 1, 0, "ä日", 2, 5);
    wl_proxy_marshal_flags(im, 3, NULL, 1, 0, serial);
    assert(wl_display_roundtrip(d) >= 0 && getchar() == '\n');
    wl_proxy_marshal_flags(im, 0, NULL, 1, 0, "完成");
    wl_proxy_marshal_flags(im, 1, NULL, 1, 0, "🟢", 4, 4);
    wl_proxy_marshal_flags(im, 3, NULL, 1, 0, serial);
    assert(wl_display_roundtrip(d) >= 0);
    /* Client clears composition by committing a disable followed by enable. */
    wl_display_disconnect(d);
    return 0;
}
