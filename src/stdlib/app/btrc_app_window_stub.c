#include "btrc_app.h"
#include "btrc_app_window_internal.h"

int btrc_app_platform_set_titlebar_style(GLFWwindow* window, int style) {
    if (!window || (style != BTRC_APP_TITLEBAR_STANDARD && style != BTRC_APP_TITLEBAR_OVERLAY)) { return BTRC_APP_ERROR_INVALID_ARGUMENT; }
    return style == BTRC_APP_TITLEBAR_STANDARD ? BTRC_APP_ERROR_NONE : BTRC_APP_ERROR_BACKEND_UNAVAILABLE;
}
