#ifndef BTRC_GTK_CONTROLS_H
#define BTRC_GTK_CONTROLS_H
/* The provider's native controls: GTK widgets the shim owns, placed over a
 * window's content at the frames the provider's own layout computed. BTRC
 * holds each as an opaque handle. What a person does to one arrives as a
 * BTRC_GTK_EVENT_CONTROL_* event carrying the control's id; no callback
 * enters BTRC. A control that can have the keyboard also reports gaining and
 * losing it (BTRC_GTK_EVENT_CONTROL_FOCUS_GAINED, _LOST).
 *
 * As in GtkShim.h, every function belongs to the thread that started GTK,
 * and coordinates are the window content's logical points. */
#include "GtkShim.h"

typedef struct BtrcGtkControl BtrcGtkControl;

/* A control is made with the id its events will carry: the provider's own
 * name for the view it belongs to. */
void btrcGtkControlDestroy(BtrcGtkControl* control);
void btrcGtkControlSetEnabled(BtrcGtkControl* control, bool enabled);
/* Hover help; an empty text removes it. */
void btrcGtkControlSetToolTip(BtrcGtkControl* control, const char* text);
void btrcGtkControlSetFont(BtrcGtkControl* control, double size, bool bold);
/* The size the control takes when nothing constrains it. */
int btrcGtkControlNaturalWidth(BtrcGtkControl* control);
int btrcGtkControlNaturalHeight(BtrcGtkControl* control);
/* Its height when it is `width` wide: what wrapped text needs. */
int btrcGtkControlNaturalHeightFor(BtrcGtkControl* control, int width);

/* One placement names, back to front, every control a window shows, each
 * with its frame and the rectangle its ancestors clip it to. A control the
 * placement does not name leaves the window. */
void btrcGtkWindowBeginPlacement(BtrcGtkWindow* window);
void btrcGtkWindowPlace(BtrcGtkWindow* window, BtrcGtkControl* control, double x, double y, double width, double height, double clipX, double clipY, double clipWidth, double clipHeight);
void btrcGtkWindowEndPlacement(BtrcGtkWindow* window);

/* Draw the window's controls, as GTK draws them, over a picture of its
 * content: `pixels` is `pixelWidth` by `pixelHeight` RGBA, row after row. */
bool btrcGtkWindowDrawControls(BtrcGtkWindow* window, unsigned char* pixels, int pixelWidth, int pixelHeight);

/* A push button: BTRC_GTK_EVENT_CONTROL_ACTIVATED when it is clicked. */
BtrcGtkControl* btrcGtkButtonCreate(unsigned int id, const char* title);
void btrcGtkButtonSetTitle(BtrcGtkControl* button, const char* title);
void btrcGtkButtonSetCentered(BtrcGtkControl* button, bool centered);
/* A symbol beside the title: a square `size` points wide, drawn in the
 * title's colour from the shapes added after Begin, each in points from the
 * square's top left. A stroke of zero fills the shape. */
void btrcGtkButtonBeginSymbol(BtrcGtkControl* button, double size);
void btrcGtkButtonSymbolLine(BtrcGtkControl* button, double x0, double y0, double x1, double y1, double width);
void btrcGtkButtonSymbolTriangle(BtrcGtkControl* button, double x0, double y0, double x1, double y1, double x2, double y2);
void btrcGtkButtonSymbolRectangle(BtrcGtkControl* button, double x, double y, double width, double height, double radius, double stroke);
void btrcGtkButtonSymbolCircle(BtrcGtkControl* button, double centerX, double centerY, double radius, double stroke);
void btrcGtkButtonSetBordered(BtrcGtkControl* button, bool bordered);
void btrcGtkButtonSetSelected(BtrcGtkControl* button, bool selected);
/* A transparent button draws nothing and still takes clicks. */
void btrcGtkButtonSetTransparent(BtrcGtkControl* button, bool transparent);

/* Text. It takes no input. */
BtrcGtkControl* btrcGtkLabelCreate(unsigned int id, const char* text);
void btrcGtkLabelSetText(BtrcGtkControl* label, const char* text);
/* Secondary text is dimmer, as the theme has it. */
void btrcGtkLabelSetSecondary(BtrcGtkControl* label, bool secondary);
void btrcGtkLabelSetCentered(BtrcGtkControl* label, bool centered);
void btrcGtkLabelSetWrapping(BtrcGtkControl* label, bool wrapping);

/* A spinner: work in progress with no known end. It takes no input. */
BtrcGtkControl* btrcGtkSpinnerCreate(unsigned int id);
void btrcGtkSpinnerSetRunning(BtrcGtkControl* spinner, bool running);

/* A capacity bar from zero to one: green below `warning`, amber from it,
 * red from `critical`. It takes no input. */
BtrcGtkControl* btrcGtkLevelCreate(unsigned int id, double warning, double critical);
void btrcGtkLevelSetValue(BtrcGtkControl* level, double value);

/* A horizontal slider. It shows the value it is given and never changes it
 * itself: BTRC_GTK_EVENT_CONTROL_SLIDER_PRESSED and _RELEASED bracket a
 * drag, _CHANGED says how the person asked for another value, and
 * _CANCELLED that Escape gave a drag up. */
BtrcGtkControl* btrcGtkSliderCreate(unsigned int id);
void btrcGtkSliderSet(BtrcGtkControl* slider, double minimum, double maximum, double step, double value);
#endif
