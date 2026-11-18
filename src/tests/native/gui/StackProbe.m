#import "StackProbe.h"
#include <assert.h>
#include <math.h>

static NSHashTable *observedViews;
static NSHashTable *editorIdentity;

@implementation StackProbe
+ (NSWindow *)window {
	for (NSWindow *window in NSApp.windows) {
		if ([window.title isEqualToString:@"Recursive native layout"]) return window;
	}
	[NSException raise:NSInternalInconsistencyException format:@"Missing layout test window"];
	return nil;
}

/* A stack's native view is a host that pins its NSStackView by the stack's
 * padding: the provider owns padding, because NSStackView ignores its far
 * edge inset under end and centre alignment. */
+ (NSView *)columnHost { return [self window].contentView.subviews.firstObject; }

+ (NSStackView *)stackIn:(NSView *)host {
	assert(host.subviews.count == 1);
	NSStackView *stack = host.subviews.firstObject;
	assert([stack isKindOfClass:NSStackView.class]);
	assert(!stack.translatesAutoresizingMaskIntoConstraints);
	return stack;
}

+ (NSStackView *)column { return [self stackIn:[self columnHost]]; }

+ (NSStackView *)row { return [self stackIn:[self column].arrangedSubviews[1]]; }

+ (NSTextField *)field { return (NSTextField *)[self column].arrangedSubviews.firstObject; }

+ (void)near:(double)actual expected:(double)expected { assert(fabs(actual - expected) < 0.1); }

+ (void)verifyLayout:(double)width {
	NSView *host = [self columnHost];
	NSStackView *column = [self column];
	assert(column.orientation == NSUserInterfaceLayoutOrientationVertical);
	assert(column.arrangedSubviews.count == 2);
	NSTextField *field = [self field];
	NSView *rowHost = column.arrangedSubviews[1];
	NSStackView *row = [self row];
	assert(row.orientation == NSUserInterfaceLayoutOrientationHorizontal);
	assert(row.arrangedSubviews.count == 2);
	NSView *first = row.arrangedSubviews[0], *second = row.arrangedSubviews[1];
	/* The field and the row in the column's own coordinates, then the field
	 * in the host's, where the padding shows. */
	NSRect fieldRect = [field alignmentRectForFrame:field.frame];
	NSRect rowRect = [rowHost alignmentRectForFrame:rowHost.frame];
	NSRect paddedField = [host convertRect:fieldRect fromView:column];
	NSRect firstRect = [first alignmentRectForFrame:first.frame];
	NSRect secondRect = [second alignmentRectForFrame:second.frame];
	[self near:host.frame.size.width expected:width];
	[self near:paddedField.origin.x expected:20];
	[self near:paddedField.size.width expected:width - 40];
	[self near:NSMaxY(paddedField) expected:host.bounds.size.height - 20];
	[self near:NSMinY(fieldRect) - NSMaxY(rowRect) expected:column.spacing];
	[self near:NSMinX(secondRect) - NSMaxX(firstRect) expected:row.spacing];
	assert(first.frame.size.width < width / 2);
	assert(field.frame.size.height >= field.intrinsicContentSize.height);
	assert(!field.translatesAutoresizingMaskIntoConstraints && !rowHost.translatesAutoresizingMaskIntoConstraints);
}

+ (void)beginEditing {
	NSTextField *field = [self field];
	assert([[self window] makeFirstResponder:field]);
	NSTextView *editor = (NSTextView *)field.currentEditor;
	assert(editor != nil);
	[editorIdentity release];
	editorIdentity = [[NSHashTable weakObjectsHashTable] retain];
	[editorIdentity addObject:editor];
	[editor setSelectedRange:NSMakeRange(0, editor.string.length)];
	[editor insertText:@"Edited title" replacementRange:editor.selectedRange];
	[editor setSelectedRange:NSMakeRange(2, 4)];
	assert(editor.undoManager.canUndo);
}

+ (void)verifyEditing {
	NSTextView *editor = (NSTextView *)[self field].currentEditor;
	assert(editor != nil && [editorIdentity containsObject:editor]);
	assert([editor.string isEqualToString:@"Edited title"]);
	assert(NSEqualRanges(editor.selectedRange, NSMakeRange(2, 4)));
	assert(editor.undoManager.canUndo);
}

+ (void)undoEditing {
	NSTextView *editor = (NSTextView *)[self field].currentEditor;
	[editor.undoManager undo];
	assert([editor.string isEqualToString:@"Original title"]);
}

+ (void)observeViews {
	[observedViews release];
	observedViews = [[NSHashTable weakObjectsHashTable] retain];
	NSStackView *column = [self column];
	NSStackView *row = [self row];
	[observedViews addObject:column];
	[observedViews addObject:row];
	for (NSView *view in row.arrangedSubviews) [observedViews addObject:view];
	assert(observedViews.allObjects.count == 4);
	// AppKit can retain its first text field process-wide; the separately tested
	// direct-native baseline owns that quirk. Stacks and buttons must reach zero.
}

+ (NSInteger)remainingViews { return observedViews.allObjects.count; }

+ (void)verifyDetachedButton {
	NSStackView *row = [self row];
	assert(row.arrangedSubviews.count == 1);
	NSInteger detached = 0;
	for (NSView *view in observedViews.allObjects) {
		if ([view isKindOfClass:NSButton.class] && view.superview == nil) {
			assert(view.translatesAutoresizingMaskIntoConstraints);
			detached++;
		}
	}
	assert(detached == 1);
}

+ (void)verifyHiddenButton {
	NSStackView *row = [self row];
	assert(row.arrangedSubviews.count == 2);
	NSView *button = row.arrangedSubviews[1];
	assert(button.hidden && button.superview == row);
}

+ (void)reset { [observedViews release]; observedViews = nil; [editorIdentity release]; editorIdentity = nil; }
@end
