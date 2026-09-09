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
#include <stdlib.h>

static NSButton* alert_button(NSView* view) {
    if ([view isKindOfClass:[NSButton class]] && [((NSButton*)view).title isEqualToString:@"OK"]) { return (NSButton*)view; }
    for (NSView* child in view.subviews) {
        NSButton* button = alert_button(child);
        if (button) { return button; }
    }
    return nil;
}

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
        assert(std_app_window_show_alert(window, window_receipt, "Settings could not be applied", "Audio device change is deferred while the player is active.") == BTRC_APP_ERROR_NONE);
        NSWindow* sheet = native.attachedSheet;
        assert(sheet && sheet.sheetParent == native);
        assert(std_app_window_show_alert(window, window_receipt, "Another error", "Preserve the first sheet") == BTRC_APP_ERROR_RESOURCE_BUSY);
        while (std_app_poll(app) != BTRC_APP_EVENT_IDLE) { }
        NSButton* acknowledge = alert_button(sheet.contentView);
        assert(acknowledge);
        const char* capture_path = getenv("BTRC_APP_ALERT_CAPTURE");
        if (capture_path) {
            NSView* content = sheet.contentView;
            [content displayIfNeeded];
            NSBitmapImageRep* image = [content bitmapImageRepForCachingDisplayInRect:content.bounds];
            [content cacheDisplayInRect:content.bounds toBitmapImageRep:image];
            NSData* png = [image representationUsingType:NSBitmapImageFileTypePNG properties:@{}];
            assert([png writeToFile:[NSString stringWithUTF8String:capture_path] atomically:YES]);
        }
        [acknowledge performClick:nil];
        NSDate* deadline = [NSDate dateWithTimeIntervalSinceNow:3.0];
        while (native.attachedSheet && deadline.timeIntervalSinceNow > 0.0) { [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.01]]; }
        assert(!native.attachedSheet);
        assert(native && (native.styleMask & NSWindowStyleMaskFullSizeContentView));
        assert(native.titleVisibility == NSWindowTitleHidden && native.titlebarAppearsTransparent);
        assert(native.contentView.frame.size.height == native.frame.size.height);
        while (std_app_poll(app) != BTRC_APP_EVENT_IDLE) { }
        for (NSInteger clicks = 1; clicks <= 3; ++clicks) {
            NSEvent* down = [NSEvent mouseEventWithType:NSEventTypeLeftMouseDown location:NSMakePoint(100, 100) modifierFlags:0 timestamp:NSProcessInfo.processInfo.systemUptime windowNumber:native.windowNumber context:nil eventNumber:clicks clickCount:clicks pressure:1.0];
            NSEvent* up = [NSEvent mouseEventWithType:NSEventTypeLeftMouseUp location:NSMakePoint(100, 100) modifierFlags:0 timestamp:NSProcessInfo.processInfo.systemUptime windowNumber:native.windowNumber context:nil eventNumber:clicks clickCount:clicks pressure:0.0];
            [NSApp postEvent:down atStart:NO];
            [NSApp postEvent:up atStart:NO];
            int presses = 0;
            int releases = 0;
            int kind;
            while ((kind = std_app_poll(app)) != BTRC_APP_EVENT_IDLE) {
                if (kind != BTRC_APP_EVENT_POINTER || std_app_event_pointer_button(app) != BTRC_APP_BUTTON_PRIMARY) { continue; }
                assert(std_app_event_pointer_click_count(app) == clicks);
                if (std_app_event_pointer_action(app) == BTRC_APP_POINTER_PRESSED) { ++presses; }
                if (std_app_event_pointer_action(app) == BTRC_APP_POINTER_RELEASED) { ++releases; }
            }
            assert(presses == 1 && releases == 1);
        }
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
        assert(std_app_window_show_alert(window, window_receipt, "Closing", "Closing the window dismisses its sheet") == BTRC_APP_ERROR_NONE);
        [native retain];
        assert(std_app_window_close(window, window_receipt) == BTRC_APP_ERROR_NONE);
        assert(!native.attachedSheet);
        [native release];
        assert(std_app_close(app, app_receipt) == BTRC_APP_ERROR_NONE);
        puts("PASS: native macOS integrated titlebar, controls, resize, and restoration");
    }
    return 0;
}
