#import "UI2MacOSTextField.h"
#include <assert.h>
#include <stdio.h>

@implementation BTRCUI2TextProbe
+ (void)prepare { [NSApplication sharedApplication]; [NSApp setActivationPolicy:NSApplicationActivationPolicyProhibited]; }
+ (NSWindow *)host:(NSTextField *)field {
    NSWindow *window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 320, 40)
        styleMask:NSWindowStyleMaskBorderless backing:NSBackingStoreBuffered defer:NO];
    window.releasedWhenClosed = NO;
    window.contentView = field;
    return [window autorelease];
}
+ (BOOL)focus:(NSTextField *)field { return [field.window makeFirstResponder:field] && field.currentEditor != nil; }
+ (void)blur:(NSTextField *)field { assert([field.window makeFirstResponder:nil]); }
+ (void)replace:(NSTextField *)field value:(NSString *)value {
    NSTextView *editor = (NSTextView *)field.currentEditor; assert(editor != nil);
    @try { [editor insertText:value replacementRange:NSMakeRange(0, editor.string.length)]; }
    @catch (NSException *error) { fprintf(stderr, "replace value=%s old=%s undo-level=%ld exception=%s\n", value.UTF8String, editor.string.UTF8String, (long)editor.undoManager.groupingLevel, error.reason.UTF8String); @throw; }
}
+ (void)select:(NSTextField *)field location:(NSUInteger)location length:(NSUInteger)length {
    NSTextView *editor = (NSTextView *)field.currentEditor; assert(editor != nil);
    editor.selectedRange = NSMakeRange(location, length);
}
+ (void)mark:(NSTextField *)field value:(NSString *)value {
    NSTextView *editor = (NSTextView *)field.currentEditor; assert(editor != nil);
    [editor setMarkedText:value selectedRange:NSMakeRange(value.length, 0) replacementRange:NSMakeRange(NSNotFound, 0)];
}
+ (void)escape:(NSTextField *)field {
    NSTextView *editor = (NSTextView *)field.currentEditor; assert(editor != nil);
    [editor doCommandBySelector:@selector(cancelOperation:)];
}
+ (void)accept:(NSTextField *)field {
    NSTextView *editor = (NSTextView *)field.currentEditor; assert(editor != nil);
    [editor doCommandBySelector:@selector(insertNewline:)];
}
+ (BOOL)state:(NSTextField *)field text:(NSString *)text composing:(BOOL)composing location:(NSUInteger)location length:(NSUInteger)length {
    NSTextView *editor = (NSTextView *)field.currentEditor;
    BOOL matches = editor != nil && [editor.string isEqualToString:text] && editor.hasMarkedText == composing &&
        NSEqualRanges(editor.selectedRange, NSMakeRange(location, length));
    if (!matches) { fprintf(stderr, "text state: editor=%d text=%s composing=%d selection=%lu:%lu expected=%s/%d/%lu:%lu\n", editor != nil, editor.string.UTF8String, editor.hasMarkedText, (unsigned long)editor.selectedRange.location, (unsigned long)editor.selectedRange.length, text.UTF8String, composing, (unsigned long)location, (unsigned long)length); }
    return matches;
}
+ (void)undo:(NSTextField *)field {
    NSTextView *editor = (NSTextView *)field.currentEditor; assert(editor != nil && editor.undoManager.canUndo);
    while (editor.undoManager.groupingLevel > 0) { [editor.undoManager endUndoGrouping]; }
    [editor.undoManager undo];
    // This direct-call fixture has no native event boundary to open the next group.
    if (editor.undoManager.groupingLevel == 0) { [editor.undoManager beginUndoGrouping]; }
}
+ (void)finish:(NSWindow *)window { [window makeFirstResponder:nil]; window.contentView = nil; [window close]; }
@end
