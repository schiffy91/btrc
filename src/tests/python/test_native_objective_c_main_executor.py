"""Stored Objective-C blocks bound to the main thread (executor = "main", interop step 6).

AVAudioSession posts its interruption notifications on a thread of its own; an
observer registered with NSOperationQueue.mainQueue receives them on the main
thread. Binding the observer's block with `executor = "main"` makes that a
checked fact (native-interop-ownership.md section 1, rules 3 and 4): the
registration must run on the main thread, so the callback context's own
thread check admits every entry and the final release there only, and the
generated holder posts a release that the SDK makes on another thread to the
main queue instead of touching ARC there.

Foundation's NSNotificationCenter stands in for AVAudioSession on the Mac: a
probe posts each interruption on a background queue and the main run loop
delivers it. A proxy center drops its observer block on another thread, as an
SDK that keeps observers on its own queue may; under `executor = "caller"` the
same release terminates. The iOS simulator posts a real
AVAudioSessionInterruptionNotification (test_native_uikit_application.py).
"""

import subprocess

import pytest

from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder

HEADER = """#import <Foundation/Foundation.h>
extern NSString * const _Nonnull NativeInterruptionTypeKey;
@interface NativePoster : NSObject
/* Posts on a background queue and returns at once. */
+ (void)post:(NSString * _Nullable)name type:(int)type;
+ (int)pending;
@end
/* One observer at a time. Its block is released on another thread, and
 * postInBackground: delivers to it from another thread. */
@interface NativeAudioCenter : NSObject
+ (NativeAudioCenter * _Nonnull)shared;
- (id _Nullable)addObserverForName:(NSString * _Nullable)name object:(id _Nullable)object queue:(NSOperationQueue * _Nullable)queue usingBlock:(void (^ _Nonnull)(NSNotification * _Nonnull notification))block;
- (void)removeObserver:(id _Nonnull)observer;
- (void)post:(NSString * _Nullable)name;
- (void)postInBackground:(NSString * _Nullable)name;
+ (int)backgroundReleases;
@end
"""

PROBE = """#import "Foundation.h"
#include <pthread.h>
#include <stdatomic.h>
NSString * const NativeInterruptionTypeKey = @"NativeInterruptionTypeKey";
static atomic_int pending;
static atomic_int backgroundReleases;
@implementation NativePoster
+ (void)post:(NSString *)name type:(int)type {
    atomic_fetch_add(&pending, 1);
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_DEFAULT, 0), ^{
        @autoreleasepool {
            NSDictionary *info = [NSDictionary dictionaryWithObject:[NSNumber numberWithInt:type]
                                                             forKey:NativeInterruptionTypeKey];
            [[NSNotificationCenter defaultCenter] postNotificationName:name object:nil userInfo:info];
        }
        atomic_fetch_sub(&pending, 1);
    });
}
+ (int)pending { return atomic_load(&pending); }
@end
static void *releaseBlock(void *block) {
    Block_release(block);
    atomic_fetch_add(&backgroundReleases, 1);
    return NULL;
}
static NSString *backgroundName;
static void *deliver(void *center) {
    @autoreleasepool { [(NativeAudioCenter *)center post:backgroundName]; }
    return NULL;
}
@implementation NativeAudioCenter {
    void (^_block)(NSNotification *);
    NSString *_name;
}
+ (NativeAudioCenter *)shared {
    static NativeAudioCenter *shared;
    if (shared == nil) shared = [[NativeAudioCenter alloc] init];
    return shared;
}
+ (int)backgroundReleases { return atomic_load(&backgroundReleases); }
- (id)addObserverForName:(NSString *)name object:(id)object queue:(NSOperationQueue *)queue
              usingBlock:(void (^)(NSNotification *))block {
    (void)object;
    (void)queue;
    if (_block != nil) return nil;
    _block = [block copy];
    _name = [name copy];
    return [[[NSObject alloc] init] autorelease];
}
- (void)removeObserver:(id)observer {
    (void)observer;
    void *block = (void *)_block;
    _block = nil;
    [_name release];
    _name = nil;
    if (block == NULL) return;
    /* An SDK that keeps its observers on its own queue drops them there. */
    pthread_t thread;
    if (pthread_create(&thread, NULL, releaseBlock, block) == 0) pthread_join(thread, NULL);
}
- (void)post:(NSString *)name {
    if (_block != nil && [_name isEqualToString:name]) _block([NSNotification notificationWithName:name object:self]);
}
- (void)postInBackground:(NSString *)name {
    pthread_t thread;
    backgroundName = name;
    if (pthread_create(&thread, NULL, deliver, self) == 0) pthread_join(thread, NULL);
}
@end
"""

SYMBOLS = [
    "+[NSNotificationCenter defaultCenter]",
    "-[NSNotificationCenter addObserverForName:object:queue:usingBlock:]",
    "-[NSNotificationCenter removeObserver:]",
    "+[NSOperationQueue mainQueue]",
    "+[NSString stringWithUTF8String:]",
    "-[NSNotification userInfo]",
    "-[NSDictionary objectForKey:]",
    "-[NSNumber intValue]",
    "+[NSThread isMainThread]",
    "+[NSRunLoop currentRunLoop]",
    "-[NSRunLoop runUntilDate:]",
    "+[NSDate dateWithTimeIntervalSinceNow:]",
    "-[NSNotificationCenter postNotificationName:object:userInfo:]",
    "+[NSMutableDictionary dictionary]",
    "-[NSMutableDictionary setValue:forKey:]",
    "+[NSNumber numberWithInt:]",
    "NativeInterruptionTypeKey",
    "+[NativePoster post:type:]",
    "+[NativePoster pending]",
    "+[NativeAudioCenter shared]",
    "-[NativeAudioCenter addObserverForName:object:queue:usingBlock:]",
    "-[NativeAudioCenter removeObserver:]",
    "-[NativeAudioCenter post:]",
    "-[NativeAudioCenter postInBackground:]",
    "+[NativeAudioCenter backgroundReleases]",
]

MANIFEST = f"""manifest-version = 1
[package]
name = "mainExecutorConsumer"
[[native.bindings]]
module = "Foundation"
header = "Foundation.h"
language = "objective-c"
standard = "c11"
os = ["macos"]
symbols = [{", ".join(f'"{symbol}"' for symbol in SYMBOLS)}]
[native.bindings.callbacks."-[NSNotificationCenter addObserverForName:object:queue:usingBlock:].block"]
interface = "IInterruptionObserver"
lifetime = "stored"
failure = "abort"
executor = "main"
unregister = "-[NSNotificationCenter removeObserver:]"
activation-failure = "abort"
cancellation = "entry-barrier"
[native.bindings.callbacks."-[NativeAudioCenter addObserverForName:object:queue:usingBlock:].block"]
interface = "IAudioObserver"
lifetime = "stored"
failure = "abort"
executor = "AUDIO_EXECUTOR"
unregister = "-[NativeAudioCenter removeObserver:]"
activation-failure = "abort"
cancellation = "entry-barrier"
[[native.sources]]
path = "Probe.m"
language = "objective-c"
standard = "c11"
os = ["macos"]
[[native.frameworks]]
name = "Foundation"
os = ["macos"]
"""

PROGRAM = """import Library.Callback;
import ./Foundation.btrc;
#include <assert.h>
int deliveries = 0;
int offMain = 0;
int lastType = -1;
int destroyed = 0;
int destroyedOffMain = 0;
int audioDeliveries = 0;
int audioDestroyed = 0;
bool rejected = false;
class Interruption implements IInterruptionObserver {
	private CallbackScope scope;
	public Interruption(CallbackScope scope) { self.scope = scope; }
	public void invoke(NSNotification notification) {
		deliveries++;
		if (!NSThread.isMainThread()) { offMain++; }
		lastType = -1;
		NSDictionary? info = notification.userInfo();
		if (info != null) {
			NSNumber? type = (NSNumber?)info.objectForKey(NativeInterruptionTypeKey);
			if (type != null) { lastType = type.intValue(); }
		}
		// The interruption that ends cancels its own observation.
		if (lastType == 0) { assert(self.scope.cancel() == CALLBACK_CANCELLATION_PENDING); }
	}
	public void __del__() {
		destroyed++;
		if (!NSThread.isMainThread()) { destroyedOffMain++; }
	}
}
class AudioObserver implements IAudioObserver {
	public void invoke(NSNotification notification) { audioDeliveries++; }
	public void __del__() {
		audioDestroyed++;
		if (!NSThread.isMainThread()) { destroyedOffMain++; }
	}
}
// The main run loop drains the main queue: deliveries and posted releases.
void spin(int expected) {
	for (int index = 0; index < 2000 && (deliveries < expected || NativePoster.pending() > 0); index++) {
		NSRunLoop.currentRunLoop().runUntilDate(NSDate.dateWithTimeIntervalSinceNow(0.005));
	}
}
int main() {
	var name = NSString.stringWithUTF8String("BTRC.NativeInterruption");
	for (int round = 0; round < 25; round++) {
		var scope = CallbackScope();
		ICallbackRegistration observation = NSNotificationCenter.defaultCenter().addObserverForName(name, null, NSOperationQueue.mainQueue(), Interruption(scope), scope);
		// Posted on a background queue, delivered on the main queue.
		NativePoster.post(name, 1);
		spin(2 * round + 1);
		assert(deliveries == 2 * round + 1 && offMain == 0 && lastType == 1 && observation.isOpen());
		NativePoster.post(name, 0);
		spin(2 * round + 2);
		assert(deliveries == 2 * round + 2 && offMain == 0 && lastType == 0);
		assert(!observation.isOpen() && scope.pollCompletion() == CALLBACK_CANCELLATION_COMPLETE);
		assert(destroyed == round + 1 && destroyedOffMain == 0);
		// Nothing arrives after cancellation.
		NativePoster.post(name, 1);
		spin(2 * round + 2);
		assert(deliveries == 2 * round + 2);
	}
	// A BTRC thread posts, as AVAudioSession's own thread does on iOS; the
	// poster waits for the main queue, which this thread drains before joining.
	var posterScope = CallbackScope();
	ICallbackRegistration posterObservation = NSNotificationCenter.defaultCenter().addObserverForName(name, null, NSOperationQueue.mainQueue(), Interruption(posterScope), posterScope);
	var poster = spawn(() => {
			NSMutableDictionary info = NSMutableDictionary.dictionary();
			info.setValue(NSNumber.numberWithInt(0), NativeInterruptionTypeKey);
			NSString? posted = NSString.stringWithUTF8String("BTRC.NativeInterruption");
			if (posted != null) { NSNotificationCenter.defaultCenter().postNotificationName(posted, null, info); }
		});
	for (int index = 0; index < 2000 && deliveries < 51; index++) {
		NSRunLoop.currentRunLoop().runUntilDate(NSDate.dateWithTimeIntervalSinceNow(0.005));
	}
	poster.join();
	assert(deliveries == 51 && offMain == 0 && lastType == 0);
	assert(!posterObservation.isOpen() && posterScope.pollCompletion() == CALLBACK_CANCELLATION_COMPLETE && destroyed == 26);
	var audio = NSString.stringWithUTF8String("BTRC.NativeAudio");
	NativeAudioCenter center = NativeAudioCenter.shared();
	for (int round = 0; round < 25; round++) {
		var scope = CallbackScope();
		ICallbackRegistration observation = center.addObserverForName(audio, null, null, AudioObserver(), scope);
		center.post(audio);
		assert(audioDeliveries == round + 1);
		MODE
		// The center drops the block on another thread; the holder posts its release to the main queue.
		assert(scope.cancel() == CALLBACK_CANCELLATION_COMPLETE && !observation.isOpen());
		assert(audioDestroyed == round + 1 && NativeAudioCenter.backgroundReleases() == round + 1);
		spin(0);
		NSRunLoop.currentRunLoop().runUntilDate(NSDate.dateWithTimeIntervalSinceNow(0.005));
		center.post(audio);
		assert(audioDeliveries == round + 1);
	}
	assert(destroyedOffMain == 0);
	// Registration is checked on the main thread before anything is published.
	var worker = spawn(() => {
			var scope = CallbackScope();
			try {
				NativeAudioCenter.shared().addObserverForName(NSString.stringWithUTF8String("BTRC.Worker"), null, null, AudioObserver(), scope);
			} catch (string error) {
				rejected = error == "Stored callback -[NativeAudioCenter addObserverForName:object:queue:usingBlock:] requires the main thread";
			}
		});
	worker.join();
	assert(rejected && audioDestroyed == 26);
	return 0;
}
"""


@pytest.fixture
def main_project(native_project):
    source, _, _ = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(HEADER)
    (root / "Probe.m").write_text(PROBE)
    (source.parent / "Foundation.btrc").write_text("")
    return source


def _build_and_run(source, native_compile, sanitize):
    root = source.parent.parent
    plan_path = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan_path)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Program.c"
    generated.write_text(compiled.c_source)

    def run(command, **kwargs):
        flags = ["-O1", "-g", "-fsanitize=address,undefined"] if sanitize else ["-O2"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    executable = root / "Program"
    NativePlanBuilder(runner=run).build(
        plan_path=plan_path, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    return subprocess.run(
        [str(executable)],
        env={**apple_environment(), "UBSAN_OPTIONS": "halt_on_error=1"},
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize(
    ("scenario", "executor", "mode", "failure"),
    [
        ("main-queue", "main", "", None),
        # The center calls the block on another thread: the entry is checked.
        (
            "wrong-thread-delivery",
            "main",
            "center.postInBackground(audio);",
            "Callback context requires its creating thread",
        ),
        # The caller executor touches ARC where the SDK released the block, and terminates.
        ("caller-release-off-thread", "caller", "", "Callback context requires its creating thread"),
    ],
)
def test_main_executor_blocks_deliver_and_release_on_main(
    main_project, native_compile, sanitize, scenario, executor, mode, failure
):
    source = main_project
    (source.parent.parent / "btrc.toml").write_text(MANIFEST.replace("AUDIO_EXECUTOR", executor))
    source.write_text(PROGRAM.replace("MODE", mode))
    completed = _build_and_run(source, native_compile, sanitize)
    if failure is None:
        assert completed.returncode == 0, (scenario, completed.returncode, completed.stderr)
        assert not completed.stderr, completed.stderr
    else:
        assert completed.returncode == -6, (scenario, completed.returncode, completed.stderr)
        assert failure in completed.stderr
    assert "ERROR: AddressSanitizer" not in completed.stderr
    assert "runtime error:" not in completed.stderr


CALLER_MANIFEST = MANIFEST.replace("AUDIO_EXECUTOR", "caller")
AUDIO_CALLBACK = CALLER_MANIFEST[
    CALLER_MANIFEST.index('[native.bindings.callbacks."-[NativeAudioCenter') : CALLER_MANIFEST.index(
        "[[native.sources]]"
    )
]
ONE_SHOT = """[native.bindings.callbacks."-[NativeAudioCenter addObserverForName:object:queue:usingBlock:].block"]
interface = "IAudioObserver"
lifetime = "one-shot"
failure = "abort"
executor = "main"
activation-failure = "abort"
cancellation = "abandon"
"""


@pytest.mark.parametrize(
    ("old", "new"),
    [
        # Only a stored block takes the main executor.
        (AUDIO_CALLBACK, ONE_SHOT),
        ('executor = "main"', 'executor = "main-context"'),
    ],
)
def test_main_executor_rejects_other_forms(main_project, native_compile, old, new):
    source = main_project
    assert old in CALLER_MANIFEST
    (source.parent.parent / "btrc.toml").write_text(CALLER_MANIFEST.replace(old, new, 1))
    source.write_text("import Library.Callback;\nimport ./Foundation.btrc;\nint main() { return 0; }\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert "executor currently requires caller, or main for a stored Objective-C block" in str(compiled.failure) + str(
        compiled.diagnostics
    )
