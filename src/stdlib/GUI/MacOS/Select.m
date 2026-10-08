#import "Select.h"

@implementation BTRCMacOSSelect {
    __weak id<BTRCMacOSSelectEvents> _semanticEvents;
    NSUInteger _trackingDepth;
    BOOL _escape;
}

+ (instancetype)selection {
    BTRCMacOSSelect *control = [[self alloc] initWithFrame:NSZeroRect pullsDown:NO];
    control.autoenablesItems = NO;
    control.target = control;
    control.action = @selector(semanticAction:);
    control.menu.delegate = control;
    return control;
}

- (void)setSemanticEvents:(id<BTRCMacOSSelectEvents>)events { _semanticEvents = events; }
- (id<BTRCMacOSSelectEvents>)semanticEvents { return _semanticEvents; }

- (void)setMenu:(NSMenu *)menu {
    NSMenu *previous = self.menu;
    if (previous.delegate == self) { previous.delegate = nil; }
    [super setMenu:menu];
    menu.delegate = self;
}

- (BOOL)beginTracking {
    if (_trackingDepth != 0) { _trackingDepth++; return YES; }
    id<BTRCMacOSSelectEvents> sink = _semanticEvents;
    if (!sink || ![sink shouldBegin]) { return NO; }
    _trackingDepth = 1;
    _escape = NO;
    return YES;
}

- (void)endTracking {
    if (--_trackingDepth == 0) { [_semanticEvents ended:_escape]; }
}

- (void)mouseDown:(NSEvent *)event {
    if (![self beginTracking]) { return; }
    @try { [super mouseDown:event]; }
    @finally { [self endTracking]; }
}

- (void)performClick:(id)sender {
    if (![self beginTracking]) { return; }
    @try { [super performClick:sender]; }
    @finally { [self endTracking]; }
}

- (void)keyDown:(NSEvent *)event {
    NSString *characters = event.charactersIgnoringModifiers;
    unichar key = characters.length ? [characters characterAtIndex:0] : 0;
    BOOL relevant = key == NSUpArrowFunctionKey || key == NSDownArrowFunctionKey ||
        key == NSLeftArrowFunctionKey || key == NSRightArrowFunctionKey ||
        key == NSHomeFunctionKey || key == NSEndFunctionKey ||
        key == NSPageUpFunctionKey || key == NSPageDownFunctionKey ||
        key == ' ' || key == '\r' || key == '\n' || key == 0x1b;
    if (!relevant) { [super keyDown:event]; return; }
    if (![self beginTracking]) { return; }
    if (key == 0x1b) { _escape = YES; }
    @try { [super keyDown:event]; }
    @finally { [self endTracking]; }
}

- (BOOL)accessibilityPerformPress {
    if (![self beginTracking]) { return NO; }
    @try { [super performClick:nil]; }
    @finally { [self endTracking]; }
    return YES;
}

- (void)menuWillOpen:(NSMenu *)menu {
    if (menu == self.menu && _trackingDepth != 0) { [_semanticEvents opened]; }
}

- (void)menu:(NSMenu *)menu willHighlightItem:(NSMenuItem *)item {
    if (menu != self.menu || _trackingDepth == 0 || !item || !item.enabled) { return; }
    if (![_semanticEvents candidate:[menu indexOfItem:item]]) { [menu cancelTrackingWithoutAnimation]; }
}

- (void)semanticAction:(id)sender {
    (void)sender;
    if (_trackingDepth != 0) { [_semanticEvents accepted:self.indexOfSelectedItem]; }
}

- (void)cancelMenu { [self.menu cancelTrackingWithoutAnimation]; }
@end
