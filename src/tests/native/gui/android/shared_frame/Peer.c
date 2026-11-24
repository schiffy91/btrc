#include "Peer.h"
#include <errno.h>
#include <poll.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;
static int channel = -1;
static pid_t child = -1;

int startFramePeer(const char *path) {
	int pair[2];
	if (child >= 0 || socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, pair)) { return -1; }
	posix_spawn_file_actions_t actions;
	int error = posix_spawn_file_actions_init(&actions);
	if (!error) {
		error = posix_spawn_file_actions_adddup2(&actions, pair[1], STDIN_FILENO);
		if (!error) {
			char *const args[] = {(char *)path, NULL};
			error = posix_spawn(&child, path, &actions, NULL, args, environ);
		}
		posix_spawn_file_actions_destroy(&actions);
	}
	close(pair[1]);
	if (error) { close(pair[0]); child = -1; return -1; }
	channel = pair[0];
	return child;
}

int submitFrame(const char *address, int width, int pattern) {
	char command[128];
	int count = snprintf(command, sizeof command, "%s %d %d", address, width, pattern);
	if (count <= 0 || (size_t)count >= sizeof command || send(channel, command, count, MSG_NOSIGNAL) != count) { return -1; }
	struct pollfd response = {.fd = channel, .events = POLLIN};
	unsigned char result;
	if (poll(&response, 1, 10000) != 1 || recv(channel, &result, 1, 0) != 1) { return -1; }
	return result;
}

int finishFramePeer(void) {
	if (channel >= 0) { close(channel); channel = -1; }
	if (child < 0) { return -1; }
	int status = 0;
	pid_t done;
	do { done = waitpid(child, &status, 0); } while (done < 0 && errno == EINTR);
	child = -1;
	return done >= 0 && WIFEXITED(status) ? WEXITSTATUS(status) : -1;
}
