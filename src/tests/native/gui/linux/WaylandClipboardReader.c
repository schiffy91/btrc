/* Pass the caller's descriptor directly to the real selection owner. This
 * exercises both regular files and peers that hold a full, unread pipe. */
#include <wayland-client.h>
#include <assert.h>
#include <fcntl.h>
#include <string.h>
#include <unistd.h>

static const struct wl_message offerRequests[] = {{"receive", "sh", NULL}};
static const struct wl_message offerEvents[] = {{"offer", "s", NULL}};
static const struct wl_interface offerType = {"zwlr_data_control_offer_v1", 1, 1, offerRequests, 1, offerEvents};
static const struct wl_interface *offerArgs[] = {&offerType};
static const struct wl_message deviceEvents[] = {
    {"data_offer", "n", offerArgs}, {"selection", "?o", offerArgs}, {"finished", "", NULL}
};
static const struct wl_interface deviceType = {"zwlr_data_control_device_v1", 1, 0, NULL, 3, deviceEvents};
static const struct wl_interface *deviceArgs[] = {&deviceType, &wl_seat_interface};
static const struct wl_message requests[] = {{"create_data_source", "n", NULL}, {"get_data_device", "no", deviceArgs}};
static const struct wl_interface managerType = {"zwlr_data_control_manager_v1", 1, 2, requests, 0, NULL};
static struct wl_proxy *manager;
static struct wl_seat *seat;
static struct wl_proxy *selected;

static void global(void *data, struct wl_registry *registry, uint32_t name, const char *type, uint32_t version) {
    (void)data; (void)version;
    if (!strcmp(type, managerType.name)) { manager = wl_registry_bind(registry, name, &managerType, 1); }
    if (!strcmp(type, "wl_seat") && !seat) { seat = wl_registry_bind(registry, name, &wl_seat_interface, 1); }
}
static void removed(void *data, struct wl_registry *registry, uint32_t name) { (void)data; (void)registry; (void)name; }
static const struct wl_registry_listener registryListener = {global, removed};

static int event(const void *impl, void *target, uint32_t opcode, const struct wl_message *msg, union wl_argument *args) {
    (void)impl; (void)target; (void)msg;
    if (opcode == 1) { selected = (struct wl_proxy *)args[0].o; }
    return 0;
}

int main(int argc, char **argv) {
    assert(argc == 2);
    struct wl_display *display = wl_display_connect(NULL);
    assert(display);
    struct wl_registry *registry = wl_display_get_registry(display);
    wl_registry_add_listener(registry, &registryListener, NULL);
    assert(wl_display_roundtrip(display) >= 0 && manager && seat);
    struct wl_proxy *device = wl_proxy_marshal_flags(manager, 1, &deviceType, 1, 0, NULL, seat);
    assert(device && !wl_proxy_add_dispatcher(device, event, NULL, NULL));
    assert(wl_display_roundtrip(display) >= 0 && selected);
    int fd = open(argv[1], O_WRONLY);
    assert(fd >= 0);
    wl_proxy_marshal_flags(selected, 0, NULL, 1, 0, "text/plain;charset=utf-8", fd);
    close(fd);
    assert(wl_display_roundtrip(display) >= 0);
    wl_display_disconnect(display);
    return 0;
}
