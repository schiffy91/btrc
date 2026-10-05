/* Force the clipboard requestor-destruction interleaving on two X11 clients.
 * The SDL owner does not pump until the request has been sent and the other
 * client's window destruction has been acknowledged by the X server. */
#include <SDL3/SDL.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

/* Required calls and checks remain active in release (-DNDEBUG) builds. */
#define REQUIRE(condition) do { \
    if (!(condition)) { \
        fprintf(stderr, "ERROR: %s failed\n", #condition); \
        exit(2); \
    } \
} while (0)

int main(int argc, char **argv) {
    int destroy_before_dispatch = argc == 2 ? atoi(argv[1]) : 1;
    REQUIRE(argc <= 2 && (destroy_before_dispatch == 0 || destroy_before_dispatch == 1));
    alarm(10);
    REQUIRE(SDL_Init(SDL_INIT_VIDEO));
    SDL_Window *window = SDL_CreateWindow("Clipboard owner", 80, 40, SDL_WINDOW_HIDDEN);
    REQUIRE(window);
    REQUIRE(SDL_SetClipboardText("clipboard boundary"));
    Display *owner = SDL_GetPointerProperty(SDL_GetWindowProperties(window),
                                           SDL_PROP_WINDOW_X11_DISPLAY_POINTER, NULL);
    REQUIRE(owner);
    XSync(owner, False);
    Display *requestor = XOpenDisplay(NULL);
    REQUIRE(requestor);
    Window peer = XCreateSimpleWindow(requestor, DefaultRootWindow(requestor), 0, 0, 1, 1, 0, 0, 0);
    Atom clipboard = XInternAtom(requestor, "CLIPBOARD", False);
    Atom target = XInternAtom(requestor, "TARGETS", False);
    Atom property = XInternAtom(requestor, "BTRC_CLIPBOARD_BOUNDARY", False);
    REQUIRE(XGetSelectionOwner(requestor, clipboard) != None);
    XConvertSelection(requestor, clipboard, target, property, peer, CurrentTime);
    XSync(requestor, False);
    if (destroy_before_dispatch) {
        XDestroyWindow(requestor, peer);
        XSync(requestor, False);
    }
    printf("requestor=0x%lx destroyed=%d; dispatching queued clipboard request\n", peer, destroy_before_dispatch);
    fflush(stdout);
    SDL_PumpEvents();
    XSync(owner, False);
    puts("clipboard owner survived dispatch");
    if (!destroy_before_dispatch) XDestroyWindow(requestor, peer);
    XCloseDisplay(requestor);
    SDL_DestroyWindow(window);
    SDL_Quit();
    alarm(0);
    return 0;
}
