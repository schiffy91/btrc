#include "btrc_tray.h"

#include <stdio.h>

int main(void) {
    void* tray = btrc_tray_create("disconnect-test");
    if (!tray) { return 2; }
    puts("READY");
    fflush(stdout);
    if (getchar() == EOF) {
        btrc_tray_destroy(tray);
        return 3;
    }
    for (int attempt = 0; attempt < 50; attempt++) {
        if (!btrc_tray_run_iteration(tray, 100)) {
            btrc_tray_destroy(tray);
            return 0;
        }
    }
    btrc_tray_destroy(tray);
    return 4;
}
