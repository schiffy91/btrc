#import "TextProbe.h"

static NSWindow *host;
static NSTextView *rememberedEditor;
static NSRange rememberedSelection;
static NSRange rememberedMarked;
static NSString *rememberedText;
static BOOL rememberedUndo;

@implementation UI2TextProbe
+ (NSView *)open {
    [NSApplication sharedApplication];
    host = [[NSWindow alloc] initWithContentRect:NSMakeRect(100, 100, 400, 160)
                                    styleMask:NSWindowStyleMaskTitled
                                      backing:NSBackingStoreBuffered defer:NO];
    host.releasedWhenClosed = NO;
    [host makeKeyAndOrderFront:nil];
    return host.contentView;
}
+ (NSTextView *)editor:(NSTextField *)field {
    NSText *editor = field.currentEditor;
    if (![editor isKindOfClass:NSTextView.class]) {
        [NSException raise:NSInternalInconsistencyException format:@"Text probe requires the actual field editor"];
    }
    return (NSTextView *)editor;
}
+ (BOOL)begin:(NSTextField *)field {
    [field selectText:nil];
    return field.currentEditor != nil;
}
+ (void)insert:(NSTextField *)field text:(NSString *)text {
    [[self editor:field] insertText:text replacementRange:NSMakeRange(NSNotFound, 0)];
}
+ (void)mark:(NSTextField *)field text:(NSString *)text {
    [[self editor:field] setMarkedText:text selectedRange:NSMakeRange(text.length, 0)
                    replacementRange:NSMakeRange(NSNotFound, 0)];
}
+ (void)accept:(NSTextField *)field { [[self editor:field] doCommandBySelector:@selector(insertNewline:)]; }
+ (void)escape:(NSTextField *)field { [[self editor:field] doCommandBySelector:@selector(cancelOperation:)]; }
+ (void)blur { [host makeFirstResponder:host.contentView]; }
+ (BOOL)marked:(NSTextField *)field { return [self editor:field].hasMarkedText; }
+ (void)rememberEditor:(NSTextField *)field {
    rememberedEditor = [self editor:field];
    rememberedSelection = rememberedEditor.selectedRange;
    rememberedMarked = rememberedEditor.markedRange;
    rememberedText = [rememberedEditor.string copy];
    rememberedUndo = rememberedEditor.undoManager.canUndo;
}
+ (BOOL)editorUnchanged:(NSTextField *)field {
    NSTextView *editor = [self editor:field];
    return editor == rememberedEditor && NSEqualRanges(editor.selectedRange, rememberedSelection)
        && NSEqualRanges(editor.markedRange, rememberedMarked) && [editor.string isEqualToString:rememberedText]
        && editor.undoManager.canUndo == rememberedUndo;
}
+ (void)close {
    rememberedEditor = nil;
    rememberedText = nil;
    [host orderOut:nil];
    [host close];
    host = nil;
}
@end
