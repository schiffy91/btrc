#import "UI2MacOSSelectCapture.h"
#import <objc/runtime.h>
#include <assert.h>
#include <signal.h>
#include <unistd.h>
// The legacy entry is still what AppKit invokes for an item's advertised AX action.
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
static id willObserver, didObserver;
static NSInteger willSend, didSend;
static NSInteger presentationAttempts;
static NSInteger injectedExceptions;
static void openingTimedOut(int signal) { (void)signal; _exit(124); }
static void failAdmittedClick(id cell, SEL selector, NSRect frame, NSView *view) {
    (void)cell; (void)selector; (void)frame; (void)view;
    injectedExceptions++;
    [NSException raise:@"SelectCaptureSuperclassFailure" format:@"injected admitted selection superclass failure"];
}
static BOOL preventPresentation(id menu, SEL selector, NSMenuItem *item, NSPoint point, NSView *view) {
    (void)menu; (void)selector; (void)item; (void)point; (void)view;
    presentationAttempts++; return NO;
}
// A successful entry may reach native menu setup, but this local fixture never
// permits presentation. Forward the actual provider's delegate before cancelling.
@interface SelectOpeningObserver : NSObject <NSMenuDelegate> {
@public
    id<NSMenuDelegate> original;
    NSInteger openings;
    NSInteger closes;
    NSPopUpButton *nestedButton;
    BOOL nestedAttempted;
}
@end
@implementation SelectOpeningObserver
- (void)menuWillOpen:(NSMenu *)menu {
    openings++;
    if ([original respondsToSelector:_cmd]) [original menuWillOpen:menu];
    // This callback is entered by the real superclass while its first native
    // opening is active. Only the second opening is injected here.
    if (nestedButton && !nestedAttempted) {
        nestedAttempted = YES;
        [nestedButton performClick:nil];
    }
    [menu cancelTracking];
}
- (void)menuDidClose:(NSMenu *)menu {
    closes++;
    if ([original respondsToSelector:_cmd]) [original menuDidClose:menu];
}
- (void)menu:(NSMenu *)menu willHighlightItem:(NSMenuItem *)item {
    if ([original respondsToSelector:_cmd]) [original menu:menu willHighlightItem:item];
}
@end
@implementation BTRCUI2SelectCaptureProbe
+ (NSWindow *)host:(NSView *)view {
    assert([view isKindOfClass:NSPopUpButton.class]);
    [NSApp setActivationPolicy:NSApplicationActivationPolicyProhibited];
    NSWindow *window = [[NSWindow alloc] initWithContentRect:NSMakeRect(-10000, -10000, 240, 100) styleMask:NSWindowStyleMaskBorderless backing:NSBackingStoreBuffered defer:NO];
    window.releasedWhenClosed = NO; window.contentView = view;
    assert(!window.visible && !window.keyWindow); return window;
}
+ (void)finish:(NSWindow *)window {
    assert(!window.visible && !window.keyWindow);
    if (willObserver) { [NSNotificationCenter.defaultCenter removeObserver:willObserver]; willObserver = nil; }
    if (didObserver) { [NSNotificationCenter.defaultCenter removeObserver:didObserver]; didObserver = nil; }
    window.contentView = nil; [window close];
}
+ (void)choose:(NSPopUpButton *)button index:(NSInteger)index { [button.menu performActionForItemAtIndex:index]; }
+ (BOOL)key:(NSPopUpButton *)button index:(NSInteger)index {
    NSMenuItem *item = [button itemAtIndex:index]; item.keyEquivalent = @"b"; item.keyEquivalentModifierMask = 0;
    NSEvent *event = [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint modifierFlags:0 timestamp:0 windowNumber:button.window.windowNumber context:nil characters:@"b" charactersIgnoringModifiers:@"b" isARepeat:NO keyCode:11];
    return [button.menu performKeyEquivalent:event];
}
+ (BOOL)press:(NSMenuItem *)item legacy:(BOOL)legacy pick:(BOOL)pick {
    if (legacy) { [item accessibilityPerformAction:pick ? NSAccessibilityPickAction : NSAccessibilityPressAction]; return YES; }
    return pick ? [item accessibilityPerformPick] : [item accessibilityPerformPress];
}
+ (BOOL)cancel:(NSMenuItem *)item { return [item accessibilityPerformCancel]; }
+ (NSMenuItem *)item:(NSPopUpButton *)button index:(NSInteger)index { return [button itemAtIndex:index]; }
+ (BOOL)state:(NSPopUpButton *)button index:(NSInteger)index {
    [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.01]];
    if (button.indexOfSelectedItem != index || button.window.visible || button.window.keyWindow) { return NO; }
    if (index < 0) { return YES; }
    id exposed = NSAccessibilityUnignoredDescendant(button);
    NSString *value = [exposed accessibilityAttributeValue:NSAccessibilityValueAttribute];
    return [value isEqualToString:[button itemAtIndex:index].title];
}
+ (void)observe:(NSPopUpButton *)button {
    if (willObserver) { [NSNotificationCenter.defaultCenter removeObserver:willObserver]; }
    if (didObserver) { [NSNotificationCenter.defaultCenter removeObserver:didObserver]; }
    willSend = 0; didSend = 0;
    willObserver = [NSNotificationCenter.defaultCenter addObserverForName:NSMenuWillSendActionNotification object:button.menu queue:nil usingBlock:^(NSNotification *note) { (void)note; willSend++; }];
    didObserver = [NSNotificationCenter.defaultCenter addObserverForName:NSMenuDidSendActionNotification object:button.menu queue:nil usingBlock:^(NSNotification *note) { (void)note; didSend++; }];
}
+ (BOOL)notifications:(NSPopUpButton *)button expected:(NSInteger)count {
    [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.01]];
    return !button.window.visible && !button.window.keyWindow && willSend == count && didSend == count;
}
+ (void)opening:(NSPopUpButton *)button route:(NSInteger)route refused:(BOOL)refused nested:(BOOL)nested {
    assert(!button.window.visible && !button.window.keyWindow && !NSApp.active);
    NSMenu *menu = button.menu;
    SEL popup = @selector(popUpMenuPositioningItem:atLocation:inView:);
    Method method = class_getInstanceMethod(NSMenu.class, popup);
    assert(method);
    if (!class_addMethod(menu.class, popup, (IMP)preventPresentation, method_getTypeEncoding(method))) {
        assert(class_getMethodImplementation(menu.class, popup) == (IMP)preventPresentation);
    }
    SelectOpeningObserver *observer = [SelectOpeningObserver new];
    observer->nestedButton = nested ? button : nil;
    observer->original = menu.delegate; menu.delegate = observer;
    NSInteger selected = button.indexOfSelectedItem;
    NSResponder *responder = button.window.firstResponder;
    NSInteger actions = didSend;
    presentationAttempts = 0;
    signal(SIGALRM, openingTimedOut); alarm(4);
    if (route == 0) {
        NSEvent *event = [NSEvent mouseEventWithType:NSEventTypeLeftMouseDown location:NSMakePoint(20,20) modifierFlags:0 timestamp:0 windowNumber:button.window.windowNumber context:nil eventNumber:1 clickCount:1 pressure:1];
        [button mouseDown:event];
    } else if (route == 1) {
        [button performClick:nil];
    } else if (route == 2) {
        (void)[button.cell accessibilityPerformPress];
    } else {
        assert(route == 3); [button.cell accessibilityPerformAction:NSAccessibilityPressAction];
    }
    [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.2]];
    NSInteger opened = observer->openings;
    [NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.1]];
    alarm(0);
    assert(opened == observer->openings && presentationAttempts == 0);
    assert(opened == (nested ? (refused ? 1 : 2) : (refused ? 0 : 1)));
    assert(!nested || observer->nestedAttempted);
    // Cancelling inside willOpen prevents presentation. AppKit does not emit
    // didClose for this path; Escape tracking belongs to the hosted fixture.
    if (!nested) { assert(observer->closes == 0); }
    assert(button.indexOfSelectedItem == selected && button.window.firstResponder == responder && didSend == actions);
    assert(!button.window.visible && !button.window.keyWindow && !NSApp.active);
    menu.delegate = observer->original;
}
+ (void)nestedOpening:(NSPopUpButton *)button refused:(BOOL)refused {
    [self opening:button route:1 refused:refused nested:YES];
}
+ (void)failedSuperclass:(NSPopUpButton *)button {
    assert(!button.window.visible && !button.window.keyWindow && !NSApp.active);
    SEL selector = @selector(performClickWithFrame:inView:);
    Method method = class_getInstanceMethod(NSPopUpButtonCell.class, selector); assert(method);
    IMP previous = method_getImplementation(method);
    NSInteger selected = button.indexOfSelectedItem;
    NSResponder *responder = button.window.firstResponder;
    NSInteger actions = didSend;
    injectedExceptions = 0;
    class_replaceMethod(NSPopUpButtonCell.class, selector, (IMP)failAdmittedClick, method_getTypeEncoding(method));
    signal(SIGALRM, openingTimedOut); alarm(4);
    @try { [button performClick:nil]; }
    @finally {
        class_replaceMethod(NSPopUpButtonCell.class, selector, previous, method_getTypeEncoding(method));
        alarm(0);
    }
    assert(injectedExceptions == 1);
    assert(button.indexOfSelectedItem == selected && button.window.firstResponder == responder && didSend == actions);
    assert(!button.window.visible && !button.window.keyWindow && !NSApp.active);
}
+ (void)refusedOpening:(NSPopUpButton *)button route:(NSInteger)route {
    [self opening:button route:route refused:YES nested:NO];
}
+ (void)cancelledOpening:(NSPopUpButton *)button route:(NSInteger)route {
    [self opening:button route:route refused:NO nested:NO];
}
@end
