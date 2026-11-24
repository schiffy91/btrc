#include "Win32ShimPrivate.h"
#include "SharedFrameDXGI.h"
#include "../Shim/SharedFrame.h"
#include <d3d11_1.h>
#include <dxgi1_2.h>
#include <stdint.h>
#include <wchar.h>

typedef struct {
	HWND host, canvas;
	HANDLE pipe;
	DWORD producer;
	char address[96];
	LUID adapter;
	IDXGIFactory2 *factory;
	ID3D11Device1 *device;
	ID3D11DeviceContext *context;
	IDXGISwapChain1 *chain;
	UINT bufferWidth, bufferHeight;
	int width, height;
} BtrcFrameView;

static void releaseDevice(BtrcFrameView *view) {
	if (view->chain) { IDXGISwapChain1_Release(view->chain); view->chain = NULL; }
	if (view->context) {
		ID3D11DeviceContext_ClearState(view->context);
		ID3D11DeviceContext_Flush(view->context);
		ID3D11DeviceContext_Release(view->context);
		view->context = NULL;
	}
	if (view->device) { ID3D11Device1_Release(view->device); view->device = NULL; }
	if (view->factory) { IDXGIFactory2_Release(view->factory); view->factory = NULL; }
	view->bufferWidth = view->bufferHeight = 0;
}

static void disconnect(BtrcFrameView *view) {
	if (view->pipe != INVALID_HANDLE_VALUE) { CloseHandle(view->pipe); view->pipe = INVALID_HANDLE_VALUE; }
	releaseDevice(view);
	view->producer = 0;
	view->address[0] = '\0';
	view->width = view->height = 0;
	if (view->canvas) { ShowWindow(view->canvas, SW_HIDE); }
}

static void releaseView(void *data) {
	BtrcFrameView *view = data;
	disconnect(view);
	SetWindowLongPtrW(view->host, GWLP_USERDATA, 0);
	free(view);
}

static void layout(BtrcFrameView *view) {
	RECT area;
	if (!view->width || !view->height || !GetClientRect(view->host, &area)) { return; }
	int w = area.right, h = area.bottom;
	if ((int64_t)w * view->height > (int64_t)h * view->width) { w = MulDiv(h, view->width, view->height); }
	else { h = MulDiv(w, view->height, view->width); }
	SetWindowPos(view->canvas, NULL, (area.right - w) / 2, (area.bottom - h) / 2, w, h,
	             SWP_NOACTIVATE | SWP_NOZORDER | SWP_SHOWWINDOW);
}

static LRESULT CALLBACK hostProcedure(HWND window, UINT message, WPARAM w, LPARAM l) {
	BtrcFrameView *view = (void *)GetWindowLongPtrW(window, GWLP_USERDATA);
	if (message == WM_SIZE && view) { layout(view); }
	return DefWindowProcW(window, message, w, l);
}

static LRESULT CALLBACK canvasProcedure(HWND window, UINT message, WPARAM w, LPARAM l) {
	if (message == WM_NCHITTEST) { return HTTRANSPARENT; }
	if (message == WM_ERASEBKGND) { return 1; }
	return DefWindowProcW(window, message, w, l);
}

static bool registerHost(void) {
	WNDCLASSW wc = {0};
	wc.hInstance = btrcWinModule();
	wc.lpfnWndProc = canvasProcedure;
	wc.lpszClassName = L"BtrcSharedFrameCanvas";
	if (!RegisterClassW(&wc) && GetLastError() != ERROR_CLASS_ALREADY_EXISTS) { return false; }
	wc.lpfnWndProc = hostProcedure;
	wc.lpszClassName = L"BtrcSharedFrameHost";
	wc.hbrBackground = GetStockObject(BLACK_BRUSH);
	return RegisterClassW(&wc) || GetLastError() == ERROR_CLASS_ALREADY_EXISTS;
}

const char *btrcShimFrameTransport(void) { return "dxgi"; }

BtrcShimControl *btrcShimFrameCreate(unsigned int id) {
	if (!registerHost()) { return NULL; }
	BtrcFrameView *view = calloc(1, sizeof *view);
	if (!view) { return NULL; }
	view->pipe = INVALID_HANDLE_VALUE;
	BtrcShimControl *control = btrcWinControlHost(id, L"BtrcSharedFrameHost", view, releaseView);
	if (!control) { free(view); return NULL; }
	view->host = btrcWinControlHandle(control);
	view->canvas = CreateWindowExW(0, L"BtrcSharedFrameCanvas", L"", WS_CHILD | WS_DISABLED, 0, 0, 0, 0,
	                               view->host, NULL, btrcWinModule(), NULL);
	if (!view->canvas) { btrcShimControlDestroy(control); return NULL; }
	SetWindowLongPtrW(view->host, GWLP_USERDATA, (LONG_PTR)view);
	return control;
}

const char *btrcShimFrameListen(BtrcShimControl *control, int producerPid) {
	BtrcFrameView *view = btrcWinControlExtension(control);
	disconnect(view);
	GUID id;
	wchar_t suffix[39], path[96];
	if (producerPid <= 0 || FAILED(CoCreateGuid(&id)) || !StringFromGUID2(&id, suffix, 39)) { return NULL; }
	if (swprintf(path, 96, L"\\\\.\\pipe\\BtrcFrame-%ls", suffix) < 0 ||
	    !WideCharToMultiByte(CP_UTF8, 0, path, -1, view->address, sizeof view->address, NULL, NULL)) { return NULL; }
	view->pipe = CreateNamedPipeW(path, PIPE_ACCESS_DUPLEX | FILE_FLAG_FIRST_PIPE_INSTANCE,
	                             PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_NOWAIT | PIPE_REJECT_REMOTE_CLIENTS,
	                             1, 128, 128, 0, NULL);
	if (view->pipe == INVALID_HANDLE_VALUE) { return NULL; }
	ConnectNamedPipe(view->pipe, NULL); /* Put the nonblocking instance into listening state. */
	view->producer = (DWORD)producerPid;
	return view->address;
}

static bool openDevice(BtrcFrameView *view, LUID luid) {
	if (view->device && view->adapter.LowPart == luid.LowPart && view->adapter.HighPart == luid.HighPart) { return true; }
	/* An attached producer uses one adapter. Keep its last frame visible
	 * if a message for another adapter arrives. listen() starts a new session. */
	if (view->width) { return false; }
	releaseDevice(view);
	if (FAILED(CreateDXGIFactory1(&IID_IDXGIFactory2, (void **)&view->factory))) { return false; }
	for (UINT i = 0; ; ++i) {
		IDXGIAdapter1 *adapter = NULL;
		if (FAILED(IDXGIFactory2_EnumAdapters1(view->factory, i, &adapter))) { break; }
		DXGI_ADAPTER_DESC1 desc;
		bool match = SUCCEEDED(IDXGIAdapter1_GetDesc1(adapter, &desc)) &&
		             desc.AdapterLuid.LowPart == luid.LowPart && desc.AdapterLuid.HighPart == luid.HighPart;
		if (match) {
			ID3D11Device *device = NULL;
			HRESULT hr = D3D11CreateDevice((IDXGIAdapter *)adapter, D3D_DRIVER_TYPE_UNKNOWN, NULL,
			                               D3D11_CREATE_DEVICE_BGRA_SUPPORT, NULL, 0, D3D11_SDK_VERSION,
			                               &device, NULL, &view->context);
			if (SUCCEEDED(hr)) {
				hr = ID3D11Device_QueryInterface(device, &IID_ID3D11Device1, (void **)&view->device);
				ID3D11Device_Release(device);
			}
			IDXGIAdapter1_Release(adapter);
			if (FAILED(hr)) { break; }
			view->adapter = luid;
			return true;
		}
		IDXGIAdapter1_Release(adapter);
	}
	releaseDevice(view);
	return false;
}

static bool sizeBuffers(BtrcFrameView *view, UINT width, UINT height) {
	if (view->chain && view->bufferWidth == width && view->bufferHeight == height) { return true; }
	if (view->chain) {
		if (FAILED(IDXGISwapChain1_ResizeBuffers(view->chain, 0, width, height, DXGI_FORMAT_UNKNOWN, 0))) { return false; }
	} else {
		DXGI_SWAP_CHAIN_DESC1 desc = {0};
		desc.Width = width;
		desc.Height = height;
		desc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
		desc.SampleDesc.Count = 1;
		desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
		desc.BufferCount = 2;
		desc.Scaling = DXGI_SCALING_STRETCH;
		desc.SwapEffect = DXGI_SWAP_EFFECT_FLIP_SEQUENTIAL;
		if (FAILED(IDXGIFactory2_CreateSwapChainForHwnd(view->factory, (IUnknown *)view->device, view->canvas,
		                                              &desc, NULL, NULL, &view->chain))) { return false; }
	}
	view->bufferWidth = width;
	view->bufferHeight = height;
	return true;
}

static bool presentTexture(BtrcFrameView *view, ID3D11Texture2D *texture) {
	D3D11_TEXTURE2D_DESC desc;
	ID3D11Texture2D_GetDesc(texture, &desc);
	if (!desc.Width || !desc.Height || desc.Width > 16384 || desc.Height > 16384 ||
	    (uint64_t)desc.Width * desc.Height > 16777216 || desc.Format != DXGI_FORMAT_B8G8R8A8_UNORM ||
	    desc.ArraySize != 1 || desc.MipLevels != 1 || desc.SampleDesc.Count != 1) { return false; }
	IDXGIKeyedMutex *mutex = NULL;
	if (FAILED(ID3D11Texture2D_QueryInterface(texture, &IID_IDXGIKeyedMutex, (void **)&mutex))) { return false; }
	bool copied = false;
	if (IDXGIKeyedMutex_AcquireSync(mutex, 1, 0) == S_OK) {
		ID3D11Texture2D *back = NULL;
		if (sizeBuffers(view, desc.Width, desc.Height) &&
		    SUCCEEDED(IDXGISwapChain1_GetBuffer(view->chain, 0, &IID_ID3D11Texture2D, (void **)&back))) {
			ID3D11DeviceContext_CopyResource(view->context, (ID3D11Resource *)back, (ID3D11Resource *)texture);
			ID3D11Texture2D_Release(back);
			copied = true;
		}
		if (FAILED(IDXGIKeyedMutex_ReleaseSync(mutex, 0))) { copied = false; }
	}
	IDXGIKeyedMutex_Release(mutex);
	if (!copied) { return false; }
	int previousWidth = view->width, previousHeight = view->height;
	view->width = (int)desc.Width;
	view->height = (int)desc.Height;
	layout(view);
	HRESULT hr = IDXGISwapChain1_Present(view->chain, 0, DXGI_PRESENT_DO_NOT_WAIT);
	if (hr == S_OK) { return true; }
	if (hr == DXGI_ERROR_DEVICE_REMOVED || hr == DXGI_ERROR_DEVICE_RESET) {
		releaseDevice(view);
		previousWidth = previousHeight = 0;
	}
	view->width = previousWidth;
	view->height = previousHeight;
	if (previousWidth) { layout(view); }
	else { ShowWindow(view->canvas, SW_HIDE); }
	return false;
}

static bool importFrame(BtrcFrameView *view, const BtrcDxgiFrameMessage *message) {
	wchar_t suffix[39], name[64];
	if (message->version != BTRC_DXGI_FRAME_VERSION || !StringFromGUID2(&message->resource, suffix, 39) ||
	    swprintf(name, 64, BTRC_DXGI_RESOURCE_PREFIX L"%ls", suffix) < 0 || !openDevice(view, message->adapter)) { return false; }
	ID3D11Texture2D *texture = NULL;
	if (FAILED(ID3D11Device1_OpenSharedResourceByName(view->device, name, DXGI_SHARED_RESOURCE_READ,
	                                                 &IID_ID3D11Texture2D, (void **)&texture))) { return false; }
	bool accepted = presentTexture(view, texture);
	ID3D11Texture2D_Release(texture);
	return accepted;
}

static void listenAgain(BtrcFrameView *view) {
	DisconnectNamedPipe(view->pipe);
	ConnectNamedPipe(view->pipe, NULL);
}

bool btrcShimFramePresent(BtrcShimControl *control) {
	BtrcFrameView *view = btrcWinControlExtension(control);
	if (view->pipe == INVALID_HANDLE_VALUE) { return false; }
	if (ConnectNamedPipe(view->pipe, NULL)) { return false; }
	DWORD error = GetLastError();
	if (error == ERROR_NO_DATA) { listenAgain(view); return false; }
	if (error != ERROR_PIPE_CONNECTED) { return false; }
	ULONG pid;
	if (!GetNamedPipeClientProcessId(view->pipe, &pid) || pid != view->producer) {
		listenAgain(view);
		return false;
	}
	DWORD bytes;
	if (!PeekNamedPipe(view->pipe, NULL, 0, NULL, NULL, &bytes)) { listenAgain(view); return false; }
	if (bytes == 0) { return false; }
	BtrcDxgiFrameMessage message;
	if (bytes != sizeof message || !ReadFile(view->pipe, &message, sizeof message, &bytes, NULL) || bytes != sizeof message) {
		listenAgain(view);
		return false;
	}
	unsigned char ack = importFrame(view, &message) ? 1 : 0;
	if (!WriteFile(view->pipe, &ack, 1, &bytes, NULL) || bytes != 1) { listenAgain(view); }
	return ack != 0;
}

void btrcShimFrameDisconnect(BtrcShimControl *control) { disconnect(btrcWinControlExtension(control)); }
int btrcShimFrameWidth(BtrcShimControl *control) { return ((BtrcFrameView *)btrcWinControlExtension(control))->width; }
int btrcShimFrameHeight(BtrcShimControl *control) { return ((BtrcFrameView *)btrcWinControlExtension(control))->height; }
