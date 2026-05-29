/*
 * btrc GUI — native window backend (GLFW + legacy GL). See btrc_gui_window.h.
 *
 * The software surface is uploaded each frame with glDrawPixels using
 * GL_UNSIGNED_INT_8_8_8_8, which maps each 0xRRGGBBAA word to RGBA regardless
 * of host endianness; glPixelZoom(1,-1) flips to top-left origin.
 */
#include "btrc_gui_window.h"
#include "btrc_gui.h"
#include <stdlib.h>

#define GLFW_INCLUDE_NONE
#ifndef GL_SILENCE_DEPRECATION
#define GL_SILENCE_DEPRECATION
#endif
#include <GLFW/glfw3.h>
#if defined(__APPLE__)
#  include <OpenGL/gl.h>
#else
#  include <GL/gl.h>
#endif

typedef struct {
    GLFWwindow* win;
    unsigned int tex;   /* GPU texture the software surface is uploaded into */
    int mouse_x;
    int mouse_y;
    bool mouse_down;
} btrc_window;

static int g_glfw_inited = 0;

void* btrc_gui_window_open(char* title, int width, int height) {
    if (!g_glfw_inited) {
        if (!glfwInit()) { return NULL; }
        g_glfw_inited = 1;
    }
    glfwWindowHint(GLFW_RESIZABLE, GLFW_TRUE);
    GLFWwindow* w = glfwCreateWindow(width, height, title ? title : "btrc", NULL, NULL);
    if (!w) { return NULL; }
    glfwMakeContextCurrent(w);
    glfwSwapInterval(1);
    btrc_window* bw = (btrc_window*)malloc(sizeof(btrc_window));
    if (!bw) { glfwDestroyWindow(w); return NULL; }
    bw->win = w;
    bw->mouse_x = 0;
    bw->mouse_y = 0;
    bw->mouse_down = false;
    /* Create the GPU texture used to present the surface (hardware sampling). */
    glGenTextures(1, &bw->tex);
    glBindTexture(GL_TEXTURE_2D, bw->tex);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glBindTexture(GL_TEXTURE_2D, 0);
    return (void*)bw;
}

bool btrc_gui_window_should_close(void* winv) {
    btrc_window* bw = (btrc_window*)winv;
    if (!bw) { return true; }
    return glfwWindowShouldClose(bw->win) != 0;
}

void btrc_gui_window_poll(void* winv) {
    btrc_window* bw = (btrc_window*)winv;
    if (!bw) { return; }
    glfwPollEvents();
    double mx = 0, my = 0;
    glfwGetCursorPos(bw->win, &mx, &my);
    bw->mouse_x = (int)mx;
    bw->mouse_y = (int)my;
    bw->mouse_down = glfwGetMouseButton(bw->win, GLFW_MOUSE_BUTTON_LEFT) == GLFW_PRESS;
}

int  btrc_gui_window_mouse_x(void* winv)   { btrc_window* bw=(btrc_window*)winv; return bw ? bw->mouse_x : -1; }
int  btrc_gui_window_mouse_y(void* winv)   { btrc_window* bw=(btrc_window*)winv; return bw ? bw->mouse_y : -1; }
bool btrc_gui_window_mouse_down(void* winv){ btrc_window* bw=(btrc_window*)winv; return bw ? bw->mouse_down : false; }

int btrc_gui_window_fb_width(void* winv) {
    btrc_window* bw = (btrc_window*)winv;
    if (!bw) { return 0; }
    int w = 0, h = 0; glfwGetFramebufferSize(bw->win, &w, &h); return w;
}
int btrc_gui_window_fb_height(void* winv) {
    btrc_window* bw = (btrc_window*)winv;
    if (!bw) { return 0; }
    int w = 0, h = 0; glfwGetFramebufferSize(bw->win, &w, &h); return h;
}

void btrc_gui_window_present(void* winv, void* surface) {
    btrc_window* bw = (btrc_window*)winv;
    if (!bw || !surface) { return; }
    int sw = btrc_gui_surface_width(surface);
    int sh = btrc_gui_surface_height(surface);
    void* px = btrc_gui_surface_pixels(surface);
    int fbw = 0, fbh = 0;
    glfwGetFramebufferSize(bw->win, &fbw, &fbh);
    glViewport(0, 0, fbw, fbh);
    glClearColor(0, 0, 0, 1);
    glClear(GL_COLOR_BUFFER_BIT);
    /* Upload the CPU surface into the GPU texture and let the hardware sample +
     * composite it onto a fullscreen quad. Texture v runs top→bottom to match
     * the surface's top-left origin; bilinear filtering scales it for free. */
    glEnable(GL_TEXTURE_2D);
    glBindTexture(GL_TEXTURE_2D, bw->tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, sw, sh, 0,
                 GL_RGBA, GL_UNSIGNED_INT_8_8_8_8, px);
    glBegin(GL_QUADS);
    glTexCoord2f(0.0f, 0.0f); glVertex2f(-1.0f,  1.0f);
    glTexCoord2f(1.0f, 0.0f); glVertex2f( 1.0f,  1.0f);
    glTexCoord2f(1.0f, 1.0f); glVertex2f( 1.0f, -1.0f);
    glTexCoord2f(0.0f, 1.0f); glVertex2f(-1.0f, -1.0f);
    glEnd();
    glBindTexture(GL_TEXTURE_2D, 0);
    glfwSwapBuffers(bw->win);
}

void btrc_gui_window_close(void* winv) {
    btrc_window* bw = (btrc_window*)winv;
    if (!bw) { return; }
    if (bw->tex) { glDeleteTextures(1, &bw->tex); }
    if (bw->win) { glfwDestroyWindow(bw->win); }
    free(bw);
}
