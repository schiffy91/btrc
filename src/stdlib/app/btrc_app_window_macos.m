#import "btrc_app.h"
#import "btrc_app_window_internal.h"

#ifndef GLFW_INCLUDE_NONE
#define GLFW_INCLUDE_NONE
#endif
#define GLFW_EXPOSE_NATIVE_COCOA
#include <GLFW/glfw3.h>
#include <GLFW/glfw3native.h>
#import <Cocoa/Cocoa.h>
#include <limits.h>

int btrc_app_platform_click_count(GLFWwindow* window) {
    if (![NSThread isMainThread] || !window) { return 1; }
    NSEvent* event = NSApp.currentEvent;
    if (!event || event.window != glfwGetCocoaWindow(window)) { return 1; }
    NSEventType type = event.type;
    if (type != NSEventTypeLeftMouseDown && type != NSEventTypeLeftMouseUp &&
        type != NSEventTypeRightMouseDown && type != NSEventTypeRightMouseUp &&
        type != NSEventTypeOtherMouseDown && type != NSEventTypeOtherMouseUp) { return 1; }
    NSInteger count = event.clickCount;
    return count > INT_MAX ? INT_MAX : (count > 0 ? (int)count : 1);
}

int btrc_app_platform_set_titlebar_style(GLFWwindow* window, int style) {
    if (![NSThread isMainThread]) { return BTRC_APP_ERROR_NOT_MAIN_THREAD; }
    if (!window || (style != BTRC_APP_TITLEBAR_STANDARD && style != BTRC_APP_TITLEBAR_OVERLAY)) { return BTRC_APP_ERROR_INVALID_ARGUMENT; }
    @autoreleasepool {
        NSWindow* native = glfwGetCocoaWindow(window);
        if (!native || !native.contentView) { return BTRC_APP_ERROR_INTERNAL; }
        NSSize contentSize = native.contentView.frame.size;
        BOOL overlay = style == BTRC_APP_TITLEBAR_OVERLAY;
        native.styleMask = overlay ? native.styleMask | NSWindowStyleMaskFullSizeContentView : native.styleMask & ~NSWindowStyleMaskFullSizeContentView;
        native.titleVisibility = overlay ? NSWindowTitleHidden : NSWindowTitleVisible;
        native.titlebarAppearsTransparent = overlay;
        /* Style-mask changes otherwise add/remove title-bar height from the
         * logical viewport, shifting layout and pointer coordinates. */
        [native setContentSize:contentSize];
        return BTRC_APP_ERROR_NONE;
    }
}
