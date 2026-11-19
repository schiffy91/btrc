/* The Win32 shim's controls; ../Shim/ShimControls.h is the contract.
 *
 * A control is a child window of the window it is placed in, above the
 * content window. Until it is placed, and after it leaves, it lives in a
 * hidden window of the shim's own. Its frame is its window's; the rectangle
 * its ancestors clip it to, and the holes placed after it, are its window
 * region. Every control's messages pass through one procedure that queues
 * what the mouse and keyboard did for the window, and what a person did to
 * the control for the control. */
#include "Win32ShimPrivate.h"

#include <uxtheme.h>
#include <windowsx.h>

enum BtrcWinKind {
	BTRC_WIN_BUTTON = 1,
	BTRC_WIN_LABEL,
	BTRC_WIN_SPINNER,
	BTRC_WIN_LEVEL,
	BTRC_WIN_SLIDER,
	BTRC_WIN_SELECT,
	BTRC_WIN_TEXT,
	BTRC_WIN_PICTURE,
	BTRC_WIN_FILL,
	BTRC_WIN_SCROLLBAR,
	/* A window another source file fills (Win32Web.c). */
	BTRC_WIN_HOSTED
};

enum { BTRC_WIN_SHAPE_LINE = 1, BTRC_WIN_SHAPE_TRIANGLE, BTRC_WIN_SHAPE_RECTANGLE, BTRC_WIN_SHAPE_CIRCLE };

typedef struct BtrcWinShape {
	int kind;
	double a, b, c, d, e, f;
} BtrcWinShape;

struct BtrcShimControl {
	unsigned int id;
	int kind;
	HWND handle;
	BtrcShimWindow* window;
	HFONT font;
	bool silent;
	/* Placement: the frame and clip in device pixels, the place in the
	 * order, and what the window region was last made from. */
	BtrcShimControl* nextPlaced;
	bool placed;
	int order;
	RECT frame;
	RECT clip;
	RECT shownFrame;
	unsigned long shape;
	bool shownOnce;
	/* A button. */
	bool chosen;
	bool bordered;
	bool transparent;
	double symbolSize;
	BtrcWinShape* shapes;
	int shapeCount;
	/* A label. */
	bool secondary;
	/* A level. */
	double warning;
	double critical;
	/* A slider. */
	double minimum;
	double maximum;
	double step;
	double value;
	bool dragging;
	/* A select. */
	int selected;
	bool* enabledItems;
	int itemCount;
	bool closing;
	/* A picture: RGBA rows. */
	unsigned char* pixels;
	int pixelWidth;
	int pixelHeight;
	/* A fill. */
	int red, green, blue, alpha;
	double radius;
	/* A hosted window: what its owner keeps for it, and how that is let go. */
	void* extension;
	void (*release)(void* extension);
	/* A scroll bar. */
	bool vertical;
	double offset;
	double viewport;
	double content;
};

static HWND btrcWinNursery;
static HWND btrcWinToolTips;
static HFONT btrcWinDefaultFont;

static double btrcWinControlScale(const BtrcShimControl* control) {
	if (control->window != NULL) { return btrcWinScale(control->window->handle); }
	UINT dpi = GetDpiForSystem();
	return dpi == 0u ? 1.0 : (double)dpi / 96.0;
}

static void btrcWinControlPush(BtrcShimControl* control, unsigned int type, int data, double value, const char* text) {
	BtrcShimEvent event;
	memset(&event, 0, sizeof event);
	event.type = type;
	event.window = control->window == NULL ? 0u : control->window->id;
	event.control = control->id;
	event.data1 = data;
	event.value = value;
	btrcWinPush(&event, text);
}

static BtrcShimControl* btrcWinControlOf(HWND handle) { return handle == NULL ? NULL : (BtrcShimControl*)GetPropW(handle, L"BtrcShimControl"); }

static HFONT btrcWinFont(double size, bool bold, double scale) {
	NONCLIENTMETRICSW metrics;
	memset(&metrics, 0, sizeof metrics);
	metrics.cbSize = sizeof metrics;
	LOGFONTW font;
	if (SystemParametersInfoW(SPI_GETNONCLIENTMETRICS, sizeof metrics, &metrics, 0u)) { font = metrics.lfMessageFont; }
	else { memset(&font, 0, sizeof font); lstrcpynW(font.lfFaceName, L"Segoe UI", LF_FACESIZE); font.lfHeight = -12; }
	if (size > 0.0) { font.lfHeight = -(LONG)(size * scale + 0.5); }
	font.lfWeight = bold ? FW_BOLD : FW_NORMAL;
	return CreateFontIndirectW(&font);
}

static HFONT btrcWinControlFont(const BtrcShimControl* control) {
	if (control->font != NULL) { return control->font; }
	if (btrcWinDefaultFont == NULL) { btrcWinDefaultFont = btrcWinFont(0.0, false, 1.0); }
	return btrcWinDefaultFont;
}

static wchar_t* btrcWinControlText(HWND handle) {
	int length = GetWindowTextLengthW(handle);
	wchar_t* text = malloc(((size_t)length + 1u) * sizeof *text);
	if (text != NULL) { text[0] = L'\0'; GetWindowTextW(handle, text, length + 1); }
	return text;
}

/* The size a text needs in the control's font, in device pixels: on one
 * line, or wrapped to `width` when that is positive. */
static SIZE btrcWinMeasure(const BtrcShimControl* control, const wchar_t* text, int width) {
	SIZE size = {0, 0};
	HDC screen = GetDC(NULL);
	HGDIOBJ previous = SelectObject(screen, btrcWinControlFont(control));
	RECT bounds = {0, 0, width > 0 ? width : 0, 0};
	DrawTextW(screen, text[0] == L'\0' ? L" " : text, -1, &bounds, DT_CALCRECT | DT_NOPREFIX | (width > 0 ? DT_WORDBREAK : DT_SINGLELINE));
	size.cx = text[0] == L'\0' ? 0 : bounds.right - bounds.left;
	size.cy = bounds.bottom - bounds.top;
	SelectObject(screen, previous);
	ReleaseDC(NULL, screen);
	return size;
}

/* A slider's value at a pointer position along its channel. */
static double btrcWinSliderAt(const BtrcShimControl* slider, int x) {
	RECT channel;
	RECT thumb;
	SendMessageW(slider->handle, TBM_GETCHANNELRECT, 0u, (LPARAM)&channel);
	SendMessageW(slider->handle, TBM_GETTHUMBRECT, 0u, (LPARAM)&thumb);
	int half = (thumb.right - thumb.left) / 2;
	int left = channel.left + half;
	int right = channel.right - half;
	double fraction = right > left ? (double)(x - left) / (double)(right - left) : 0.0;
	if (fraction < 0.0) { fraction = 0.0; }
	if (fraction > 1.0) { fraction = 1.0; }
	return slider->minimum + fraction * (slider->maximum - slider->minimum);
}

static void btrcWinSliderShow(BtrcShimControl* slider) {
	double span = slider->maximum - slider->minimum;
	LPARAM position = span > 0.0 ? (LPARAM)((slider->value - slider->minimum) / span * 10000.0 + 0.5) : 0;
	SendMessageW(slider->handle, TBM_SETPOS, TRUE, position);
}

static void btrcWinDrawShapes(const BtrcShimControl* button, HDC drawing, double originX, double originY, double scale, COLORREF colour) {
	HBRUSH fill = CreateSolidBrush(colour);
	for (int index = 0; index < button->shapeCount; index++) {
		const BtrcWinShape* shape = &button->shapes[index];
		double stroke = shape->kind == BTRC_WIN_SHAPE_LINE ? shape->e : shape->kind == BTRC_WIN_SHAPE_RECTANGLE ? shape->f : shape->kind == BTRC_WIN_SHAPE_CIRCLE ? shape->d : 0.0;
		int width = (int)(stroke * scale + 0.5);
		HPEN pen = stroke > 0.0 ? CreatePen(PS_SOLID | PS_ENDCAP_ROUND, width < 1 ? 1 : width, colour) : (HPEN)GetStockObject(NULL_PEN);
		HGDIOBJ previousPen = SelectObject(drawing, pen);
		HGDIOBJ previousBrush = SelectObject(drawing, stroke > 0.0 && shape->kind != BTRC_WIN_SHAPE_LINE ? GetStockObject(NULL_BRUSH) : fill);
		int ax = (int)(originX + shape->a * scale + 0.5);
		int ay = (int)(originY + shape->b * scale + 0.5);
		int cx = (int)(originX + shape->c * scale + 0.5);
		int cy = (int)(originY + shape->d * scale + 0.5);
		switch (shape->kind) {
		case BTRC_WIN_SHAPE_LINE:
			MoveToEx(drawing, ax, ay, NULL);
			LineTo(drawing, cx, cy);
			break;
		case BTRC_WIN_SHAPE_TRIANGLE: {
			POINT points[3] = {{ax, ay}, {cx, cy}, {(int)(originX + shape->e * scale + 0.5), (int)(originY + shape->f * scale + 0.5)}};
			Polygon(drawing, points, 3);
			break;
		}
		case BTRC_WIN_SHAPE_RECTANGLE: {
			int corner = (int)(shape->e * scale * 2.0 + 0.5);
			RoundRect(drawing, ax, ay, (int)(originX + (shape->a + shape->c) * scale + 0.5) + 1, (int)(originY + (shape->b + shape->d) * scale + 0.5) + 1, corner, corner);
			break;
		}
		case BTRC_WIN_SHAPE_CIRCLE: {
			int radius = (int)(shape->c * scale + 0.5);
			Ellipse(drawing, ax - radius, ay - radius, ax + radius + 1, ay + radius + 1);
			break;
		}
		default: break;
		}
		SelectObject(drawing, previousBrush);
		SelectObject(drawing, previousPen);
		if (stroke > 0.0) { DeleteObject(pen); }
	}
	DeleteObject(fill);
}

static COLORREF btrcWinTextColour(void) { return btrcWinIsDark() ? RGB(240, 240, 240) : GetSysColor(COLOR_BTNTEXT); }

/* What a fill shows where it is not opaque: its colour over the window's. */
static COLORREF btrcWinFillColour(const BtrcShimControl* fill) {
	COLORREF under = btrcWinIsDark() ? RGB(30, 30, 33) : RGB(238, 238, 240);
	int alpha = fill->alpha;
	int red = (fill->red * alpha + GetRValue(under) * (255 - alpha) + 127) / 255;
	int green = (fill->green * alpha + GetGValue(under) * (255 - alpha) + 127) / 255;
	int blue = (fill->blue * alpha + GetBValue(under) * (255 - alpha) + 127) / 255;
	return RGB(red, green, blue);
}

/* The rectangle a picture is shown in: whole, undistorted, centred. */
static RECT btrcWinPictureArea(const BtrcShimControl* picture, int width, int height) {
	RECT area = {0, 0, 0, 0};
	if (picture->pixels == NULL || picture->pixelWidth <= 0 || picture->pixelHeight <= 0 || width <= 0 || height <= 0) { return area; }
	double fit = (double)width / (double)picture->pixelWidth;
	if ((double)height / (double)picture->pixelHeight < fit) { fit = (double)height / (double)picture->pixelHeight; }
	int shownWidth = (int)((double)picture->pixelWidth * fit + 0.5);
	int shownHeight = (int)((double)picture->pixelHeight * fit + 0.5);
	area.left = (width - shownWidth) / 2;
	area.top = (height - shownHeight) / 2;
	area.right = area.left + shownWidth;
	area.bottom = area.top + shownHeight;
	return area;
}

static void btrcWinPaintDrawn(BtrcShimControl* control, HDC drawing) {
	RECT client;
	GetClientRect(control->handle, &client);
	if (control->kind == BTRC_WIN_FILL) {
		HBRUSH brush = CreateSolidBrush(btrcWinFillColour(control));
		FillRect(drawing, &client, brush);
		DeleteObject(brush);
		return;
	}
	FillRect(drawing, &client, btrcWinBackgroundBrush());
	RECT area = btrcWinPictureArea(control, client.right, client.bottom);
	if (area.right <= area.left) { return; }
	/* GDI wants BGRA rows; over the window's colour where a pixel is not opaque. */
	size_t count = (size_t)control->pixelWidth * (size_t)control->pixelHeight;
	unsigned char* rows = malloc(count * 4u);
	if (rows == NULL) { return; }
	COLORREF under = btrcWinIsDark() ? RGB(30, 30, 33) : RGB(238, 238, 240);
	for (size_t index = 0; index < count; index++) {
		const unsigned char* pixel = control->pixels + index * 4u;
		unsigned int alpha = pixel[3];
		rows[index * 4u] = (unsigned char)((pixel[2] * alpha + GetBValue(under) * (255u - alpha) + 127u) / 255u);
		rows[index * 4u + 1u] = (unsigned char)((pixel[1] * alpha + GetGValue(under) * (255u - alpha) + 127u) / 255u);
		rows[index * 4u + 2u] = (unsigned char)((pixel[0] * alpha + GetRValue(under) * (255u - alpha) + 127u) / 255u);
		rows[index * 4u + 3u] = 255u;
	}
	BITMAPINFO info;
	memset(&info, 0, sizeof info);
	info.bmiHeader.biSize = sizeof info.bmiHeader;
	info.bmiHeader.biWidth = control->pixelWidth;
	info.bmiHeader.biHeight = -control->pixelHeight;
	info.bmiHeader.biPlanes = 1;
	info.bmiHeader.biBitCount = 32;
	info.bmiHeader.biCompression = BI_RGB;
	SetStretchBltMode(drawing, HALFTONE);
	StretchDIBits(drawing, area.left, area.top, area.right - area.left, area.bottom - area.top, 0, 0, control->pixelWidth, control->pixelHeight, rows, &info, DIB_RGB_COLORS, SRCCOPY);
	free(rows);
}

/* A window class for what the shim draws itself: a fill and a picture.
 * Neither takes input: what falls on one falls on what is under it. */
static LRESULT CALLBACK btrcWinDrawnProcedure(HWND handle, UINT message, WPARAM wide, LPARAM value) {
	BtrcShimControl* control = btrcWinControlOf(handle);
	switch (message) {
	case WM_NCHITTEST: return HTTRANSPARENT;
	case WM_ERASEBKGND: return 1;
	case WM_PAINT: {
		PAINTSTRUCT paint;
		HDC drawing = BeginPaint(handle, &paint);
		if (control != NULL) { btrcWinPaintDrawn(control, drawing); }
		EndPaint(handle, &paint);
		return 0;
	}
	case WM_PRINTCLIENT:
		if (control != NULL) { btrcWinPaintDrawn(control, (HDC)wide); }
		return 0;
	default: return DefWindowProcW(handle, message, wide, value);
	}
}

/* Controls that are in no window still need a parent, and still send it
 * their notifications. */
static LRESULT CALLBACK btrcWinNurseryProcedure(HWND handle, UINT message, WPARAM wide, LPARAM value) {
	LRESULT result = 0;
	if (btrcWinControlMessage(NULL, handle, message, wide, value, &result)) { return result; }
	return DefWindowProcW(handle, message, wide, value);
}

bool btrcWinRegisterControls(void) {
	WNDCLASSEXW drawn;
	memset(&drawn, 0, sizeof drawn);
	drawn.cbSize = sizeof drawn;
	drawn.lpfnWndProc = btrcWinDrawnProcedure;
	drawn.hInstance = btrcWinModule();
	drawn.lpszClassName = L"BtrcShimDrawn";
	WNDCLASSEXW nursery = drawn;
	nursery.lpfnWndProc = btrcWinNurseryProcedure;
	nursery.lpszClassName = L"BtrcShimNursery";
	if (!RegisterClassExW(&drawn) || !RegisterClassExW(&nursery)) { return false; }
	btrcWinNursery = CreateWindowExW(0u, L"BtrcShimNursery", L"", WS_OVERLAPPED, 0, 0, 0, 0, NULL, NULL, btrcWinModule(), NULL);
	return btrcWinNursery != NULL;
}

static void btrcWinSelectRestore(BtrcShimControl* select) { SendMessageW(select->handle, CB_SETCURSEL, (WPARAM)select->selected, 0); }

bool btrcWinControlMessage(BtrcShimWindow* window, HWND handle, UINT message, WPARAM wide, LPARAM value, LRESULT* result) {
	(void)handle;
	switch (message) {
	case WM_COMMAND: {
		BtrcShimControl* control = btrcWinControlOf((HWND)value);
		if (control == NULL) { return false; }
		unsigned int code = HIWORD(wide);
		if (control->kind == BTRC_WIN_BUTTON && code == BN_CLICKED) { btrcWinControlPush(control, BTRC_SHIM_EVENT_CONTROL_ACTIVATED, 0, 0.0, NULL); }
		else if (control->kind == BTRC_WIN_TEXT && code == EN_CHANGE && !control->silent) {
			wchar_t* wideText = btrcWinControlText(control->handle);
			char* text = btrcWinNarrow(wideText);
			btrcWinControlPush(control, BTRC_SHIM_EVENT_CONTROL_TEXT_CHANGED, 0, 0.0, text);
			free(text);
			free(wideText);
		} else if (control->kind == BTRC_WIN_SELECT) {
			int current = (int)SendMessageW(control->handle, CB_GETCURSEL, 0u, 0);
			bool open = SendMessageW(control->handle, CB_GETDROPPEDSTATE, 0u, 0) != 0;
			if (code == CBN_DROPDOWN) { control->closing = false; btrcWinControlPush(control, BTRC_SHIM_EVENT_CONTROL_SELECT_OPENED, 0, 0.0, NULL); }
			else if (code == CBN_SELENDOK) {
				control->closing = true;
				bool allowed = current >= 0 && current < control->itemCount && control->enabledItems[current];
				btrcWinControlPush(control, allowed ? BTRC_SHIM_EVENT_CONTROL_SELECT_CHOSEN : BTRC_SHIM_EVENT_CONTROL_SELECT_DISMISSED, allowed ? current : 0, 0.0, NULL);
			} else if (code == CBN_SELENDCANCEL) {
				control->closing = true;
				btrcWinControlPush(control, BTRC_SHIM_EVENT_CONTROL_SELECT_DISMISSED, GetKeyState(VK_ESCAPE) < 0 ? 1 : 0, 0.0, NULL);
			} else if (code == CBN_CLOSEUP) { btrcWinSelectRestore(control); }
			else if (code == CBN_SELCHANGE) {
				if (open && !control->closing) { btrcWinControlPush(control, BTRC_SHIM_EVENT_CONTROL_SELECT_CANDIDATE, current, 0.0, NULL); }
				else if (!control->closing) {
					/* An arrow key on a closed select chooses at once. */
					if (current >= 0 && current < control->itemCount && control->enabledItems[current]) { btrcWinControlPush(control, BTRC_SHIM_EVENT_CONTROL_SELECT_CHOSEN, current, 0.0, NULL); }
					btrcWinSelectRestore(control);
				} else { control->closing = false; btrcWinSelectRestore(control); }
			}
		}
		*result = 0;
		return true;
	}
	case WM_HSCROLL:
	case WM_VSCROLL: {
		BtrcShimControl* control = btrcWinControlOf((HWND)value);
		if (control == NULL || control->kind != BTRC_WIN_SCROLLBAR) { return false; }
		SCROLLINFO info;
		memset(&info, 0, sizeof info);
		info.cbSize = sizeof info;
		info.fMask = SIF_ALL;
		GetScrollInfo(control->handle, SB_CTL, &info);
		double target = control->offset;
		switch (LOWORD(wide)) {
		case SB_LINEUP: target -= 40.0; break;
		case SB_LINEDOWN: target += 40.0; break;
		case SB_PAGEUP: target -= control->viewport; break;
		case SB_PAGEDOWN: target += control->viewport; break;
		case SB_THUMBTRACK:
		case SB_THUMBPOSITION: target = (double)info.nTrackPos; break;
		case SB_TOP: target = 0.0; break;
		case SB_BOTTOM: target = control->content - control->viewport; break;
		default: *result = 0; return true;
		}
		double furthest = control->content - control->viewport;
		if (target > furthest) { target = furthest; }
		if (target < 0.0) { target = 0.0; }
		btrcWinControlPush(control, BTRC_SHIM_EVENT_CONTROL_SCROLLBAR_CHANGED, control->vertical ? 1 : 0, target, NULL);
		*result = 0;
		return true;
	}
	case WM_CTLCOLORSTATIC:
	case WM_CTLCOLORBTN: {
		BtrcShimControl* control = btrcWinControlOf((HWND)value);
		if (control == NULL) { return false; }
		HDC drawing = (HDC)wide;
		SetBkMode(drawing, TRANSPARENT);
		SetTextColor(drawing, control->secondary ? GetSysColor(COLOR_GRAYTEXT) : btrcWinTextColour());
		*result = (LRESULT)btrcWinBackgroundBrush();
		return true;
	}
	case WM_NOTIFY: {
		const NMHDR* header = (const NMHDR*)value;
		BtrcShimControl* control = btrcWinControlOf(header->hwndFrom);
		if (control == NULL || control->kind != BTRC_WIN_BUTTON || header->code != NM_CUSTOMDRAW) { return false; }
		const NMCUSTOMDRAW* draw = (const NMCUSTOMDRAW*)value;
		if (draw->dwDrawStage == CDDS_PREERASE && (control->transparent || !control->bordered)) {
			/* An unbordered button is its title and symbol alone; a
			 * transparent one is nothing at all. */
			if (!control->transparent) {
				RECT client = draw->rc;
				FillRect(draw->hdc, &client, btrcWinBackgroundBrush());
				wchar_t* title = btrcWinControlText(control->handle);
				HGDIOBJ previous = SelectObject(draw->hdc, btrcWinControlFont(control));
				SetBkMode(draw->hdc, TRANSPARENT);
				SetTextColor(draw->hdc, IsWindowEnabled(control->handle) ? btrcWinTextColour() : GetSysColor(COLOR_GRAYTEXT));
				double scale = btrcWinControlScale(control);
				RECT text = client;
				text.left += (LONG)(control->symbolSize > 0.0 ? (control->symbolSize + 8.0) * scale : 0.0);
				bool left = (GetWindowLongPtrW(control->handle, GWL_STYLE) & BS_LEFT) != 0;
				if (title != NULL) { DrawTextW(draw->hdc, title, -1, &text, DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX | (left ? DT_LEFT : DT_CENTER)); }
				SelectObject(draw->hdc, previous);
				free(title);
				if (control->shapeCount > 0) { btrcWinDrawShapes(control, draw->hdc, 4.0 * scale, ((double)(client.bottom - client.top) - control->symbolSize * scale) / 2.0, scale, btrcWinTextColour()); }
			}
			*result = CDRF_SKIPDEFAULT;
			return true;
		}
		if (draw->dwDrawStage == CDDS_PREPAINT && control->shapeCount > 0) { *result = CDRF_NOTIFYPOSTPAINT; return true; }
		if (draw->dwDrawStage == CDDS_POSTPAINT && control->shapeCount > 0) {
			double scale = btrcWinControlScale(control);
			RECT client = draw->rc;
			bool alone = GetWindowTextLengthW(control->handle) == 0;
			double x = alone ? ((double)(client.right - client.left) - control->symbolSize * scale) / 2.0 : 8.0 * scale;
			btrcWinDrawShapes(control, draw->hdc, x, ((double)(client.bottom - client.top) - control->symbolSize * scale) / 2.0, scale, IsWindowEnabled(control->handle) ? btrcWinTextColour() : GetSysColor(COLOR_GRAYTEXT));
		}
		*result = CDRF_DODEFAULT;
		return true;
	}
	default:
		(void)window;
		return false;
	}
}

/* Every control's messages. */
static LRESULT CALLBACK btrcWinControlProcedure(HWND handle, UINT message, WPARAM wide, LPARAM value, UINT_PTR subclass, DWORD_PTR data) {
	BtrcShimControl* control = (BtrcShimControl*)data;
	(void)subclass;
	btrcWinCount();
	if (message == WM_NCDESTROY) {
		RemoveWindowSubclass(handle, btrcWinControlProcedure, 1u);
		return DefSubclassProc(handle, message, wide, value);
	}
	if (control->window != NULL) { btrcWinObserve(control->window, handle, message, wide, value); }
	switch (message) {
	case WM_SETFOCUS: btrcWinControlPush(control, BTRC_SHIM_EVENT_CONTROL_FOCUS_GAINED, 0, 0.0, NULL); break;
	case WM_KILLFOCUS:
		if (control->dragging) { control->dragging = false; ReleaseCapture(); btrcWinControlPush(control, BTRC_SHIM_EVENT_CONTROL_SLIDER_CANCELLED, 0, 0.0, NULL); }
		btrcWinControlPush(control, BTRC_SHIM_EVENT_CONTROL_FOCUS_LOST, 0, 0.0, NULL);
		break;
	case WM_MOUSEWHEEL:
	case WM_MOUSEHWHEEL:
		/* The wheel scrolls the view under the pointer, which the provider
		 * decides: a control does not take it for itself. */
		return 0;
	default: break;
	}
	if (control->kind == BTRC_WIN_TEXT) {
		if (message == WM_KEYDOWN && wide == VK_RETURN) { btrcWinControlPush(control, BTRC_SHIM_EVENT_CONTROL_TEXT_ACTIVATED, 0, 0.0, NULL); return 0; }
		if (message == WM_KEYDOWN && wide == VK_ESCAPE) { btrcWinControlPush(control, BTRC_SHIM_EVENT_CONTROL_TEXT_ESCAPED, 0, 0.0, NULL); return 0; }
		/* The characters those two keys also send would only make the field beep. */
		if (message == WM_CHAR && (wide == L'\r' || wide == 27 || wide == L'\t')) { return 0; }
	}
	if (control->kind == BTRC_WIN_SLIDER) {
		/* The slider shows the value it is given and never changes it
		 * itself, so the mouse and keys are the shim's to read. */
		switch (message) {
		case WM_LBUTTONDOWN:
			SetFocus(handle);
			SetCapture(handle);
			control->dragging = true;
			btrcWinControlPush(control, BTRC_SHIM_EVENT_CONTROL_SLIDER_PRESSED, 0, 0.0, NULL);
			btrcWinControlPush(control, BTRC_SHIM_EVENT_CONTROL_SLIDER_CHANGED, BTRC_SHIM_SLIDER_JUMP, btrcWinSliderAt(control, GET_X_LPARAM(value)), NULL);
			return 0;
		case WM_MOUSEMOVE:
			if (control->dragging) { btrcWinControlPush(control, BTRC_SHIM_EVENT_CONTROL_SLIDER_CHANGED, BTRC_SHIM_SLIDER_JUMP, btrcWinSliderAt(control, GET_X_LPARAM(value)), NULL); }
			return 0;
		case WM_LBUTTONUP:
			if (control->dragging) { control->dragging = false; ReleaseCapture(); btrcWinControlPush(control, BTRC_SHIM_EVENT_CONTROL_SLIDER_RELEASED, 0, 0.0, NULL); }
			return 0;
		case WM_CAPTURECHANGED:
			if (control->dragging) { control->dragging = false; btrcWinControlPush(control, BTRC_SHIM_EVENT_CONTROL_SLIDER_CANCELLED, 0, 0.0, NULL); }
			break;
		case WM_KEYDOWN: {
			int change = -1;
			if (wide == VK_ESCAPE && control->dragging) { control->dragging = false; ReleaseCapture(); btrcWinControlPush(control, BTRC_SHIM_EVENT_CONTROL_SLIDER_CANCELLED, 0, 0.0, NULL); return 0; }
			if (wide == VK_LEFT || wide == VK_DOWN) { change = BTRC_SHIM_SLIDER_STEP_BACKWARD; }
			else if (wide == VK_RIGHT || wide == VK_UP) { change = BTRC_SHIM_SLIDER_STEP_FORWARD; }
			else if (wide == VK_PRIOR) { change = BTRC_SHIM_SLIDER_PAGE_FORWARD; }
			else if (wide == VK_NEXT) { change = BTRC_SHIM_SLIDER_PAGE_BACKWARD; }
			else if (wide == VK_HOME) { change = BTRC_SHIM_SLIDER_START; }
			else if (wide == VK_END) { change = BTRC_SHIM_SLIDER_END; }
			if (change >= 0) { btrcWinControlPush(control, BTRC_SHIM_EVENT_CONTROL_SLIDER_CHANGED, change, control->value, NULL); return 0; }
			break;
		}
		case WM_LBUTTONDBLCLK:
		case WM_KEYUP: return 0;
		default: break;
		}
	}
	/* Return presses the button that has the keyboard, as Space does. */
	if (control->kind == BTRC_WIN_BUTTON && message == WM_KEYDOWN && wide == VK_RETURN) { SendMessageW(handle, BM_CLICK, 0u, 0); return 0; }
	if (control->kind == BTRC_WIN_BUTTON && control->transparent && (message == WM_PAINT || message == WM_ERASEBKGND)) {
		if (message == WM_PAINT) { ValidateRect(handle, NULL); return 0; }
		return 1;
	}
	LRESULT result = DefSubclassProc(handle, message, wide, value);
	if (control->kind == BTRC_WIN_BUTTON && control->chosen && (message == WM_LBUTTONUP || message == WM_KEYUP || message == WM_KILLFOCUS || message == WM_MOUSELEAVE || message == WM_CAPTURECHANGED)) {
		SendMessageW(handle, BM_SETSTATE, TRUE, 0);
	}
	return result;
}

static BtrcShimControl* btrcWinControlNew(unsigned int id, int kind, const wchar_t* class, const wchar_t* text, DWORD style, DWORD extended) {
	BtrcShimControl* control = calloc(1, sizeof *control);
	if (control == NULL) { return NULL; }
	control->id = id;
	control->kind = kind;
	control->bordered = true;
	control->selected = -1;
	control->handle = CreateWindowExW(extended, class, text, WS_CHILD | WS_CLIPSIBLINGS | style, 0, 0, 0, 0, btrcWinNursery, NULL, btrcWinModule(), NULL);
	if (control->handle == NULL) { free(control); return NULL; }
	SetPropW(control->handle, L"BtrcShimControl", control);
	SendMessageW(control->handle, WM_SETFONT, (WPARAM)btrcWinControlFont(control), FALSE);
	SetWindowSubclass(control->handle, btrcWinControlProcedure, 1u, (DWORD_PTR)control);
	return control;
}

BtrcShimControl* btrcWinControlHost(unsigned int id, const wchar_t* class, void* extension, void (*release)(void* extension)) {
	BtrcShimControl* control = btrcWinControlNew(id, BTRC_WIN_HOSTED, class, L"", WS_CLIPCHILDREN, 0u);
	if (control == NULL) { return NULL; }
	control->extension = extension;
	control->release = release;
	return control;
}

HWND btrcWinControlHandle(BtrcShimControl* control) { return control->handle; }

void* btrcWinControlExtension(BtrcShimControl* control) { return control->extension; }

void btrcWinControlPushText(BtrcShimControl* control, unsigned int type, int data, const char* text) { btrcWinControlPush(control, type, data, 0.0, text); }

void btrcShimControlDestroy(BtrcShimControl* control) {
	if (control == NULL) { return; }
	if (control->window != NULL) {
		for (BtrcShimControl** link = &control->window->placed; *link != NULL; link = &(*link)->nextPlaced) {
			if (*link == control) { *link = control->nextPlaced; control->window->placedCount--; break; }
		}
	}
	if (control->release != NULL) { control->release(control->extension); }
	RemovePropW(control->handle, L"BtrcShimControl");
	RemoveWindowSubclass(control->handle, btrcWinControlProcedure, 1u);
	DestroyWindow(control->handle);
	if (control->font != NULL) { DeleteObject(control->font); }
	free(control->shapes);
	free(control->enabledItems);
	free(control->pixels);
	free(control);
}

void btrcShimControlSetEnabled(BtrcShimControl* control, bool enabled) { EnableWindow(control->handle, enabled); }

void btrcShimControlSetToolTip(BtrcShimControl* control, const char* text) {
	if (btrcWinToolTips == NULL) {
		btrcWinToolTips = CreateWindowExW(WS_EX_TOPMOST, TOOLTIPS_CLASSW, NULL, WS_POPUP | TTS_NOPREFIX | TTS_ALWAYSTIP, 0, 0, 0, 0, NULL, NULL, btrcWinModule(), NULL);
		if (btrcWinToolTips == NULL) { return; }
	}
	TOOLINFOW tool;
	memset(&tool, 0, sizeof tool);
	tool.cbSize = sizeof tool;
	tool.uFlags = TTF_IDISHWND | TTF_SUBCLASS;
	tool.hwnd = control->handle;
	tool.uId = (UINT_PTR)control->handle;
	SendMessageW(btrcWinToolTips, TTM_DELTOOLW, 0u, (LPARAM)&tool);
	if (text == NULL || text[0] == '\0') { return; }
	wchar_t* wide = btrcWinWide(text);
	if (wide == NULL) { return; }
	tool.lpszText = wide;
	SendMessageW(btrcWinToolTips, TTM_ADDTOOLW, 0u, (LPARAM)&tool);
	free(wide);
}

void btrcShimControlSetFont(BtrcShimControl* control, double size, bool bold) {
	HFONT font = btrcWinFont(size, bold, btrcWinControlScale(control));
	if (font == NULL) { return; }
	SendMessageW(control->handle, WM_SETFONT, (WPARAM)font, TRUE);
	if (control->font != NULL) { DeleteObject(control->font); }
	control->font = font;
}

static SIZE btrcWinNatural(BtrcShimControl* control, int width) {
	double scale = btrcWinControlScale(control);
	SIZE size = {0, 0};
	switch (control->kind) {
	case BTRC_WIN_BUTTON: {
		SIZE ideal = {0, 0};
		SendMessageW(control->handle, BCM_GETIDEALSIZE, 0u, (LPARAM)&ideal);
		wchar_t* title = btrcWinControlText(control->handle);
		SIZE text = btrcWinMeasure(control, title == NULL ? L"" : title, 0);
		free(title);
		size.cx = text.cx + (LONG)(24.0 * scale) + (LONG)(control->symbolSize > 0.0 ? (control->symbolSize + 8.0) * scale : 0.0);
		size.cy = text.cy + (LONG)(12.0 * scale);
		if (ideal.cy > size.cy && control->font == NULL) { size.cy = ideal.cy; }
		break;
	}
	case BTRC_WIN_LABEL: {
		wchar_t* text = btrcWinControlText(control->handle);
		size = btrcWinMeasure(control, text == NULL ? L"" : text, width);
		free(text);
		break;
	}
	case BTRC_WIN_TEXT: {
		SIZE line = btrcWinMeasure(control, L"Mg", 0);
		size.cx = (LONG)(120.0 * scale);
		size.cy = line.cy + (LONG)(10.0 * scale);
		break;
	}
	case BTRC_WIN_SELECT: {
		SIZE line = btrcWinMeasure(control, L"Mg", 0);
		size.cx = (LONG)((double)btrcShimSelectNaturalWidth(control) * scale);
		size.cy = line.cy + (LONG)(10.0 * scale);
		break;
	}
	case BTRC_WIN_SLIDER: size.cx = (LONG)(120.0 * scale); size.cy = (LONG)(28.0 * scale); break;
	case BTRC_WIN_SPINNER: size.cx = (LONG)(48.0 * scale); size.cy = (LONG)(12.0 * scale); break;
	case BTRC_WIN_LEVEL: size.cx = (LONG)(100.0 * scale); size.cy = (LONG)(16.0 * scale); break;
	case BTRC_WIN_SCROLLBAR:
		size.cx = control->vertical ? GetSystemMetrics(SM_CXVSCROLL) : (LONG)(40.0 * scale);
		size.cy = control->vertical ? (LONG)(40.0 * scale) : GetSystemMetrics(SM_CYHSCROLL);
		break;
	default: break;
	}
	size.cx = (LONG)((double)size.cx / scale + 0.999);
	size.cy = (LONG)((double)size.cy / scale + 0.999);
	return size;
}

int btrcShimControlNaturalWidth(BtrcShimControl* control) { return (int)btrcWinNatural(control, 0).cx; }

int btrcShimControlNaturalHeight(BtrcShimControl* control) { return (int)btrcWinNatural(control, 0).cy; }

int btrcShimControlNaturalHeightFor(BtrcShimControl* control, int width) {
	return (int)btrcWinNatural(control, control->kind == BTRC_WIN_LABEL && width > 0 ? (int)((double)width * btrcWinControlScale(control)) : 0).cy;
}

void btrcShimWindowBeginPlacement(BtrcShimWindow* window) {
	for (BtrcShimControl* control = window->placed; control != NULL; control = control->nextPlaced) { control->placed = false; }
	window->placedCount = 0;
	window->holeCount = 0;
}

static RECT btrcWinPixels(BtrcShimWindow* window, double x, double y, double width, double height) {
	double scale = btrcWinScale(window->handle);
	RECT area = {(LONG)(x * scale + 0.5), (LONG)(y * scale + 0.5), (LONG)((x + width) * scale + 0.5), (LONG)((y + height) * scale + 0.5)};
	return area;
}

void btrcShimWindowPlace(BtrcShimWindow* window, BtrcShimControl* control, double x, double y, double width, double height, double clipX, double clipY, double clipWidth, double clipHeight) {
	if (control->window != window) {
		/* It arrives from the nursery, or from another window. */
		if (control->window != NULL) {
			for (BtrcShimControl** link = &control->window->placed; *link != NULL; link = &(*link)->nextPlaced) {
				if (*link == control) { *link = control->nextPlaced; break; }
			}
		}
		control->window = window;
		control->nextPlaced = window->placed;
		window->placed = control;
		control->shownOnce = false;
		SetParent(control->handle, window->handle);
	}
	control->placed = true;
	control->order = window->placedCount++;
	control->frame = btrcWinPixels(window, x, y, width, height);
	control->clip = btrcWinPixels(window, clipX, clipY, clipWidth, clipHeight);
}

void btrcShimWindowPlaceHole(BtrcShimWindow* window, double x, double y, double width, double height, double clipX, double clipY, double clipWidth, double clipHeight) {
	if (window->holeCount == window->holeCapacity) {
		int capacity = window->holeCapacity == 0 ? 8 : window->holeCapacity * 2;
		BtrcWinHole* holes = realloc(window->holes, (size_t)capacity * sizeof *holes);
		if (holes == NULL) { return; }
		window->holes = holes;
		window->holeCapacity = capacity;
	}
	RECT frame = btrcWinPixels(window, x, y, width, height);
	RECT clip = btrcWinPixels(window, clipX, clipY, clipWidth, clipHeight);
	BtrcWinHole* hole = &window->holes[window->holeCount];
	if (!IntersectRect(&hole->area, &frame, &clip)) { return; }
	hole->after = window->placedCount;
	window->holeCount++;
}

/* A control's window region: what its ancestors let show of its frame, less
 * the holes placed after it, and for a fill its rounded corners. */
static void btrcWinShape(BtrcShimWindow* window, BtrcShimControl* control) {
	RECT visible;
	bool shown = IntersectRect(&visible, &control->frame, &control->clip) != 0;
	unsigned long shape = 2166136261ul;
	const LONG parts[9] = {visible.left, visible.top, visible.right, visible.bottom, control->frame.left, control->frame.top, control->frame.right, control->frame.bottom, (LONG)(control->radius * 16.0)};
	for (int index = 0; index < 9; index++) { shape = (shape ^ (unsigned long)parts[index]) * 16777619ul; }
	for (int index = 0; index < window->holeCount; index++) {
		const BtrcWinHole* hole = &window->holes[index];
		if (hole->after <= control->order) { continue; }
		shape = (((((shape ^ (unsigned long)hole->area.left) * 16777619ul) ^ (unsigned long)hole->area.top) * 16777619ul ^ (unsigned long)hole->area.right) * 16777619ul ^ (unsigned long)hole->area.bottom) * 16777619ul;
	}
	if (control->shownOnce && shape == control->shape) { return; }
	control->shape = shape;
	HRGN region = shown ? CreateRectRgn(visible.left - control->frame.left, visible.top - control->frame.top, visible.right - control->frame.left, visible.bottom - control->frame.top) : CreateRectRgn(0, 0, 0, 0);
	if (shown && control->kind == BTRC_WIN_FILL && control->radius > 0.0) {
		int corner = (int)(control->radius * btrcWinScale(window->handle) * 2.0 + 0.5);
		HRGN rounded = CreateRoundRectRgn(0, 0, control->frame.right - control->frame.left + 1, control->frame.bottom - control->frame.top + 1, corner, corner);
		CombineRgn(region, region, rounded, RGN_AND);
		DeleteObject(rounded);
	}
	for (int index = 0; shown && index < window->holeCount; index++) {
		const BtrcWinHole* hole = &window->holes[index];
		if (hole->after <= control->order) { continue; }
		HRGN cut = CreateRectRgn(hole->area.left - control->frame.left, hole->area.top - control->frame.top, hole->area.right - control->frame.left, hole->area.bottom - control->frame.top);
		CombineRgn(region, region, cut, RGN_DIFF);
		DeleteObject(cut);
	}
	/* The system owns the region from here. */
	SetWindowRgn(control->handle, region, TRUE);
}

/* A control the placement left out no longer belongs to this window. The
 * others take their frames, their regions, and their order: the first
 * placed lowest, just above the content. */
void btrcShimWindowEndPlacement(BtrcShimWindow* window) {
	BtrcShimControl** link = &window->placed;
	bool reorder = false;
	int count = 0;
	while (*link != NULL) {
		BtrcShimControl* control = *link;
		if (!control->placed) {
			*link = control->nextPlaced;
			control->nextPlaced = NULL;
			control->window = NULL;
			if (control->dragging) { control->dragging = false; ReleaseCapture(); }
			ShowWindow(control->handle, SW_HIDE);
			SetParent(control->handle, btrcWinNursery);
			continue;
		}
		count++;
		if (!control->shownOnce) { reorder = true; }
		link = &control->nextPlaced;
	}
	if (count == 0) { return; }
	/* The list in placement order. */
	BtrcShimControl** ordered = calloc((size_t)count, sizeof *ordered);
	if (ordered == NULL) { return; }
	int previous = -1;
	int index = 0;
	for (BtrcShimControl* control = window->placed; control != NULL; control = control->nextPlaced) {
		if (control->order >= 0 && control->order < count) { ordered[control->order] = control; }
		index++;
	}
	/* Whether the windows are already stacked in this order, lowest first. */
	HWND above = window->content;
	for (index = 0; index < count && !reorder; index++) {
		HWND next = GetWindow(above, GW_HWNDPREV);
		if (ordered[index] == NULL || next != ordered[index]->handle) { reorder = true; }
		above = next;
	}
	(void)previous;
	for (index = 0; index < count; index++) {
		BtrcShimControl* control = ordered[index];
		if (control == NULL) { continue; }
		int width = control->frame.right - control->frame.left;
		int height = control->frame.bottom - control->frame.top;
		/* A select is given two heights: its button's, which fills the
		 * frame, and with it the room its list may take. */
		int given = height;
		if (control->kind == BTRC_WIN_SELECT) {
			int edges = (int)SendMessageW(control->handle, CB_GETITEMHEIGHT, (WPARAM)-1, 0);
			RECT button;
			GetWindowRect(control->handle, &button);
			edges = button.bottom - button.top - edges;
			if (edges < 0 || edges > 16) { edges = 6; }
			if (height > edges) { SendMessageW(control->handle, CB_SETITEMHEIGHT, (WPARAM)-1, height - edges); }
			given = height + (int)(240.0 * btrcWinScale(window->handle));
		}
		UINT flags = SWP_NOACTIVATE | (reorder ? 0u : SWP_NOZORDER);
		if (!control->shownOnce || !EqualRect(&control->frame, &control->shownFrame)) {
			SetWindowPos(control->handle, HWND_TOP, control->frame.left, control->frame.top, width, given, flags);
			control->shownFrame = control->frame;
		} else if (reorder) { SetWindowPos(control->handle, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE); }
		btrcWinShape(window, control);
		if (!control->shownOnce) { control->shownOnce = true; ShowWindow(control->handle, SW_SHOWNA); }
	}
	free(ordered);
}

/* The controls as the system draws them, over a picture of the content:
 * each control is printed into a bitmap of its own and copied where its
 * window region shows it. */
bool btrcShimWindowDrawControls(BtrcShimWindow* window, unsigned char* pixels, int pixelWidth, int pixelHeight) {
	if (pixels == NULL || pixelWidth <= 0 || pixelHeight <= 0) { return false; }
	int count = window->placedCount;
	if (count <= 0) { return true; }
	BtrcShimControl** ordered = calloc((size_t)count, sizeof *ordered);
	if (ordered == NULL) { return false; }
	for (BtrcShimControl* control = window->placed; control != NULL; control = control->nextPlaced) {
		if (control->placed && control->order >= 0 && control->order < count) { ordered[control->order] = control; }
	}
	HDC screen = GetDC(NULL);
	HDC drawing = CreateCompatibleDC(screen);
	bool drawn = drawing != NULL;
	for (int index = 0; drawn && index < count; index++) {
		BtrcShimControl* control = ordered[index];
		if (control == NULL || (control->kind == BTRC_WIN_BUTTON && control->transparent)) { continue; }
		int width = control->frame.right - control->frame.left;
		int height = control->frame.bottom - control->frame.top;
		RECT visible;
		if (width <= 0 || height <= 0 || !IntersectRect(&visible, &control->frame, &control->clip)) { continue; }
		BITMAPINFO info;
		memset(&info, 0, sizeof info);
		info.bmiHeader.biSize = sizeof info.bmiHeader;
		info.bmiHeader.biWidth = width;
		info.bmiHeader.biHeight = -height;
		info.bmiHeader.biPlanes = 1;
		info.bmiHeader.biBitCount = 32;
		info.bmiHeader.biCompression = BI_RGB;
		void* bits = NULL;
		HBITMAP bitmap = CreateDIBSection(drawing, &info, DIB_RGB_COLORS, &bits, NULL, 0u);
		if (bitmap == NULL || bits == NULL) { drawn = false; break; }
		HGDIOBJ previous = SelectObject(drawing, bitmap);
		RECT whole = {0, 0, width, height};
		FillRect(drawing, &whole, btrcWinBackgroundBrush());
		SendMessageW(control->handle, WM_PRINT, (WPARAM)drawing, PRF_CLIENT | PRF_NONCLIENT | PRF_ERASEBKGND | PRF_CHILDREN);
		GdiFlush();
		HRGN region = CreateRectRgn(0, 0, 0, 0);
		int kind = GetWindowRgn(control->handle, region);
		const unsigned char* rows = bits;
		for (int y = visible.top; y < visible.bottom; y++) {
			if (y < 0 || y >= pixelHeight) { continue; }
			for (int x = visible.left; x < visible.right; x++) {
				if (x < 0 || x >= pixelWidth) { continue; }
				int localX = x - control->frame.left;
				int localY = y - control->frame.top;
				if (kind != ERROR && kind != NULLREGION && !PtInRegion(region, localX, localY)) { continue; }
				if (kind == NULLREGION) { continue; }
				const unsigned char* source = rows + ((size_t)localY * (size_t)width + (size_t)localX) * 4u;
				unsigned char* target = pixels + ((size_t)y * (size_t)pixelWidth + (size_t)x) * 4u;
				target[0] = source[2];
				target[1] = source[1];
				target[2] = source[0];
				target[3] = 255u;
			}
		}
		DeleteObject(region);
		SelectObject(drawing, previous);
		DeleteObject(bitmap);
	}
	if (drawing != NULL) { DeleteDC(drawing); }
	ReleaseDC(NULL, screen);
	free(ordered);
	return drawn;
}

BtrcShimControl* btrcShimButtonCreate(unsigned int id, const char* title) {
	wchar_t* wide = btrcWinWide(title);
	BtrcShimControl* control = btrcWinControlNew(id, BTRC_WIN_BUTTON, WC_BUTTONW, wide == NULL ? L"" : wide, WS_TABSTOP | BS_PUSHBUTTON | BS_CENTER, 0u);
	free(wide);
	return control;
}

void btrcShimButtonSetTitle(BtrcShimControl* button, const char* title) {
	wchar_t* wide = btrcWinWide(title);
	if (wide != NULL) { SetWindowTextW(button->handle, wide); free(wide); }
}

void btrcShimButtonSetCentered(BtrcShimControl* button, bool centered) {
	LONG_PTR style = GetWindowLongPtrW(button->handle, GWL_STYLE) & ~(LONG_PTR)(BS_CENTER | BS_LEFT);
	SetWindowLongPtrW(button->handle, GWL_STYLE, style | (centered ? BS_CENTER : BS_LEFT));
	InvalidateRect(button->handle, NULL, TRUE);
}

static void btrcWinButtonShape(BtrcShimControl* button, int kind, double a, double b, double c, double d, double e, double f) {
	BtrcWinShape* shapes = realloc(button->shapes, ((size_t)button->shapeCount + 1u) * sizeof *shapes);
	if (shapes == NULL) { return; }
	button->shapes = shapes;
	BtrcWinShape* shape = &shapes[button->shapeCount++];
	shape->kind = kind;
	shape->a = a; shape->b = b; shape->c = c; shape->d = d; shape->e = e; shape->f = f;
	InvalidateRect(button->handle, NULL, TRUE);
}

void btrcShimButtonBeginSymbol(BtrcShimControl* button, double size) {
	button->symbolSize = size;
	button->shapeCount = 0;
	/* The title starts after the symbol. */
	RECT margin = {(LONG)(size > 0.0 ? (size + 8.0) * btrcWinControlScale(button) : 0.0), 0, 0, 0};
	SendMessageW(button->handle, BCM_SETTEXTMARGIN, 0u, (LPARAM)&margin);
	InvalidateRect(button->handle, NULL, TRUE);
}

void btrcShimButtonSymbolLine(BtrcShimControl* button, double x0, double y0, double x1, double y1, double width) { btrcWinButtonShape(button, BTRC_WIN_SHAPE_LINE, x0, y0, x1, y1, width, 0.0); }

void btrcShimButtonSymbolTriangle(BtrcShimControl* button, double x0, double y0, double x1, double y1, double x2, double y2) { btrcWinButtonShape(button, BTRC_WIN_SHAPE_TRIANGLE, x0, y0, x1, y1, x2, y2); }

void btrcShimButtonSymbolRectangle(BtrcShimControl* button, double x, double y, double width, double height, double radius, double stroke) { btrcWinButtonShape(button, BTRC_WIN_SHAPE_RECTANGLE, x, y, width, height, radius, stroke); }

void btrcShimButtonSymbolCircle(BtrcShimControl* button, double centerX, double centerY, double radius, double stroke) { btrcWinButtonShape(button, BTRC_WIN_SHAPE_CIRCLE, centerX, centerY, radius, stroke, 0.0, 0.0); }

void btrcShimButtonSetBordered(BtrcShimControl* button, bool bordered) { button->bordered = bordered; InvalidateRect(button->handle, NULL, TRUE); }

/* A selected button looks held down. It stays a push button to assistive
 * technology; the system lets the look go after each click, so it is given
 * back then (the control's procedure). */
void btrcShimButtonSetSelected(BtrcShimControl* button, bool selected) {
	button->chosen = selected;
	SendMessageW(button->handle, BM_SETSTATE, selected ? TRUE : FALSE, 0);
}

void btrcShimButtonSetTransparent(BtrcShimControl* button, bool transparent) { button->transparent = transparent; InvalidateRect(button->handle, NULL, TRUE); }

BtrcShimControl* btrcShimLabelCreate(unsigned int id, const char* text) {
	wchar_t* wide = btrcWinWide(text);
	BtrcShimControl* control = btrcWinControlNew(id, BTRC_WIN_LABEL, WC_STATICW, wide == NULL ? L"" : wide, SS_LEFTNOWORDWRAP | SS_NOPREFIX, 0u);
	free(wide);
	return control;
}

void btrcShimLabelSetText(BtrcShimControl* label, const char* text) {
	wchar_t* wide = btrcWinWide(text);
	if (wide != NULL) { SetWindowTextW(label->handle, wide); free(wide); }
}

void btrcShimLabelSetSecondary(BtrcShimControl* label, bool secondary) { label->secondary = secondary; InvalidateRect(label->handle, NULL, TRUE); }

static void btrcWinLabelStyle(BtrcShimControl* label, LONG_PTR set, LONG_PTR clear) {
	LONG_PTR style = GetWindowLongPtrW(label->handle, GWL_STYLE);
	SetWindowLongPtrW(label->handle, GWL_STYLE, (style & ~clear) | set);
	InvalidateRect(label->handle, NULL, TRUE);
}

/* A static control's alignment is one field: centred text wraps, as left
 * text does unless told not to. */
void btrcShimLabelSetCentered(BtrcShimControl* label, bool centered) {
	LONG_PTR style = GetWindowLongPtrW(label->handle, GWL_STYLE);
	bool wraps = (style & SS_TYPEMASK) != SS_LEFTNOWORDWRAP;
	btrcWinLabelStyle(label, centered ? SS_CENTER : (wraps ? SS_LEFT : SS_LEFTNOWORDWRAP), SS_TYPEMASK);
}

void btrcShimLabelSetWrapping(BtrcShimControl* label, bool wrapping) {
	LONG_PTR style = GetWindowLongPtrW(label->handle, GWL_STYLE);
	if ((style & SS_TYPEMASK) == SS_CENTER) { return; }
	btrcWinLabelStyle(label, wrapping ? SS_LEFT : SS_LEFTNOWORDWRAP, SS_TYPEMASK);
}

BtrcShimControl* btrcShimSpinnerCreate(unsigned int id) { return btrcWinControlNew(id, BTRC_WIN_SPINNER, PROGRESS_CLASSW, L"", PBS_MARQUEE, 0u); }

void btrcShimSpinnerSetRunning(BtrcShimControl* spinner, bool running) { SendMessageW(spinner->handle, PBM_SETMARQUEE, running ? TRUE : FALSE, 30); }

BtrcShimControl* btrcShimLevelCreate(unsigned int id, double warning, double critical) {
	BtrcShimControl* control = btrcWinControlNew(id, BTRC_WIN_LEVEL, PROGRESS_CLASSW, L"", PBS_SMOOTH, 0u);
	if (control == NULL) { return NULL; }
	control->warning = warning;
	control->critical = critical;
	SendMessageW(control->handle, PBM_SETRANGE32, 0u, 1000);
	return control;
}

void btrcShimLevelSetValue(BtrcShimControl* level, double value) {
	if (value < 0.0) { value = 0.0; }
	if (value > 1.0) { value = 1.0; }
	/* The bar's three states are the theme's green, amber and red. */
	SendMessageW(level->handle, PBM_SETSTATE, value >= level->critical ? PBST_ERROR : value >= level->warning ? PBST_PAUSED : PBST_NORMAL, 0);
	SendMessageW(level->handle, PBM_SETPOS, (WPARAM)(value * 1000.0 + 0.5), 0);
}

BtrcShimControl* btrcShimSliderCreate(unsigned int id) {
	BtrcShimControl* control = btrcWinControlNew(id, BTRC_WIN_SLIDER, TRACKBAR_CLASSW, L"", WS_TABSTOP | TBS_HORZ | TBS_NOTICKS | TBS_BOTH, 0u);
	if (control == NULL) { return NULL; }
	control->maximum = 1.0;
	SendMessageW(control->handle, TBM_SETRANGEMIN, FALSE, 0);
	SendMessageW(control->handle, TBM_SETRANGEMAX, FALSE, 10000);
	return control;
}

void btrcShimSliderSet(BtrcShimControl* slider, double minimum, double maximum, double step, double value) {
	slider->minimum = minimum;
	slider->maximum = maximum;
	slider->step = step;
	slider->value = value;
	btrcWinSliderShow(slider);
}

BtrcShimControl* btrcShimSelectCreate(unsigned int id) { return btrcWinControlNew(id, BTRC_WIN_SELECT, WC_COMBOBOXW, L"", WS_TABSTOP | WS_VSCROLL | CBS_DROPDOWNLIST | CBS_HASSTRINGS, 0u); }

void btrcShimSelectClear(BtrcShimControl* select) {
	SendMessageW(select->handle, CB_RESETCONTENT, 0u, 0);
	select->itemCount = 0;
	select->selected = -1;
}

void btrcShimSelectAppend(BtrcShimControl* select, const char* title, bool enabled) {
	wchar_t* wide = btrcWinWide(title);
	bool* items = realloc(select->enabledItems, ((size_t)select->itemCount + 1u) * sizeof *items);
	if (wide == NULL || items == NULL) { free(wide); return; }
	select->enabledItems = items;
	select->enabledItems[select->itemCount++] = enabled;
	SendMessageW(select->handle, CB_ADDSTRING, 0u, (LPARAM)wide);
	free(wide);
}

void btrcShimSelectShow(BtrcShimControl* select, int selected, const char* shown, bool available) {
	select->selected = selected >= 0 && selected < select->itemCount ? selected : -1;
	btrcWinSelectRestore(select);
	/* With nothing selected the button shows the text as a cue. */
	wchar_t* wide = btrcWinWide(select->selected < 0 ? shown : "");
	if (wide != NULL) { SendMessageW(select->handle, CB_SETCUEBANNER, 0u, (LPARAM)wide); free(wide); }
	EnableWindow(select->handle, available);
}

void btrcShimSelectDismiss(BtrcShimControl* select) { SendMessageW(select->handle, CB_SHOWDROPDOWN, FALSE, 0); }

int btrcShimSelectNaturalWidth(BtrcShimControl* select) {
	double scale = btrcWinControlScale(select);
	LONG widest = 0;
	int count = (int)SendMessageW(select->handle, CB_GETCOUNT, 0u, 0);
	for (int index = 0; index < count; index++) {
		wchar_t item[512];
		if (SendMessageW(select->handle, CB_GETLBTEXTLEN, (WPARAM)index, 0) >= 512) { continue; }
		SendMessageW(select->handle, CB_GETLBTEXT, (WPARAM)index, (LPARAM)item);
		SIZE size = btrcWinMeasure(select, item, 0);
		if (size.cx > widest) { widest = size.cx; }
	}
	return (int)(((double)widest + (double)GetSystemMetrics(SM_CXVSCROLL)) / scale + 20.0);
}

BtrcShimControl* btrcShimTextCreate(unsigned int id, const char* text, const char* placeholder) {
	wchar_t* wide = btrcWinWide(text);
	BtrcShimControl* control = btrcWinControlNew(id, BTRC_WIN_TEXT, WC_EDITW, wide == NULL ? L"" : wide, WS_TABSTOP | ES_AUTOHSCROLL, WS_EX_CLIENTEDGE);
	free(wide);
	if (control != NULL) { btrcShimTextSetPlaceholder(control, placeholder); }
	return control;
}

/* The program's own text: not an edit, so not reported. The caret goes to its end. */
void btrcShimTextSet(BtrcShimControl* field, const char* text) {
	wchar_t* wide = btrcWinWide(text);
	wchar_t* present = btrcWinControlText(field->handle);
	if (wide != NULL && present != NULL && wcscmp(wide, present) != 0) {
		field->silent = true;
		SetWindowTextW(field->handle, wide);
		int length = GetWindowTextLengthW(field->handle);
		SendMessageW(field->handle, EM_SETSEL, (WPARAM)length, length);
		field->silent = false;
	}
	free(wide);
	free(present);
}

void btrcShimTextSetPlaceholder(BtrcShimControl* field, const char* placeholder) {
	wchar_t* wide = btrcWinWide(placeholder);
	/* Shown while the field has the keyboard too, as other toolkits show theirs. */
	if (wide != NULL) { SendMessageW(field->handle, EM_SETCUEBANNER, TRUE, (LPARAM)wide); free(wide); }
}

BtrcShimControl* btrcShimPictureCreate(unsigned int id) { return btrcWinControlNew(id, BTRC_WIN_PICTURE, L"BtrcShimDrawn", L"", 0u, 0u); }

void btrcShimPictureSet(BtrcShimControl* picture, const unsigned char* pixels, int width, int height) {
	free(picture->pixels);
	picture->pixels = NULL;
	picture->pixelWidth = 0;
	picture->pixelHeight = 0;
	if (pixels != NULL && width > 0 && height > 0) {
		size_t bytes = (size_t)width * (size_t)height * 4u;
		picture->pixels = malloc(bytes);
		if (picture->pixels != NULL) { memcpy(picture->pixels, pixels, bytes); picture->pixelWidth = width; picture->pixelHeight = height; }
	}
	InvalidateRect(picture->handle, NULL, TRUE);
}

BtrcShimControl* btrcShimFillCreate(unsigned int id) { return btrcWinControlNew(id, BTRC_WIN_FILL, L"BtrcShimDrawn", L"", 0u, 0u); }

void btrcShimFillSet(BtrcShimControl* fill, int red, int green, int blue, int alpha, double radius) {
	fill->red = red;
	fill->green = green;
	fill->blue = blue;
	fill->alpha = alpha;
	fill->radius = radius;
	/* The corners are part of the window region, made at the next placement. */
	fill->shownOnce = fill->shownOnce && fill->window != NULL;
	fill->shape = 0ul;
	InvalidateRect(fill->handle, NULL, TRUE);
}

BtrcShimControl* btrcShimScrollbarCreate(unsigned int id, bool vertical) {
	BtrcShimControl* control = btrcWinControlNew(id, BTRC_WIN_SCROLLBAR, WC_SCROLLBARW, L"", vertical ? SBS_VERT : SBS_HORZ, 0u);
	if (control != NULL) { control->vertical = vertical; }
	return control;
}

void btrcShimScrollbarSet(BtrcShimControl* bar, double offset, double viewport, double content) {
	bar->offset = offset;
	bar->viewport = viewport;
	bar->content = content;
	SCROLLINFO info;
	memset(&info, 0, sizeof info);
	info.cbSize = sizeof info;
	info.fMask = SIF_RANGE | SIF_PAGE | SIF_POS;
	info.nMin = 0;
	info.nMax = content > 1.0 ? (int)(content + 0.5) - 1 : 0;
	info.nPage = viewport > 0.0 ? (UINT)(viewport + 0.5) : 0u;
	info.nPos = (int)(offset + 0.5);
	SetScrollInfo(bar->handle, SB_CTL, &info, TRUE);
}
