#import "TextFieldControl.h"
#include <stdio.h>

/* Drives AppKit's real shared field editor. No replacement text widget or
 * synthetic value store participates in these checks. */
static NSWindow *testWindow;
static NSTextView *editor;

@implementation NativeTextFieldProbe
+ (void)prepare:(NSWindow *)window { testWindow = window; }
+ (BOOL)mount:(NSTextField *)field {
    if (![testWindow.title isEqualToString:@"Library Música 🎸"] || testWindow.releasedWhenClosed ||
        !NSEqualSizes(testWindow.contentView.frame.size, NSMakeSize(480, 180))) { return NO; }
    if (field.superview != testWindow.contentView) { return NO; }
    if (!NSEqualRects(field.frame, NSMakeRect(24.25, 72.5, 431.75, 30.125))) { return NO; }
    if (![testWindow makeFirstResponder:field]) { return NO; }
    editor = (NSTextView *)field.currentEditor;
    return [field isKindOfClass:[NSTextField class]] && editor != nil &&
        editor.isFieldEditor && [field.placeholderString isEqualToString:@"Search library"];
}
+ (BOOL)replaceSelection {
    if (!editor.allowsUndo) {
        fprintf(stderr, "AppKit field editor has undo disabled\n");
        return NO;
    }
    [editor.undoManager beginUndoGrouping];
    [editor setSelectedRange:NSMakeRange(0, editor.string.length)];
    [editor insertText:@"Guitar 🎸" replacementRange:editor.selectedRange];
    [editor.undoManager endUndoGrouping];
    [editor setSelectedRange:NSMakeRange(0, 6)];
    return [editor.string isEqualToString:@"Guitar 🎸"];
}
+ (BOOL)selectionUnchanged { return NSEqualRanges(editor.selectedRange, NSMakeRange(0, 6)); }
+ (BOOL)undo {
    if (!editor.undoManager.canUndo) { return NO; }
    [editor.undoManager undo];
    return [editor.string isEqualToString:@"Library Música 🎸"];
}
+ (BOOL)redo {
    if (!editor.undoManager.canRedo) { return NO; }
    [editor.undoManager redo];
    return [editor.string isEqualToString:@"Guitar 🎸"];
}
+ (BOOL)queueKey {
    [testWindow makeKeyAndOrderFront:nil];
    if (![testWindow makeFirstResponder:editor]) { return NO; }
    [editor setSelectedRange:NSMakeRange(0, 6)];
    NSEvent *event = [NSEvent keyEventWithType:NSEventTypeKeyDown location:NSZeroPoint modifierFlags:0
        timestamp:0 windowNumber:testWindow.windowNumber context:nil characters:@"n"
        charactersIgnoringModifiers:@"n" isARepeat:NO keyCode:45];
    if (!event) { return NO; }
    [NSApp postEvent:event atStart:YES];
    return YES;
}
+ (BOOL)finish:(NSTextField *)field {
    BOOL detached = field.superview == nil && field.currentEditor == nil;
    editor = nil;
    testWindow = nil;
    return detached;
}
@end
