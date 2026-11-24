#define COBJMACROS
#include "../../../../stdlib/GUI/Windows/SharedFrameDXGI.h"
#include <d3d11_1.h>
#include <dxgi1_2.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

static void check(HRESULT hr, const char *operation) {
	if (FAILED(hr)) {
		fprintf(stderr, "%s: HRESULT 0x%08lx\n", operation, (unsigned long)hr);
		exit(1);
	}
}

static BOOL CALLBACK findCanvas(HWND child, LPARAM output) {
	wchar_t name[64];
	if (GetClassNameW(child, name, 64) && wcscmp(name, L"BtrcSharedFrameCanvas") == 0) {
		*(HWND *)output = child;
		return FALSE;
	}
	return TRUE;
}

static int pixels(DWORD viewerPid) {
	if (!SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)) { SetProcessDPIAware(); }
	RECT lastRect = {0};
	COLORREF lastUpper = 0, lastLower = 0;
	HWND lastCover = NULL;
	int foundCanvas = 0;
	for (int attempt = 0; attempt < 100; ++attempt) {
		HWND top = FindWindowW(NULL, L"Shared frame view"), canvas = NULL;
		DWORD pid = 0;
		GetWindowThreadProcessId(top, &pid);
		if (top && pid == viewerPid) {
			if (IsIconic(top)) { ShowWindow(top, SW_RESTORE); }
			SetWindowPos(top, HWND_TOPMOST, 40, 40, 0, 0, SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW);
			EnumChildWindows(top, findCanvas, (LPARAM)&canvas);
		}
		RECT rect;
		if (canvas && IsWindowVisible(canvas) && GetWindowRect(canvas, &rect)) {
			foundCanvas = 1;
			lastRect = rect;
			int x = (rect.left + rect.right) / 2, height = rect.bottom - rect.top;
			POINT upperPoint = {x, rect.top + height / 4};
			POINT lowerPoint = {x, rect.top + 3 * height / 4};
			lastCover = WindowFromPoint(upperPoint);
			HDC screen = GetDC(NULL);
			COLORREF upper = GetPixel(screen, upperPoint.x, upperPoint.y);
			COLORREF lower = GetPixel(screen, lowerPoint.x, lowerPoint.y);
			ReleaseDC(NULL, screen);
			lastUpper = upper;
			lastLower = lower;
			if (GetRValue(upper) > 235 && GetGValue(upper) < 20 && GetBValue(upper) < 20 &&
			    GetBValue(lower) > 235 && GetGValue(lower) < 20 && GetRValue(lower) < 20) {
				SetWindowPos(top, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
				return 0;
			}
		}
		Sleep(40);
	}
	wchar_t coverClass[64] = L"", coverTitle[64] = L"";
	DWORD coverPid = 0;
	if (lastCover) {
		HWND root = GetAncestor(lastCover, GA_ROOT);
		if (!root) { root = lastCover; }
		GetClassNameW(root, coverClass, 64);
		GetWindowTextW(root, coverTitle, 64);
		GetWindowThreadProcessId(root, &coverPid);
	}
	fprintf(stderr,
	        "The screen did not show the producer's red and blue bands "
	        "(canvas=%d rect=%ld,%ld,%ld,%ld upper=%u,%u,%u lower=%u,%u,%u cover=[%ls] '%ls' pid=%lu)\n",
	        foundCanvas, (long)lastRect.left, (long)lastRect.top, (long)lastRect.right, (long)lastRect.bottom,
	        (unsigned)GetRValue(lastUpper), (unsigned)GetGValue(lastUpper), (unsigned)GetBValue(lastUpper),
	        (unsigned)GetRValue(lastLower), (unsigned)GetGValue(lastLower), (unsigned)GetBValue(lastLower),
	        coverClass, coverTitle, (unsigned long)coverPid);
	return 1;
}

static void sendFrame(HANDLE pipe, unsigned width, int valid) {
	ID3D11Device *device = NULL;
	ID3D11DeviceContext *context = NULL;
	HRESULT hr = D3D11CreateDevice(NULL, D3D_DRIVER_TYPE_HARDWARE, NULL, D3D11_CREATE_DEVICE_BGRA_SUPPORT,
	                               NULL, 0, D3D11_SDK_VERSION, &device, NULL, &context);
	if (FAILED(hr)) {
		check(D3D11CreateDevice(NULL, D3D_DRIVER_TYPE_WARP, NULL, D3D11_CREATE_DEVICE_BGRA_SUPPORT,
		                        NULL, 0, D3D11_SDK_VERSION, &device, NULL, &context), "create device");
	}
	IDXGIDevice *dxgi = NULL;
	IDXGIAdapter *adapter = NULL;
	DXGI_ADAPTER_DESC adapterDesc;
	check(ID3D11Device_QueryInterface(device, &IID_IDXGIDevice, (void **)&dxgi), "DXGI device");
	check(IDXGIDevice_GetAdapter(dxgi, &adapter), "adapter");
	check(IDXGIAdapter_GetDesc(adapter, &adapterDesc), "adapter description");

	D3D11_TEXTURE2D_DESC desc = {0};
	desc.Width = width;
	desc.Height = width / 2;
	desc.Format = valid ? DXGI_FORMAT_B8G8R8A8_UNORM : DXGI_FORMAT_R8G8B8A8_UNORM;
	desc.ArraySize = desc.MipLevels = desc.SampleDesc.Count = 1;
	desc.BindFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_RENDER_TARGET;
	desc.MiscFlags = D3D11_RESOURCE_MISC_SHARED_NTHANDLE | D3D11_RESOURCE_MISC_SHARED_KEYEDMUTEX;
	ID3D11Texture2D *texture = NULL;
	check(ID3D11Device_CreateTexture2D(device, &desc, NULL, &texture), "shared texture");
	IDXGIResource1 *resource = NULL;
	IDXGIKeyedMutex *mutex = NULL;
	check(ID3D11Texture2D_QueryInterface(texture, &IID_IDXGIResource1, (void **)&resource), "shared resource");
	check(ID3D11Texture2D_QueryInterface(texture, &IID_IDXGIKeyedMutex, (void **)&mutex), "keyed mutex");
	if (IDXGIKeyedMutex_AcquireSync(mutex, 0, 3000) != S_OK) { exit(1); }
	uint32_t *pattern = malloc((size_t)width * desc.Height * sizeof *pattern);
	if (!pattern) { exit(1); }
	for (unsigned y = 0; y < desc.Height; ++y) {
		uint32_t color = y < desc.Height / 2 ? 0xffff0000u : 0xff0000ffu;
		for (unsigned x = 0; x < width; ++x) { pattern[y * width + x] = color; }
	}
	ID3D11DeviceContext_UpdateSubresource(context, (ID3D11Resource *)texture, 0, NULL, pattern, width * 4, 0);
	free(pattern);
	check(IDXGIKeyedMutex_ReleaseSync(mutex, 1), "publish texture");

	BtrcDxgiFrameMessage message = {.version = BTRC_DXGI_FRAME_VERSION, .adapter = adapterDesc.AdapterLuid};
	check(CoCreateGuid(&message.resource), "resource GUID");
	wchar_t suffix[39], name[64];
	if (!StringFromGUID2(&message.resource, suffix, 39) ||
	    swprintf(name, 64, BTRC_DXGI_RESOURCE_PREFIX L"%ls", suffix) < 0) { exit(1); }
	HANDLE handle = NULL;
	check(IDXGIResource1_CreateSharedHandle(resource, NULL, DXGI_SHARED_RESOURCE_READ, name, &handle), "share handle");
	DWORD bytes;
	if (!WriteFile(pipe, &message, sizeof message, &bytes, NULL) || bytes != sizeof message) { puts("closed"); }
	else {
		puts("sent");
		unsigned char response = 0;
		BOOL read = ReadFile(pipe, &response, 1, &bytes, NULL);
		puts(read && bytes == 1 && response == 1 ? "accepted" : "rejected");
	}
	CloseHandle(handle);
	IDXGIKeyedMutex_Release(mutex);
	IDXGIResource1_Release(resource);
	ID3D11Texture2D_Release(texture);
	IDXGIAdapter_Release(adapter);
	IDXGIDevice_Release(dxgi);
	ID3D11DeviceContext_Release(context);
	ID3D11Device_Release(device);
}

int main(int argc, char **argv) {
	if (argc == 3 && strcmp(argv[1], "--pixels") == 0) { return pixels(strtoul(argv[2], NULL, 10)); }
	setvbuf(stdout, NULL, _IONBF, 0);
	HANDLE pipe = INVALID_HANDLE_VALUE;
	char current[96] = "", line[150], address[96];
	unsigned width;
	int valid;
	while (fgets(line, sizeof line, stdin)) {
		if (sscanf(line, "%95s %u %d", address, &width, &valid) != 3 || width < 2 || width > 640) { return 1; }
		if (strcmp(address, current) != 0 || pipe == INVALID_HANDLE_VALUE) {
			if (pipe != INVALID_HANDLE_VALUE) { CloseHandle(pipe); }
			pipe = CreateFileA(address, GENERIC_READ | GENERIC_WRITE, 0, NULL, OPEN_EXISTING, 0, NULL);
			if (pipe == INVALID_HANDLE_VALUE) { puts("closed"); continue; }
			strcpy(current, address);
		}
		sendFrame(pipe, width, valid);
	}
	if (pipe != INVALID_HANDLE_VALUE) { CloseHandle(pipe); }
	return 0;
}
