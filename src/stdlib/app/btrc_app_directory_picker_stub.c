#include "btrc_app.h"
#include "btrc_app_directory_picker_internal.h"

int btrc_app_platform_choose_directory(const char* title, const char* initial_directory, char* selected_directory, size_t selected_directory_capacity, int* error_out) {
    (void)title;
    (void)initial_directory;
    if (selected_directory && selected_directory_capacity > 0) { selected_directory[0] = '\0'; }
    if (error_out) { *error_out = BTRC_APP_ERROR_BACKEND_UNAVAILABLE; }
    return BTRC_APP_DIRECTORY_PICKER_FAILED;
}
