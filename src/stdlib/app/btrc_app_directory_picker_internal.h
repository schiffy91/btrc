#ifndef BTRC_APP_DIRECTORY_PICKER_INTERNAL_H
#define BTRC_APP_DIRECTORY_PICKER_INTERNAL_H

#include <stddef.h>

int btrc_app_platform_choose_directory(const char* title, const char* initial_directory, char* selected_directory, size_t selected_directory_capacity, int* error_out);

#endif
