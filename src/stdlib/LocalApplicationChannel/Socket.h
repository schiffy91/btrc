#pragma once
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>
#include <poll.h>
#include <fcntl.h>
#include <errno.h>

typedef struct sockaddr_un LocalSocketAddress;
