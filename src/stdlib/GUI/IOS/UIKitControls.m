/* The UIKit shim's controls; ../Shim/ShimControls.h is the contract. Each is
 * the system's own control (UIButton, UILabel, UITextField, UISlider,
 * UIActivityIndicatorView, UIProgressView, UIImageView) in a slot that
 * clips it to its ancestors and cuts out the drawn content placed after it.
 * A select is a button that opens a list; a scroll bar is drawn here, for a
 * view the provider scrolls itself. */
#import "UIKitShimPrivate.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

/* The slider a person is dragging, the one whose drag Escape ended, the
 * select whose list is open, and the text field the keyboard is in. */
static BtrcUIKitControl* btrcUIKitDragging;
static BtrcUIKitControl* btrcUIKitCancelled;
static BtrcUIKitControl* btrcUIKitOpened;
static BtrcUIKitControl* btrcUIKitEditing;

static void btrcUIKitSelectClose(BtrcUIKitControl* control, BOOL report, BOOL escaped);

@interface BtrcUIKitControl (Events) <UITextFieldDelegate>
- (void)activated:(id)sender;
- (void)textChanged:(UITextField*)field;
- (void)textBegan:(UITextField*)field;
- (void)textEnded:(UITextField*)field;
- (void)selectPressed:(id)sender;
- (void)selectBackdrop:(id)sender;
@end

/* Slots. */

@implementation BtrcUIKitSlot {
	CGRect _clip;
	CGRect* _holes;
	int _holeCount;
}

- (void)dealloc {
	free(_holes);
	[super dealloc];
}

/* What shows is the clip less the holes, as rectangles that do not overlap:
 * each hole splits what it crosses into the strips around it. */
- (void)showWithin:(CGRect)clip cutting:(const CGRect*)holes count:(int)count {
	_clip = clip;
	free(_holes);
	_holes = NULL;
	_holeCount = 0;
	if (count > 0) {
		_holes = malloc((size_t)count * sizeof *_holes);
		if (_holes != NULL) {
			memcpy(_holes, holes, (size_t)count * sizeof *_holes);
			_holeCount = count;
		}
	}
	int capacity = 1 + _holeCount * 4;
	int pieces = 1;
	CGRect* shown = malloc((size_t)capacity * sizeof *shown);
	CGRect* next = malloc((size_t)capacity * sizeof *next);
	CGMutablePathRef path = CGPathCreateMutable();
	if (shown != NULL && next != NULL) {
		shown[0] = clip;
		for (int hole = 0; hole < _holeCount; hole++) {
			int kept = 0;
			for (int piece = 0; piece < pieces; piece++) {
				CGRect whole = shown[piece];
				CGRect cut = CGRectIntersection(whole, _holes[hole]);
				if (CGRectIsNull(cut) || CGRectIsEmpty(cut)) { next[kept++] = whole; continue; }
				if (kept + 4 > capacity) {
					capacity = (kept + 4) * 2;
					CGRect* grown = realloc(next, (size_t)capacity * sizeof *next);
					if (grown == NULL) { break; }
					next = grown;
				}
				if (CGRectGetMinY(cut) > CGRectGetMinY(whole)) { next[kept++] = CGRectMake(whole.origin.x, whole.origin.y, whole.size.width, CGRectGetMinY(cut) - CGRectGetMinY(whole)); }
				if (CGRectGetMaxY(cut) < CGRectGetMaxY(whole)) { next[kept++] = CGRectMake(whole.origin.x, CGRectGetMaxY(cut), whole.size.width, CGRectGetMaxY(whole) - CGRectGetMaxY(cut)); }
				if (CGRectGetMinX(cut) > CGRectGetMinX(whole)) { next[kept++] = CGRectMake(whole.origin.x, cut.origin.y, CGRectGetMinX(cut) - CGRectGetMinX(whole), cut.size.height); }
				if (CGRectGetMaxX(cut) < CGRectGetMaxX(whole)) { next[kept++] = CGRectMake(CGRectGetMaxX(cut), cut.origin.y, CGRectGetMaxX(whole) - CGRectGetMaxX(cut), cut.size.height); }
			}
			CGRect* grown = realloc(shown, (size_t)capacity * sizeof *shown);
			if (grown == NULL) { break; }
			shown = grown;
			memcpy(shown, next, (size_t)kept * sizeof *shown);
			pieces = kept;
		}
		for (int piece = 0; piece < pieces; piece++) { CGPathAddRect(path, NULL, shown[piece]); }
	}
	free(shown);
	free(next);
	CAShapeLayer* mask = [CAShapeLayer layer];
	mask.path = path;
	CGPathRelease(path);
	self.layer.mask = mask;
}

- (BOOL)shows:(CGPoint)point {
	if (!CGRectContainsPoint(_clip, point)) { return NO; }
	for (int hole = 0; hole < _holeCount; hole++) {
		if (CGRectContainsPoint(_holes[hole], point)) { return NO; }
	}
	return YES;
}

/* The slot is never a touch's own: what does not belong to its control goes
 * to whatever lies behind. A transparent button draws nothing and still
 * takes touches, which UIKit would deny a view it cannot see. */
- (UIView*)hitTest:(CGPoint)point withEvent:(UIEvent*)event {
	if (![self shows:point]) { return nil; }
	UIView* hit = [super hitTest:point withEvent:event];
	if (hit != nil && hit != self) { return hit; }
	if (owner != nil && owner->transparent && [owner->view isKindOfClass:UIControl.class] && ((UIControl*)owner->view).enabled && CGRectContainsPoint(owner->view.frame, point)) { return owner->view; }
	return nil;
}
@end

@implementation BtrcUIKitControl
- (void)dealloc {
	[view release];
	[slot release];
	[toolTip release];
	[title release];
	[items release];
	[itemEnabled release];
	[list release];
	free(shapes);
	[super dealloc];
}

/* Buttons. */

- (void)activated:(id)sender {
	(void)sender;
	btrcUIKitPushControl(self, BTRC_SHIM_EVENT_CONTROL_ACTIVATED, 0, 0.0, nil);
}

/* Text fields. UIKit owns the editing; what it leaves is reported. */

- (void)textChanged:(UITextField*)field {
	btrcUIKitPushControl(self, BTRC_SHIM_EVENT_CONTROL_TEXT_CHANGED, field.markedTextRange != nil ? 1 : 0, 0.0, field.text != nil ? field.text : @"");
}

- (void)textBegan:(UITextField*)field {
	(void)field;
	btrcUIKitEditing = self;
	btrcUIKitPushControl(self, BTRC_SHIM_EVENT_CONTROL_FOCUS_GAINED, 0, 0.0, nil);
}

- (void)textEnded:(UITextField*)field {
	(void)field;
	if (btrcUIKitEditing == self) { btrcUIKitEditing = nil; }
	btrcUIKitPushControl(self, BTRC_SHIM_EVENT_CONTROL_FOCUS_LOST, 0, 0.0, nil);
}

/* Return in the field, from any keyboard. The field keeps the keyboard. */
- (BOOL)textFieldShouldReturn:(UITextField*)field {
	(void)field;
	btrcUIKitPushControl(self, BTRC_SHIM_EVENT_CONTROL_TEXT_ACTIVATED, 0, 0.0, nil);
	return NO;
}
@end

/* A button's symbol: lines, triangles, rectangles and circles, drawn as a
 * template so that it takes the title's colour. */
static UIImage* btrcUIKitSymbol(BtrcUIKitControl* control) {
	if (control->symbolSize <= 0.0 || control->shapeCount == 0) { return nil; }
	CGSize size = CGSizeMake((CGFloat)control->symbolSize, (CGFloat)control->symbolSize);
	UIGraphicsImageRenderer* renderer = [[UIGraphicsImageRenderer alloc] initWithSize:size];
	UIImage* image = [renderer imageWithActions:^(UIGraphicsImageRendererContext* context) {
		(void)context;
		[UIColor.blackColor set];
		for (int index = 0; index < control->shapeCount; index++) {
			const double* shape = control->shapes + (size_t)index * 7u;
			int kind = (int)shape[0];
			UIBezierPath* path = nil;
			double stroke = 0.0;
			if (kind == 1) {
				path = [UIBezierPath bezierPath];
				[path moveToPoint:CGPointMake(shape[1], shape[2])];
				[path addLineToPoint:CGPointMake(shape[3], shape[4])];
				path.lineCapStyle = kCGLineCapRound;
				stroke = shape[5] > 0.0 ? shape[5] : 1.0;
			} else if (kind == 2) {
				path = [UIBezierPath bezierPath];
				[path moveToPoint:CGPointMake(shape[1], shape[2])];
				[path addLineToPoint:CGPointMake(shape[3], shape[4])];
				[path addLineToPoint:CGPointMake(shape[5], shape[6])];
				[path closePath];
			} else if (kind == 3) {
				path = [UIBezierPath bezierPathWithRoundedRect:CGRectMake(shape[1], shape[2], shape[3], shape[4]) cornerRadius:shape[5]];
				stroke = shape[6];
			} else if (kind == 4) {
				path = [UIBezierPath bezierPathWithArcCenter:CGPointMake(shape[1], shape[2]) radius:shape[3] startAngle:0.0 endAngle:2.0 * M_PI clockwise:YES];
				stroke = shape[4];
			}
			if (stroke > 0.0) {
				path.lineWidth = stroke;
				[path stroke];
			} else {
				[path fill];
			}
		}
	}];
	[renderer release];
	return [image imageWithRenderingMode:UIImageRenderingModeAlwaysTemplate];
}

static UIFont* btrcUIKitFont(BtrcUIKitControl* control) {
	CGFloat size = control->fontSize > 0.0 ? (CGFloat)control->fontSize : UIFont.labelFontSize;
	return [UIFont systemFontOfSize:size weight:control->bold ? UIFontWeightSemibold : UIFontWeightRegular];
}

/* A button and a select's button are their configuration, made whole from
 * what the program last said of them. */
static void btrcUIKitShowButton(BtrcUIKitControl* control) {
	UIButton* button = (UIButton*)control->view;
	BOOL select = control->kind == BTRC_UIKIT_SELECT;
	UIButtonConfiguration* configuration = !control->bordered ? [UIButtonConfiguration plainButtonConfiguration] : control->selected ? [UIButtonConfiguration tintedButtonConfiguration] : [UIButtonConfiguration grayButtonConfiguration];
	NSAttributedString* text = [[NSAttributedString alloc] initWithString:control->title != nil ? control->title : @"" attributes:@{NSFontAttributeName : btrcUIKitFont(control)}];
	configuration.attributedTitle = text;
	[text release];
	configuration.titleLineBreakMode = NSLineBreakByTruncatingTail;
	configuration.contentInsets = NSDirectionalEdgeInsetsMake(6.0, 12.0, 6.0, 12.0);
	if (select) {
		configuration.image = [UIImage systemImageNamed:@"chevron.up.chevron.down"];
		configuration.imagePlacement = NSDirectionalRectEdgeTrailing;
		configuration.preferredSymbolConfigurationForImage = [UIImageSymbolConfiguration configurationWithPointSize:btrcUIKitFont(control).pointSize * 0.75];
	} else {
		configuration.image = btrcUIKitSymbol(control);
	}
	configuration.imagePadding = 6.0;
	if (!control->bordered && control->selected) { configuration.baseForegroundColor = UIColor.labelColor; }
	button.configuration = configuration;
	button.contentHorizontalAlignment = control->centered && !select ? UIControlContentHorizontalAlignmentCenter : UIControlContentHorizontalAlignmentLeading;
	button.selected = control->selected;
	button.alpha = control->transparent ? 0.0 : 1.0;
}

/* Sliders. A slider shows the value it is given and never changes it itself:
 * the drag is read here, and what a person asks for is reported. */

@interface BtrcUIKitSlider : UISlider {
@public
	BtrcUIKitControl* owner;
}
@end

static void btrcUIKitShowSlider(BtrcUIKitControl* control) {
	UISlider* slider = (UISlider*)control->view;
	slider.minimumValue = (float)control->minimum;
	slider.maximumValue = (float)(control->maximum > control->minimum ? control->maximum : control->minimum + 1.0);
	slider.value = (float)control->value;
}

@implementation BtrcUIKitSlider
/* The value whose thumb would be centred at `x`, less where the thumb was grabbed. */
- (double)valueAt:(CGFloat)x {
	CGRect track = [self trackRectForBounds:self.bounds];
	CGFloat low = CGRectGetMidX([self thumbRectForBounds:self.bounds trackRect:track value:self.minimumValue]);
	CGFloat high = CGRectGetMidX([self thumbRectForBounds:self.bounds trackRect:track value:self.maximumValue]);
	double along = high > low ? (double)((x - (CGFloat)owner->grabbed - low) / (high - low)) : 0.0;
	if (self.effectiveUserInterfaceLayoutDirection == UIUserInterfaceLayoutDirectionRightToLeft) { along = 1.0 - along; }
	along = along < 0.0 ? 0.0 : along > 1.0 ? 1.0 : along;
	return owner->minimum + (owner->maximum - owner->minimum) * along;
}

- (BOOL)beginTrackingWithTouch:(UITouch*)touch withEvent:(UIEvent*)event {
	if (owner == nil || owner->cancelledDrag) { return NO; }
	CGPoint at = [touch locationInView:self];
	CGRect thumb = [self thumbRectForBounds:self.bounds trackRect:[self trackRectForBounds:self.bounds] value:self.value];
	/* A touch on the thumb drags it from where it was taken; one on the
	 * track brings the thumb to the finger. */
	BOOL onThumb = CGRectContainsPoint(CGRectInset(thumb, -8.0, -8.0), at);
	owner->grabbed = onThumb ? (double)(at.x - CGRectGetMidX(thumb)) : 0.0;
	[super beginTrackingWithTouch:touch withEvent:event];
	owner->tracking = YES;
	btrcUIKitDragging = owner;
	btrcUIKitPushControl(owner, BTRC_SHIM_EVENT_CONTROL_SLIDER_PRESSED, 0, 0.0, nil);
	if (!onThumb) { btrcUIKitPushControl(owner, BTRC_SHIM_EVENT_CONTROL_SLIDER_CHANGED, BTRC_SHIM_SLIDER_JUMP, [self valueAt:at.x], nil); }
	btrcUIKitShowSlider(owner);
	return YES;
}

- (BOOL)continueTrackingWithTouch:(UITouch*)touch withEvent:(UIEvent*)event {
	(void)event;
	if (owner == nil || !owner->tracking) { return owner != nil && owner->cancelledDrag; }
	btrcUIKitPushControl(owner, BTRC_SHIM_EVENT_CONTROL_SLIDER_CHANGED, BTRC_SHIM_SLIDER_JUMP, [self valueAt:[touch locationInView:self].x], nil);
	return YES;
}

- (void)finish {
	if (owner == nil) { return; }
	if (btrcUIKitDragging == owner) { btrcUIKitDragging = nil; }
	if (owner->tracking) {
		owner->tracking = NO;
		btrcUIKitPushControl(owner, BTRC_SHIM_EVENT_CONTROL_SLIDER_RELEASED, 0, 0.0, nil);
	}
	btrcUIKitShowSlider(owner);
}

- (void)endTrackingWithTouch:(UITouch*)touch withEvent:(UIEvent*)event {
	[super endTrackingWithTouch:touch withEvent:event];
	[self finish];
}

- (void)cancelTrackingWithEvent:(UIEvent*)event {
	[super cancelTrackingWithEvent:event];
	[self finish];
}
@end

/* A scroll bar for a view the program scrolls itself: it shows where the
 * view is, and reports where a person drags it to. */
@interface BtrcUIKitScrollbar : UIView {
@public
	BtrcUIKitControl* owner;
}
@end

@implementation BtrcUIKitScrollbar
- (CGFloat)length {
	return owner->vertical ? self.bounds.size.height : self.bounds.size.width;
}

- (CGFloat)thumb {
	CGFloat thumb = (CGFloat)((double)[self length] * owner->viewport / owner->content);
	return thumb < 16.0 ? 16.0 : thumb;
}

- (void)drawRect:(CGRect)rect {
	(void)rect;
	if (owner == nil || owner->content <= owner->viewport || owner->content <= 0.0) { return; }
	CGFloat thumb = [self thumb];
	CGFloat start = (CGFloat)((double)([self length] - thumb) * owner->offset / (owner->content - owner->viewport));
	CGRect bar = owner->vertical ? CGRectMake(2.0, start, self.bounds.size.width - 4.0, thumb) : CGRectMake(start, 2.0, thumb, self.bounds.size.height - 4.0);
	[[UIColor colorWithWhite:0.5 alpha:0.4] setFill];
	[[UIBezierPath bezierPathWithRoundedRect:bar cornerRadius:3.0] fill];
}

- (CGFloat)along:(NSSet<UITouch*>*)touches {
	CGPoint at = [touches.anyObject locationInView:self];
	return owner->vertical ? at.y : at.x;
}

- (void)touchesBegan:(NSSet<UITouch*>*)touches withEvent:(UIEvent*)event {
	(void)event;
	if (owner == nil || owner->content <= owner->viewport) { return; }
	double travel = (double)([self length] - [self thumb]);
	owner->grabbed = (double)[self along:touches] - travel * owner->offset / (owner->content - owner->viewport);
}

- (void)touchesMoved:(NSSet<UITouch*>*)touches withEvent:(UIEvent*)event {
	(void)event;
	if (owner == nil || owner->content <= owner->viewport) { return; }
	double travel = (double)([self length] - [self thumb]);
	double asked = travel > 0.0 ? ((double)[self along:touches] - owner->grabbed) / travel * (owner->content - owner->viewport) : 0.0;
	asked = asked < 0.0 ? 0.0 : asked > owner->content - owner->viewport ? owner->content - owner->viewport : asked;
	btrcUIKitPushControl(owner, BTRC_SHIM_EVENT_CONTROL_SCROLLBAR_CHANGED, owner->vertical ? 1 : 0, asked, nil);
}

- (void)touchesEnded:(NSSet<UITouch*>*)touches withEvent:(UIEvent*)event {
	(void)touches;
	(void)event;
}

- (void)touchesCancelled:(NSSet<UITouch*>*)touches withEvent:(UIEvent*)event {
	(void)touches;
	(void)event;
}
@end

/* A select's list: its items in a table over the window, under the button
 * where there is room. Its keys are read by the window (btrcUIKitControlsKeyDown),
 * so that what a person steps to and chooses is the same with any keyboard. */
@interface BtrcUIKitSelectList : UIView <UITableViewDataSource, UITableViewDelegate> {
@public
	BtrcUIKitControl* owner;
	UITableView* table;
}
@end

enum { BTRC_UIKIT_SELECT_ROW = 44, BTRC_UIKIT_SELECT_ROWS = 8 };

@implementation BtrcUIKitSelectList
- (void)dealloc {
	[table release];
	[super dealloc];
}

- (NSInteger)tableView:(UITableView*)tableView numberOfRowsInSection:(NSInteger)section {
	(void)tableView;
	(void)section;
	return owner == nil ? 0 : (NSInteger)owner->items.count;
}

- (UITableViewCell*)tableView:(UITableView*)tableView cellForRowAtIndexPath:(NSIndexPath*)path {
	UITableViewCell* cell = [tableView dequeueReusableCellWithIdentifier:@"item"];
	if (cell == nil) { cell = [[[UITableViewCell alloc] initWithStyle:UITableViewCellStyleDefault reuseIdentifier:@"item"] autorelease]; }
	BOOL enabled = owner->itemEnabled[(NSUInteger)path.row].boolValue;
	UIListContentConfiguration* content = [UIListContentConfiguration cellConfiguration];
	content.text = owner->items[(NSUInteger)path.row];
	content.textProperties.color = enabled ? UIColor.labelColor : UIColor.tertiaryLabelColor;
	cell.contentConfiguration = content;
	cell.accessoryType = path.row == owner->candidate ? UITableViewCellAccessoryCheckmark : UITableViewCellAccessoryNone;
	cell.selectionStyle = enabled ? UITableViewCellSelectionStyleDefault : UITableViewCellSelectionStyleNone;
	cell.backgroundColor = UIColor.clearColor;
	return cell;
}

- (NSIndexPath*)tableView:(UITableView*)tableView willSelectRowAtIndexPath:(NSIndexPath*)path {
	(void)tableView;
	return owner != nil && owner->itemEnabled[(NSUInteger)path.row].boolValue ? path : nil;
}

- (void)tableView:(UITableView*)tableView didSelectRowAtIndexPath:(NSIndexPath*)path {
	(void)tableView;
	BtrcUIKitControl* control = owner;
	if (control == nil) { return; }
	btrcUIKitPushControl(control, BTRC_SHIM_EVENT_CONTROL_SELECT_CHOSEN, (int)path.row, 0.0, nil);
	btrcUIKitSelectClose(control, NO, NO);
}
@end

static void btrcUIKitSelectClose(BtrcUIKitControl* control, BOOL report, BOOL escaped) {
	if (control->list == nil) { return; }
	UIView* backdrop = control->list;
	control->list = nil;
	if (btrcUIKitOpened == control) { btrcUIKitOpened = nil; }
	for (UIView* part in backdrop.subviews) {
		if ([part isKindOfClass:BtrcUIKitSelectList.class]) { ((BtrcUIKitSelectList*)part)->owner = nil; }
	}
	[backdrop removeFromSuperview];
	[backdrop release];
	if (report) { btrcUIKitPushControl(control, BTRC_SHIM_EVENT_CONTROL_SELECT_DISMISSED, escaped ? 1 : 0, 0.0, nil); }
}

static void btrcUIKitSelectOpen(BtrcUIKitControl* control) {
	if (control->list != nil || control->window == nil || control->items.count == 0u) { return; }
	if (btrcUIKitOpened != nil) { btrcUIKitSelectClose(btrcUIKitOpened, YES, NO); }
	UIView* root = btrcUIKitPresenter(control->window).view;
	/* Everything outside the list is the backdrop: a touch there closes it. */
	UIControl* backdrop = [[UIControl alloc] initWithFrame:root.bounds];
	backdrop.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
	[backdrop addTarget:control action:@selector(selectBackdrop:) forControlEvents:UIControlEventTouchDown];
	CGRect anchor = [control->view convertRect:control->view.bounds toView:root];
	CGRect safe = root.safeAreaLayoutGuide.layoutFrame;
	NSUInteger rows = control->items.count < BTRC_UIKIT_SELECT_ROWS ? control->items.count : BTRC_UIKIT_SELECT_ROWS;
	CGFloat height = (CGFloat)rows * BTRC_UIKIT_SELECT_ROW;
	CGFloat width = anchor.size.width < 200.0 ? 200.0 : anchor.size.width;
	if (width > safe.size.width - 16.0) { width = safe.size.width - 16.0; }
	CGFloat x = anchor.origin.x;
	if (x + width > CGRectGetMaxX(safe) - 8.0) { x = CGRectGetMaxX(safe) - 8.0 - width; }
	if (x < CGRectGetMinX(safe) + 8.0) { x = CGRectGetMinX(safe) + 8.0; }
	CGFloat y = CGRectGetMaxY(anchor) + 4.0;
	if (y + height > CGRectGetMaxY(safe) - 8.0) { y = CGRectGetMinY(anchor) - 4.0 - height; }
	if (y < CGRectGetMinY(safe) + 8.0) { y = CGRectGetMinY(safe) + 8.0; }
	BtrcUIKitSelectList* list = [[BtrcUIKitSelectList alloc] initWithFrame:CGRectMake(x, y, width, height)];
	list->owner = control;
	list.backgroundColor = UIColor.secondarySystemBackgroundColor;
	list.layer.cornerRadius = 12.0;
	list.layer.shadowColor = UIColor.blackColor.CGColor;
	list.layer.shadowOpacity = 0.25f;
	list.layer.shadowRadius = 12.0;
	list.layer.shadowOffset = CGSizeMake(0.0, 4.0);
	list->table = [[UITableView alloc] initWithFrame:list.bounds style:UITableViewStylePlain];
	list->table.rowHeight = BTRC_UIKIT_SELECT_ROW;
	list->table.backgroundColor = UIColor.clearColor;
	list->table.layer.cornerRadius = 12.0;
	list->table.clipsToBounds = YES;
	list->table.dataSource = list;
	list->table.delegate = list;
	list->table.alwaysBounceVertical = NO;
	[list addSubview:list->table];
	[backdrop addSubview:list];
	[list release];
	[root addSubview:backdrop];
	control->list = backdrop;
	control->candidate = control->marked;
	btrcUIKitOpened = control;
	btrcUIKitPushControl(control, BTRC_SHIM_EVENT_CONTROL_SELECT_OPENED, 0, 0.0, nil);
	if (control->candidate >= 0) { [list->table scrollToRowAtIndexPath:[NSIndexPath indexPathForRow:control->candidate inSection:0] atScrollPosition:UITableViewScrollPositionMiddle animated:NO]; }
}

@implementation BtrcUIKitControl (Select)
- (void)selectPressed:(id)sender {
	(void)sender;
	btrcUIKitSelectOpen(self);
}

- (void)selectBackdrop:(id)sender {
	(void)sender;
	btrcUIKitSelectClose(self, YES, NO);
}
@end

static UITableView* btrcUIKitSelectTable(BtrcUIKitControl* control) {
	for (UIView* part in control->list.subviews) {
		if ([part isKindOfClass:BtrcUIKitSelectList.class]) { return ((BtrcUIKitSelectList*)part)->table; }
	}
	return nil;
}

static int btrcUIKitSelectStep(BtrcUIKitControl* control, int from, int direction) {
	for (int index = from + direction; index >= 0 && index < (int)control->items.count; index += direction) {
		if (control->itemEnabled[(NSUInteger)index].boolValue) { return index; }
	}
	return from;
}

/* What the window's event observation asks of the controls. */

BOOL btrcUIKitControlsKeyDown(BtrcUIKitWindow* window, unsigned int key) {
	if (key == BTRC_SHIM_KEY_ESCAPE && btrcUIKitDragging != nil) {
		/* Escape abandons the drag: what the finger does until it lifts is no longer the slider's. */
		btrcUIKitCancelled = btrcUIKitDragging;
		btrcUIKitDragging = nil;
		btrcUIKitCancelled->tracking = NO;
		btrcUIKitCancelled->cancelledDrag = YES;
		btrcUIKitPushControl(btrcUIKitCancelled, BTRC_SHIM_EVENT_CONTROL_SLIDER_CANCELLED, 0, 0.0, nil);
		btrcUIKitShowSlider(btrcUIKitCancelled);
	}
	BtrcUIKitControl* select = btrcUIKitOpened;
	if (select != nil && select->window == window) {
		if (key == BTRC_SHIM_KEY_DOWN || key == BTRC_SHIM_KEY_UP) {
			int next = btrcUIKitSelectStep(select, select->candidate, key == BTRC_SHIM_KEY_DOWN ? 1 : -1);
			if (next != select->candidate && next >= 0) {
				select->candidate = next;
				UITableView* table = btrcUIKitSelectTable(select);
				[table reloadData];
				[table scrollToRowAtIndexPath:[NSIndexPath indexPathForRow:next inSection:0] atScrollPosition:UITableViewScrollPositionNone animated:NO];
				btrcUIKitPushControl(select, BTRC_SHIM_EVENT_CONTROL_SELECT_CANDIDATE, next, 0.0, nil);
			}
			return YES;
		}
		if (key == BTRC_SHIM_KEY_RETURN || key == BTRC_SHIM_KEY_KP_ENTER || key == BTRC_SHIM_KEY_SPACE) {
			if (select->candidate >= 0 && select->itemEnabled[(NSUInteger)select->candidate].boolValue) {
				btrcUIKitPushControl(select, BTRC_SHIM_EVENT_CONTROL_SELECT_CHOSEN, select->candidate, 0.0, nil);
				btrcUIKitSelectClose(select, NO, NO);
			}
			return YES;
		}
		if (key == BTRC_SHIM_KEY_ESCAPE) {
			btrcUIKitSelectClose(select, YES, YES);
			return YES;
		}
		return NO;
	}
	if (key == BTRC_SHIM_KEY_ESCAPE && btrcUIKitEditing != nil && btrcUIKitEditing->window == window) { btrcUIKitPushControl(btrcUIKitEditing, BTRC_SHIM_EVENT_CONTROL_TEXT_ESCAPED, 0, 0.0, nil); }
	return NO;
}

void btrcUIKitControlsTouchDown(void) {
	if (btrcUIKitCancelled != nil) {
		btrcUIKitCancelled->cancelledDrag = NO;
		btrcUIKitCancelled = nil;
	}
}

void btrcUIKitControlsLeave(BtrcUIKitWindow* window) {
	if (btrcUIKitOpened != nil && btrcUIKitOpened->window == window) { btrcUIKitSelectClose(btrcUIKitOpened, YES, NO); }
}

BOOL btrcUIKitControlsTextFocused(BtrcUIKitWindow* window) { return btrcUIKitEditing != nil && btrcUIKitEditing->window == window && btrcUIKitEditing->view.isFirstResponder; }

/* Making and unmaking. */

static BtrcUIKitControl* btrcUIKitControlWrap(int kind, unsigned int identifier, UIView* view) {
	BtrcUIKitControl* control = [[BtrcUIKitControl alloc] init];
	control->identifier = identifier;
	control->kind = kind;
	control->view = [view retain];
	control->bordered = YES;
	control->marked = -1;
	control->candidate = -1;
	control->maximum = 1.0;
	control->slot = [[BtrcUIKitSlot alloc] initWithFrame:CGRectZero];
	control->slot->owner = control;
	[control->slot addSubview:view];
	return control;
}

BtrcShimControl* btrcUIKitControlAdopt(int kind, unsigned int identifier, UIView* view) { return (BtrcShimControl*)(void*)btrcUIKitControlWrap(kind, identifier, view); }

static BtrcShimControl* btrcUIKitControlNew(int kind, unsigned int identifier, const char* text, const char* more, bool flag) {
	__block BtrcUIKitControl* made = nil;
	NSString* first = btrcUIKitString(text);
	NSString* second = btrcUIKitString(more);
	btrcUIKitOnMain(^{
		UIView* view = nil;
		switch (kind) {
		case BTRC_UIKIT_BUTTON:
		case BTRC_UIKIT_SELECT:
			view = [UIButton buttonWithType:UIButtonTypeSystem];
			break;
		case BTRC_UIKIT_LABEL: {
			UILabel* label = [[[UILabel alloc] initWithFrame:CGRectZero] autorelease];
			label.text = first;
			label.numberOfLines = 1;
			label.lineBreakMode = NSLineBreakByTruncatingTail;
			label.userInteractionEnabled = NO;
			view = label;
			break;
		}
		case BTRC_UIKIT_SPINNER: {
			UIActivityIndicatorView* spinner = [[[UIActivityIndicatorView alloc] initWithActivityIndicatorStyle:UIActivityIndicatorViewStyleMedium] autorelease];
			spinner.hidesWhenStopped = YES;
			spinner.userInteractionEnabled = NO;
			view = spinner;
			break;
		}
		case BTRC_UIKIT_LEVEL: {
			UIProgressView* level = [[[UIProgressView alloc] initWithProgressViewStyle:UIProgressViewStyleDefault] autorelease];
			level.userInteractionEnabled = NO;
			view = level;
			break;
		}
		case BTRC_UIKIT_SLIDER:
			view = [[[BtrcUIKitSlider alloc] initWithFrame:CGRectZero] autorelease];
			break;
		case BTRC_UIKIT_TEXT: {
			UITextField* field = [[[UITextField alloc] initWithFrame:CGRectZero] autorelease];
			field.borderStyle = UITextBorderStyleRoundedRect;
			field.text = first;
			field.placeholder = second;
			/* The text is the person's as typed: a field of program data, not prose. */
			field.autocapitalizationType = UITextAutocapitalizationTypeNone;
			field.autocorrectionType = UITextAutocorrectionTypeNo;
			field.spellCheckingType = UITextSpellCheckingTypeNo;
			field.smartQuotesType = UITextSmartQuotesTypeNo;
			field.smartDashesType = UITextSmartDashesTypeNo;
			field.smartInsertDeleteType = UITextSmartInsertDeleteTypeNo;
			field.inlinePredictionType = UITextInlinePredictionTypeNo;
			field.returnKeyType = UIReturnKeyDone;
			view = field;
			break;
		}
		case BTRC_UIKIT_PICTURE: {
			UIImageView* picture = [[[UIImageView alloc] initWithFrame:CGRectZero] autorelease];
			picture.contentMode = UIViewContentModeScaleAspectFit;
			picture.userInteractionEnabled = NO;
			view = picture;
			break;
		}
		case BTRC_UIKIT_FILL:
			view = [[[UIView alloc] initWithFrame:CGRectZero] autorelease];
			view.userInteractionEnabled = NO;
			break;
		case BTRC_UIKIT_SCROLLBAR:
			view = [[[BtrcUIKitScrollbar alloc] initWithFrame:CGRectZero] autorelease];
			view.opaque = NO;
			view.backgroundColor = UIColor.clearColor;
			view.contentMode = UIViewContentModeRedraw;
			break;
		default:
			return;
		}
		made = btrcUIKitControlWrap(kind, identifier, view);
		switch (kind) {
		case BTRC_UIKIT_BUTTON:
			made->title = [first copy];
			[(UIButton*)view addTarget:made action:@selector(activated:) forControlEvents:UIControlEventPrimaryActionTriggered];
			btrcUIKitShowButton(made);
			break;
		case BTRC_UIKIT_SELECT:
			made->title = [[NSString alloc] init];
			made->items = [[NSMutableArray alloc] init];
			made->itemEnabled = [[NSMutableArray alloc] init];
			[(UIButton*)view addTarget:made action:@selector(selectPressed:) forControlEvents:UIControlEventPrimaryActionTriggered];
			btrcUIKitShowButton(made);
			break;
		case BTRC_UIKIT_SLIDER:
			((BtrcUIKitSlider*)view)->owner = made;
			break;
		case BTRC_UIKIT_TEXT:
			[(UITextField*)view addTarget:made action:@selector(textChanged:) forControlEvents:UIControlEventEditingChanged];
			[(UITextField*)view addTarget:made action:@selector(textBegan:) forControlEvents:UIControlEventEditingDidBegin];
			[(UITextField*)view addTarget:made action:@selector(textEnded:) forControlEvents:UIControlEventEditingDidEnd];
			((UITextField*)view).delegate = made;
			break;
		case BTRC_UIKIT_SCROLLBAR:
			((BtrcUIKitScrollbar*)view)->owner = made;
			made->vertical = flag ? YES : NO;
			break;
		default:
			break;
		}
	});
	[first release];
	[second release];
	return (BtrcShimControl*)(void*)made;
}

void btrcShimControlDestroy(BtrcShimControl* handle) {
	if (handle == NULL) { return; }
	BtrcUIKitControl* control = btrcUIKitControl(handle);
	btrcUIKitOnMain(^{
		btrcUIKitSelectClose(control, NO, NO);
		if (btrcUIKitDragging == control) { btrcUIKitDragging = nil; }
		if (btrcUIKitCancelled == control) { btrcUIKitCancelled = nil; }
		if (btrcUIKitEditing == control) { btrcUIKitEditing = nil; }
		if ([control->view isKindOfClass:UIControl.class]) { [(UIControl*)control->view removeTarget:control action:NULL forControlEvents:UIControlEventAllEvents]; }
		if (control->kind == BTRC_UIKIT_TEXT) { ((UITextField*)control->view).delegate = nil; }
		if (control->kind == BTRC_UIKIT_SLIDER) { ((BtrcUIKitSlider*)control->view)->owner = nil; }
		if (control->kind == BTRC_UIKIT_SCROLLBAR) { ((BtrcUIKitScrollbar*)control->view)->owner = nil; }
		if (control->window != nil) { [control->window->placed removeObject:control->slot]; }
		control->slot->owner = nil;
		[control->slot removeFromSuperview];
		[control->view removeFromSuperview];
		[control release];
	});
}

void btrcShimControlSetEnabled(BtrcShimControl* handle, bool enabled) {
	BtrcUIKitControl* control = btrcUIKitControl(handle);
	btrcUIKitOnMain(^{
		if ([control->view isKindOfClass:UIControl.class]) { ((UIControl*)control->view).enabled = enabled; }
		else if ([control->view isKindOfClass:UILabel.class]) { ((UILabel*)control->view).enabled = enabled; }
	});
}

/* Help shown when a pointer rests on the control; a finger has none. */
void btrcShimControlSetToolTip(BtrcShimControl* handle, const char* text) {
	BtrcUIKitControl* control = btrcUIKitControl(handle);
	NSString* help = btrcUIKitString(text);
	btrcUIKitOnMain(^{
		if (control->toolTip != nil) {
			[control->view removeInteraction:control->toolTip];
			[control->toolTip release];
			control->toolTip = nil;
		}
		if (help.length > 0u) {
			control->toolTip = [[UIToolTipInteraction alloc] initWithDefaultToolTip:help];
			[control->view addInteraction:control->toolTip];
		}
	});
	[help release];
}

void btrcShimControlSetFont(BtrcShimControl* handle, double size, bool bold) {
	BtrcUIKitControl* control = btrcUIKitControl(handle);
	btrcUIKitOnMain(^{
		control->fontSize = size;
		control->bold = bold ? YES : NO;
		if (control->kind == BTRC_UIKIT_BUTTON || control->kind == BTRC_UIKIT_SELECT) { btrcUIKitShowButton(control); }
		else if ([control->view isKindOfClass:UILabel.class]) { ((UILabel*)control->view).font = btrcUIKitFont(control); }
		else if ([control->view isKindOfClass:UITextField.class]) { ((UITextField*)control->view).font = btrcUIKitFont(control); }
	});
}

/* {width, height} in points: what the control takes when nothing constrains it, or at this width. */
static void btrcUIKitNatural(BtrcShimControl* handle, int forWidth, int* width, int* height) {
	BtrcUIKitControl* control = btrcUIKitControl(handle);
	btrcUIKitOnMain(^{
		CGSize size = CGSizeZero;
		switch (control->kind) {
		case BTRC_UIKIT_SCROLLBAR:
			size = control->vertical ? CGSizeMake(8.0, 40.0) : CGSizeMake(40.0, 8.0);
			break;
		case BTRC_UIKIT_SLIDER:
		case BTRC_UIKIT_LEVEL:
			/* Neither has a width of its own. */
			size = CGSizeMake(120.0, [control->view sizeThatFits:CGSizeMake(120.0, CGFLOAT_MAX)].height);
			break;
		case BTRC_UIKIT_SELECT: {
			/* Wide enough for the longest item, not only the one shown. */
			size = [control->view sizeThatFits:CGSizeMake(CGFLOAT_MAX, CGFLOAT_MAX)];
			CGFloat shown = [control->title sizeWithAttributes:@{NSFontAttributeName : btrcUIKitFont(control)}].width;
			CGFloat widest = shown;
			for (NSString* item in control->items) {
				CGFloat wide = [item sizeWithAttributes:@{NSFontAttributeName : btrcUIKitFont(control)}].width;
				if (wide > widest) { widest = wide; }
			}
			size.width += widest - shown;
			break;
		}
		default:
			size = [control->view sizeThatFits:CGSizeMake(forWidth > 0 ? (CGFloat)forWidth : CGFLOAT_MAX, CGFLOAT_MAX)];
			if (forWidth > 0) { size.width = (CGFloat)forWidth; }
			break;
		}
		*width = (int)ceil(size.width);
		*height = (int)ceil(size.height);
	});
}

int btrcShimControlNaturalWidth(BtrcShimControl* control) {
	int width = 0;
	int height = 0;
	btrcUIKitNatural(control, 0, &width, &height);
	return width;
}

int btrcShimControlNaturalHeight(BtrcShimControl* control) {
	int width = 0;
	int height = 0;
	btrcUIKitNatural(control, 0, &width, &height);
	return height;
}

int btrcShimControlNaturalHeightFor(BtrcShimControl* control, int forWidth) {
	int width = 0;
	int height = 0;
	btrcUIKitNatural(control, forWidth, &width, &height);
	return height;
}

/* Placement. The program's thread gathers one, and it crosses to the main thread whole. */

void btrcShimWindowBeginPlacement(BtrcShimWindow* window) { btrcUIKitWindow(window)->placingCount = 0; }

static void btrcUIKitPlace(BtrcUIKitWindow* window, BtrcUIKitControl* control, double x, double y, double width, double height, double clipX, double clipY, double clipWidth, double clipHeight) {
	if (window->placingCount == window->placingCapacity) {
		int capacity = window->placingCapacity == 0 ? 32 : window->placingCapacity * 2;
		BtrcUIKitControl** controls = realloc(window->placing, (size_t)capacity * sizeof *controls);
		if (controls == NULL) { return; }
		window->placing = controls;
		double* rectangles = realloc(window->rectangles, (size_t)capacity * 8u * sizeof *rectangles);
		if (rectangles == NULL) { return; }
		window->rectangles = rectangles;
		window->placingCapacity = capacity;
	}
	window->placing[window->placingCount] = control;
	double* rectangle = window->rectangles + (size_t)window->placingCount * 8u;
	rectangle[0] = x; rectangle[1] = y; rectangle[2] = width; rectangle[3] = height;
	rectangle[4] = clipX; rectangle[5] = clipY; rectangle[6] = clipWidth; rectangle[7] = clipHeight;
	window->placingCount++;
}

void btrcShimWindowPlace(BtrcShimWindow* window, BtrcShimControl* control, double x, double y, double width, double height, double clipX, double clipY, double clipWidth, double clipHeight) {
	btrcUIKitPlace(btrcUIKitWindow(window), btrcUIKitControl(control), x, y, width, height, clipX, clipY, clipWidth, clipHeight);
}

void btrcShimWindowPlaceHole(BtrcShimWindow* window, double x, double y, double width, double height, double clipX, double clipY, double clipWidth, double clipHeight) {
	btrcUIKitPlace(btrcUIKitWindow(window), nil, x, y, width, height, clipX, clipY, clipWidth, clipHeight);
}

void btrcShimWindowEndPlacement(BtrcShimWindow* handle) {
	BtrcUIKitWindow* window = btrcUIKitWindow(handle);
	btrcUIKitOnMain(^{
		NSMutableArray<BtrcUIKitSlot*>* now = [NSMutableArray array];
		int holeCount = 0;
		CGRect* holes = window->placingCount > 0 ? malloc((size_t)window->placingCount * sizeof *holes) : NULL;
		CGRect* local = window->placingCount > 0 ? malloc((size_t)window->placingCount * sizeof *local) : NULL;
		/* Holes cut the controls placed before them: walk front to back. */
		for (int index = window->placingCount - 1; index >= 0 && holes != NULL && local != NULL; index--) {
			const double* rectangle = window->rectangles + (size_t)index * 8u;
			CGRect frame = CGRectMake(rectangle[0], rectangle[1], rectangle[2], rectangle[3]);
			CGRect clip = CGRectMake(rectangle[4], rectangle[5], rectangle[6], rectangle[7]);
			BtrcUIKitControl* control = window->placing[index];
			if (control == nil) {
				CGRect hole = CGRectIntersection(frame, clip);
				if (!CGRectIsNull(hole) && !CGRectIsEmpty(hole)) { holes[holeCount++] = hole; }
				continue;
			}
			BtrcUIKitSlot* slot = control->slot;
			if (control->window != window) {
				if (control->window != nil) {
					[control->window->placed removeObject:slot];
					[slot removeFromSuperview];
				}
				control->window = window;
			}
			if (!CGRectEqualToRect(slot.frame, frame)) { slot.frame = frame; }
			CGRect inside = CGRectMake(0.0, 0.0, frame.size.width, frame.size.height);
			if (!CGRectEqualToRect(control->view.frame, inside)) { control->view.frame = inside; }
			for (int hole = 0; hole < holeCount; hole++) { local[hole] = CGRectOffset(holes[hole], -frame.origin.x, -frame.origin.y); }
			[slot showWithin:CGRectOffset(clip, -frame.origin.x, -frame.origin.y) cutting:local count:holeCount];
			[now insertObject:slot atIndex:0];
		}
		free(holes);
		free(local);
		for (BtrcUIKitSlot* slot in window->placed) {
			if (![now containsObject:slot]) {
				if (slot->owner != nil) {
					if (slot->owner == btrcUIKitOpened) { btrcUIKitSelectClose(slot->owner, YES, NO); }
					slot->owner->window = nil;
				}
				[slot removeFromSuperview];
			}
		}
		/* The content's own layer is the drawn frame; the slots lie over it in order. */
		NSUInteger at = 0;
		for (BtrcUIKitSlot* slot in now) {
			if (slot.superview != window->content || [window->content.subviews indexOfObjectIdenticalTo:slot] != at) { [window->content insertSubview:slot atIndex:(NSInteger)at]; }
			at++;
		}
		[window->placed setArray:now];
	});
}

/* The controls as UIKit draws them, laid over a picture of the content. */
bool btrcShimWindowDrawControls(BtrcShimWindow* handle, unsigned char* pixels, int pixelWidth, int pixelHeight) {
	if (pixels == NULL || pixelWidth <= 0 || pixelHeight <= 0) { return false; }
	BtrcUIKitWindow* window = btrcUIKitWindow(handle);
	__block bool drawn = false;
	btrcUIKitOnMain(^{
		CGSize size = window->content.bounds.size;
		if (size.width <= 0.0 || size.height <= 0.0) { return; }
		CGColorSpaceRef space = CGColorSpaceCreateWithName(kCGColorSpaceSRGB);
		CGContextRef context = CGBitmapContextCreate(NULL, (size_t)pixelWidth, (size_t)pixelHeight, 8u, (size_t)pixelWidth * 4u, space, (CGBitmapInfo)kCGImageAlphaPremultipliedLast | kCGBitmapByteOrder32Big);
		CGColorSpaceRelease(space);
		if (context == NULL) { return; }
		/* UIKit's points from the top left, onto the picture's pixels. */
		CGContextTranslateCTM(context, 0.0, (CGFloat)pixelHeight);
		CGContextScaleCTM(context, (CGFloat)pixelWidth / size.width, -(CGFloat)pixelHeight / size.height);
		[window->content layoutIfNeeded];
		UIGraphicsPushContext(context);
		[window->native.traitCollection performAsCurrentTraitCollection:^{
			for (BtrcUIKitSlot* slot in window->placed) {
				CGContextSaveGState(context);
				CGContextTranslateCTM(context, slot.frame.origin.x, slot.frame.origin.y);
				[slot layoutIfNeeded];
				[slot.layer renderInContext:context];
				CGContextRestoreGState(context);
			}
		}];
		UIGraphicsPopContext();
		const unsigned char* over = CGBitmapContextGetData(context);
		size_t stride = CGBitmapContextGetBytesPerRow(context);
		for (int row = 0; over != NULL && row < pixelHeight; row++) {
			const unsigned char* from = over + (size_t)row * stride;
			unsigned char* onto = pixels + (size_t)row * (size_t)pixelWidth * 4u;
			for (size_t index = 0; index < (size_t)pixelWidth * 4u; index += 4u) {
				unsigned int covered = 255u - from[index + 3u];
				for (size_t channel = 0; channel < 4u; channel++) { onto[index + channel] = (unsigned char)(from[index + channel] + (onto[index + channel] * covered + 127u) / 255u); }
			}
		}
		drawn = over != NULL;
		CGContextRelease(context);
	});
	return drawn;
}

/* The kinds. */

BtrcShimControl* btrcShimButtonCreate(unsigned int id, const char* title) { return btrcUIKitControlNew(BTRC_UIKIT_BUTTON, id, title, "", false); }

void btrcShimButtonSetTitle(BtrcShimControl* handle, const char* title) {
	BtrcUIKitControl* button = btrcUIKitControl(handle);
	NSString* text = btrcUIKitString(title);
	btrcUIKitOnMain(^{
		[button->title release];
		button->title = [text copy];
		btrcUIKitShowButton(button);
	});
	[text release];
}

void btrcShimButtonSetCentered(BtrcShimControl* handle, bool centered) {
	BtrcUIKitControl* button = btrcUIKitControl(handle);
	btrcUIKitOnMain(^{
		button->centered = centered ? YES : NO;
		btrcUIKitShowButton(button);
	});
}

void btrcShimButtonBeginSymbol(BtrcShimControl* handle, double size) {
	BtrcUIKitControl* button = btrcUIKitControl(handle);
	btrcUIKitOnMain(^{
		button->symbolSize = size;
		button->shapeCount = 0;
		btrcUIKitShowButton(button);
	});
}

static void btrcUIKitShape(BtrcShimControl* handle, double kind, double a, double b, double c, double d, double e, double f) {
	BtrcUIKitControl* button = btrcUIKitControl(handle);
	btrcUIKitOnMain(^{
		double* shapes = realloc(button->shapes, ((size_t)button->shapeCount + 1u) * 7u * sizeof *shapes);
		if (shapes == NULL) { return; }
		button->shapes = shapes;
		double* shape = shapes + (size_t)button->shapeCount * 7u;
		shape[0] = kind; shape[1] = a; shape[2] = b; shape[3] = c; shape[4] = d; shape[5] = e; shape[6] = f;
		button->shapeCount++;
		btrcUIKitShowButton(button);
	});
}

void btrcShimButtonSymbolLine(BtrcShimControl* button, double x0, double y0, double x1, double y1, double width) { btrcUIKitShape(button, 1.0, x0, y0, x1, y1, width, 0.0); }

void btrcShimButtonSymbolTriangle(BtrcShimControl* button, double x0, double y0, double x1, double y1, double x2, double y2) { btrcUIKitShape(button, 2.0, x0, y0, x1, y1, x2, y2); }

void btrcShimButtonSymbolRectangle(BtrcShimControl* button, double x, double y, double width, double height, double radius, double stroke) { btrcUIKitShape(button, 3.0, x, y, width, height, radius, stroke); }

void btrcShimButtonSymbolCircle(BtrcShimControl* button, double centerX, double centerY, double radius, double stroke) { btrcUIKitShape(button, 4.0, centerX, centerY, radius, stroke, 0.0, 0.0); }

void btrcShimButtonSetBordered(BtrcShimControl* handle, bool bordered) {
	BtrcUIKitControl* button = btrcUIKitControl(handle);
	btrcUIKitOnMain(^{
		button->bordered = bordered ? YES : NO;
		btrcUIKitShowButton(button);
	});
}

void btrcShimButtonSetSelected(BtrcShimControl* handle, bool selected) {
	BtrcUIKitControl* button = btrcUIKitControl(handle);
	btrcUIKitOnMain(^{
		button->selected = selected ? YES : NO;
		btrcUIKitShowButton(button);
	});
}

void btrcShimButtonSetTransparent(BtrcShimControl* handle, bool transparent) {
	BtrcUIKitControl* button = btrcUIKitControl(handle);
	btrcUIKitOnMain(^{
		button->transparent = transparent ? YES : NO;
		btrcUIKitShowButton(button);
	});
}

BtrcShimControl* btrcShimLabelCreate(unsigned int id, const char* text) { return btrcUIKitControlNew(BTRC_UIKIT_LABEL, id, text, "", false); }

void btrcShimLabelSetText(BtrcShimControl* handle, const char* text) {
	BtrcUIKitControl* label = btrcUIKitControl(handle);
	NSString* string = btrcUIKitString(text);
	btrcUIKitOnMain(^{ ((UILabel*)label->view).text = string; });
	[string release];
}

void btrcShimLabelSetSecondary(BtrcShimControl* handle, bool secondary) {
	BtrcUIKitControl* label = btrcUIKitControl(handle);
	btrcUIKitOnMain(^{ ((UILabel*)label->view).textColor = secondary ? UIColor.secondaryLabelColor : UIColor.labelColor; });
}

void btrcShimLabelSetCentered(BtrcShimControl* handle, bool centered) {
	BtrcUIKitControl* label = btrcUIKitControl(handle);
	btrcUIKitOnMain(^{ ((UILabel*)label->view).textAlignment = centered ? NSTextAlignmentCenter : NSTextAlignmentNatural; });
}

void btrcShimLabelSetWrapping(BtrcShimControl* handle, bool wrapping) {
	BtrcUIKitControl* label = btrcUIKitControl(handle);
	btrcUIKitOnMain(^{
		((UILabel*)label->view).numberOfLines = wrapping ? 0 : 1;
		((UILabel*)label->view).lineBreakMode = wrapping ? NSLineBreakByWordWrapping : NSLineBreakByTruncatingTail;
	});
}

BtrcShimControl* btrcShimSpinnerCreate(unsigned int id) { return btrcUIKitControlNew(BTRC_UIKIT_SPINNER, id, "", "", false); }

void btrcShimSpinnerSetRunning(BtrcShimControl* handle, bool running) {
	BtrcUIKitControl* spinner = btrcUIKitControl(handle);
	btrcUIKitOnMain(^{
		if (running) { [(UIActivityIndicatorView*)spinner->view startAnimating]; }
		else { [(UIActivityIndicatorView*)spinner->view stopAnimating]; }
	});
}

BtrcShimControl* btrcShimLevelCreate(unsigned int id, double warning, double critical) {
	BtrcShimControl* handle = btrcUIKitControlNew(BTRC_UIKIT_LEVEL, id, "", "", false);
	if (handle != NULL) {
		btrcUIKitControl(handle)->warning = warning;
		btrcUIKitControl(handle)->critical = critical;
	}
	return handle;
}

void btrcShimLevelSetValue(BtrcShimControl* handle, double value) {
	BtrcUIKitControl* level = btrcUIKitControl(handle);
	btrcUIKitOnMain(^{
		double shown = value < 0.0 ? 0.0 : value > 1.0 ? 1.0 : value;
		UIProgressView* bar = (UIProgressView*)level->view;
		bar.progressTintColor = shown >= level->critical ? UIColor.systemRedColor : shown >= level->warning ? UIColor.systemOrangeColor : UIColor.systemGreenColor;
		bar.progress = (float)shown;
	});
}

BtrcShimControl* btrcShimSliderCreate(unsigned int id) { return btrcUIKitControlNew(BTRC_UIKIT_SLIDER, id, "", "", false); }

void btrcShimSliderSet(BtrcShimControl* handle, double minimum, double maximum, double step, double value) {
	(void)step;
	BtrcUIKitControl* slider = btrcUIKitControl(handle);
	btrcUIKitOnMain(^{
		slider->minimum = minimum;
		slider->maximum = maximum;
		slider->value = value;
		btrcUIKitShowSlider(slider);
	});
}

BtrcShimControl* btrcShimSelectCreate(unsigned int id) { return btrcUIKitControlNew(BTRC_UIKIT_SELECT, id, "", "", false); }

void btrcShimSelectClear(BtrcShimControl* handle) {
	BtrcUIKitControl* select = btrcUIKitControl(handle);
	btrcUIKitOnMain(^{
		btrcUIKitSelectClose(select, YES, NO);
		[select->items removeAllObjects];
		[select->itemEnabled removeAllObjects];
		select->marked = -1;
	});
}

void btrcShimSelectAppend(BtrcShimControl* handle, const char* title, bool enabled) {
	BtrcUIKitControl* select = btrcUIKitControl(handle);
	NSString* item = btrcUIKitString(title);
	btrcUIKitOnMain(^{
		[select->items addObject:item];
		[select->itemEnabled addObject:@(enabled)];
	});
	[item release];
}

void btrcShimSelectShow(BtrcShimControl* handle, int selected, const char* shown, bool available) {
	BtrcUIKitControl* select = btrcUIKitControl(handle);
	NSString* text = btrcUIKitString(shown);
	btrcUIKitOnMain(^{
		select->marked = selected >= 0 && selected < (int)select->items.count ? selected : -1;
		[select->title release];
		select->title = [text copy];
		btrcUIKitShowButton(select);
		((UIButton*)select->view).enabled = available;
	});
	[text release];
}

void btrcShimSelectDismiss(BtrcShimControl* handle) {
	BtrcUIKitControl* select = btrcUIKitControl(handle);
	btrcUIKitOnMain(^{ btrcUIKitSelectClose(select, YES, NO); });
}

int btrcShimSelectNaturalWidth(BtrcShimControl* select) { return btrcShimControlNaturalWidth(select); }

BtrcShimControl* btrcShimTextCreate(unsigned int id, const char* text, const char* placeholder) { return btrcUIKitControlNew(BTRC_UIKIT_TEXT, id, text, placeholder, false); }

/* The program's own text: not an edit, so not reported. The caret goes to its end. */
void btrcShimTextSet(BtrcShimControl* handle, const char* text) {
	BtrcUIKitControl* field = btrcUIKitControl(handle);
	NSString* string = btrcUIKitString(text);
	btrcUIKitOnMain(^{
		UITextField* view = (UITextField*)field->view;
		if (![view.text isEqualToString:string]) { view.text = string; }
	});
	[string release];
}

void btrcShimTextSetPlaceholder(BtrcShimControl* handle, const char* placeholder) {
	BtrcUIKitControl* field = btrcUIKitControl(handle);
	NSString* string = btrcUIKitString(placeholder);
	btrcUIKitOnMain(^{ ((UITextField*)field->view).placeholder = string; });
	[string release];
}

BtrcShimControl* btrcShimPictureCreate(unsigned int id) { return btrcUIKitControlNew(BTRC_UIKIT_PICTURE, id, "", "", false); }

/* RGBA rows, not premultiplied; NULL shows nothing. */
void btrcShimPictureSet(BtrcShimControl* handle, const unsigned char* pixels, int width, int height) {
	BtrcUIKitControl* picture = btrcUIKitControl(handle);
	btrcUIKitOnMain(^{
		UIImage* image = nil;
		if (pixels != NULL && width > 0 && height > 0) {
			CFDataRef data = CFDataCreate(kCFAllocatorDefault, pixels, (CFIndex)width * (CFIndex)height * 4);
			CGDataProviderRef provider = data == NULL ? NULL : CGDataProviderCreateWithCFData(data);
			CGColorSpaceRef space = CGColorSpaceCreateWithName(kCGColorSpaceSRGB);
			CGImageRef bitmap = provider == NULL ? NULL : CGImageCreate((size_t)width, (size_t)height, 8u, 32u, (size_t)width * 4u, space, (CGBitmapInfo)kCGImageAlphaLast | kCGBitmapByteOrder32Big, provider, NULL, false, kCGRenderingIntentDefault);
			if (bitmap != NULL) {
				image = [UIImage imageWithCGImage:bitmap scale:1.0 orientation:UIImageOrientationUp];
				CGImageRelease(bitmap);
			}
			CGColorSpaceRelease(space);
			if (provider != NULL) { CGDataProviderRelease(provider); }
			if (data != NULL) { CFRelease(data); }
		}
		((UIImageView*)picture->view).image = image;
	});
}

BtrcShimControl* btrcShimFillCreate(unsigned int id) { return btrcUIKitControlNew(BTRC_UIKIT_FILL, id, "", "", false); }

void btrcShimFillSet(BtrcShimControl* handle, int red, int green, int blue, int alpha, double radius) {
	BtrcUIKitControl* fill = btrcUIKitControl(handle);
	btrcUIKitOnMain(^{
		fill->view.backgroundColor = [UIColor colorWithRed:(CGFloat)red / 255.0 green:(CGFloat)green / 255.0 blue:(CGFloat)blue / 255.0 alpha:(CGFloat)alpha / 255.0];
		fill->view.layer.cornerRadius = (CGFloat)radius;
	});
}

BtrcShimControl* btrcShimScrollbarCreate(unsigned int id, bool vertical) { return btrcUIKitControlNew(BTRC_UIKIT_SCROLLBAR, id, "", "", vertical); }

void btrcShimScrollbarSet(BtrcShimControl* handle, double offset, double viewport, double content) {
	BtrcUIKitControl* bar = btrcUIKitControl(handle);
	btrcUIKitOnMain(^{
		bar->offset = offset;
		bar->viewport = viewport;
		bar->content = content;
		[bar->view setNeedsDisplay];
	});
}
