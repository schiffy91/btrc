#import "ExampleProbe.h"
#include <assert.h>

static NSInteger step;
static NSHashTable *exampleWindows;

@implementation ExampleProbe
+ (void)advance:(NSTimer *)timer {
	NSWindow *window = exampleWindows.allObjects.firstObject;
	if (step == 0) {
		for (NSWindow *candidate in NSApp.windows) {
			if ([candidate.title isEqualToString:@"Native BTRC"]) { window = candidate; break; }
		}
		assert(window != nil);
		[exampleWindows addObject:window];
		NSStackView *column = (NSStackView *)window.contentView.subviews.firstObject;
		assert([column isKindOfClass:NSStackView.class]);
		NSTextField *field = column.arrangedSubviews.firstObject;
		NSStackView *row = column.arrangedSubviews[1];
		assert(field.frame.size.width > 300 && field.frame.size.height >= field.intrinsicContentSize.height);
		assert(row.arrangedSubviews.count == 2 && row.frame.size.height > 0);
		assert([window makeFirstResponder:field]);
		NSTextView *editor = (NSTextView *)field.currentEditor;
		assert(editor != nil);
		[editor setSelectedRange:NSMakeRange(0, editor.string.length)];
		[editor insertText:@"Renamed through native editing" replacementRange:editor.selectedRange];
		[(NSButton *)row.arrangedSubviews[0] performClick:nil];
		step = 1;
		return;
	}
	assert(step == 1 && window != nil);
	assert([window.title isEqualToString:@"Renamed through native editing"]);
	NSView *content = window.contentView;
	NSBitmapImageRep *bitmap = [content bitmapImageRepForCachingDisplayInRect:content.bounds];
	assert(bitmap != nil);
	[content cacheDisplayInRect:content.bounds toBitmapImageRep:bitmap];
	assert([bitmap.TIFFRepresentation writeToFile:@"NativeExample.tiff" atomically:YES]);
	NSStackView *column = (NSStackView *)content.subviews.firstObject;
	NSStackView *row = column.arrangedSubviews[1];
	[(NSButton *)row.arrangedSubviews[1] performClick:nil];
	step = 2;
	[timer invalidate];
}

+ (void)schedule {
	step = 0;
	exampleWindows = [[NSHashTable weakObjectsHashTable] retain];
	[NSTimer scheduledTimerWithTimeInterval:0.1 target:self selector:@selector(advance:) userInfo:nil repeats:YES];
}

+ (void)verify {
	assert(step == 2);
	for (NSWindow *window in exampleWindows.allObjects) assert(!window.visible);
	[exampleWindows release];
	exampleWindows = nil;
}
@end
