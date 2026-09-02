#include "btrc_app.h"
#include "btrc_app_directory_picker_internal.h"

#include <assert.h>
#include <pthread.h>
#include <stdio.h>

typedef struct {
    int outcome;
    int error;
    char selected_directory[64];
} DirectoryPickerProbe;

static void* choose_on_worker(void* userdata) {
    DirectoryPickerProbe* probe = (DirectoryPickerProbe*)userdata;
    probe->outcome = btrc_app_platform_choose_directory("Probe", "", probe->selected_directory, sizeof(probe->selected_directory), &probe->error);
    return NULL;
}

int main(void) {
    DirectoryPickerProbe probe = { 0 };
    pthread_t worker;
    assert(pthread_create(&worker, NULL, choose_on_worker, &probe) == 0);
    assert(pthread_join(worker, NULL) == 0);
    assert(probe.outcome == BTRC_APP_DIRECTORY_PICKER_FAILED);
    assert(probe.error == BTRC_APP_ERROR_NOT_MAIN_THREAD);
    assert(probe.selected_directory[0] == '\0');
    puts("PASS: macOS directory picker native provider");
    return 0;
}
