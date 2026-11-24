/* Independent EGL producer for the Linux Library.GUI frame test. */
#define _GNU_SOURCE
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES2/gl2.h>
#include <GLES2/gl2ext.h>
#include <endian.h>
#include <errno.h>
#include <fcntl.h>
#include <gbm.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#define REQUIRE(x) do { if (!(x)) { fprintf(stderr, "%s failed at line %d\n", #x, __LINE__); exit(1); } } while (0)

static struct gbm_device* device;
static EGLDisplay display;
static EGLContext context;

static void initialize(const char* renderNode) {
    int drm = open(renderNode, O_RDWR | O_CLOEXEC);
    REQUIRE(drm >= 0);
    device = gbm_create_device(drm);
    REQUIRE(device);
    display = eglGetPlatformDisplay(EGL_PLATFORM_GBM_KHR, device, NULL);
    REQUIRE(eglInitialize(display, NULL, NULL));
    REQUIRE(eglBindAPI(EGL_OPENGL_ES_API));
    EGLint attrs[] = { EGL_RENDERABLE_TYPE, EGL_OPENGL_ES2_BIT, EGL_SURFACE_TYPE, 0, EGL_NONE };
    EGLConfig config;
    EGLint count;
    REQUIRE(eglChooseConfig(display, attrs, &config, 1, &count) && count == 1);
    EGLint version[] = { EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE };
    context = eglCreateContext(display, config, EGL_NO_CONTEXT, version);
    REQUIRE(context != EGL_NO_CONTEXT);
    REQUIRE(eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, context));
    fprintf(stderr, "Producer renderer %s\n", glGetString(GL_RENDERER));
}

static void deliver(const char* path, unsigned width, unsigned format) {
    unsigned height = width / 2;
    GLuint texture, fb;
    glGenTextures(1, &texture);
    glBindTexture(GL_TEXTURE_2D, texture);
    struct gbm_bo* bo = gbm_bo_create(device, width, height, GBM_FORMAT_XRGB8888, GBM_BO_USE_RENDERING | GBM_BO_USE_SCANOUT | GBM_BO_USE_LINEAR);
    REQUIRE(bo);
    int backingFd = gbm_bo_get_fd(bo);
    REQUIRE(backingFd >= 0);
    REQUIRE(gbm_bo_get_plane_count(bo) == 1 && gbm_bo_get_modifier(bo) == 0);
    EGLAttrib attrs[] = { EGL_WIDTH, width, EGL_HEIGHT, height, EGL_LINUX_DRM_FOURCC_EXT, GBM_FORMAT_XRGB8888,
        EGL_DMA_BUF_PLANE0_FD_EXT, backingFd, EGL_DMA_BUF_PLANE0_OFFSET_EXT, 0, EGL_DMA_BUF_PLANE0_PITCH_EXT, gbm_bo_get_stride(bo), EGL_NONE };
    EGLImage backing = eglCreateImage(display, EGL_NO_CONTEXT, EGL_LINUX_DMA_BUF_EXT, NULL, attrs);
    REQUIRE(backing != EGL_NO_IMAGE);
    PFNGLEGLIMAGETARGETTEXTURE2DOESPROC target = (PFNGLEGLIMAGETARGETTEXTURE2DOESPROC)eglGetProcAddress("glEGLImageTargetTexture2DOES");
    REQUIRE(target);
    target(GL_TEXTURE_2D, backing);
    glGenFramebuffers(1, &fb);
    glBindFramebuffer(GL_FRAMEBUFFER, fb);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, texture, 0);
    REQUIRE(glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE);
    glClearColor(0, 0, 1, 1);
    glClear(GL_COLOR_BUFFER_BIT);
    glEnable(GL_SCISSOR_TEST);
    glScissor(0, 0, width, height / 2);
    glClearColor(1, 0, 0, 1);
    glClear(GL_COLOR_BUFFER_BIT);
    glDisable(GL_SCISSOR_TEST);
    glFinish();
    REQUIRE(glGetError() == GL_NO_ERROR);

    /* Encode one linear XRGB plane independently of the receiver. An invalid
     * request points past the end of a real DMA-BUF of the right format. */
    uint32_t words[16] = { 0, htole32(width), htole32(height), htole32(GBM_FORMAT_XRGB8888),
                           0, 0, htole32(1), 0, htole32(gbm_bo_get_stride(bo)),
                           format == 1 ? 0 : UINT32_MAX };
    memcpy(words, "BTF1", 4);
    struct sockaddr_un peer = { .sun_family = AF_UNIX };
    REQUIRE(strlen(path) < sizeof peer.sun_path);
    strcpy(peer.sun_path, path);
    struct iovec payload = {words, sizeof words};
    union { struct cmsghdr align; char bytes[CMSG_SPACE(sizeof backingFd)]; } control;
    struct msghdr msg = { .msg_name = &peer, .msg_namelen = sizeof peer, .msg_iov = &payload, .msg_iovlen = 1,
        .msg_control = control.bytes, .msg_controllen = CMSG_SPACE(sizeof backingFd) };
    struct cmsghdr* c = CMSG_FIRSTHDR(&msg);
    c->cmsg_level = SOL_SOCKET;
    c->cmsg_type = SCM_RIGHTS;
    c->cmsg_len = CMSG_LEN(sizeof backingFd);
    memcpy(CMSG_DATA(c), &backingFd, sizeof backingFd);
    int sock = socket(AF_UNIX, SOCK_DGRAM | SOCK_CLOEXEC, 0);
    REQUIRE(sock >= 0);
    ssize_t size = sendmsg(sock, &msg, MSG_DONTWAIT);
    if (size < 0 && (errno == ENOENT || errno == ECONNREFUSED)) { puts("closed"); }
    else { REQUIRE(size == sizeof words); puts("sent"); }
    close(sock);
    eglDestroyImage(display, backing);
    close(backingFd);
    gbm_bo_destroy(bo);
    glDeleteFramebuffers(1, &fb);
    glDeleteTextures(1, &texture);
    fflush(stdout);
}

int main(int argc, char** argv) {
    REQUIRE(argc == 2);
    initialize(argv[1]);
    char address[108];
    unsigned width, format;
    while (scanf("%107s %u %u", address, &width, &format) == 3) {
        REQUIRE(width == 320 || width == 640);
        deliver(address, width, format);
    }
    return 0;
}
