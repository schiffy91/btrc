/*
 * btrc native system tray — macOS menu-bar backend (Cocoa, dependency-free).
 *
 * Drives NSStatusBar / NSStatusItem / NSMenu directly. The only dependency is
 * the system Cocoa framework (-framework Cocoa); no third-party libraries.
 *
 * The OS renders the menu-bar icon and the drop-down menu natively (the window
 * server composites them on the GPU). When a menu item is selected, the target
 * records the item's command string; the btrc side pumps the loop with
 * btrc_tray_run_iteration() and runs the command via the UnixShell stdlib.
 *
 * Threading: AppKit requires UI work on the main thread. The btrc consumer is
 * expected to drive the tray from main() (see tray.btrc).
 */
#import "btrc_tray.h"

#import <Cocoa/Cocoa.h>
#include <limits.h>
#include <stdint.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>

/* Pre-10.14 fall-back branches use NSStatusItem.title/image/toolTip, which are
 * deprecated in favor of .button on modern macOS (where the .button path is
 * always taken). Silence the deprecation noise for those legacy branches. */
#pragma clang diagnostic ignored "-Wdeprecated-declarations"

/* ---- Objective-C target that owns the menu + activation state ---- */
@interface BtrcTrayTarget : NSObject {
@public
    NSStatusItem* statusItem;
    NSMenu*       menu;
    NSString*     title;
    char*         pendingCommand;         /* last activated command (C-owned) */
    char*         returnedCommand;        /* last command returned to C caller */
    atomic_bool   shouldQuit;
}
- (void)onItem:(id)sender;
@end

@implementation BtrcTrayTarget
- (instancetype)init {
    self = [super init];
    if (self) {
        self->statusItem = nil;
        self->menu = nil;
        self->title = @"";
        self->pendingCommand = NULL;
        self->returnedCommand = NULL;
        atomic_init(&self->shouldQuit, false);
    }
    return self;
}

/* A menu item was clicked: copy its command into a C-owned buffer. The item's
 * representedObject holds the command NSString set in btrc_tray_add_item. */
- (void)onItem:(id)sender {
    NSMenuItem* item = (NSMenuItem*)sender;
    NSString* cmd = (NSString*)[item representedObject];
    if (cmd == nil) { return; }
    const char* utf8 = [cmd UTF8String];
    if (utf8 == NULL) { return; }
    size_t length = strlen(utf8);
    if (length == SIZE_MAX) { return; }
    size_t size = length + 1;
    char* replacement = (char*)malloc(size);
    if (!replacement) { return; }
    memcpy(replacement, utf8, size);
    free(self->pendingCommand);
    self->pendingCommand = replacement;
}
@end

/* Ensure there is an NSApplication configured as a menu-bar accessory (no Dock
 * icon, no main window). Safe to call repeatedly. */
static void btrc_tray_ensure_app(void) {
    @autoreleasepool {
        NSApplication* app = [NSApplication sharedApplication];
        /* Accessory: lives in the menu bar only, no Dock tile / app menu. */
        [app setActivationPolicy:NSApplicationActivationPolicyAccessory];
    }
}

void* btrc_tray_create(char* title) {
    @autoreleasepool {
        btrc_tray_ensure_app();
        NSStatusBar* bar = [NSStatusBar systemStatusBar];
        if (bar == nil) { return NULL; }
        BtrcTrayTarget* t = [[BtrcTrayTarget alloc] init];
        if (t == nil) { return NULL; }
        t->statusItem = [bar statusItemWithLength:NSVariableStatusItemLength];
        if (t->statusItem == nil) { return NULL; }
        NSString* ttl = title ? [NSString stringWithUTF8String:title] : @"";
        if (ttl == nil) { ttl = @""; }
        t->title = ttl;
        /* Show the title text until/unless an icon is set. */
        if ([t->statusItem respondsToSelector:@selector(button)] &&
            t->statusItem.button != nil) {
            t->statusItem.button.title = ttl;
        } else {
            t->statusItem.title = ttl;
        }
        t->menu = [[NSMenu alloc] initWithTitle:ttl];
        if (t->menu == nil) {
            [bar removeStatusItem:t->statusItem];
            t->statusItem = nil;
            return NULL;
        }
        [t->menu setAutoenablesItems:NO];
        /* Retain across the C boundary; released in btrc_tray_destroy. */
        return (void*)CFBridgingRetain(t);
    }
}

void btrc_tray_set_icon(void* tray, char* icon_path) {
    if (!tray) { return; }
    @autoreleasepool {
        BtrcTrayTarget* t = (__bridge BtrcTrayTarget*)tray;
        NSString* path = (icon_path && icon_path[0])
            ? [NSString stringWithUTF8String:icon_path]
            : nil;
        NSImage* img = path ? [[NSImage alloc] initWithContentsOfFile:path] : nil;
        if (img == nil) {
            if ([t->statusItem respondsToSelector:@selector(button)] &&
                t->statusItem.button != nil) {
                t->statusItem.button.image = nil;
                t->statusItem.button.title = t->title;
            } else {
                t->statusItem.image = nil;
                t->statusItem.title = t->title;
            }
            return;
        }
        /* Template images render as crisp monochrome menu-bar glyphs that adapt
         * to light/dark mode; scale to the standard 18pt menu-bar height. */
        [img setTemplate:YES];
        [img setSize:NSMakeSize(18, 18)];
        if ([t->statusItem respondsToSelector:@selector(button)] &&
            t->statusItem.button != nil) {
            t->statusItem.button.image = img;
            t->statusItem.button.title = @"";
        } else {
            t->statusItem.image = img;
            t->statusItem.title = @"";
        }
    }
}

void btrc_tray_set_tooltip(void* tray, char* tooltip) {
    if (!tray) { return; }
    @autoreleasepool {
        BtrcTrayTarget* t = (__bridge BtrcTrayTarget*)tray;
        NSString* tip = tooltip ? [NSString stringWithUTF8String:tooltip] : @"";
        if (tip == nil) { tip = @""; }
        if ([t->statusItem respondsToSelector:@selector(button)] &&
            t->statusItem.button != nil) {
            t->statusItem.button.toolTip = tip;
        } else {
            t->statusItem.toolTip = tip;
        }
    }
}

int btrc_tray_add_item(void* tray, char* label, char* command, bool enabled) {
    if (!tray) { return -1; }
    @autoreleasepool {
        BtrcTrayTarget* t = (__bridge BtrcTrayTarget*)tray;
        if (t->menu == nil || [t->menu numberOfItems] >= INT_MAX) { return -1; }
        NSString* lbl = label ? [NSString stringWithUTF8String:label] : @"";
        NSString* cmd = command ? [NSString stringWithUTF8String:command] : @"";
        if (lbl == nil) { lbl = @""; }
        if (cmd == nil) { cmd = @""; }
        NSMenuItem* item = [[NSMenuItem alloc] initWithTitle:lbl
                                                      action:@selector(onItem:)
                                               keyEquivalent:@""];
        if (item == nil) { return -1; }
        [item setTarget:t];
        [item setRepresentedObject:cmd];
        [item setEnabled:(enabled ? YES : NO)];
        [t->menu addItem:item];
        return (int)([t->menu numberOfItems] - 1);
    }
}

void btrc_tray_add_separator(void* tray) {
    if (!tray) { return; }
    @autoreleasepool {
        BtrcTrayTarget* t = (__bridge BtrcTrayTarget*)tray;
        [t->menu addItem:[NSMenuItem separatorItem]];
    }
}

void btrc_tray_set_menu(void* tray) {
    if (!tray) { return; }
    @autoreleasepool {
        BtrcTrayTarget* t = (__bridge BtrcTrayTarget*)tray;
        [t->statusItem setMenu:t->menu];
    }
}

bool btrc_tray_show(void* tray) {
    if (!tray) { return false; }
    @autoreleasepool {
        BtrcTrayTarget* t = (__bridge BtrcTrayTarget*)tray;
        if (t->statusItem == nil) { return false; }
        [t->statusItem setVisible:YES];
        return true;
    }
}

bool btrc_tray_run_iteration(void* tray, int timeout_ms) {
    if (!tray) { return false; }
    @autoreleasepool {
        BtrcTrayTarget* t = (__bridge BtrcTrayTarget*)tray;
        if (atomic_load_explicit(&t->shouldQuit, memory_order_acquire)) {
            return false;
        }
        NSApplication* app = [NSApplication sharedApplication];
        NSDate* until;
        if (timeout_ms < 0) {
            until = [NSDate distantFuture];
        } else {
            until = [NSDate dateWithTimeIntervalSinceNow:(timeout_ms / 1000.0)];
        }
        /* Pump every pending event (menu clicks dispatch the target action). */
        NSEvent* ev;
        while ((ev = [app nextEventMatchingMask:NSEventMaskAny
                                      untilDate:until
                                         inMode:NSDefaultRunLoopMode
                                        dequeue:YES]) != nil) {
            [app sendEvent:ev];
            until = [NSDate dateWithTimeIntervalSinceNow:0];  /* drain backlog */
        }
        return !atomic_load_explicit(&t->shouldQuit, memory_order_acquire);
    }
}

char* btrc_tray_take_command(void* tray) {
    if (!tray) { return NULL; }
    BtrcTrayTarget* t = (__bridge BtrcTrayTarget*)tray;
    if (t->returnedCommand) {
        free(t->returnedCommand);
        t->returnedCommand = NULL;
    }
    t->returnedCommand = t->pendingCommand;
    t->pendingCommand = NULL;
    return t->returnedCommand;
}

bool btrc_tray_should_quit(void* tray) {
    if (!tray) { return true; }
    BtrcTrayTarget* t = (__bridge BtrcTrayTarget*)tray;
    return atomic_load_explicit(&t->shouldQuit, memory_order_acquire);
}

void btrc_tray_request_quit(void* tray) {
    if (!tray) { return; }
    @autoreleasepool {
        BtrcTrayTarget* t = (__bridge BtrcTrayTarget*)tray;
        atomic_store_explicit(&t->shouldQuit, true, memory_order_release);
        NSEvent* wake = [NSEvent otherEventWithType:NSEventTypeApplicationDefined
                                          location:NSZeroPoint
                                     modifierFlags:0
                                         timestamp:0
                                      windowNumber:0
                                           context:nil
                                           subtype:0
                                             data1:0
                                             data2:0];
        if (wake) {
            [[NSApplication sharedApplication] postEvent:wake atStart:NO];
        }
    }
}

void btrc_tray_destroy(void* tray) {
    if (!tray) { return; }
    @autoreleasepool {
        BtrcTrayTarget* t = (BtrcTrayTarget*)CFBridgingRelease(tray);
        if (t->statusItem != nil) {
            [[NSStatusBar systemStatusBar] removeStatusItem:t->statusItem];
            t->statusItem = nil;
        }
        if (t->pendingCommand) {
            free(t->pendingCommand);
            t->pendingCommand = NULL;
        }
        if (t->returnedCommand) {
            free(t->returnedCommand);
            t->returnedCommand = NULL;
        }
        t->menu = nil;
        t->title = nil;
        /* CFBridgingRelease transferred ownership; ARC frees `t` here. */
    }
}
