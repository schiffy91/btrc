#import "SelectProbe.h"
#include <stdio.h>
#import <objc/runtime.h>

@implementation UI2SelectProbe {
    NSWindow *_window;
    NSPopUpButton *_button;
    NSTimer *_timer;
    NSHashTable *_receiver;
    NSInteger _opened, _highlights, _actions, _step, _terminal;
    BOOL _inside, _timedOut, _controlDiagnostic;
    NSTimeInterval _deadline;
}
+ (instancetype)create {
    NSApplication *application = NSApplication.sharedApplication;
    NSApplicationActivationPolicy before = application.activationPolicy;
    BOOL accepted = before == NSApplicationActivationPolicyRegular ||
        [application setActivationPolicy:NSApplicationActivationPolicyRegular];
    fprintf(stderr, "select-host policyBefore=%ld policyAccepted=%d policyAfter=%ld active=%d running=%d\n",
        (long)before, accepted, (long)application.activationPolicy, application.active, application.running);
    if (!accepted || application.activationPolicy != NSApplicationActivationPolicyRegular) {
        [NSException raise:NSInternalInconsistencyException format:@"Select host requires regular activation policy"];
    }
    [application finishLaunching];
    fprintf(stderr, "select-host finishLaunching=returned policy=%ld active=%d running=%d\n",
        (long)application.activationPolicy, application.active, application.running);
    UI2SelectProbe *probe = [[self alloc] init];
    probe->_receiver = [[NSHashTable alloc] initWithOptions:NSPointerFunctionsWeakMemory | NSPointerFunctionsObjectPointerPersonality capacity:1];
    probe->_window = [[NSWindow alloc] initWithContentRect:NSMakeRect(120, 120, 400, 180)
        styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
    probe->_window.releasedWhenClosed = NO;
    [probe->_window makeKeyAndOrderFront:nil];
    return [probe autorelease];
}
- (NSView *)parent { return _window.contentView; }
- (void)setTrackingReceiver:(id<UI2SelectTrackingReceiver>)receiver {
    [_receiver removeAllObjects];
    if (receiver) { [_receiver addObject:receiver]; }
}
- (id<UI2SelectTrackingReceiver>)trackingReceiver { return [[_receiver.anyObject retain] autorelease]; }
- (BOOL)inside { return _inside; }
- (BOOL)timedOut { return _timedOut; }
- (NSInteger)opened { return _opened; }
- (NSInteger)highlights { return _highlights; }
- (NSInteger)actions { return _actions; }
- (NSEvent *)key:(unichar)code {
    /* SDK27 HIToolbox/Events.h: kVK_ANSI_B=0x0B, Return=0x24,
     * Space=0x31, Escape=0x35. Characters alone are not a physical key. */
    unsigned short keyCode;
    switch (code) {
        case 'b': keyCode = 11; break;
        case '\r': keyCode = 36; break;
        case ' ': keyCode = 49; break;
        case 0x1b: keyCode = 53; break;
        default: [NSException raise:NSInvalidArgumentException format:@"Unsupported Select probe key"]; return nil;
    }
    NSString *text = [NSString stringWithCharacters:&code length:1];
    return [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint modifierFlags:0
        timestamp:NSProcessInfo.processInfo.systemUptime windowNumber:_window.windowNumber context:nil
        characters:text charactersIgnoringModifiers:text isARepeat:NO keyCode:keyCode];
}
- (void)began:(NSNotification *)notice {
    (void)notice; _opened++;
    fprintf(stderr, "select-native begin inside=%d selected=%ld\n", _inside, (long)_button.indexOfSelectedItem);
}
- (void)action:(NSNotification *)notice {
    (void)notice; _actions++;
    fprintf(stderr, "select-native action inside=%d highlighted=%ld selected=%ld\n", _inside,
        (long)[_button.menu indexOfItem:_button.menu.highlightedItem], (long)_button.indexOfSelectedItem);
}
- (void)ended:(NSNotification *)notice {
    (void)notice;
    fprintf(stderr, "select-native end inside=%d selected=%ld\n", _inside, (long)_button.indexOfSelectedItem);
}
- (void)tick:(NSTimer *)timer {
    (void)timer;
    if (NSProcessInfo.processInfo.systemUptime >= _deadline) {
        _timedOut = YES;
        fprintf(stderr, "select-native timeout opened=%ld step=%ld\n", (long)_opened, (long)_step);
        [_button.menu cancelTrackingWithoutAnimation];
        return;
    }
    if (!_opened) { return; }
    if (_step == 0) {
        _step = 1;
        [NSApp postEvent:[self key:'b'] atStart:NO];
    } else if (_step == 1 && [_button.menu indexOfItem:_button.menu.highlightedItem] == 1) {
        _step = 2; _highlights++;
        fprintf(stderr, "select-native highlight inside=%d index=1\n", _inside);
        // This is an actual native tracking observation, not a semantic injection.
        if (!_controlDiagnostic) { [[self trackingReceiver] highlighted]; }
        if (_terminal != 2) { [NSApp postEvent:[self key:_terminal == 1 ? 0x1b : '\r'] atStart:NO]; }
    }
}
- (void)standardAction:(id)sender { (void)sender; }
- (void)standardKeyboardControl:(NSPopUpButton *)provider {
    NSPopUpButton *control = [[NSPopUpButton alloc] initWithFrame:provider.frame pullsDown:NO];
    if (!control) { [NSException raise:NSMallocException format:@"Cannot create matched native popup"]; }
    _controlDiagnostic = YES;
    @try {
        control.autoenablesItems = NO;
        NSMenu *menu = [[[NSMenu alloc] initWithTitle:provider.menu.title] autorelease];
        if (!menu) { [NSException raise:NSMallocException format:@"Cannot create matched native menu"]; }
        menu.autoenablesItems = NO;
        for (NSMenuItem *item in provider.menu.itemArray) {
            NSMenuItem *copy = [menu addItemWithTitle:item.title action:NULL keyEquivalent:@""];
            copy.enabled = item.enabled;
        }
        control.menu = menu;
        [control selectItemAtIndex:provider.indexOfSelectedItem];
        control.enabled = provider.enabled;
        control.font = provider.font;
        control.controlSize = provider.controlSize;
        control.target = self;
        control.action = @selector(standardAction:);
        [provider.superview addSubview:control];
        fprintf(stderr, "select-keyboard matched-standard begin\n");
        [self journey:control mode:2 terminal:0];
        fprintf(stderr, "select-keyboard matched-standard result opened=%ld highlights=%ld actions=%ld selected=%ld timeout=%d\n",
            (long)_opened, (long)_highlights, (long)_actions, (long)control.indexOfSelectedItem, _timedOut);
    } @finally {
        [control removeFromSuperview];
        [control release];
        _controlDiagnostic = NO;
    }
}
- (void)journey:(NSView *)view mode:(NSInteger)mode terminal:(NSInteger)terminal {
    if (_inside || ![view isKindOfClass:NSPopUpButton.class] || view.window != _window) {
        [NSException raise:NSInternalInconsistencyException format:@"Select probe requires its mounted native popup"];
    }
    if (mode == 2 && !_controlDiagnostic) { [self standardKeyboardControl:(NSPopUpButton *)view]; }
    if (mode >= 2) {
        BOOL focused = [_window makeFirstResponder:view];
        /* SDK27 permits activation to complete later or be refused. Observe
         * the actual host state while dispatching AppKit events; do not force it. */
        [NSApp activate];
        NSTimeInterval started = NSProcessInfo.processInfo.systemUptime;
        NSTimeInterval deadline = started + 3.0;
        NSUInteger dispatched = 0;
        while (focused && (!NSApp.active || !_window.keyWindow || _window.firstResponder != view) &&
                NSProcessInfo.processInfo.systemUptime < deadline) {
            NSTimeInterval remaining = deadline - NSProcessInfo.processInfo.systemUptime;
            if (remaining <= 0) { break; }
            NSEvent *event = [NSApp nextEventMatchingMask:NSEventMaskAny
                untilDate:[NSDate dateWithTimeIntervalSinceNow:MIN(0.01, remaining)]
                inMode:NSDefaultRunLoopMode dequeue:YES];
            if (event) { [NSApp sendEvent:event]; dispatched++; }
            [NSApp updateWindows];
        }
        fprintf(stderr, "select-host keyboardReady=%d policy=%ld waited=%.6f dispatched=%lu\n",
            focused && NSApp.active && _window.keyWindow && _window.firstResponder == view,
            (long)NSApp.activationPolicy, NSProcessInfo.processInfo.systemUptime - started, (unsigned long)dispatched);
        fprintf(stderr, "select-keyboard class=%s focusAccepted=%d firstResponder=%d accepts=%d keyWindow=%d active=%d keyCode=%u\n",
            class_getName(view.class), focused, _window.firstResponder == view, view.acceptsFirstResponder,
            _window.keyWindow, NSApp.active, (unsigned int)[self key:mode == 3 ? 'b' : ' '].keyCode);
        if (!focused || !NSApp.active || !_window.keyWindow || _window.firstResponder != view) {
            [NSException raise:NSInternalInconsistencyException format:@"Select keyboard probe requires active app, key window and actual first responder"];
        }
    }
    _button = (NSPopUpButton *)view; _terminal = terminal;
    _opened = 0; _highlights = 0; _actions = 0; _step = 0; _timedOut = NO;
    NSNotificationCenter *center = NSNotificationCenter.defaultCenter;
    [center addObserver:self selector:@selector(began:) name:NSMenuDidBeginTrackingNotification object:_button.menu];
    [center addObserver:self selector:@selector(action:) name:NSMenuDidSendActionNotification object:_button.menu];
    [center addObserver:self selector:@selector(ended:) name:NSMenuDidEndTrackingNotification object:_button.menu];
    _deadline = NSProcessInfo.processInfo.systemUptime + 3.0;
    _timer = [[NSTimer timerWithTimeInterval:0.01 target:self selector:@selector(tick:) userInfo:nil repeats:YES] retain];
    [NSRunLoop.mainRunLoop addTimer:_timer forMode:NSEventTrackingRunLoopMode];
    [NSRunLoop.mainRunLoop addTimer:_timer forMode:NSDefaultRunLoopMode];
    _inside = YES;
    @try {
        if (mode == 0) { [_button performClick:nil]; }
        else if (mode == 1) {
            NSPoint point = [_button convertPoint:NSMakePoint(NSMidX(_button.bounds), NSMidY(_button.bounds)) toView:nil];
            NSEvent *event = [NSEvent mouseEventWithType:NSEventTypeLeftMouseDown location:point modifierFlags:0
                timestamp:NSProcessInfo.processInfo.systemUptime windowNumber:_window.windowNumber context:nil
                eventNumber:1 clickCount:1 pressure:1];
            [_button mouseDown:event];
        } else { [_button keyDown:[self key:mode == 3 ? 'b' : ' ']]; }
    } @finally {
        _inside = NO;
        [_timer invalidate]; [_timer release]; _timer = nil;
        [center removeObserver:self];
        fprintf(stderr, "select-native return opened=%ld highlights=%ld actions=%ld selected=%ld timeout=%d\n",
            (long)_opened, (long)_highlights, (long)_actions, (long)_button.indexOfSelectedItem, _timedOut);
        _button = nil;
    }
}
- (void)printable:(NSView *)view { [self journey:view mode:3 terminal:0]; }
- (void)close {
    [_timer invalidate]; [_timer release]; _timer = nil;
    [NSNotificationCenter.defaultCenter removeObserver:self];
    [_receiver removeAllObjects]; [_receiver release]; _receiver = nil;
    [_window orderOut:nil]; [_window close]; [_window release]; _window = nil;
}
- (void)dealloc { [self close]; [super dealloc]; }
@end
