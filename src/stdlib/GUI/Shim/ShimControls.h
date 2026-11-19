#ifndef BTRC_SHIM_CONTROLS_H
#define BTRC_SHIM_CONTROLS_H
/* The provider's native controls: GTK widgets the shim owns, placed over a
 * window's content at the frames the provider's own layout computed. BTRC
 * holds each as an opaque handle. What a person does to one arrives as a
 * BTRC_SHIM_EVENT_CONTROL_* event carrying the control's id; no callback
 * enters BTRC. A control that can have the keyboard also reports gaining and
 * losing it (BTRC_SHIM_EVENT_CONTROL_FOCUS_GAINED, _LOST).
 *
 * As in GtkShim.h, every function belongs to the thread that started GTK,
 * and coordinates are the window content's logical points. */
#include "Shim.h"

typedef struct BtrcShimControl BtrcShimControl;

/* A control is made with the id its events will carry: the provider's own
 * name for the view it belongs to. */
void btrcShimControlDestroy(BtrcShimControl* control);
void btrcShimControlSetEnabled(BtrcShimControl* control, bool enabled);
/* Hover help; an empty text removes it. */
void btrcShimControlSetToolTip(BtrcShimControl* control, const char* text);
void btrcShimControlSetFont(BtrcShimControl* control, double size, bool bold);
/* The size the control takes when nothing constrains it. */
int btrcShimControlNaturalWidth(BtrcShimControl* control);
int btrcShimControlNaturalHeight(BtrcShimControl* control);
/* Its height when it is `width` wide: what wrapped text needs. */
int btrcShimControlNaturalHeightFor(BtrcShimControl* control, int width);

/* One placement names, back to front, every control a window shows, each
 * with its frame and the rectangle its ancestors clip it to. A control the
 * placement does not name leaves the window. */
void btrcShimWindowBeginPlacement(BtrcShimWindow* window);
void btrcShimWindowPlace(BtrcShimWindow* window, BtrcShimControl* control, double x, double y, double width, double height, double clipX, double clipY, double clipWidth, double clipHeight);
/* A hole in the placement: a rectangle where the provider's drawn content
 * (a GPU view) shows through every control placed before it, and under
 * every control placed after. */
void btrcShimWindowPlaceHole(BtrcShimWindow* window, double x, double y, double width, double height, double clipX, double clipY, double clipWidth, double clipHeight);
void btrcShimWindowEndPlacement(BtrcShimWindow* window);

/* Draw the window's controls, as GTK draws them, over a picture of its
 * content: `pixels` is `pixelWidth` by `pixelHeight` RGBA, row after row. */
bool btrcShimWindowDrawControls(BtrcShimWindow* window, unsigned char* pixels, int pixelWidth, int pixelHeight);

/* A push button: BTRC_SHIM_EVENT_CONTROL_ACTIVATED when it is clicked. */
BtrcShimControl* btrcShimButtonCreate(unsigned int id, const char* title);
void btrcShimButtonSetTitle(BtrcShimControl* button, const char* title);
void btrcShimButtonSetCentered(BtrcShimControl* button, bool centered);
/* A symbol beside the title: a square `size` points wide, drawn in the
 * title's colour from the shapes added after Begin, each in points from the
 * square's top left. A stroke of zero fills the shape. */
void btrcShimButtonBeginSymbol(BtrcShimControl* button, double size);
void btrcShimButtonSymbolLine(BtrcShimControl* button, double x0, double y0, double x1, double y1, double width);
void btrcShimButtonSymbolTriangle(BtrcShimControl* button, double x0, double y0, double x1, double y1, double x2, double y2);
void btrcShimButtonSymbolRectangle(BtrcShimControl* button, double x, double y, double width, double height, double radius, double stroke);
void btrcShimButtonSymbolCircle(BtrcShimControl* button, double centerX, double centerY, double radius, double stroke);
void btrcShimButtonSetBordered(BtrcShimControl* button, bool bordered);
void btrcShimButtonSetSelected(BtrcShimControl* button, bool selected);
/* A transparent button draws nothing and still takes clicks. */
void btrcShimButtonSetTransparent(BtrcShimControl* button, bool transparent);

/* Text. It takes no input. */
BtrcShimControl* btrcShimLabelCreate(unsigned int id, const char* text);
void btrcShimLabelSetText(BtrcShimControl* label, const char* text);
/* Secondary text is dimmer, as the theme has it. */
void btrcShimLabelSetSecondary(BtrcShimControl* label, bool secondary);
void btrcShimLabelSetCentered(BtrcShimControl* label, bool centered);
void btrcShimLabelSetWrapping(BtrcShimControl* label, bool wrapping);

/* A spinner: work in progress with no known end. It takes no input. */
BtrcShimControl* btrcShimSpinnerCreate(unsigned int id);
void btrcShimSpinnerSetRunning(BtrcShimControl* spinner, bool running);

/* A capacity bar from zero to one: green below `warning`, amber from it,
 * red from `critical`. It takes no input. */
BtrcShimControl* btrcShimLevelCreate(unsigned int id, double warning, double critical);
void btrcShimLevelSetValue(BtrcShimControl* level, double value);

/* A horizontal slider. It shows the value it is given and never changes it
 * itself: BTRC_SHIM_EVENT_CONTROL_SLIDER_PRESSED and _RELEASED bracket a
 * drag, _CHANGED says how the person asked for another value, and
 * _CANCELLED that Escape gave a drag up. */
BtrcShimControl* btrcShimSliderCreate(unsigned int id);
void btrcShimSliderSet(BtrcShimControl* slider, double minimum, double maximum, double step, double value);

/* A select: a button showing one text that opens a list of items. It never
 * changes what it shows itself. BTRC_SHIM_EVENT_CONTROL_SELECT_OPENED says a
 * person opened the list, _CANDIDATE which item a choice would now take,
 * _CHOSEN which item was chosen, and _DISMISSED that the list closed
 * without a choice. Dismiss closes an open list. */
BtrcShimControl* btrcShimSelectCreate(unsigned int id);
void btrcShimSelectClear(BtrcShimControl* select);
void btrcShimSelectAppend(BtrcShimControl* select, const char* title, bool enabled);
/* The item marked in the list (-1 for none), the text on the button, and
 * whether the list can be opened. */
void btrcShimSelectShow(BtrcShimControl* select, int selected, const char* shown, bool available);
void btrcShimSelectDismiss(BtrcShimControl* select);
/* Wide enough for the longest item, not only the one shown. */
int btrcShimSelectNaturalWidth(BtrcShimControl* select);

/* A one-line text field. GTK owns the editing.
 * BTRC_SHIM_EVENT_CONTROL_TEXT_CHANGED carries the text as a person's edit
 * left it, _ACTIVATED says Return was pressed, _ESCAPED that Escape was.
 * Set is the program's own text and is not reported back. */
BtrcShimControl* btrcShimTextCreate(unsigned int id, const char* text, const char* placeholder);
void btrcShimTextSet(BtrcShimControl* field, const char* text);
void btrcShimTextSetPlaceholder(BtrcShimControl* field, const char* placeholder);

/* A picture, shown whole and undistorted in whatever frame it is given.
 * `pixels` is `width` by `height` RGBA, copied; NULL shows nothing. It takes
 * no input. */
BtrcShimControl* btrcShimPictureCreate(unsigned int id);
void btrcShimPictureSet(BtrcShimControl* picture, const unsigned char* pixels, int width, int height);

/* A fill: one colour (each part 0 to 255) in the control's frame, with
 * rounded corners. It takes no input. */
BtrcShimControl* btrcShimFillCreate(unsigned int id);
void btrcShimFillSet(BtrcShimControl* fill, int red, int green, int blue, int alpha, double radius);

/* A scroll bar for a view the provider scrolls itself. Set says where the
 * view is: `offset` into a document `content` long, of which `viewport`
 * shows. BTRC_SHIM_EVENT_CONTROL_SCROLLBAR_CHANGED says where a person moved
 * it to. */
BtrcShimControl* btrcShimScrollbarCreate(unsigned int id, bool vertical);
void btrcShimScrollbarSet(BtrcShimControl* bar, double offset, double viewport, double content);
#endif
