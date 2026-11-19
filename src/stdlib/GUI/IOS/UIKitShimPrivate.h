#ifndef BTRC_UIKIT_SHIM_PRIVATE_H
#define BTRC_UIKIT_SHIM_PRIVATE_H
/* What the UIKit shim's source files share. Nothing here is the provider's:
 * BTRC sees only ../Shim/Shim.h, ShimControls.h, ShimSurface.h and ShimWeb.h.
 *
 * Native sources are compiled without ARC, so these files retain and release
 * what they keep. */
#import <UIKit/UIKit.h>
#include "../Shim/ShimControls.h"

enum {
	BTRC_UIKIT_BUTTON = 1,
	BTRC_UIKIT_LABEL,
	BTRC_UIKIT_SPINNER,
	BTRC_UIKIT_LEVEL,
	BTRC_UIKIT_SLIDER,
	BTRC_UIKIT_SELECT,
	BTRC_UIKIT_TEXT,
	BTRC_UIKIT_PICTURE,
	BTRC_UIKIT_FILL,
	BTRC_UIKIT_SCROLLBAR,
	BTRC_UIKIT_WEB
};

@class BtrcUIKitWindow;
@class BtrcUIKitControl;

/* One control in a window: clipped to what its ancestors show, and cut out
 * where drawn content placed after it shows through. A touch outside what
 * shows of the control is not the control's. */
@interface BtrcUIKitSlot : UIView {
@public
	BtrcUIKitControl* owner;
}
/* `clip` and each hole are in the slot's own points. */
- (void)showWithin:(CGRect)clip cutting:(const CGRect*)holes count:(int)count;
@end

/* A control: a UIKit view in a slot, with what its kind keeps. A
 * BtrcShimControl* is one of these, retained until btrcShimControlDestroy. */
@interface BtrcUIKitControl : NSObject {
@public
	unsigned int identifier;
	int kind;
	UIView* view;
	BtrcUIKitSlot* slot;
	/* The window the last placement put it in; not retained. */
	BtrcUIKitWindow* window;
	UIToolTipInteraction* toolTip;
	/* A button's and a select's text. */
	NSString* title;
	double fontSize;
	BOOL bold;
	BOOL centered;
	BOOL bordered;
	BOOL selected;
	BOOL transparent;
	/* A button's symbol: seven numbers a shape (its kind, then six). */
	double symbolSize;
	double* shapes;
	int shapeCount;
	/* A level's thresholds. */
	double warning;
	double critical;
	/* A slider's model, and the drag a person has it in. */
	double minimum;
	double maximum;
	double value;
	BOOL tracking;
	BOOL cancelledDrag;
	double grabbed;
	/* A select's items, the one marked, and the list while it is open. */
	NSMutableArray<NSString*>* items;
	NSMutableArray<NSNumber*>* itemEnabled;
	int marked;
	int candidate;
	UIView* list;
	/* A scroll bar's place in its document. */
	BOOL vertical;
	double offset;
	double viewport;
	double content;
}
@end

/* A window: one UIWindow of the scene the program's windows live in. A
 * BtrcShimWindow* is one of these, retained until btrcShimWindowDestroy. */
@interface BtrcUIKitWindow : NSObject {
@public
	unsigned int identifier;
	NSString* title;
	/* The size the program asked for, which is the window's until it is first
	 * shown: from then on it has the scene's. */
	int askedWidth;
	int askedHeight;
	BOOL sized;
	/* Whether the size it has now has been reported. */
	BOOL announced;
	BOOL textInput;
	UIWindow* native;
	/* The drawn content's view, whose layer is a CAMetalLayer; the controls'
	 * slots are its subviews, back to front. */
	UIView* content;
	NSMutableArray<BtrcUIKitSlot*>* placed;
	BOOL pointerInside;
	CGPoint pointer;
	/* The placement in progress, on the program's thread: a control (NULL for
	 * a hole) and eight numbers each. */
	BtrcUIKitControl** placing;
	double* rectangles;
	int placingCount;
	int placingCapacity;
}
@end

static inline BtrcUIKitWindow* btrcUIKitWindow(BtrcShimWindow* window) { return (BtrcUIKitWindow*)(void*)window; }
static inline BtrcUIKitControl* btrcUIKitControl(BtrcShimControl* control) { return (BtrcUIKitControl*)(void*)control; }

void btrcUIKitFail(const char* message);
/* Do the work on the main thread and wait for it. The program's thread is
 * the only caller: the main thread never waits for the program. */
void btrcUIKitOnMain(void (^work)(void));
/* UTF-8 text as a string the caller releases; never nil. */
NSString* btrcUIKitString(const char* text);

/* The queue (UIKitShim.m). Safe from any thread. */
bool btrcUIKitPush(const BtrcShimEvent* event, const char* text);
void btrcUIKitPushWindow(BtrcUIKitWindow* window, unsigned int type);
void btrcUIKitPushControl(BtrcUIKitControl* control, unsigned int type, int data, double value, NSString* text);

/* For a kind of control that has a source file of its own (UIKitWeb.m): a
 * control around a view, which the control then owns. */
BtrcShimControl* btrcUIKitControlAdopt(int kind, unsigned int identifier, UIView* view);

/* What the window's own event observation asks of the controls
 * (UIKitControls.m), on the main thread. Each returns YES when the key was
 * the control's and goes no further. */
BOOL btrcUIKitControlsKeyDown(BtrcUIKitWindow* window, unsigned int key);
/* A touch went down anywhere: a slider's cancelled drag is over. */
void btrcUIKitControlsTouchDown(void);
/* The window is hidden or destroyed: nothing of it stays open. */
void btrcUIKitControlsLeave(BtrcUIKitWindow* window);
/* Whether the keyboard is in a text field of this window. */
BOOL btrcUIKitControlsTextFocused(BtrcUIKitWindow* window);
/* The window's root view controller, which presents what is modal to it. */
UIViewController* btrcUIKitPresenter(BtrcUIKitWindow* window);
#endif
