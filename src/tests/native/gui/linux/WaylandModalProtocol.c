#include "Client.h"
#include <assert.h>
#include <stdlib.h>

int main(int count, char **args) {
    assert(count == 2);
    BtrcWaylandDisplay d = {.wire = btrcWaylandConnect()};
    assert(d.wire);
    d.registry = btrcWaylandObject(d.wire, "wl_registry", &d, NULL, 0);
    BtrcWaylandWindow owner = {.display = &d}, modal = {.display = &d};
    owner.toplevel = btrcWaylandObject(d.wire, "xdg_toplevel", &owner, NULL, 0);
    modal.toplevel = btrcWaylandObject(d.wire, "xdg_toplevel", &modal, NULL, 0);
    d.dialogManagerName = (uint32_t)atoi(args[1]);
    assert(!btrcWaylandWindowMakeDialog(&modal, &modal));
    assert(btrcWaylandWindowMakeDialog(&modal, &owner));
    assert((d.dialogManagerName != 0) == (modal.dialog != 0));
    btrcWaylandDisconnect(d.wire);
    return 0;
}
