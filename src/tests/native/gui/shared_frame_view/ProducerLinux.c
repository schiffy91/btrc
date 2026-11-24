/* Independent EGL producer for the Linux Library.GUI frame test. */
#define _GNU_SOURCE
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES2/gl2.h>
#include <GLES2/gl2ext.h>
#include <fcntl.h>
#include <gbm.h>
#include "LinuxFramePacket.h"

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

    sendFrame(path, backingFd, width, height, GBM_FORMAT_XRGB8888, gbm_bo_get_stride(bo), format == 1 ? 0 : UINT32_MAX);
    eglDestroyImage(display, backing);
    close(backingFd);
    gbm_bo_destroy(bo);
    glDeleteFramebuffers(1, &fb);
    glDeleteTextures(1, &texture);
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
