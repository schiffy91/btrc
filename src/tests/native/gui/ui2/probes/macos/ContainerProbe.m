#import "ContainerProbe.h"
#import <objc/runtime.h>

static NSView *faultParent;
static NSView *faultChild;
static int firstFailure;
static int secondFailure;
static int orderCalls;
static bool firstAfter;
static bool secondAfter;
static bool hideMembership;
static IMP originalAdd;
static IMP originalRemove;
static IMP originalSort;
static IMP originalSubviews;
static IMP originalArrangedInsert;
static NSWindow *hostWindow;
static NSTextField *editingField;
static NSTextView *editor;
static NSRange selectedRange;
static NSRange markedRange;
static NSString *editorText;
static id endObserver;
static int editingNotifications;

static bool shouldFail(NSView *parent) {
    if (parent != faultParent || faultChild != nil) { return false; }
    orderCalls++;
    return orderCalls == firstFailure || orderCalls == secondFailure;
}

static bool failAfterMutation(void) {
    return orderCalls == firstFailure ? firstAfter : secondAfter;
}

static void failOrder(void) {
    [NSException raise:@"UI2ContainerInjectedFailure" format:@"native order step %d", orderCalls];
}

static bool shouldFailAttachment(NSView *parent, NSView *child) {
    if (parent != faultParent || child != faultChild) { return false; }
    orderCalls++;
    return orderCalls == firstFailure || orderCalls == secondFailure;
}

static void interceptedAdd(NSView *self, SEL selector, NSView *child) {
    bool fail = shouldFailAttachment(self, child);
    if (fail && !failAfterMutation()) { failOrder(); }
    ((void (*)(id, SEL, NSView *))originalAdd)(self, selector, child);
    if (fail && failAfterMutation()) { failOrder(); }
}

static void interceptedRemove(NSView *self, SEL selector) {
    bool fail = shouldFailAttachment(self.superview, self);
    if (fail && !failAfterMutation()) { failOrder(); }
    ((void (*)(id, SEL))originalRemove)(self, selector);
    if (fail && failAfterMutation()) { failOrder(); }
}

static void interceptedSort(NSView *self, SEL selector,
                            NSComparisonResult (*comparator)(NSView *, NSView *, void *), void *context) {
    bool fail = shouldFail(self);
    if (fail && !failAfterMutation()) { failOrder(); }
    ((void (*)(id, SEL, NSComparisonResult (*)(NSView *, NSView *, void *), void *))originalSort)(self, selector, comparator, context);
    if (fail && failAfterMutation()) { failOrder(); }
}

static void interceptedArrangedInsert(NSStackView *self, SEL selector, NSView *view, NSUInteger index) {
    bool fail = shouldFail(self);
    if (fail && !failAfterMutation()) { failOrder(); }
    ((void (*)(id, SEL, NSView *, NSUInteger))originalArrangedInsert)(self, selector, view, index);
    if (fail && failAfterMutation()) { failOrder(); }
}

static NSArray<NSView *> *interceptedSubviews(NSView *self, SEL selector) {
    if (self == faultParent && hideMembership && secondFailure > 0 && orderCalls >= secondFailure) {
        [NSException raise:@"UI2ContainerUnknownMembership" format:@"injected native inspection failure"];
    }
    return ((NSArray<NSView *> *(*)(id, SEL))originalSubviews)(self, selector);
}

@implementation UI2ContainerProbe
+ (int)indexOf:(NSView *)child inParent:(NSView *)parent {
    NSUInteger index = [parent.subviews indexOfObjectIdenticalTo:child];
    return index == NSNotFound ? -1 : (int)index;
}

+ (int)arrangedIndexOf:(NSView *)child inStack:(NSView *)stack {
    if (![stack isKindOfClass:NSStackView.class]) { return -1; }
    NSUInteger index = [((NSStackView *)stack).arrangedSubviews indexOfObjectIdenticalTo:child];
    return index == NSNotFound ? -1 : (int)index;
}

+ (void)armOrderFaults:(NSView *)parent first:(int)first second:(int)second firstAfter:(bool)afterFirst secondAfter:(bool)afterSecond hideMembership:(bool)unknown {
    [self resetFaults];
    faultParent = parent;
    firstFailure = first;
    secondFailure = second;
    firstAfter = afterFirst;
    secondAfter = afterSecond;
    hideMembership = unknown;
    orderCalls = 0;
    originalSort = method_setImplementation(class_getInstanceMethod(NSView.class, @selector(sortSubviewsUsingFunction:context:)), (IMP)interceptedSort);
    originalSubviews = method_setImplementation(class_getInstanceMethod(NSView.class, @selector(subviews)), (IMP)interceptedSubviews);
    originalArrangedInsert = method_setImplementation(class_getInstanceMethod(NSStackView.class, @selector(insertArrangedSubview:atIndex:)), (IMP)interceptedArrangedInsert);
}

+ (void)armAttachmentFaults:(NSView *)parent child:(NSView *)child first:(int)first second:(int)second firstAfter:(bool)afterFirst secondAfter:(bool)afterSecond {
    [self resetFaults];
    faultParent = parent;
    faultChild = child;
    firstFailure = first;
    secondFailure = second;
    firstAfter = afterFirst;
    secondAfter = afterSecond;
    orderCalls = 0;
    originalAdd = method_setImplementation(class_getInstanceMethod(NSView.class, @selector(addSubview:)), (IMP)interceptedAdd);
    originalRemove = method_setImplementation(class_getInstanceMethod(NSView.class, @selector(removeFromSuperview)), (IMP)interceptedRemove);
}

+ (int)orderCalls { return orderCalls; }

+ (void)resetFaults {
    if (originalAdd) { method_setImplementation(class_getInstanceMethod(NSView.class, @selector(addSubview:)), originalAdd); originalAdd = NULL; }
    if (originalRemove) { method_setImplementation(class_getInstanceMethod(NSView.class, @selector(removeFromSuperview)), originalRemove); originalRemove = NULL; }
    if (originalSort) { method_setImplementation(class_getInstanceMethod(NSView.class, @selector(sortSubviewsUsingFunction:context:)), originalSort); originalSort = NULL; }
    if (originalSubviews) { method_setImplementation(class_getInstanceMethod(NSView.class, @selector(subviews)), originalSubviews); originalSubviews = NULL; }
    if (originalArrangedInsert) { method_setImplementation(class_getInstanceMethod(NSStackView.class, @selector(insertArrangedSubview:atIndex:)), originalArrangedInsert); originalArrangedInsert = NULL; }
    faultParent = nil;
    faultChild = nil;
}

+ (NSView *)openHost {
    NSCAssert(hostWindow == nil, @"one host per probe");
    hostWindow = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 400, 240) styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
    hostWindow.releasedWhenClosed = NO;
    return hostWindow.contentView;
}

+ (NSView *)newField {
    NSTextField *field = [[NSTextField alloc] initWithFrame:NSMakeRect(0, 0, 160, 24)];
    field.stringValue = @"accepted baseline";
    return field;
}

+ (void)beginEditing:(NSView *)view {
    NSCAssert([view isKindOfClass:NSTextField.class], @"actual NSTextField required");
    editingField = (NSTextField *)view;
    NSCAssert(editingField.window == hostWindow, @"field must belong to host");
    [editingField selectText:nil];
    NSResponder *responder = hostWindow.firstResponder;
    NSCAssert([responder isKindOfClass:NSTextView.class], @"actual AppKit field editor required");
    editor = (NSTextView *)responder;
    NSCAssert(editor == editingField.currentEditor, @"field editor identity required");
    [editor setMarkedText:@"pending composition" selectedRange:NSMakeRange(2, 3) replacementRange:NSMakeRange(0, editor.string.length)];
    NSCAssert(editor.hasMarkedText, @"marked text must be established before MOVE");
    selectedRange = editor.selectedRange;
    markedRange = editor.markedRange;
    editorText = [editor.string copy];
    editingNotifications = 0;
    endObserver = [NSNotificationCenter.defaultCenter addObserverForName:NSControlTextDidEndEditingNotification object:editingField queue:nil usingBlock:^(NSNotification *note) {
        (void)note;
        editingNotifications++;
    }];
}

+ (bool)editorUnchanged {
    return hostWindow.firstResponder == editor && editingField.currentEditor == editor && editor.hasMarkedText &&
           NSEqualRanges(editor.selectedRange, selectedRange) && NSEqualRanges(editor.markedRange, markedRange) &&
           [editor.string isEqualToString:editorText];
}

+ (int)editingNotifications { return editingNotifications; }

+ (void)closeHost {
    [self resetFaults];
    if (endObserver) { [NSNotificationCenter.defaultCenter removeObserver:endObserver]; endObserver = nil; }
    [hostWindow endEditingFor:nil];
    editor = nil;
    editingField = nil;
    editorText = nil;
    [hostWindow close];
    hostWindow = nil;
}
@end
