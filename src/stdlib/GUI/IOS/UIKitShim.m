/* The UIKit side of the shim provider, for iOS and iPadOS; ../Shim/Shim.h is
 * the contract.
 *
 * UIKit owns the process: btrcUIKitMain is the program's entry (an app links
 * with -e _btrcUIKitMain), enters UIApplicationMain on the main thread and
 * never returns. The program's own main runs on a thread of its own. Each
 * function of the contract does its work on the main thread and returns when
 * that is done; what a person does comes back as events pushed onto the
 * queue below, which the program polls. No callback enters BTRC.
 *
 * A window is a UIWindow of the scene the program's windows live in, and
 * the scene gives it the whole of itself: the last window shown is the one
 * on the screen. Its content keeps clear of the bars and the sensor housing
 * (the safe area), and is a whole number of points each way. */
#import "UIKitShimPrivate.h"

#import <CoreText/CoreText.h>
#import <QuartzCore/CAMetalLayer.h>
#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

enum { BTRC_UIKIT_QUEUE = 16384, BTRC_UIKIT_SCENE_SECONDS = 30 };
static const CFTimeInterval BTRC_UIKIT_SCENE_ARRIVAL_SECONDS = 1.0;

struct BtrcShimFolderDialog {
	int state;
};

struct BtrcShimFileDialog {
	pthread_mutex_t lock;
	int state;
	char** paths;
	int pathCount;
	id delegate;
};

static struct {
	BtrcShimEvent events[BTRC_UIKIT_QUEUE];
	char* texts[BTRC_UIKIT_QUEUE];
	unsigned int head;
	unsigned int count;
	pthread_mutex_t lock;
	pthread_cond_t arrived;
	char* handed;
	unsigned long serial;
} btrcUIKitQueue = {.lock = PTHREAD_MUTEX_INITIALIZER, .arrived = PTHREAD_COND_INITIALIZER};

/* Whether a scene has connected for the program's windows; the scene itself
 * is the main thread's. */
static struct {
	pthread_mutex_t lock;
	pthread_cond_t changed;
	bool connected;
} btrcUIKitSession = {.lock = PTHREAD_MUTEX_INITIALIZER, .changed = PTHREAD_COND_INITIALIZER};

static pthread_t btrcUIKitThread;
static bool btrcUIKitRunning;
static bool btrcUIKitStarted;
static char btrcUIKitFailure[160];
static int btrcUIKitArgumentCount;
static char** btrcUIKitArguments;
static char btrcUIKitOutput[1024];
static volatile unsigned int btrcUIKitModifiers;

/* The main thread's. */
static UIWindowScene* btrcUIKitScene;
static BOOL btrcUIKitActive;
/* When the scene last became the one a person is using (CACurrentMediaTime). */
static CFTimeInterval btrcUIKitActiveSince;
static BOOL btrcUIKitDark = YES;
static BOOL btrcUIKitWantsSecondScene;
static BOOL btrcUIKitAwaitsSecondScene;
static NSMutableArray<BtrcUIKitWindow*>* btrcUIKitWindows;
static NSMutableArray<BtrcUIKitWindow*>* btrcUIKitShown;
static unsigned int btrcUIKitNextWindow = 1u;

void btrcUIKitFail(const char* message) { snprintf(btrcUIKitFailure, sizeof btrcUIKitFailure, "%s", message); }

const char* btrcShimError(void) { return btrcUIKitFailure; }

void btrcUIKitOnMain(void (^work)(void)) {
	if (pthread_main_np() != 0) { work(); return; }
	dispatch_sync(dispatch_get_main_queue(), work);
}

NSString* btrcUIKitString(const char* text) {
	NSString* string = text == NULL ? nil : [[NSString alloc] initWithUTF8String:text];
	return string != nil ? string : [[NSString alloc] init];
}

/* The queue. */

bool btrcUIKitPush(const BtrcShimEvent* event, const char* text) {
	bool queued = false;
	pthread_mutex_lock(&btrcUIKitQueue.lock);
	if (btrcUIKitQueue.count < BTRC_UIKIT_QUEUE) {
		unsigned int slot = (btrcUIKitQueue.head + btrcUIKitQueue.count) % BTRC_UIKIT_QUEUE;
		btrcUIKitQueue.events[slot] = *event;
		btrcUIKitQueue.events[slot].text = NULL;
		btrcUIKitQueue.texts[slot] = text == NULL ? NULL : strdup(text);
		btrcUIKitQueue.count++;
		queued = true;
	}
	btrcUIKitQueue.serial++;
	pthread_cond_broadcast(&btrcUIKitQueue.arrived);
	pthread_mutex_unlock(&btrcUIKitQueue.lock);
	return queued;
}

void btrcUIKitPushWindow(BtrcUIKitWindow* window, unsigned int type) {
	BtrcShimEvent event;
	memset(&event, 0, sizeof event);
	event.type = type;
	event.window = window->identifier;
	btrcUIKitPush(&event, NULL);
}

void btrcUIKitPushControl(BtrcUIKitControl* control, unsigned int type, int data, double value, NSString* text) {
	BtrcShimEvent event;
	memset(&event, 0, sizeof event);
	event.type = type;
	event.window = control->window == nil ? 0u : control->window->identifier;
	event.control = control->identifier;
	event.data1 = data;
	event.value = value;
	btrcUIKitPush(&event, text == nil ? NULL : text.UTF8String);
}

static int btrcUIKitPop(BtrcShimEvent* out) {
	int popped = 0;
	free(btrcUIKitQueue.handed);
	btrcUIKitQueue.handed = NULL;
	if (btrcUIKitQueue.count > 0u) {
		unsigned int slot = btrcUIKitQueue.head;
		*out = btrcUIKitQueue.events[slot];
		btrcUIKitQueue.handed = btrcUIKitQueue.texts[slot];
		btrcUIKitQueue.texts[slot] = NULL;
		out->text = btrcUIKitQueue.handed;
		btrcUIKitQueue.head = (btrcUIKitQueue.head + 1u) % BTRC_UIKIT_QUEUE;
		btrcUIKitQueue.count--;
		popped = 1;
	}
	return popped;
}

/* The main thread runs by itself: there is nothing to let run before looking. */
int btrcShimPollEvent(BtrcShimEvent* out) {
	pthread_mutex_lock(&btrcUIKitQueue.lock);
	int popped = btrcUIKitPop(out);
	pthread_mutex_unlock(&btrcUIKitQueue.lock);
	return popped;
}

static struct timespec btrcUIKitDeadline(int milliseconds) {
	struct timespec deadline;
	clock_gettime(CLOCK_REALTIME, &deadline);
	deadline.tv_sec += milliseconds / 1000;
	deadline.tv_nsec += (long)(milliseconds % 1000) * 1000000L;
	if (deadline.tv_nsec >= 1000000000L) { deadline.tv_sec++; deadline.tv_nsec -= 1000000000L; }
	return deadline;
}

int btrcShimWaitEvent(BtrcShimEvent* out, int timeoutMilliseconds) {
	pthread_mutex_lock(&btrcUIKitQueue.lock);
	if (btrcUIKitQueue.count == 0u) {
		if (timeoutMilliseconds < 0) { pthread_cond_wait(&btrcUIKitQueue.arrived, &btrcUIKitQueue.lock); }
		else if (timeoutMilliseconds > 0) {
			struct timespec deadline = btrcUIKitDeadline(timeoutMilliseconds);
			pthread_cond_timedwait(&btrcUIKitQueue.arrived, &btrcUIKitQueue.lock, &deadline);
		}
	}
	int popped = btrcUIKitPop(out);
	pthread_mutex_unlock(&btrcUIKitQueue.lock);
	return popped;
}

bool btrcShimPushWake(void) {
	BtrcShimEvent event;
	memset(&event, 0, sizeof event);
	event.type = BTRC_SHIM_EVENT_USER;
	return btrcUIKitPush(&event, NULL);
}

/* Keys. UIKey's codes are the keyboard page's usages. */

static unsigned int btrcUIKitKey(UIKeyboardHIDUsage usage) {
	switch (usage) {
	case UIKeyboardHIDUsageKeyboardEscape: return BTRC_SHIM_KEY_ESCAPE;
	case UIKeyboardHIDUsageKeyboardReturnOrEnter: return BTRC_SHIM_KEY_RETURN;
	case UIKeyboardHIDUsageKeypadEnter: return BTRC_SHIM_KEY_KP_ENTER;
	case UIKeyboardHIDUsageKeyboardSpacebar: return BTRC_SHIM_KEY_SPACE;
	case UIKeyboardHIDUsageKeyboardLeftArrow: return BTRC_SHIM_KEY_LEFT;
	case UIKeyboardHIDUsageKeyboardRightArrow: return BTRC_SHIM_KEY_RIGHT;
	case UIKeyboardHIDUsageKeyboardUpArrow: return BTRC_SHIM_KEY_UP;
	case UIKeyboardHIDUsageKeyboardDownArrow: return BTRC_SHIM_KEY_DOWN;
	case UIKeyboardHIDUsageKeyboardTab: return BTRC_SHIM_KEY_TAB;
	case UIKeyboardHIDUsageKeyboardDeleteOrBackspace: return BTRC_SHIM_KEY_BACKSPACE;
	case UIKeyboardHIDUsageKeyboardDeleteForward: return BTRC_SHIM_KEY_DELETE;
	case UIKeyboardHIDUsageKeyboardHome: return BTRC_SHIM_KEY_HOME;
	case UIKeyboardHIDUsageKeyboardEnd: return BTRC_SHIM_KEY_END;
	case UIKeyboardHIDUsageKeyboardLeftShift: return BTRC_SHIM_KEY_LSHIFT;
	case UIKeyboardHIDUsageKeyboardRightShift: return BTRC_SHIM_KEY_RSHIFT;
	case UIKeyboardHIDUsageKeyboardLeftAlt: return BTRC_SHIM_KEY_LALT;
	case UIKeyboardHIDUsageKeyboardRightAlt: return BTRC_SHIM_KEY_RALT;
	case UIKeyboardHIDUsageKeyboardA: return BTRC_SHIM_KEY_A;
	case UIKeyboardHIDUsageKeyboardC: return BTRC_SHIM_KEY_C;
	case UIKeyboardHIDUsageKeyboardV: return BTRC_SHIM_KEY_V;
	default: return BTRC_SHIM_KEY_UNKNOWN;
	}
}

/* Letters and brackets as their unshifted character; Shim.h's named codes. */
static unsigned int btrcUIKitScancode(UIKeyboardHIDUsage usage) {
	if (usage >= UIKeyboardHIDUsageKeyboardA && usage <= UIKeyboardHIDUsageKeyboardZ) { return (unsigned int)'a' + (unsigned int)(usage - UIKeyboardHIDUsageKeyboardA); }
	switch (usage) {
	case UIKeyboardHIDUsageKeyboardOpenBracket: return BTRC_SHIM_SCANCODE_LEFTBRACKET;
	case UIKeyboardHIDUsageKeyboardCloseBracket: return BTRC_SHIM_SCANCODE_RIGHTBRACKET;
	case UIKeyboardHIDUsageKeyboardDeleteOrBackspace: return BTRC_SHIM_SCANCODE_BACKSPACE;
	case UIKeyboardHIDUsageKeyboardLeftArrow: return BTRC_SHIM_SCANCODE_LEFT;
	case UIKeyboardHIDUsageKeyboardEnd: return BTRC_SHIM_SCANCODE_END;
	default: return 0u;
	}
}

static unsigned int btrcUIKitModifierBits(UIKeyModifierFlags flags) {
	return ((flags & UIKeyModifierShift) != 0 ? BTRC_SHIM_MOD_SHIFT : 0u) | ((flags & UIKeyModifierControl) != 0 ? BTRC_SHIM_MOD_CTRL : 0u) | ((flags & UIKeyModifierAlternate) != 0 ? BTRC_SHIM_MOD_ALT : 0u) |
		((flags & UIKeyModifierCommand) != 0 ? BTRC_SHIM_MOD_GUI : 0u);
}

unsigned int btrcShimModState(void) { return btrcUIKitModifiers; }

/* Windows. */

static BtrcUIKitWindow* btrcUIKitTop(void) { return btrcUIKitShown.lastObject; }

/* How many times a window has been put on show. */
static int btrcUIKitShows;

/* The alert on show, and what the program's thread waits on for it. */
static UIAlertController* btrcUIKitAlert;
static dispatch_semaphore_t btrcUIKitAlertDismissed;

static void btrcUIKitAlertFinished(void) {
	if (btrcUIKitAlert == nil) { return; }
	[btrcUIKitAlert release];
	btrcUIKitAlert = nil;
	dispatch_semaphore_signal(btrcUIKitAlertDismissed);
}

/* YES when the key was the alert's: Return and Escape dismiss it. */
static BOOL btrcUIKitAlertKeyDown(unsigned int key) {
	if (btrcUIKitAlert == nil) { return NO; }
	if (key != BTRC_SHIM_KEY_RETURN && key != BTRC_SHIM_KEY_KP_ENTER && key != BTRC_SHIM_KEY_ESCAPE) { return NO; }
	if (!btrcUIKitAlert.beingDismissed) { [btrcUIKitAlert dismissViewControllerAnimated:YES completion:^{ btrcUIKitAlertFinished(); }]; }
	return YES;
}

static void btrcUIKitPushPointer(BtrcUIKitWindow* window, unsigned int type, CGPoint at, unsigned int button, unsigned int clicks, int down, unsigned int modifiers) {
	BtrcShimEvent event;
	memset(&event, 0, sizeof event);
	event.type = type;
	event.window = window->identifier;
	event.x = (float)at.x;
	event.y = (float)at.y;
	event.button = button;
	event.clicks = clicks;
	event.down = down;
	event.modifiers = modifiers;
	btrcUIKitPush(&event, NULL);
}

/* The view a window's drawn content is presented on: a CAMetalLayer in the
 * view's first subview, beneath the controls' slots, which are the subviews
 * after it. The layer is its own and no view's backing layer, because the
 * program's thread configures and presents it, and UIKit lets only the main
 * thread touch a layer a view answers for. */
@interface BtrcUIKitContentView : UIView {
@public
	CAMetalLayer* metal;
	UIView* surface;
}
@end

@implementation BtrcUIKitContentView
- (instancetype)initWithFrame:(CGRect)frame {
	self = [super initWithFrame:frame];
	if (self == nil) { return nil; }
	surface = [[UIView alloc] initWithFrame:self.bounds];
	surface.userInteractionEnabled = NO;
	metal = [[CAMetalLayer alloc] init];
	metal.opaque = YES;
	metal.frame = surface.bounds;
	/* It follows the view at once: nothing of it animates. */
	metal.actions = @{@"bounds" : NSNull.null, @"position" : NSNull.null, @"contents" : NSNull.null, @"contentsScale" : NSNull.null, @"hidden" : NSNull.null};
	[surface.layer addSublayer:metal];
	[self addSubview:surface];
	return self;
}

- (void)dealloc {
	[metal removeFromSuperlayer];
	[metal release];
	[surface release];
	[super dealloc];
}

- (void)layoutSubviews {
	[super layoutSubviews];
	if (!CGRectEqualToRect(surface.frame, self.bounds)) { surface.frame = self.bounds; }
	if (!CGRectEqualToRect(metal.frame, surface.bounds)) { metal.frame = surface.bounds; }
}
@end

/* A window's root: it fills the scene, keeps the content inside the safe
 * area, and hears the keyboard's close request. */
@interface BtrcUIKitRootController : UIViewController {
@public
	BtrcUIKitWindow* owner;
}
@end

/* The UIWindow itself: what a person does reaches the program's queue before
 * any view acts on it. */
@interface BtrcUIKitNativeWindow : UIWindow {
@public
	BtrcUIKitWindow* owner;
	/* The finger or button a press began with; compared, never used. */
	UITouch* primary;
	BOOL pressed;
	NSMutableSet<NSNumber*>* held;
	/* The keys the controls took, whose release is theirs too. */
	NSMutableSet<NSNumber*>* taken;
	unsigned long hoverGeneration;
	/* How far the wheel's gesture under way has turned, of which every report is the whole. */
	CGPoint turned;
}
- (BOOL)observePresses:(UIPressesEvent*)event;
- (void)observeHover:(UIHoverGestureRecognizer*)hover;
- (void)observeScroll:(UIPanGestureRecognizer*)scroll;
@end

@implementation BtrcUIKitWindow
- (instancetype)initWithTitle:(NSString*)name width:(int)width height:(int)height {
	self = [super init];
	if (self == nil) { return nil; }
	identifier = btrcUIKitNextWindow++;
	title = [name copy];
	askedWidth = width;
	askedHeight = height;
	placed = [[NSMutableArray alloc] init];
	BtrcUIKitNativeWindow* window = [[BtrcUIKitNativeWindow alloc] initWithWindowScene:btrcUIKitScene];
	window->owner = self;
	window->held = [[NSMutableSet alloc] init];
	window->taken = [[NSMutableSet alloc] init];
	native = window;
	BtrcUIKitRootController* root = [[BtrcUIKitRootController alloc] init];
	root->owner = self;
	window.rootViewController = root;
	[root release];
	window.overrideUserInterfaceStyle = btrcUIKitDark ? UIUserInterfaceStyleDark : UIUserInterfaceStyleLight;
	content = [[BtrcUIKitContentView alloc] initWithFrame:CGRectMake(0.0, 0.0, (CGFloat)width, (CGFloat)height)];
	((BtrcUIKitContentView*)content)->metal.contentsScale = btrcUIKitScene.screen.scale;
	[root.view addSubview:content];
	UIHoverGestureRecognizer* hover = [[UIHoverGestureRecognizer alloc] initWithTarget:window action:@selector(observeHover:)];
	[content addGestureRecognizer:hover];
	[hover release];
	/* A wheel and a trackpad's two fingers, never a finger on the screen. */
	UIPanGestureRecognizer* scroll = [[UIPanGestureRecognizer alloc] initWithTarget:window action:@selector(observeScroll:)];
	scroll.allowedScrollTypesMask = UIScrollTypeMaskAll;
	scroll.allowedTouchTypes = @[];
	scroll.cancelsTouchesInView = NO;
	[content addGestureRecognizer:scroll];
	[scroll release];
	return self;
}

- (void)dealloc {
	[title release];
	[placed release];
	[content release];
	[native release];
	free(placing);
	free(rectangles);
	[super dealloc];
}

/* One request a press of Command-W, whichever of UIKit's two ways of hearing
 * the key reaches here first. */
- (void)closeRequested {
	CFTimeInterval now = CACurrentMediaTime();
	if (now - closeAsked < 0.25) { return; }
	closeAsked = now;
	btrcUIKitPushWindow(self, BTRC_SHIM_EVENT_WINDOW_CLOSE_REQUESTED);
}

/* The content is the safe area's whole points, once the window has been
 * shown; a new size is the program's to hear of. */
- (void)settle {
	if (!sized) { return; }
	UIView* root = native.rootViewController.view;
	CGRect safe = root.safeAreaLayoutGuide.layoutFrame;
	CGRect frame = CGRectMake(safe.origin.x, safe.origin.y, floor(safe.size.width), floor(safe.size.height));
	if (frame.size.width <= 0.0 || frame.size.height <= 0.0) { return; }
	CGFloat scale = native.traitCollection.displayScale;
	CAMetalLayer* metal = ((BtrcUIKitContentView*)content)->metal;
	BOOL changed = !CGSizeEqualToSize(content.frame.size, frame.size) || (scale > 0.0 && metal.contentsScale != scale);
	if (scale > 0.0) { metal.contentsScale = scale; }
	if (!CGRectEqualToRect(content.frame, frame)) {
		content.frame = frame;
		[content layoutIfNeeded];
	}
	if (changed || !announced) {
		announced = YES;
		btrcUIKitPushWindow(self, BTRC_SHIM_EVENT_WINDOW_RESIZED);
		btrcUIKitPushWindow(self, BTRC_SHIM_EVENT_WINDOW_PIXEL_SIZE_CHANGED);
		btrcUIKitPushWindow(self, BTRC_SHIM_EVENT_WINDOW_EXPOSED);
	}
}
@end

@implementation BtrcUIKitRootController
- (void)loadView {
	UIView* view = [[UIView alloc] initWithFrame:CGRectZero];
	self.view = view;
	[view release];
}

- (void)viewDidLayoutSubviews {
	[super viewDidLayoutSubviews];
	self.view.backgroundColor = btrcUIKitDark ? [UIColor colorWithRed:0.118 green:0.118 blue:0.129 alpha:1.0] : [UIColor colorWithRed:0.933 green:0.933 blue:0.941 alpha:1.0];
	[owner settle];
}

- (void)viewSafeAreaInsetsDidChange {
	[super viewSafeAreaInsetsDidChange];
	[self.view setNeedsLayout];
}

/* Command-W is the keyboard's close request, on a phone as on a tablet. The
 * command is here for the system to list among the app's shortcuts; the key
 * itself is read with every other key (observePresses), which is what asks. */
- (NSArray<UIKeyCommand*>*)keyCommands {
	UIKeyCommand* close = [UIKeyCommand keyCommandWithInput:@"w" modifierFlags:UIKeyModifierCommand action:@selector(btrcCloseRequested:)];
	close.wantsPriorityOverSystemBehavior = YES;
	close.discoverabilityTitle = @"Close Window";
	return @[close];
}

- (void)btrcCloseRequested:(id)sender {
	(void)sender;
	if (owner != nil) { [owner closeRequested]; }
}
@end

@implementation BtrcUIKitNativeWindow
- (void)dealloc {
	[held release];
	[taken release];
	[super dealloc];
}

- (void)leave {
	if (owner != nil && owner->pointerInside) {
		owner->pointerInside = NO;
		btrcUIKitPushWindow(owner, BTRC_SHIM_EVENT_WINDOW_MOUSE_LEAVE);
	}
}

/* Where the pointer or the finger is now; NO when that is outside the content. */
- (BOOL)pointAt:(CGPoint)at {
	hoverGeneration++;
	if (!CGRectContainsPoint(owner->content.bounds, at)) {
		[self leave];
		return NO;
	}
	if (!owner->pointerInside) {
		owner->pointerInside = YES;
		btrcUIKitPushWindow(owner, BTRC_SHIM_EVENT_WINDOW_MOUSE_ENTER);
	}
	owner->pointer = at;
	return YES;
}

- (void)observeTouches:(UIEvent*)event {
	unsigned int modifiers = btrcUIKitModifierBits(event.modifierFlags);
	for (UITouch* touch in event.allTouches) {
		if (touch.phase == UITouchPhaseBegan && primary == nil) { primary = touch; }
		if (touch != primary) { continue; }
		CGPoint at = [touch locationInView:owner->content];
		BOOL within = [self pointAt:at];
		switch (touch.phase) {
		case UITouchPhaseBegan:
			btrcUIKitControlsTouchDown();
			if (within) {
				pressed = YES;
				btrcUIKitPushPointer(owner, BTRC_SHIM_EVENT_MOUSE_MOTION, at, 0u, 0u, 0, modifiers);
				btrcUIKitPushPointer(owner, BTRC_SHIM_EVENT_MOUSE_BUTTON_DOWN, at, 1u, (unsigned int)touch.tapCount, 1, modifiers);
			}
			break;
		case UITouchPhaseMoved:
			if (within) { btrcUIKitPushPointer(owner, BTRC_SHIM_EVENT_MOUSE_MOTION, at, 0u, 0u, 0, modifiers); }
			break;
		case UITouchPhaseEnded:
		case UITouchPhaseCancelled:
			/* A press that began in the content ends wherever the finger lifts. */
			if (pressed) { btrcUIKitPushPointer(owner, BTRC_SHIM_EVENT_MOUSE_BUTTON_UP, at, 1u, (unsigned int)touch.tapCount, 0, modifiers); }
			pressed = NO;
			primary = nil;
			break;
		default:
			break;
		}
	}
}

/* Every key down is the window's first; then the controls', which may keep
 * it from UIKit. YES when they did. */
- (BOOL)observePresses:(UIPressesEvent*)event {
	BOOL kept = NO;
	for (UIPress* press in event.allPresses) {
		UIKey* key = press.key;
		if (key == nil) { continue; }
		NSNumber* code = @(key.keyCode);
		BOOL down = press.phase == UIPressPhaseBegan && ![held containsObject:code];
		BOOL up = (press.phase == UIPressPhaseEnded || press.phase == UIPressPhaseCancelled) && [held containsObject:code];
		if (!down && !up) {
			if ([taken containsObject:code]) { kept = YES; }
			continue;
		}
		unsigned int modifiers = btrcUIKitModifierBits(key.modifierFlags);
		btrcUIKitModifiers = modifiers;
		BtrcShimEvent pushed;
		memset(&pushed, 0, sizeof pushed);
		pushed.type = down ? BTRC_SHIM_EVENT_KEY_DOWN : BTRC_SHIM_EVENT_KEY_UP;
		pushed.window = owner->identifier;
		pushed.scancode = btrcUIKitScancode(key.keyCode);
		if (key.keyCode != 0) { pushed.physicalSet = BTRC_SHIM_PHYSICAL_USB_KEYBOARD; pushed.physicalCode = (unsigned int)key.keyCode; }
		pushed.key = btrcUIKitKey(key.keyCode);
		pushed.modifiers = modifiers;
		pushed.down = down ? 1 : 0;
		btrcUIKitPush(&pushed, NULL);
		unsigned int scancode = pushed.scancode;
		if (down) {
			[held addObject:code];
			NSString* typed = key.characters;
			if (typed.length > 0 && [typed characterAtIndex:0] >= 0x20 && [typed characterAtIndex:0] != 0x7f && ![typed hasPrefix:@"UIKeyInput"] && (modifiers & (BTRC_SHIM_MOD_CTRL | BTRC_SHIM_MOD_GUI)) == 0u) {
				memset(&pushed, 0, sizeof pushed);
				pushed.type = BTRC_SHIM_EVENT_TEXT_INPUT;
				pushed.window = owner->identifier;
				btrcUIKitPush(&pushed, typed.UTF8String);
			}
			if (scancode == BTRC_SHIM_SCANCODE_W && modifiers == BTRC_SHIM_MOD_GUI) {
				[owner closeRequested];
				[taken addObject:code];
				kept = YES;
			} else if (btrcUIKitAlertKeyDown(btrcUIKitKey(key.keyCode)) || btrcUIKitControlsKeyDown(owner, btrcUIKitKey(key.keyCode))) {
				[taken addObject:code];
				kept = YES;
			}
		} else {
			[held removeObject:code];
			if ([taken containsObject:code]) {
				[taken removeObject:code];
				kept = YES;
			}
		}
	}
	return kept;
}

- (void)sendEvent:(UIEvent*)event {
	BOOL touching = owner != nil && event.type == UIEventTypeTouches;
	if (touching) { [self observeTouches:event]; }
	[super sendEvent:event];
	if (touching && primary == nil) { btrcUIKitControlsTouchUp(); }
}

/* A pointer over the content with no button down. A hover ends when the
 * pointer leaves, and also when its button goes down, which is not leaving:
 * the press that follows says so. */
- (void)observeHover:(UIHoverGestureRecognizer*)hover {
	if (owner == nil) { return; }
	if (hover.state == UIGestureRecognizerStateBegan || hover.state == UIGestureRecognizerStateChanged) {
		CGPoint at = [hover locationInView:owner->content];
		if ([self pointAt:at]) { btrcUIKitPushPointer(owner, BTRC_SHIM_EVENT_MOUSE_MOTION, at, 0u, 0u, 0, btrcUIKitModifierBits(hover.modifierFlags)); }
		return;
	}
	if (hover.state == UIGestureRecognizerStateEnded || hover.state == UIGestureRecognizerStateCancelled) {
		unsigned long generation = ++hoverGeneration;
		BtrcUIKitNativeWindow* window = [self retain];
		dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 50 * (int64_t)NSEC_PER_MSEC), dispatch_get_main_queue(), ^{
			if (window->hoverGeneration == generation) { [window leave]; }
			[window release];
		});
	}
}

/* A wheel's notches and a trackpad's fingers arrive as the points they would
 * move a document by: a notch is a gesture of its own, which begins with the
 * whole of it. */
- (void)observeScroll:(UIPanGestureRecognizer*)scroll {
	if (owner == nil || (scroll.state != UIGestureRecognizerStateBegan && scroll.state != UIGestureRecognizerStateChanged)) { return; }
	CGPoint whole = [scroll translationInView:owner->content];
	if (scroll.state == UIGestureRecognizerStateBegan) { turned = CGPointZero; }
	CGPoint moved = CGPointMake(whole.x - turned.x, whole.y - turned.y);
	turned = whole;
	if (moved.x == 0.0 && moved.y == 0.0) { return; }
	/* The wheel turns where the pointer is, which may have rested there since before the
	 * window was: the gesture's own place has moved from it by all the gesture has turned. */
	CGPoint place = [scroll locationInView:owner->content];
	CGPoint at = CGPointMake(place.x - whole.x, place.y - whole.y);
	if (![self pointAt:at]) { return; }
	BtrcShimEvent event;
	memset(&event, 0, sizeof event);
	event.type = BTRC_SHIM_EVENT_MOUSE_WHEEL;
	event.window = owner->identifier;
	event.x = (float)at.x;
	event.y = (float)at.y;
	event.wheelX = (float)moved.x;
	event.wheelY = (float)moved.y;
	event.modifiers = btrcUIKitModifierBits(scroll.modifierFlags);
	event.data1 = 1;
	btrcUIKitPush(&event, NULL);
}
@end

UIViewController* btrcUIKitPresenter(BtrcUIKitWindow* window) { return window->native.rootViewController; }

/* The layer a WebGPU surface is made on (UIKitSurface.c). */
void* btrcUIKitContentLayer(BtrcShimWindow* handle) {
	BtrcUIKitWindow* window = btrcUIKitWindow(handle);
	__block void* layer = NULL;
	btrcUIKitOnMain(^{ layer = ((BtrcUIKitContentView*)window->content)->metal; });
	return layer;
}

/* Put the windows on show in the scene, the last one shown in front. */
static void btrcUIKitArrange(void) {
	for (BtrcUIKitWindow* window in btrcUIKitWindows) {
		if (![btrcUIKitShown containsObject:window]) { window->native.hidden = YES; }
	}
	BtrcUIKitWindow* top = btrcUIKitTop();
	if (top == nil) { return; }
	[top->native makeKeyAndVisible];
	btrcUIKitScene.title = top->title;
	[top->native.rootViewController.view setNeedsLayout];
	[top->native layoutIfNeeded];
}

/* The scene the program's windows live in, and the session's delegates. */

static void btrcUIKitAdopt(UIWindowScene* scene) {
	[scene retain];
	[btrcUIKitScene release];
	btrcUIKitScene = scene;
	btrcUIKitActive = scene.activationState == UISceneActivationStateForegroundActive;
	btrcUIKitActiveSince = CACurrentMediaTime();
	if (btrcUIKitAwaitsSecondScene) {
		/* Whoever asked for a second scene can see that the program has one. */
		btrcUIKitAwaitsSecondScene = NO;
		fprintf(stderr, "btrc: the program's windows live in a second scene (%lu connected)\n", (unsigned long)UIApplication.sharedApplication.connectedScenes.count);
		fflush(stderr);
	}
	for (BtrcUIKitWindow* window in btrcUIKitWindows) { window->native.windowScene = scene; }
	btrcUIKitArrange();
	pthread_mutex_lock(&btrcUIKitSession.lock);
	btrcUIKitSession.connected = true;
	pthread_cond_broadcast(&btrcUIKitSession.changed);
	pthread_mutex_unlock(&btrcUIKitSession.lock);
}

@interface BtrcUIKitSceneDelegate : UIResponder <UIWindowSceneDelegate>
@end

@implementation BtrcUIKitSceneDelegate
- (void)scene:(UIScene*)scene willConnectToSession:(UISceneSession*)session options:(UISceneConnectionOptions*)options {
	(void)options;
	if (![scene isKindOfClass:UIWindowScene.class]) { return; }
	if (btrcUIKitWantsSecondScene && btrcUIKitScene == nil && UIApplication.sharedApplication.supportsMultipleScenes) {
		/* The program's windows are to live in a second scene: this one stays
		 * as the system made it, and the program waits for the next. */
		btrcUIKitWantsSecondScene = NO;
		btrcUIKitAwaitsSecondScene = YES;
		for (UISceneSession* stale in UIApplication.sharedApplication.openSessions) {
			if (stale != session) { [UIApplication.sharedApplication requestSceneSessionDestruction:stale options:nil errorHandler:nil]; }
		}
		[UIApplication.sharedApplication activateSceneSessionForRequest:[UISceneSessionActivationRequest request] errorHandler:^(NSError* error) {
			(void)error;
			/* No second scene is to be had: the program has this one. */
			btrcUIKitAwaitsSecondScene = NO;
			btrcUIKitAdopt((UIWindowScene*)scene);
		}];
		return;
	}
	if (btrcUIKitScene == nil || btrcUIKitShown.count == 0u) { btrcUIKitAdopt((UIWindowScene*)scene); }
}

/* The system took the scene away: the windows it showed are asked to close,
 * and live on in another scene if there is one. */
- (void)sceneDidDisconnect:(UIScene*)scene {
	if (scene != btrcUIKitScene) { return; }
	for (BtrcUIKitWindow* window in btrcUIKitShown) { btrcUIKitPushWindow(window, BTRC_SHIM_EVENT_WINDOW_CLOSE_REQUESTED); }
	UIWindowScene* next = nil;
	for (UIScene* other in UIApplication.sharedApplication.connectedScenes) {
		if (other != scene && [other isKindOfClass:UIWindowScene.class]) { next = (UIWindowScene*)other; break; }
	}
	if (next != nil) { btrcUIKitAdopt(next); }
}

- (void)sceneDidBecomeActive:(UIScene*)scene {
	if (scene != btrcUIKitScene || btrcUIKitActive) { return; }
	btrcUIKitActive = YES;
	btrcUIKitActiveSince = CACurrentMediaTime();
	BtrcUIKitWindow* top = btrcUIKitTop();
	if (top != nil) { btrcUIKitPushWindow(top, BTRC_SHIM_EVENT_WINDOW_FOCUS_GAINED); }
}

- (void)sceneWillResignActive:(UIScene*)scene {
	if (scene != btrcUIKitScene || !btrcUIKitActive) { return; }
	btrcUIKitActive = NO;
	BtrcUIKitWindow* top = btrcUIKitTop();
	if (top != nil) { btrcUIKitPushWindow(top, BTRC_SHIM_EVENT_WINDOW_FOCUS_LOST); }
}
@end

/* The program's main, on a thread of its own. When it returns the process
 * ends with its result, which a test host finds beside what it printed. */
extern int main(int count, char** arguments);

static void* btrcUIKitProgram(void* unused) {
	(void)unused;
	int result = main(btrcUIKitArgumentCount, btrcUIKitArguments);
	fflush(stdout);
	fflush(stderr);
	if (btrcUIKitOutput[0] != '\0') {
		char partial[1100];
		char path[1100];
		snprintf(partial, sizeof partial, "%s/exit.partial", btrcUIKitOutput);
		snprintf(path, sizeof path, "%s/exit.txt", btrcUIKitOutput);
		FILE* status = fopen(partial, "w");
		if (status != NULL) {
			fprintf(status, "%d\n", result);
			fclose(status);
			rename(partial, path);
		}
	}
	exit(result);
}

/* The application itself: every key of a hardware keyboard is the window on
 * show's first, before the scene's key window or any view acts on it. */
@interface BtrcUIKitProcess : UIApplication
@end

@implementation BtrcUIKitProcess
/* A keyboard's keys come as presses events of a type of their own, so the
 * class is what tells them, and a press that is a key has its key. */
- (void)sendEvent:(UIEvent*)event {
	if ([event isKindOfClass:UIPressesEvent.class]) {
		BtrcUIKitWindow* top = btrcUIKitTop();
		if (top != nil && [(BtrcUIKitNativeWindow*)top->native observePresses:(UIPressesEvent*)event]) { return; }
	}
	[super sendEvent:event];
}
@end

@interface BtrcUIKitApplication : UIResponder <UIApplicationDelegate>
@end

@implementation BtrcUIKitApplication
- (BOOL)application:(UIApplication*)application didFinishLaunchingWithOptions:(NSDictionary<UIApplicationLaunchOptionsKey, id>*)options {
	(void)application;
	(void)options;
	btrcUIKitWindows = [[NSMutableArray alloc] init];
	btrcUIKitShown = [[NSMutableArray alloc] init];
	pthread_attr_t attributes;
	pthread_t program;
	pthread_attr_init(&attributes);
	pthread_attr_setstacksize(&attributes, 16u * 1024u * 1024u);
	btrcUIKitRunning = pthread_create(&program, &attributes, btrcUIKitProgram, NULL) == 0;
	pthread_attr_destroy(&attributes);
	if (btrcUIKitRunning) { pthread_detach(program); }
	return btrcUIKitRunning ? YES : NO;
}

- (UISceneConfiguration*)application:(UIApplication*)application configurationForConnectingSceneSession:(UISceneSession*)session options:(UISceneConnectionOptions*)options {
	(void)application;
	(void)options;
	UISceneConfiguration* configuration = [[[UISceneConfiguration alloc] initWithName:@"btrc" sessionRole:session.role] autorelease];
	configuration.delegateClass = BtrcUIKitSceneDelegate.class;
	return configuration;
}
@end

/* The entry of a BTRC program that is an app. BTRC_SHIM_OUTPUT names a
 * directory that receives what the program prints (stdout.txt, stderr.txt)
 * and, when its main returns, its result (exit.txt): an app has no terminal.
 * BTRC_SHIM_SCENE=second puts the program's windows in a second scene, where
 * the system has more than one to give. */
int btrcUIKitMain(int count, char** arguments) {
	const char* output = getenv("BTRC_SHIM_OUTPUT");
	if (output != NULL && output[0] != '\0' && strlen(output) < sizeof btrcUIKitOutput) {
		char path[1100];
		snprintf(btrcUIKitOutput, sizeof btrcUIKitOutput, "%s", output);
		snprintf(path, sizeof path, "%s/stdout.txt", output);
		if (freopen(path, "w", stdout) == NULL) { return 127; }
		snprintf(path, sizeof path, "%s/stderr.txt", output);
		if (freopen(path, "w", stderr) == NULL) { return 127; }
	}
	const char* scene = getenv("BTRC_SHIM_SCENE");
	btrcUIKitWantsSecondScene = scene != NULL && strcmp(scene, "second") == 0;
	btrcUIKitArgumentCount = count;
	btrcUIKitArguments = arguments;
	@autoreleasepool {
		return UIApplicationMain(count, arguments, NSStringFromClass(BtrcUIKitProcess.class), NSStringFromClass(BtrcUIKitApplication.class));
	}
}

static bool btrcUIKitAwaitScene(void) {
	struct timespec deadline = btrcUIKitDeadline(BTRC_UIKIT_SCENE_SECONDS * 1000);
	pthread_mutex_lock(&btrcUIKitSession.lock);
	while (!btrcUIKitSession.connected) {
		if (pthread_cond_timedwait(&btrcUIKitSession.changed, &btrcUIKitSession.lock, &deadline) != 0) { break; }
	}
	bool connected = btrcUIKitSession.connected;
	pthread_mutex_unlock(&btrcUIKitSession.lock);
	return connected;
}

bool btrcShimInit(void) {
	if (btrcUIKitStarted) { return pthread_equal(btrcUIKitThread, pthread_self()) != 0; }
	if (!btrcUIKitRunning || pthread_main_np() != 0) { btrcUIKitFail("the program was not started by btrcUIKitMain: an app links with -e _btrcUIKitMain"); return false; }
	btrcUIKitThread = pthread_self();
	btrcUIKitStarted = true;
	return true;
}

bool btrcShimIsMainThread(void) { return !btrcUIKitStarted || pthread_equal(btrcUIKitThread, pthread_self()) != 0; }

unsigned long long btrcShimTicksNS(void) { return clock_gettime_nsec_np(CLOCK_UPTIME_RAW); }

/* One setting for the whole application, live: UIKit redraws what is shown. */
void btrcShimSetDarkAppearance(bool dark) {
	if (!btrcUIKitRunning) { return; }
	btrcUIKitOnMain(^{
		btrcUIKitDark = dark ? YES : NO;
		for (BtrcUIKitWindow* window in btrcUIKitWindows) {
			window->native.overrideUserInterfaceStyle = btrcUIKitDark ? UIUserInterfaceStyleDark : UIUserInterfaceStyleLight;
			[window->native.rootViewController.view setNeedsLayout];
		}
	});
}

BtrcShimWindow* btrcShimWindowCreate(const char* title, int width, int height) {
	if (!btrcUIKitAwaitScene()) { btrcUIKitFail("the system connected no scene for a window"); return NULL; }
	__block BtrcUIKitWindow* made = nil;
	NSString* name = btrcUIKitString(title);
	btrcUIKitOnMain(^{
		made = [[BtrcUIKitWindow alloc] initWithTitle:name width:width height:height];
		if (made != nil) { [btrcUIKitWindows addObject:made]; }
	});
	[name release];
	if (made == nil) { btrcUIKitFail("out of memory"); }
	return (BtrcShimWindow*)(void*)made;
}

void btrcShimWindowDestroy(BtrcShimWindow* handle) {
	if (handle == NULL) { return; }
	BtrcUIKitWindow* window = btrcUIKitWindow(handle);
	btrcUIKitOnMain(^{
		btrcUIKitControlsLeave(window);
		for (BtrcUIKitSlot* slot in window->placed) {
			if (slot->owner != nil) { slot->owner->window = nil; }
			[slot removeFromSuperview];
		}
		[window->placed removeAllObjects];
		[btrcUIKitShown removeObject:window];
		[btrcUIKitWindows removeObject:window];
		BtrcUIKitNativeWindow* native = (BtrcUIKitNativeWindow*)window->native;
		native->owner = nil;
		((BtrcUIKitRootController*)native.rootViewController)->owner = nil;
		native.hidden = YES;
		native.windowScene = nil;
		btrcUIKitArrange();
		[window release];
	});
}

unsigned int btrcShimWindowId(BtrcShimWindow* window) { return btrcUIKitWindow(window)->identifier; }

bool btrcShimWindowShow(BtrcShimWindow* handle) {
	BtrcUIKitWindow* window = btrcUIKitWindow(handle);
	btrcUIKitOnMain(^{
		if ([btrcUIKitShown containsObject:window]) { return; }
		BtrcUIKitWindow* before = btrcUIKitTop();
		if (before != nil) { btrcUIKitPushWindow(before, BTRC_SHIM_EVENT_WINDOW_FOCUS_LOST); }
		window->sized = YES;
		btrcUIKitShows++;
		[btrcUIKitShown addObject:window];
		btrcUIKitArrange();
		btrcUIKitPushWindow(window, BTRC_SHIM_EVENT_WINDOW_SHOWN);
		if (btrcUIKitActive) { btrcUIKitPushWindow(window, BTRC_SHIM_EVENT_WINDOW_FOCUS_GAINED); }
	});
	return true;
}

bool btrcShimWindowHide(BtrcShimWindow* handle) {
	BtrcUIKitWindow* window = btrcUIKitWindow(handle);
	btrcUIKitOnMain(^{
		if (![btrcUIKitShown containsObject:window]) { return; }
		BOOL top = btrcUIKitTop() == window;
		btrcUIKitControlsLeave(window);
		[window->native endEditing:YES];
		[btrcUIKitShown removeObject:window];
		btrcUIKitArrange();
		if (top) { btrcUIKitPushWindow(window, BTRC_SHIM_EVENT_WINDOW_FOCUS_LOST); }
		btrcUIKitPushWindow(window, BTRC_SHIM_EVENT_WINDOW_HIDDEN);
		BtrcUIKitWindow* next = btrcUIKitTop();
		if (top && next != nil && btrcUIKitActive) { btrcUIKitPushWindow(next, BTRC_SHIM_EVENT_WINDOW_FOCUS_GAINED); }
	});
	return true;
}

bool btrcShimWindowIsHidden(BtrcShimWindow* handle) {
	BtrcUIKitWindow* window = btrcUIKitWindow(handle);
	__block bool shown = false;
	btrcUIKitOnMain(^{ shown = [btrcUIKitShown containsObject:window]; });
	return !shown;
}

bool btrcShimWindowIsMinimized(BtrcShimWindow* window) { (void)window; return false; }

void btrcShimWindowSetTitle(BtrcShimWindow* handle, const char* title) {
	BtrcUIKitWindow* window = btrcUIKitWindow(handle);
	NSString* name = btrcUIKitString(title);
	btrcUIKitOnMain(^{
		[window->title release];
		window->title = [name copy];
		if (btrcUIKitTop() == window) { btrcUIKitScene.title = window->title; }
	});
	[name release];
}

/* The scene gives every window the whole of itself: a size asked for is the
 * window's until it is first shown, and no more. */
void btrcShimWindowSetSize(BtrcShimWindow* handle, int width, int height) {
	BtrcUIKitWindow* window = btrcUIKitWindow(handle);
	btrcUIKitOnMain(^{
		window->askedWidth = width;
		window->askedHeight = height;
		if (!window->sized) {
			window->content.frame = CGRectMake(0.0, 0.0, (CGFloat)width, (CGFloat)height);
			[window->content layoutIfNeeded];
		}
	});
}

void btrcShimWindowSetMinimumSize(BtrcShimWindow* window, int width, int height) {
	(void)window;
	(void)width;
	(void)height;
}

/* {width, height} of the content in points, and its pixels to a point. */
static void btrcUIKitExtent(BtrcShimWindow* handle, double* width, double* height, double* scale) {
	BtrcUIKitWindow* window = btrcUIKitWindow(handle);
	btrcUIKitOnMain(^{
		CGSize size = window->content.bounds.size;
		*width = window->sized && size.width > 0.0 ? size.width : (double)window->askedWidth;
		*height = window->sized && size.height > 0.0 ? size.height : (double)window->askedHeight;
		CGFloat pixels = ((BtrcUIKitContentView*)window->content)->metal.contentsScale;
		*scale = pixels > 0.0 ? pixels : 1.0;
	});
}

int btrcShimWindowWidth(BtrcShimWindow* window) {
	double width = 0.0, height = 0.0, scale = 1.0;
	btrcUIKitExtent(window, &width, &height, &scale);
	return (int)width;
}

int btrcShimWindowHeight(BtrcShimWindow* window) {
	double width = 0.0, height = 0.0, scale = 1.0;
	btrcUIKitExtent(window, &width, &height, &scale);
	return (int)height;
}

int btrcShimWindowPixelWidth(BtrcShimWindow* window) {
	double width = 0.0, height = 0.0, scale = 1.0;
	btrcUIKitExtent(window, &width, &height, &scale);
	return (int)(width * scale + 0.5);
}

int btrcShimWindowPixelHeight(BtrcShimWindow* window) {
	double width = 0.0, height = 0.0, scale = 1.0;
	btrcUIKitExtent(window, &width, &height, &scale);
	return (int)(height * scale + 0.5);
}

double btrcShimWindowPixelDensity(BtrcShimWindow* window) {
	double width = 0.0, height = 0.0, scale = 1.0;
	btrcUIKitExtent(window, &width, &height, &scale);
	return scale;
}

void btrcShimWindowSetCursor(BtrcShimWindow* window, int cursor) { (void)window; (void)cursor; }

/* An alert with one button; the program's thread waits here until it is
 * dismissed. Return presses the button and Escape dismisses the alert, as a
 * keyboard does a message box everywhere: UIKit leaves a hardware keyboard
 * out of an alert, so the keys are answered here. A window that is not on
 * show has nowhere to present one. */
void btrcShimWindowShowMessage(BtrcShimWindow* handle, const char* title, const char* message) {
	BtrcUIKitWindow* window = btrcUIKitWindow(handle);
	NSString* heading = btrcUIKitString(title);
	NSString* body = btrcUIKitString(message);
	dispatch_semaphore_t dismissed = dispatch_semaphore_create(0);
	__block BOOL presented = NO;
	btrcUIKitOnMain(^{
		BtrcUIKitWindow* host = [btrcUIKitShown containsObject:window] ? window : btrcUIKitTop();
		if (host == nil || btrcUIKitAlert != nil) { return; }
		UIViewController* presenter = btrcUIKitPresenter(host);
		while (presenter.presentedViewController != nil) { presenter = presenter.presentedViewController; }
		UIAlertController* alert = [UIAlertController alertControllerWithTitle:heading message:body preferredStyle:UIAlertControllerStyleAlert];
		UIAlertAction* accept = [UIAlertAction actionWithTitle:@"OK" style:UIAlertActionStyleDefault handler:^(UIAlertAction* action) {
			(void)action;
			btrcUIKitAlertFinished();
		}];
		[alert addAction:accept];
		alert.preferredAction = accept;
		btrcUIKitAlert = [alert retain];
		btrcUIKitAlertDismissed = dismissed;
		[presenter presentViewController:alert animated:YES completion:nil];
		presented = YES;
	});
	if (presented) { dispatch_semaphore_wait(dismissed, DISPATCH_TIME_FOREVER); }
	dispatch_release(dismissed);
	[heading release];
	[body release];
}

/* Frames are presented on the window's surface, never as pictures. */
bool btrcShimWindowSupportsSoftware(BtrcShimWindow* window) { (void)window; return false; }

bool btrcShimWindowShowsPictures(BtrcShimWindow* window) { (void)window; return false; }

void btrcShimWindowShowPicture(BtrcShimWindow* window, const unsigned char* pixels, int pixelWidth, int pixelHeight) {
	(void)window;
	(void)pixels;
	(void)pixelWidth;
	(void)pixelHeight;
}

/* Text entry is UIKit's fields' own; the provider's editor is not used here. */
void btrcShimWindowStartTextInput(BtrcShimWindow* window) { btrcUIKitWindow(window)->textInput = YES; }

void btrcShimWindowStopTextInput(BtrcShimWindow* window) { btrcUIKitWindow(window)->textInput = NO; }

bool btrcShimWindowTextInputActive(BtrcShimWindow* window) { return btrcUIKitWindow(window)->textInput; }

void btrcShimWindowClearComposition(BtrcShimWindow* window) { (void)window; }

void btrcShimWindowSetTextInputArea(BtrcShimWindow* window, int x, int y, int width, int height) {
	(void)window;
	(void)x;
	(void)y;
	(void)width;
	(void)height;
}

bool btrcShimSetClipboardText(const char* text) {
	NSString* string = btrcUIKitString(text);
	btrcUIKitOnMain(^{ UIPasteboard.generalPasteboard.string = string; });
	[string release];
	return true;
}

char* btrcShimGetClipboardText(void) {
	__block char* copy = NULL;
	btrcUIKitOnMain(^{
		NSString* string = UIPasteboard.generalPasteboard.hasStrings ? UIPasteboard.generalPasteboard.string : nil;
		if (string != nil) { copy = strdup(string.UTF8String); }
	});
	return copy;
}

bool btrcShimHasClipboardText(void) {
	__block bool has = false;
	btrcUIKitOnMain(^{ has = UIPasteboard.generalPasteboard.hasStrings; });
	return has;
}

void btrcShimFree(char* text) { free(text); }

/* Core Text draws the line as coverage; the picture is that coverage as
 * white's alpha. */
unsigned char* btrcShimRasterizeText(const char* text, double pixelSize, bool bold, int lineHeight, int* width, int* height) {
	if (text == NULL || width == NULL || height == NULL || pixelSize <= 0.0) { btrcUIKitFail("invalid text run"); return NULL; }
	unsigned char* pixels = NULL;
	CFStringRef string = CFStringCreateWithCString(kCFAllocatorDefault, text, kCFStringEncodingUTF8);
	CTFontRef font = CTFontCreateUIFontForLanguage(bold ? kCTFontUIFontEmphasizedSystem : kCTFontUIFontSystem, (CGFloat)pixelSize, NULL);
	if (string != NULL && font != NULL) {
		const void* keys[] = {kCTFontAttributeName, kCTForegroundColorFromContextAttributeName};
		const void* values[] = {font, kCFBooleanTrue};
		CFDictionaryRef attributes = CFDictionaryCreate(kCFAllocatorDefault, keys, values, 2, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
		CFAttributedStringRef attributed = CFAttributedStringCreate(kCFAllocatorDefault, string, attributes);
		CTLineRef line = CTLineCreateWithAttributedString(attributed);
		CGFloat ascent = 0.0, descent = 0.0, leading = 0.0;
		double advance = CTLineGetTypographicBounds(line, &ascent, &descent, &leading);
		int drawnWidth = (int)ceil(advance) < 1 ? 1 : (int)ceil(advance);
		int lineRows = (int)ceil(ascent + descent);
		int drawnHeight = lineHeight > lineRows ? lineHeight : lineRows;
		if (drawnWidth <= 4096 && drawnHeight > 0 && drawnHeight <= 4096) {
			unsigned char* coverage = calloc((size_t)drawnWidth * (size_t)drawnHeight, 1u);
			CGContextRef context = coverage == NULL ? NULL : CGBitmapContextCreate(coverage, (size_t)drawnWidth, (size_t)drawnHeight, 8u, (size_t)drawnWidth, NULL, (CGBitmapInfo)kCGImageAlphaOnly);
			if (context != NULL) {
				/* The context's origin is its bottom left; its first row is its top. */
				CGContextSetTextPosition(context, 0.0, (CGFloat)(drawnHeight - lineRows) / 2.0 + descent);
				CTLineDraw(line, context);
				CGContextRelease(context);
				pixels = malloc((size_t)drawnWidth * (size_t)drawnHeight * 4u);
				for (size_t index = 0; pixels != NULL && index < (size_t)drawnWidth * (size_t)drawnHeight; index++) {
					pixels[index * 4u] = 255u;
					pixels[index * 4u + 1u] = 255u;
					pixels[index * 4u + 2u] = 255u;
					pixels[index * 4u + 3u] = coverage[index];
				}
				*width = drawnWidth;
				*height = drawnHeight;
			}
			free(coverage);
		}
		CFRelease(line);
		CFRelease(attributed);
		CFRelease(attributes);
	}
	if (font != NULL) { CFRelease(font); }
	if (string != NULL) { CFRelease(string); }
	if (pixels == NULL) { btrcUIKitFail("the text run cannot be drawn"); }
	return pixels;
}

void btrcShimFreePixels(unsigned char* pixels) { free(pixels); }

/* The system's folder picker lends a folder for as long as a program holds
 * its security scope, not a directory a program can open by path: there is
 * no folder chooser here. */
BtrcShimFolderDialog* btrcShimFolderDialogOpen(BtrcShimWindow* window, const char* initialDirectory, const char* title) {
	(void)window;
	(void)initialDirectory;
	(void)title;
	btrcUIKitFail("iOS has no folder to choose by path");
	return NULL;
}

int btrcShimFolderDialogState(BtrcShimFolderDialog* dialog) { return dialog->state; }

const char* btrcShimFolderDialogPath(const BtrcShimFolderDialog* dialog) { (void)dialog; return ""; }

void btrcShimFolderDialogRelease(BtrcShimFolderDialog* dialog) { free(dialog); }

@interface BtrcUIKitFilePickerDelegate : NSObject <UIDocumentPickerDelegate> {
@public
	BtrcShimFileDialog* dialog;
}
@end

@implementation BtrcUIKitFilePickerDelegate
- (void)documentPicker:(UIDocumentPickerViewController*)controller didPickDocumentsAtURLs:(NSArray<NSURL*>*)urls {
	(void)controller;
	BtrcShimFileDialog* target = self->dialog;
	if (target == NULL) { return; }
	pthread_mutex_lock(&target->lock);
	NSUInteger count = [urls count];
	if (count == 0) {
		target->state = 3;
		btrcUIKitFail("iOS document picker returned no files");
	} else {
		target->paths = calloc(count, sizeof(char*));
		if (target->paths == NULL) {
			target->state = 3;
			btrcUIKitFail("out of memory copying picked files");
		} else {
			BOOL ok = YES;
			for (NSUInteger i = 0; i < count; i++) {
				NSURL* url = [urls objectAtIndex:i];
				const char* utf8 = [[url path] UTF8String];
				if (utf8 == NULL || utf8[0] == '\0') { ok = NO; break; }
				target->paths[target->pathCount++] = strdup(utf8);
			}
			target->state = (ok && target->pathCount > 0) ? 1 : 3;
			if (target->state != 1) { btrcUIKitFail("iOS document picker returned an invalid path"); }
		}
	}
	pthread_mutex_unlock(&target->lock);
}

- (void)documentPickerWasCancelled:(UIDocumentPickerViewController*)controller {
	(void)controller;
	BtrcShimFileDialog* target = self->dialog;
	if (target == NULL) { return; }
	pthread_mutex_lock(&target->lock);
	target->state = 2;
	pthread_mutex_unlock(&target->lock);
}
@end

static NSArray<UTType*>* btrcUIKitFileTypes(const char* filters) {
	NSMutableArray<UTType*>* types = [[NSMutableArray alloc] init];
	if (filters != NULL && filters[0] != '\0') {
		NSMutableSet<NSString*>* seen = [[NSMutableSet alloc] init];
		const char* cursor = filters;
		while (*cursor != '\0') {
			const char* lineEnd = strchr(cursor, '\n');
			size_t lineLen = lineEnd == NULL ? strlen(cursor) : (size_t)(lineEnd - cursor);
			const char* tab = memchr(cursor, '\t', lineLen);
			if (tab != NULL) {
				const char* extStart = tab + 1;
				const char* extLimit = cursor + lineLen;
				while (extStart < extLimit) {
					const char* comma = memchr(extStart, ',', (size_t)(extLimit - extStart));
					size_t extLen = comma == NULL ? (size_t)(extLimit - extStart) : (size_t)(comma - extStart);
					if (extLen > 0) {
						NSString* ext = [[NSString alloc] initWithBytes:extStart length:extLen encoding:NSUTF8StringEncoding];
						if (ext != nil) {
							NSString* lower = [ext lowercaseString];
							if (![seen containsObject:lower]) {
								[seen addObject:lower];
								UTType* type = [UTType typeWithFilenameExtension:lower];
								if (type != nil) { [types addObject:type]; }
							}
							[ext release];
						}
					}
					if (comma == NULL) { break; }
					extStart = comma + 1;
				}
			}
			if (lineEnd == NULL) { break; }
			cursor = lineEnd + 1;
		}
		[seen release];
	}
	if ([types count] == 0) { [types addObject:UTTypeItem]; }
	return types;
}

BtrcShimFileDialog* btrcShimFileDialogOpen(BtrcShimWindow* handle, int mode, const char* title, const char* initialDirectory, const char* defaultName, const char* filters, bool canCreateDirectories) {
	(void)title;
	(void)initialDirectory;
	(void)defaultName;
	(void)canCreateDirectories;
	BtrcShimFileDialog* dialog = calloc(1, sizeof *dialog);
	if (dialog == NULL) { return NULL; }
	pthread_mutex_init(&dialog->lock, NULL);
	if (mode != 1 && mode != 2) {
		btrcUIKitFail("iOS document picker only supports opening files as sandboxed local copies");
		dialog->state = 4;
		return dialog;
	}
	BtrcUIKitWindow* window = btrcUIKitWindow(handle);
	NSArray<UTType*>* types = btrcUIKitFileTypes(filters);
	BtrcUIKitFilePickerDelegate* delegate = [[BtrcUIKitFilePickerDelegate alloc] init];
	delegate->dialog = dialog;
	dialog->delegate = delegate;
	btrcUIKitOnMain(^{
		BtrcUIKitWindow* host = [btrcUIKitShown containsObject:window] ? window : btrcUIKitTop();
		if (host == nil) {
			pthread_mutex_lock(&dialog->lock);
			dialog->state = 4;
			btrcUIKitFail("no active iOS window to present the file picker");
			pthread_mutex_unlock(&dialog->lock);
			return;
		}
		UIViewController* presenter = btrcUIKitPresenter(host);
		while (presenter.presentedViewController != nil) { presenter = presenter.presentedViewController; }
		UIDocumentPickerViewController* picker = [[UIDocumentPickerViewController alloc] initForOpeningContentTypes:types asCopy:YES];
		picker.allowsMultipleSelection = (mode == 2) ? YES : NO;
		picker.delegate = delegate;
		[presenter presentViewController:picker animated:YES completion:nil];
		[picker release];
	});
	[types release];
	return dialog;
}

int btrcShimFileDialogState(BtrcShimFileDialog* dialog) {
	if (dialog == NULL) { return 3; }
	pthread_mutex_lock(&dialog->lock);
	int state = dialog->state;
	pthread_mutex_unlock(&dialog->lock);
	return state;
}

int btrcShimFileDialogPathCount(const BtrcShimFileDialog* dialog) {
	if (dialog == NULL) { return 0; }
	return dialog->pathCount;
}

const char* btrcShimFileDialogPathAt(const BtrcShimFileDialog* dialog, int index) {
	if (dialog == NULL || index < 0 || index >= dialog->pathCount || dialog->paths[index] == NULL) { return ""; }
	return dialog->paths[index];
}

void btrcShimFileDialogRelease(BtrcShimFileDialog* dialog) {
	if (dialog == NULL) { return; }
	BtrcUIKitFilePickerDelegate* delegate = (BtrcUIKitFilePickerDelegate*)dialog->delegate;
	if (delegate != nil) {
		btrcUIKitOnMain(^{ delegate->dialog = NULL; });
		[delegate release];
	}
	for (int i = 0; i < dialog->pathCount; i++) { free(dialog->paths[i]); }
	free(dialog->paths);
	pthread_mutex_destroy(&dialog->lock);
	free(dialog);
}

/* Automation. */

int btrcShimAutomationDisplay(void) { return BTRC_SHIM_DISPLAY_IOS; }

static BtrcUIKitWindow* btrcUIKitWindowWith(unsigned int identifier) {
	for (BtrcUIKitWindow* window in btrcUIKitWindows) {
		if (window->identifier == identifier) { return window; }
	}
	return nil;
}

unsigned int btrcShimWindowNamed(const char* title) {
	__block unsigned int found = 0u;
	NSString* name = btrcUIKitString(title);
	btrcUIKitOnMain(^{
		for (BtrcUIKitWindow* window in btrcUIKitWindows) {
			if ([window->title isEqualToString:name]) { found = window->identifier; break; }
		}
	});
	[name release];
	return found;
}

unsigned long btrcShimAutomationSerial(void) {
	pthread_mutex_lock(&btrcUIKitQueue.lock);
	unsigned long serial = btrcUIKitQueue.serial;
	pthread_mutex_unlock(&btrcUIKitQueue.lock);
	return serial;
}

/* Wait until something arrives after `serial` and arrivals then pause, or the timeout passes. */
int btrcShimAutomationAwait(unsigned long serial, int timeoutMilliseconds) {
	struct timespec deadline = btrcUIKitDeadline(timeoutMilliseconds < 0 ? 0 : timeoutMilliseconds);
	int arrived = 0;
	pthread_mutex_lock(&btrcUIKitQueue.lock);
	while (btrcUIKitQueue.serial == serial) {
		if (pthread_cond_timedwait(&btrcUIKitQueue.arrived, &btrcUIKitQueue.lock, &deadline) != 0) { break; }
	}
	if (btrcUIKitQueue.serial != serial) {
		arrived = 1;
		for (;;) {
			unsigned long seen = btrcUIKitQueue.serial;
			struct timespec pause = btrcUIKitDeadline(20);
			pthread_cond_timedwait(&btrcUIKitQueue.arrived, &btrcUIKitQueue.lock, &pause);
			if (btrcUIKitQueue.serial == seen) { break; }
		}
	}
	pthread_mutex_unlock(&btrcUIKitQueue.lock);
	return arrived;
}

int btrcShimAutomationPointer(unsigned int identifier, double* x, double* y) {
	__block int inside = 0;
	btrcUIKitOnMain(^{
		BtrcUIKitWindow* window = btrcUIKitWindowWith(identifier);
		if (window == nil) { return; }
		inside = window->pointerInside ? 1 : 0;
		*x = window->pointer.x;
		*y = window->pointer.y;
	});
	return inside;
}

int btrcShimAutomationWindows(void) {
	__block int count = 0;
	btrcUIKitOnMain(^{ count = (int)btrcUIKitWindows.count; });
	return count;
}

int btrcShimAutomationTextFocused(unsigned int identifier) {
	__block int focused = 0;
	btrcUIKitOnMain(^{
		BtrcUIKitWindow* window = btrcUIKitWindowWith(identifier);
		focused = window != nil && btrcUIKitControlsTextFocused(window) ? 1 : 0;
	});
	return focused;
}

/* Where the window's content is on the screen, in the screen's points, when
 * it is the window on show and the scene is the one a person is using; and
 * the screen's size. For a tool that sends input to the screen. The system
 * brings a scene to the screen with an animation of its own, during which
 * the scene is not yet where it will be: the answer waits that out. */
int btrcUIKitAutomationOrigin(unsigned int identifier, double* x, double* y) {
	__block int shown = 0;
	btrcUIKitOnMain(^{
		BtrcUIKitWindow* window = btrcUIKitWindowWith(identifier);
		if (window == nil || btrcUIKitTop() != window || !btrcUIKitActive || window->native.windowScene == nil) { return; }
		if (CACurrentMediaTime() - btrcUIKitActiveSince < BTRC_UIKIT_SCENE_ARRIVAL_SECONDS) { return; }
		CGPoint origin = [window->content convertPoint:CGPointZero toCoordinateSpace:window->native.windowScene.screen.coordinateSpace];
		*x = origin.x;
		*y = origin.y;
		shown = 1;
	});
	return shown;
}

/* The frame, in the screen's points, of the scene's part of the screen as
 * the window on show fills it, once the scene has arrived there: 1 when the
 * scene is as wide as a tablet's own (a regular width), 2 when it is as
 * narrow as a phone's (compact), 0 when nothing has been on show yet. With
 * no window on show any more, the scene the last one lived in answers for
 * itself: the system keeps it as that window left it. */
int btrcUIKitAutomationScene(double* x, double* y, double* width, double* height) {
	__block int kind = 0;
	btrcUIKitOnMain(^{
		BtrcUIKitWindow* window = btrcUIKitTop();
		UIWindowScene* scene = window != nil ? window->native.windowScene : (btrcUIKitShows != 0 ? btrcUIKitScene : nil);
		if (scene == nil || !btrcUIKitActive) { return; }
		if (CACurrentMediaTime() - btrcUIKitActiveSince < BTRC_UIKIT_SCENE_ARRIVAL_SECONDS) { return; }
		id<UICoordinateSpace> part = window != nil ? (id<UICoordinateSpace>)window->native : scene.coordinateSpace;
		CGRect frame = [part convertRect:part.bounds toCoordinateSpace:scene.screen.coordinateSpace];
		*x = frame.origin.x;
		*y = frame.origin.y;
		*width = frame.size.width;
		*height = frame.size.height;
		UITraitCollection* traits = window != nil ? window->native.traitCollection : scene.traitCollection;
		kind = traits.horizontalSizeClass == UIUserInterfaceSizeClassCompact ? 2 : 1;
	});
	return kind;
}

/* How many times the program has put a window on show. */
int btrcUIKitAutomationShows(void) {
	__block int shows = 0;
	btrcUIKitOnMain(^{ shows = btrcUIKitShows; });
	return shows;
}

void btrcUIKitAutomationScreen(double* width, double* height) {
	btrcUIKitOnMain(^{
		CGSize size = btrcUIKitScene == nil ? CGSizeZero : btrcUIKitScene.screen.bounds.size;
		*width = size.width;
		*height = size.height;
	});
}
