#import <AppKit/AppKit.h>
#import <objc/runtime.h>
#include <assert.h>
#include "DirectoryPickerControl.h"

static int mode, calls;

/* Modes 6/7 run AppKit's actual modal loop. Mode 7 completes it programmatically
 * with its real selected directory; this is not a native-button click test.
 * Other modes inject responses and SDK failures. */
@interface NSSavePanel (BtrcDirectoryPickerControl)
- (NSModalResponse)btrcTestRunModal;
- (NSURL *)btrcTestURL;
@end

@implementation NSSavePanel (BtrcDirectoryPickerControl)
- (NSModalResponse)btrcTestRunModal {
    calls++;
    assert([self isKindOfClass:[NSOpenPanel class]]);
    NSOpenPanel *panel = (NSOpenPanel *)self;
    assert([panel.title isEqualToString:@"Choose music"]);
    assert([panel.prompt isEqualToString:@"Use folder"]);
    assert(panel.canChooseDirectories && !panel.canChooseFiles);
    assert(!panel.allowsMultipleSelection && panel.canCreateDirectories && panel.resolvesAliases);
    assert([panel.directoryURL.path isEqualToString:@"/tmp"]);
    if (mode == 6 || mode == 7) {
        NSTimer *timer = [NSTimer timerWithTimeInterval:0.2 repeats:YES block:^(NSTimer *tick) {
            if ([NSApp modalWindow] == panel) {
                if (mode == 6) { [panel cancel:nil]; }
                else {
                    if (panel.URLs.count != 1 || !panel.URL.hasDirectoryPath) { return; }
                    NSString *selectedPath = panel.URL.path;
                    if (![selectedPath isEqualToString:@"/tmp"] && ![selectedPath isEqualToString:@"/private/tmp"]) { return; }
                    [NSApp stopModalWithCode:NSModalResponseOK];
                }
                [tick invalidate];
            }
        }];
        [[NSRunLoop mainRunLoop] addTimer:timer forMode:NSModalPanelRunLoopMode];
        NSModalResponse result = [self btrcTestRunModal];
        [timer invalidate];
        if (mode == 7) { fprintf(stderr, "selected directory: %s\n", panel.URL.path.UTF8String); }
        [panel orderOut:nil];
        return result;
    }
    if (mode == 4) { @throw [NSException exceptionWithName:@"PickerFailure" reason:@"injected picker failure" userInfo:nil]; }
    if (mode == 2) { return 987; }
    return mode == 0 ? NSModalResponseCancel : NSModalResponseOK;
}
- (NSURL *)btrcTestURL {
    if (mode >= 6) { return [self btrcTestURL]; }
    if (mode == 3) { return nil; }
    return [NSURL fileURLWithPath:@"/tmp/Música 🎸" isDirectory:YES];
}
@end

void directoryPickerPrepare(int value) {
    static BOOL installed;
    [NSApplication sharedApplication];
    if (!installed) {
        [NSApp finishLaunching];
        method_exchangeImplementations(class_getInstanceMethod([NSSavePanel class], @selector(runModal)), class_getInstanceMethod([NSSavePanel class], @selector(btrcTestRunModal)));
        method_exchangeImplementations(class_getInstanceMethod([NSSavePanel class], @selector(URL)), class_getInstanceMethod([NSSavePanel class], @selector(btrcTestURL)));
        installed = YES;
    }
    mode = value;
    calls = 0;
}

int directoryPickerCalls(void) { return calls; }
