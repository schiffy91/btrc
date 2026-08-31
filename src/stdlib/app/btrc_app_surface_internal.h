/* Private native surface lease shared only by std.app and std.gpu. */
#ifndef BTRC_APP_SURFACE_INTERNAL_H
#define BTRC_APP_SURFACE_INTERNAL_H

#include "btrc_app.h"

typedef struct BtrcAppSurfaceLease BtrcAppSurfaceLease;
typedef struct GLFWwindow GLFWwindow;
typedef void (*BtrcAppOwnerDrainHook)(void);

/* std.gpu installs one process-lifetime hook.  std.app invokes it outside the
 * app mutex before draining its own surface -> window -> loop finalizers. */
void btrc_app_register_owner_drain_hook(BtrcAppOwnerDrainHook hook);
void btrc_app_drain_owner_finalizers(void);

int std_app_surface_attach(
    unsigned long long surface, BtrcAppSurfaceLease** lease_out);
GLFWwindow* std_app_surface_glfw(BtrcAppSurfaceLease* lease);
unsigned long long std_app_surface_lease_generation(BtrcAppSurfaceLease* lease);
int std_app_surface_detach(BtrcAppSurfaceLease* lease);

#endif
