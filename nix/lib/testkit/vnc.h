#ifndef BTRC_TESTKIT_VNC_H
#define BTRC_TESTKIT_VNC_H
#include <rfb/rfbclient.h>
#include <stdlib.h>
#include <stdint.h>
#include <sys/socket.h>
#include <sys/time.h>
/* libvncclient owns the RFB protocol. The copied raster has a fixed RGBA
 * format; no native pointer escapes into a test observation. */
typedef struct TestVNC { rfbClient *client; int finished; } TestVNC;
static inline void *testVNCTagAddress(void) { static int testVNCTag; return &testVNCTag; }
static inline rfbBool testVNCAllocate(rfbClient *client) {
    if (client->width <= 0 || client->height <= 0 || client->width > 8192 || client->height > 8192 || (uint64_t)client->width * client->height > 16777216) return FALSE;
    unsigned char *frame = calloc((size_t)client->width * client->height, 4);
    if (!frame) return FALSE;
    free(client->frameBuffer); client->frameBuffer = frame; return TRUE;
}
static inline void testVNCFinished(rfbClient *client) {
    TestVNC *session = rfbClientGetClientData(client, testVNCTagAddress());
    if (session) session->finished = 1;
}
static inline void testVNCClose(TestVNC *session) {
    if (!session) return;
    if (session->client) { free(session->client->frameBuffer); session->client->frameBuffer = NULL; rfbClientCleanup(session->client); }
    free(session);
}
static inline TestVNC *testVNCOpen(const char *path) {
    TestVNC *session = calloc(1, sizeof(*session));
    if (!session) return NULL;
    rfbClient *client = rfbGetClient(8, 3, 4); session->client = client;
    if (!client) { testVNCClose(session); return NULL; }
    client->sock = ConnectClientToUnixSockWithTimeout(path, 5);
    if (client->sock == RFB_INVALID_SOCKET) { testVNCClose(session); return NULL; }
    SetBlocking(client->sock);
    struct timeval timeout = { .tv_sec = 5 };
    setsockopt(client->sock, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    setsockopt(client->sock, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
    client->MallocFrameBuffer = testVNCAllocate;
    client->FinishedFrameBufferUpdate = testVNCFinished;
    client->canHandleNewFBSize = TRUE;
    client->appData.encodingsString = "raw";
    client->format.bitsPerPixel = 32; client->format.depth = 24;
    client->format.bigEndian = FALSE; client->format.trueColour = TRUE;
    client->format.redMax = 255; client->format.greenMax = 255; client->format.blueMax = 255;
    client->format.redShift = 0; client->format.greenShift = 8; client->format.blueShift = 16;
    rfbClientSetClientData(client, testVNCTagAddress(), session);
    if (!InitialiseRFBConnection(client)) { testVNCClose(session); return NULL; }
    client->width = client->si.framebufferWidth;
    client->height = client->si.framebufferHeight;
    client->updateRect.x = client->updateRect.y = 0;
    client->updateRect.w = client->width; client->updateRect.h = client->height;
    client->isUpdateRectManagedByLib = TRUE;
    if (!SetFormatAndEncodings(client) || !testVNCAllocate(client)) { testVNCClose(session); return NULL; }
    return session;
}
static inline int testVNCRequest(TestVNC *session) {
    session->finished = 0;
    return SendFramebufferUpdateRequest(session->client, 0, 0, session->client->width, session->client->height, FALSE);
}
static inline int testVNCStep(TestVNC *session, int milliseconds) {
    int ready = session->client->buffered > 0 ? 1 : WaitForMessage(session->client, milliseconds * 1000);
    if (ready < 0) return -1;
    if (!ready) return 0;
    session->finished = 0;
    if (!HandleRFBServerMessage(session->client)) return -1;
    return session->finished ? 2 : 1;
}
static inline int testVNCWidth(TestVNC *session) { return session->client->width; }
static inline int testVNCHeight(TestVNC *session) { return session->client->height; }
static inline int testVNCLength(TestVNC *session) { return session->client->width * session->client->height * 4; }
static inline const unsigned char *testVNCPixels(TestVNC *session) {
    for (int i = 3; i < testVNCLength(session); i += 4) session->client->frameBuffer[i] = 255;
    return session->client->frameBuffer;
}
#endif
