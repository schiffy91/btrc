#include "Platform.h"
#include <poll.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

void tooltipReady(void) { puts("ok"); fflush(stdout); }

int tooltipCommand(void) {
    struct pollfd input = {.fd=STDIN_FILENO, .events=POLLIN};
    char command;
    return poll(&input, 1, 0) > 0 && read(input.fd, &command, 1) == 1 ? command : 0;
}

void tooltipBackground(BtrcShimWindow *window) {
    unsigned char picture[180 * 100 * 4];
    const unsigned char green[] = {37,179,125,255};
    for (size_t i = 0; i < sizeof(picture); i+=4) { memcpy(picture+i, green, 4); }
    btrcShimWindowShowPicture(window, picture, 180, 100);
}
