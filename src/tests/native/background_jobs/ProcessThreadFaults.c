#include <assert.h>
#include <dirent.h>
#include <errno.h>
#include <string.h>

#include "ProcessThreadFaultControl.h"

static int selected_mode;
static int entries;
static int closes;
static DIR *active;

void process_threads_fault_reset(int mode) {
    assert(active == NULL);
    assert(mode >= PROCESS_THREADS_NORMAL && mode <= PROCESS_THREADS_STALE_ERRNO);
    selected_mode = mode;
    entries = 0;
    closes = 0;
    errno = EDOM;
}
int process_threads_fault_entries(void) { return entries; }
int process_threads_fault_closes(void) { return closes; }
int process_threads_fault_live(void) { return active != NULL; }

DIR *process_threads_fault_opendir(const char *path) {
    assert(active == NULL);
    assert(strcmp(path, "/proc/self/task") == 0);
    if (selected_mode == PROCESS_THREADS_OPEN_ERROR) {
        errno = EACCES;
        return NULL;
    }
    active = opendir(path);
    assert(active != NULL);
    return active;
}

struct dirent *process_threads_fault_readdir(DIR *directory) {
    assert(directory != NULL && directory == active);
    if (selected_mode == PROCESS_THREADS_INITIAL_ERROR ||
        (selected_mode == PROCESS_THREADS_PARTIAL_ERROR && entries > 0)) {
        errno = EIO;
        return NULL;
    }
    struct dirent *entry = readdir(directory);
    if (entry != NULL && entry->d_name[0] != '.') entries++;
    if (entry != NULL && selected_mode == PROCESS_THREADS_STALE_ERRNO) errno = EIO;
    return entry;
}

int process_threads_fault_closedir(DIR *directory) {
    assert(directory != NULL && directory == active);
    int result = closedir(directory);
    assert(result == 0);
    active = NULL;
    closes++;
    /* Catch reading errno after close, for both successful and failed reads. */
    errno = (selected_mode == PROCESS_THREADS_INITIAL_ERROR ||
             selected_mode == PROCESS_THREADS_PARTIAL_ERROR) ? 0 : EOVERFLOW;
    return result;
}
