#import "btrc_app.h"
#import "btrc_app_surface_internal.h"

#ifndef GLFW_INCLUDE_NONE
#define GLFW_INCLUDE_NONE
#endif
#define GLFW_EXPOSE_NATIVE_COCOA
#include <GLFW/glfw3.h>
#include <GLFW/glfw3native.h>
#import <Cocoa/Cocoa.h>
#include <assert.h>
#include <stdio.h>

int main(void) {
    @autoreleasepool {
        unsigned long long app_receipt = 0, window_receipt = 0, surface_receipt = 0;
        unsigned long long app = std_app_create(&app_receipt);
        assert(app && app_receipt);
        unsigned long long window = std_app_window_open(app, "Titlebar verification", 640, 480, &window_receipt);
        assert(window && window_receipt);
        assert(std_app_window_set_titlebar_style(window, window_receipt, BTRC_APP_TITLEBAR_OVERLAY) == BTRC_APP_ERROR_NONE);
        assert(std_app_window_logical_width(window) == 640 && std_app_window_logical_height(window) == 480);
        unsigned long long surface = std_app_surface_create(window, &surface_receipt);
        BtrcAppSurfaceLease* lease = NULL;
        assert(surface && std_app_surface_attach(surface, &lease) == BTRC_APP_ERROR_NONE);
        GLFWwindow* glfw = std_app_surface_glfw(lease);
        NSWindow* native = glfwGetCocoaWindow(glfw);
        assert(native && (native.styleMask & NSWindowStyleMaskFullSizeContentView));
        assert(native.titleVisibility == NSWindowTitleHidden && native.titlebarAppearsTransparent);
        assert(native.contentView.frame.size.height == native.frame.size.height);
        assert([native standardWindowButton:NSWindowCloseButton] && ![native standardWindowButton:NSWindowCloseButton].hidden);
        assert([native standardWindowButton:NSWindowMiniaturizeButton] && ![native standardWindowButton:NSWindowMiniaturizeButton].hidden);
        assert([native standardWindowButton:NSWindowZoomButton] && ![native standardWindowButton:NSWindowZoomButton].hidden);
        glfwSetWindowSize(glfw, 800, 600);
        glfwPollEvents();
        assert(std_app_window_logical_width(window) == 800 && std_app_window_logical_height(window) == 600);
        assert(native.contentView.frame.size.height == native.frame.size.height);
        assert(std_app_window_framebuffer_width(window) > 0 && std_app_window_framebuffer_height(window) > 0);
        assert(std_app_window_set_titlebar_style(window, window_receipt, BTRC_APP_TITLEBAR_STANDARD) == BTRC_APP_ERROR_RESOURCE_BUSY);
        assert(std_app_surface_detach(lease) == BTRC_APP_ERROR_NONE);
        assert(std_app_surface_release(surface, surface_receipt) == BTRC_APP_ERROR_NONE);
        assert(std_app_window_set_titlebar_style(window, window_receipt, BTRC_APP_TITLEBAR_STANDARD) == BTRC_APP_ERROR_NONE);
        assert(!(native.styleMask & NSWindowStyleMaskFullSizeContentView));
        assert(native.titleVisibility == NSWindowTitleVisible && !native.titlebarAppearsTransparent);
        assert(std_app_window_logical_width(window) == 800 && std_app_window_logical_height(window) == 600);
        assert(std_app_window_close(window, window_receipt) == BTRC_APP_ERROR_NONE);
        assert(std_app_close(app, app_receipt) == BTRC_APP_ERROR_NONE);
        puts("PASS: native macOS integrated titlebar, controls, resize, and restoration");
    }
    return 0;
}
