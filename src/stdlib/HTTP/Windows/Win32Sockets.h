/* Private primitive ABI; native SOCKET values never cross this boundary. */
#pragma once

int btrcWinSocketListen(void** registry, int port, int bindAny, int backlog, int* token);
int btrcWinSocketAccept(void** registry, int listener, int* token);
int btrcWinSocketWait(void** registry, int token, int events, int milliseconds);
int btrcWinSocketReceive(void** registry, int token, char* buffer, int capacity, int* received);
int btrcWinSocketSend(void** registry, int token, char* data, int length, int* sent);
int btrcWinSocketShutdownSend(void** registry, int token);
int btrcWinSocketClose(void** registry, int token);
int btrcWinSocketLocalPort(void** registry, int token);
int btrcWinSocketInheritable(void** registry, int token);
int btrcWinSocketLive(void** registry);
int btrcWinSocketStartups(void** registry);
int btrcWinSocketCleanups(void** registry);
