/* The modal probe for the shim provider's platforms; ModalProbe.h. */
#include "ModalProbe.h"
#include "RealInput.h"
#include "ShimProbe.h"
#include <stdbool.h>

enum { REPEAT_MILLISECONDS = 600, PRESSES = 200 };

static struct { const RealInput *input; int key; int first; volatile bool done; bool running; } modal;

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
static HANDLE helper;
static void pause(int milliseconds) { Sleep((DWORD)milliseconds); }
#else
#include <pthread.h>
#include <time.h>
static pthread_t helper;
static void pause(int milliseconds) {
    struct timespec wait = { milliseconds / 1000, (long)(milliseconds % 1000) * 1000000L };
    nanosleep(&wait, NULL);
}
#endif

/* The modal is whatever window the session puts in front once it is open:
 * a press before that goes to the program's own window, which ignores it. */
static void answer(void) {
    int waited = 0;
    for (int press = 0; press < PRESSES && !modal.done; press++) {
        int until = press == 0 ? modal.first : REPEAT_MILLISECONDS;
        for (waited = 0; waited < until && !modal.done; waited += 20) { pause(20); }
        if (modal.done) { break; }
        if (modal.input->front) { modal.input->front(); }
        modal.input->key(modal.key);
    }
    if (modal.input->leave) { modal.input->leave(); }
}

#ifdef _WIN32
static DWORD WINAPI run(LPVOID unused) { (void)unused; answer(); return 0; }
#else
static void *run(void *unused) { (void)unused; answer(); return NULL; }
#endif

int modalProbeAnswer(int key, int milliseconds) {
    if (modal.running) { return 0; }
    modal.input = shimProbeInput();
    if (!modal.input) { return 0; }
    modal.key = key;
    modal.first = milliseconds;
    modal.done = false;
#ifdef _WIN32
    helper = CreateThread(NULL, 0, run, NULL, 0, NULL);
    modal.running = helper != NULL;
#else
    modal.running = pthread_create(&helper, NULL, run, NULL) == 0;
#endif
    return modal.running ? 1 : 0;
}

void modalProbeDone(void) {
    if (!modal.running) { return; }
    modal.done = true;
#ifdef _WIN32
    WaitForSingleObject(helper, INFINITE);
    CloseHandle(helper);
#else
    pthread_join(helper, NULL);
#endif
    modal.running = false;
}

int modalProbeHasFolderChooser(void) {
#if defined(__ANDROID__) || (defined(__APPLE__) && defined(__ENVIRONMENT_IPHONE_OS_VERSION_MIN_REQUIRED__))
    return 0;
#else
    return 1;
#endif
}
