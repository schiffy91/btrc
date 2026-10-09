#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <math.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static double now(void) {
    struct timespec value;
    if (clock_gettime(CLOCK_MONOTONIC, &value) != 0) {
        _exit(125);
    }
    return (double)value.tv_sec + (double)value.tv_nsec / 1000000000.0;
}

int main(int argc, char **argv) {
    if (argc < 3) {
        return 125;
    }
    char *end = NULL;
    double duration = strtod(argv[1], &end);
    if (!end || *end || !isfinite(duration) || duration <= 0) {
        return 125;
    }
    double deadline = now() + duration;
    pid_t child = fork();
    if (child < 0) {
        return 125;
    }
    if (child == 0) {
        if (setsid() < 0) {
            _exit(125);
        }
        execv(argv[2], &argv[2]);
        _exit(127);
    }
    int status = 0;
    int timed_out = 0;
    for (;;) {
        pid_t result = waitpid(child, &status, WNOHANG);
        if (result == child) {
            break;
        }
        if (result < 0 && errno != EINTR) {
            kill(-child, SIGKILL);
            kill(child, SIGKILL);
            return 125;
        }
        if (now() >= deadline) {
            timed_out = 1;
            kill(-child, SIGKILL);
            kill(child, SIGKILL);
            while (waitpid(child, &status, 0) < 0) {
                if (errno != EINTR) {
                    return 125;
                }
            }
            break;
        }
        struct timespec pause = {0, 10000000};
        nanosleep(&pause, NULL);
    }
    /* Clean up descendants retained by a program that already returned. */
    kill(-child, SIGKILL);
    FILE *output = fopen("status", "w");
    if (!output) {
        return 125;
    }
    int code = WIFEXITED(status) ? WEXITSTATUS(status) : -1;
    int signum = WIFSIGNALED(status) ? WTERMSIG(status) : 0;
    if (fprintf(output, "%d %d %d\n", code, signum, timed_out) < 0 || fclose(output) != 0) {
        return 125;
    }
    return 0;
}
