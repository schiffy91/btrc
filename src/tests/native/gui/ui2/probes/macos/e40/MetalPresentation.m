#import <AppKit/AppKit.h>
#import <Metal/Metal.h>
#import <QuartzCore/QuartzCore.h>
#include <assert.h>
#include <math.h>
#include <pthread.h>
#include <stdio.h>

/* A direct Metal control for hosted E40 failures. It records native results;
 * it neither substitutes for WebGPU presentation nor qualifies E40. */
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static unsigned completed, commandErrors, presented, skipped, invalid;
static double firstPresentation, lastPresentation;

int main(int argc, const char *argv[]) {
    assert(argc == 2);
    @autoreleasepool {
        NSApplication *application = NSApplication.sharedApplication;
        [application setActivationPolicy:NSApplicationActivationPolicyRegular];
        [application finishLaunching];
        id<MTLDevice> device = MTLCreateSystemDefaultDevice();
        if (!device) { fprintf(stderr, "Metal control: no default device\n"); return 2; }
        id<MTLCommandQueue> queue = [device newCommandQueue];
        if (!queue) { fprintf(stderr, "Metal control: no command queue\n"); return 2; }
        NSWindow *window = [[NSWindow alloc] initWithContentRect:NSMakeRect(100, 400, 320, 200)
            styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
            backing:NSBackingStoreBuffered defer:NO];
        window.releasedWhenClosed = NO;
        window.title = @"E40 direct Metal presentation control";
        NSView *view = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, 320, 200)];
        CAMetalLayer *layer = [CAMetalLayer layer];
        layer.device = device; layer.pixelFormat = MTLPixelFormatBGRA8Unorm;
        layer.framebufferOnly = YES; layer.presentsWithTransaction = NO;
        layer.displaySyncEnabled = NO; layer.drawableSize = CGSizeMake(320, 200);
        view.wantsLayer = YES; view.layer = layer; window.contentView = view;
        [window makeKeyAndOrderFront:nil]; [application activateIgnoringOtherApps:YES];
        double started = CACurrentMediaTime();
        __block unsigned attempts = 0, acquired = 0;
        __block id<MTLCommandBuffer> lastCommand = nil;
        NSTimer *timer = [NSTimer timerWithTimeInterval:0.05 repeats:YES block:^(NSTimer *tick) {
            if (CACurrentMediaTime() - started >= 5.0) {
                [tick invalidate]; [application stop:nil];
                [application postEvent:[NSEvent otherEventWithType:NSEventTypeApplicationDefined
                    location:NSZeroPoint modifierFlags:0 timestamp:0 windowNumber:0
                    context:nil subtype:0 data1:0 data2:0] atStart:NO];
                return;
            }
            if (attempts >= 20 || !window.visible || !application.active) { return; }
            attempts++;
            id<CAMetalDrawable> drawable = [layer nextDrawable];
            if (!drawable) { return; }
            acquired++;
            [drawable addPresentedHandler:^(id<MTLDrawable> shown) {
                double stamp = shown.presentedTime;
                pthread_mutex_lock(&lock);
                if (!isfinite(stamp) || stamp < 0) { invalid++; }
                else if (stamp == 0) { skipped++; }
                else {
                    if (presented == 0 || stamp < firstPresentation) { firstPresentation = stamp; }
                    if (stamp > lastPresentation) { lastPresentation = stamp; }
                    presented++;
                }
                pthread_mutex_unlock(&lock);
            }];
            MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
            pass.colorAttachments[0].texture = drawable.texture;
            pass.colorAttachments[0].loadAction = MTLLoadActionClear;
            pass.colorAttachments[0].storeAction = MTLStoreActionStore;
            pass.colorAttachments[0].clearColor = MTLClearColorMake(0.1, (attempts % 2) ? 0.3 : 0.7, 0.2, 1.0);
            id<MTLCommandBuffer> command = [queue commandBuffer]; assert(command);
            id<MTLRenderCommandEncoder> encoder = [command renderCommandEncoderWithDescriptor:pass]; assert(encoder);
            [encoder endEncoding];
            [command addCompletedHandler:^(id<MTLCommandBuffer> done) {
                pthread_mutex_lock(&lock); completed++;
                if (done.status == MTLCommandBufferStatusError) { commandErrors++; }
                pthread_mutex_unlock(&lock);
            }];
            [command presentDrawable:drawable]; [command commit]; lastCommand = command;
        }];
        [[NSRunLoop mainRunLoop] addTimer:timer forMode:NSRunLoopCommonModes];
        [application run];
        [lastCommand waitUntilCompleted];
        pthread_mutex_lock(&lock);
        NSDictionary *report = @{
            @"schema":@"btrc.ui2.metal-presentation-control/1",
            @"scope":@"direct Metal diagnostic; not E40 acceptance or a performance measurement",
            @"device":device.name, @"window_visible":@(window.visible),
            @"application_active":@(application.active), @"occlusion_state":@(window.occlusionState),
            @"window_frame":NSStringFromRect(window.frame), @"drawable_size":NSStringFromSize(layer.drawableSize),
            @"display_sync_enabled":@(layer.displaySyncEnabled),
            @"attempts":@(attempts), @"acquired":@(acquired), @"command_completed":@(completed),
            @"command_errors":@(commandErrors), @"presented":@(presented), @"skipped":@(skipped),
            @"invalid_timestamps":@(invalid), @"first_presented_seconds":@(firstPresentation),
            @"last_presented_seconds":@(lastPresentation)
        };
        pthread_mutex_unlock(&lock);
        NSError *error = nil;
        NSData *data = [NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted | NSJSONWritingSortedKeys error:&error];
        assert(data && !error);
        BOOL saved = [data writeToFile:[NSString stringWithUTF8String:argv[1]] options:NSDataWritingAtomic error:&error];
        assert(saved && !error); [window close];
    }
    return 0;
}
