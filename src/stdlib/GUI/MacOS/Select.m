#import "Select.h"

@implementation BTRCMacOSSelect {
    NSHashTable<id<BTRCMacOSSelectEvents>> *_semanticEvents;
    NSUInteger _trackingDepth;
    BOOL _escape;
}

+ (instancetype)selection {
    return [[[self alloc] initWithFrame:NSZeroRect pullsDown:NO] autorelease];
}

- (instancetype)initWithFrame:(NSRect)frame pullsDown:(BOOL)pullsDown {
    self = [super initWithFrame:frame pullsDown:pullsDown];
    if (self) {
        /* Native sources use MRC. Foundation owns this zeroing weak slot;
         * CallbackScope remains the sole owner of the generated receiver. */
        _semanticEvents = [[NSHashTable alloc]
            initWithOptions:NSPointerFunctionsWeakMemory | NSPointerFunctionsObjectPointerPersonality capacity:1];
        if (!_semanticEvents) { [self release]; return nil; }
        self.autoenablesItems = NO;
        self.target = self;
        self.action = @selector(semanticAction:);
        self.menu.delegate = self;
    }
    return self;
}

- (void)dealloc {
    if (self.menu.delegate == self) { self.menu.delegate = nil; }
    if (self.target == self) { self.target = nil; self.action = NULL; }
    [_semanticEvents release];
    [super dealloc];
}

- (void)setSemanticEvents:(id<BTRCMacOSSelectEvents>)events {
    [_semanticEvents removeAllObjects];
    if (events) { [_semanticEvents addObject:events]; }
}
- (id<BTRCMacOSSelectEvents>)semanticEvents { return [[[_semanticEvents anyObject] retain] autorelease]; }

- (void)setMenu:(NSMenu *)menu {
    NSMenu *previous = self.menu;
    if (previous.delegate == self) { previous.delegate = nil; }
    [super setMenu:menu];
    menu.delegate = self;
}

- (BOOL)beginTracking {
    if (_trackingDepth != 0) { _trackingDepth++; return YES; }
    id<BTRCMacOSSelectEvents> sink = self.semanticEvents;
    if (!sink || ![sink shouldBegin]) { return NO; }
    _trackingDepth = 1;
    _escape = NO;
    return YES;
}

- (void)endTracking {
    if (--_trackingDepth == 0) { [self.semanticEvents ended:_escape]; }
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
    if (menu == self.menu && _trackingDepth != 0) { [self.semanticEvents opened]; }
}

- (void)menu:(NSMenu *)menu willHighlightItem:(NSMenuItem *)item {
    if (menu != self.menu || _trackingDepth == 0 || !item || !item.enabled) { return; }
    if (![self.semanticEvents candidate:[menu indexOfItem:item]]) { [menu cancelTrackingWithoutAnimation]; }
}

- (void)semanticAction:(id)sender {
    (void)sender;
    if (_trackingDepth != 0) { [self.semanticEvents accepted:self.indexOfSelectedItem]; }
}

- (void)cancelMenu { [self.menu cancelTrackingWithoutAnimation]; }
@end
