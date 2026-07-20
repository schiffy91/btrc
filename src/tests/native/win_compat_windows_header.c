#include <windows.h>

int btrc_win_compat_windows_header(void) {
    return FILE_ATTRIBUTE_REPARSE_POINT != 0;
}
