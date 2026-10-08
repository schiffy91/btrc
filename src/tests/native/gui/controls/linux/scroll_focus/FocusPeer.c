/* Independent SDL client, never forked from an initialized SDL process. */
#include <SDL3/SDL.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#define REQUIRE(x) do { if (!(x)) { fprintf(stderr, "FOCUS_PEER failed: %s\n", #x); exit(2); } } while (0)
int main(void) {
    alarm(20);
    REQUIRE(SDL_Init(SDL_INIT_VIDEO));
    SDL_Window *window = SDL_CreateWindow("Controlled scrollbar focus peer", 80, 40, 0);
    REQUIRE(window != NULL);
    SDL_PropertiesID props = SDL_GetWindowProperties(window);
    Display *display = SDL_GetPointerProperty(props, SDL_PROP_WINDOW_X11_DISPLAY_POINTER, NULL);
    Window native = (Window)SDL_GetNumberProperty(props, SDL_PROP_WINDOW_X11_WINDOW_NUMBER, 0);
    REQUIRE(display != NULL && native != None);
    REQUIRE(SDL_ShowWindow(window));
    XMapRaised(display, native);
    XSync(display, False);
    XSetInputFocus(display, native, RevertToParent, CurrentTime);
    XSync(display, False);
    Window focused = None; int revert = 0;
    XGetInputFocus(display, &focused, &revert);
    REQUIRE(focused == native);
    printf("FOCUS_PEER_READY pid=%ld window=%lu\n", (long)getpid(), (unsigned long)native);
    fflush(stdout);
    REQUIRE(getchar() == '\n');
    SDL_DestroyWindow(window);
    SDL_Quit();
    return 0;
}
