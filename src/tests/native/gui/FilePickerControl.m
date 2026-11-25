#import <AppKit/AppKit.h>
#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>
#import <objc/runtime.h>
#include <assert.h>
#include "FilePickerControl.h"

static int pickerMode, pickerCalls;

/* Modes 11/12 run AppKit's real modal loop and dismiss it programmatically.
 * Modes 0-10 verify panel configuration across all six FilePickerMode variants
 * and inject selections, cancels, and native failures. */
@interface NSSavePanel (BtrcFilePickerControl)
- (NSModalResponse)btrcFileTestRunModal;
- (NSURL*)btrcFileTestURL;
@end

@interface NSOpenPanel (BtrcFilePickerControl)
- (NSArray<NSURL*>*)btrcFileTestURLs;
@end

@implementation NSSavePanel (BtrcFilePickerControl)
- (NSModalResponse)btrcFileTestRunModal {
	pickerCalls++;
	if (pickerMode == 6) {
		assert(![self isKindOfClass:[NSOpenPanel class]]);
		assert([self.title isEqualToString:@"Save image"]);
		assert([self.prompt isEqualToString:@"Save"]);
		assert([self.nameFieldStringValue isEqualToString:@"snapshot.qcow2"]);
		assert([self.directoryURL.path isEqualToString:@"/tmp"]);
		assert(self.canCreateDirectories);
		assert(self.allowedContentTypes.count == 1);
		return NSModalResponseOK;
	}
	assert([self isKindOfClass:[NSOpenPanel class]]);
	NSOpenPanel* panel = (NSOpenPanel*)self;
	assert([panel.directoryURL.path isEqualToString:@"/tmp"]);
	assert(panel.resolvesAliases);
	if (pickerMode == 0 || pickerMode == 1 || pickerMode == 7 || pickerMode == 8 || pickerMode == 9 || pickerMode == 10 || pickerMode == 11 || pickerMode == 12) {
		assert([panel.title isEqualToString:@"Choose disk"]);
		assert([panel.prompt isEqualToString:@"Choose"]);
		assert(panel.canChooseFiles && !panel.canChooseDirectories);
		assert(!panel.allowsMultipleSelection && !panel.canCreateDirectories);
		assert(panel.allowedContentTypes.count == 2);
	} else if (pickerMode == 2) {
		assert([panel.title isEqualToString:@"Choose disks"]);
		assert(panel.canChooseFiles && !panel.canChooseDirectories);
		assert(panel.allowsMultipleSelection);
		assert(panel.allowedContentTypes.count == 2);
	} else if (pickerMode == 3) {
		assert([panel.title isEqualToString:@"Choose folder"]);
		assert(!panel.canChooseFiles && panel.canChooseDirectories);
		assert(!panel.allowsMultipleSelection && panel.canCreateDirectories);
	} else if (pickerMode == 4) {
		assert([panel.title isEqualToString:@"Choose folders"]);
		assert(!panel.canChooseFiles && panel.canChooseDirectories);
		assert(panel.allowsMultipleSelection && panel.canCreateDirectories);
	} else if (pickerMode == 5) {
		assert([panel.title isEqualToString:@"Choose items"]);
		assert(panel.canChooseFiles && panel.canChooseDirectories);
		assert(panel.allowsMultipleSelection && panel.canCreateDirectories);
		assert(panel.allowedContentTypes.count == 2);
		assert([panel.allowedContentTypes containsObject:UTTypeFolder]);
	}
	if (pickerMode == 11 || pickerMode == 12) {
		NSTimer* timer = [NSTimer timerWithTimeInterval:0.2 repeats:YES block:^(NSTimer* tick) {
			if ([NSApp modalWindow] == panel) {
				if (pickerMode == 11) { [panel cancel:nil]; }
				else { [NSApp stopModalWithCode:NSModalResponseAbort]; }
				[tick invalidate];
			}
		}];
		[[NSRunLoop mainRunLoop] addTimer:timer forMode:NSModalPanelRunLoopMode];
		NSModalResponse result = [self btrcFileTestRunModal];
		[timer invalidate];
		[panel orderOut:nil];
		return result;
	}
	if (pickerMode == 9) { @throw [NSException exceptionWithName:@"FilePickerFailure" reason:@"injected file picker failure" userInfo:nil]; }
	if (pickerMode == 7) { return 987; }
	return pickerMode == 0 ? NSModalResponseCancel : NSModalResponseOK;
}

- (NSURL*)btrcFileTestURL {
	if (pickerMode >= 11) { return [self btrcFileTestURL]; }
	if (pickerMode == 8) { return nil; }
	if (pickerMode == 3) { return [NSURL fileURLWithPath:@"/tmp/vm-dir" isDirectory:YES]; }
	if (pickerMode == 6) { return [NSURL fileURLWithPath:@"/tmp/snapshot.qcow2" isDirectory:NO]; }
	return [NSURL fileURLWithPath:@"/tmp/Música 🎸.qcow2" isDirectory:NO];
}
@end

@implementation NSOpenPanel (BtrcFilePickerControl)
- (NSArray<NSURL*>*)btrcFileTestURLs {
	if (pickerMode >= 11) { return [self btrcFileTestURLs]; }
	if (pickerMode == 2) {
		return @[
			[NSURL fileURLWithPath:@"/tmp/one.raw" isDirectory:NO],
			[NSURL fileURLWithPath:@"/tmp/two.qcow2" isDirectory:NO]
		];
	}
	if (pickerMode == 4) {
		return @[
			[NSURL fileURLWithPath:@"/tmp/dir-a" isDirectory:YES],
			[NSURL fileURLWithPath:@"/tmp/dir-b" isDirectory:YES]
		];
	}
	if (pickerMode == 5) {
		return @[
			[NSURL fileURLWithPath:@"/tmp/disk.raw" isDirectory:NO],
			[NSURL fileURLWithPath:@"/tmp/shared" isDirectory:YES]
		];
	}
	return @[];
}
@end

void filePickerPrepare(int value) {
	static BOOL installed;
	[NSApplication sharedApplication];
	if (!installed) {
		[NSApp finishLaunching];
		method_exchangeImplementations(
			class_getInstanceMethod([NSSavePanel class], @selector(runModal)),
			class_getInstanceMethod([NSSavePanel class], @selector(btrcFileTestRunModal))
		);
		method_exchangeImplementations(
			class_getInstanceMethod([NSSavePanel class], @selector(URL)),
			class_getInstanceMethod([NSSavePanel class], @selector(btrcFileTestURL))
		);
		method_exchangeImplementations(
			class_getInstanceMethod([NSOpenPanel class], @selector(URLs)),
			class_getInstanceMethod([NSOpenPanel class], @selector(btrcFileTestURLs))
		);
		installed = YES;
	}
	pickerMode = value;
	pickerCalls = 0;
}

int filePickerCalls(void) { return pickerCalls; }
