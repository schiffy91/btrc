/* The Win32 web view's COM ABI. Methods outside the shim's subset occupy
 * function-pointer slots. The SDK conformance test checks their positions
 * against Microsoft's published interfaces on x64 and ARM64. */
#ifndef BTRC_WEBVIEW2_INTERFACES_H
#define BTRC_WEBVIEW2_INTERFACES_H

#include <windows.h>
#include <objidl.h>

typedef struct { INT64 value; } EventRegistrationToken;
typedef enum { COREWEBVIEW2_WEB_RESOURCE_CONTEXT_ALL = 0 } COREWEBVIEW2_WEB_RESOURCE_CONTEXT;
typedef enum { COREWEBVIEW2_MOVE_FOCUS_REASON_PROGRAMMATIC = 0 } COREWEBVIEW2_MOVE_FOCUS_REASON;
typedef void (STDMETHODCALLTYPE* BtrcWebUnusedMethod)(void);

typedef struct ICoreWebView2 ICoreWebView2;
typedef struct ICoreWebView2AddScriptToExecuteOnDocumentCreatedCompletedHandler ICoreWebView2AddScriptToExecuteOnDocumentCreatedCompletedHandler;
typedef struct ICoreWebView2Controller ICoreWebView2Controller;
typedef struct ICoreWebView2ControllerOptions ICoreWebView2ControllerOptions;
typedef struct ICoreWebView2CreateCoreWebView2ControllerCompletedHandler ICoreWebView2CreateCoreWebView2ControllerCompletedHandler;
typedef struct ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler;
typedef struct ICoreWebView2CustomSchemeRegistration ICoreWebView2CustomSchemeRegistration;
typedef struct ICoreWebView2Environment ICoreWebView2Environment;
typedef struct ICoreWebView2Environment10 ICoreWebView2Environment10;
typedef struct ICoreWebView2EnvironmentOptions ICoreWebView2EnvironmentOptions;
typedef struct ICoreWebView2EnvironmentOptions4 ICoreWebView2EnvironmentOptions4;
typedef struct ICoreWebView2ExecuteScriptCompletedHandler ICoreWebView2ExecuteScriptCompletedHandler;
typedef struct ICoreWebView2NavigationCompletedEventArgs ICoreWebView2NavigationCompletedEventArgs;
typedef struct ICoreWebView2NavigationCompletedEventHandler ICoreWebView2NavigationCompletedEventHandler;
typedef struct ICoreWebView2NavigationStartingEventArgs ICoreWebView2NavigationStartingEventArgs;
typedef struct ICoreWebView2NavigationStartingEventHandler ICoreWebView2NavigationStartingEventHandler;
typedef struct ICoreWebView2NewWindowRequestedEventArgs ICoreWebView2NewWindowRequestedEventArgs;
typedef struct ICoreWebView2NewWindowRequestedEventHandler ICoreWebView2NewWindowRequestedEventHandler;
typedef struct ICoreWebView2Settings ICoreWebView2Settings;
typedef struct ICoreWebView2WebMessageReceivedEventArgs ICoreWebView2WebMessageReceivedEventArgs;
typedef struct ICoreWebView2WebMessageReceivedEventHandler ICoreWebView2WebMessageReceivedEventHandler;
typedef struct ICoreWebView2WebResourceRequest ICoreWebView2WebResourceRequest;
typedef struct ICoreWebView2WebResourceRequestedEventArgs ICoreWebView2WebResourceRequestedEventArgs;
typedef struct ICoreWebView2WebResourceRequestedEventHandler ICoreWebView2WebResourceRequestedEventHandler;
typedef struct ICoreWebView2WebResourceResponse ICoreWebView2WebResourceResponse;

#define BTRC_WEB_UNKNOWN(Type) \
	HRESULT (STDMETHODCALLTYPE* QueryInterface)(Type*, REFIID, void**); \
	ULONG (STDMETHODCALLTYPE* AddRef)(Type*); \
	ULONG (STDMETHODCALLTYPE* Release)(Type*)

typedef struct {
	BTRC_WEB_UNKNOWN(ICoreWebView2);
	HRESULT (STDMETHODCALLTYPE* get_Settings)(ICoreWebView2*, ICoreWebView2Settings**);
	BtrcWebUnusedMethod slot4[1];
	HRESULT (STDMETHODCALLTYPE* Navigate)(ICoreWebView2*, LPCWSTR);
	BtrcWebUnusedMethod slot6[1];
	HRESULT (STDMETHODCALLTYPE* add_NavigationStarting)(ICoreWebView2*, ICoreWebView2NavigationStartingEventHandler*, EventRegistrationToken*);
	BtrcWebUnusedMethod slot8[7];
	HRESULT (STDMETHODCALLTYPE* add_NavigationCompleted)(ICoreWebView2*, ICoreWebView2NavigationCompletedEventHandler*, EventRegistrationToken*);
	BtrcWebUnusedMethod slot16[11];
	HRESULT (STDMETHODCALLTYPE* AddScriptToExecuteOnDocumentCreated)(ICoreWebView2*, LPCWSTR, ICoreWebView2AddScriptToExecuteOnDocumentCreatedCompletedHandler*);
	BtrcWebUnusedMethod slot28[1];
	HRESULT (STDMETHODCALLTYPE* ExecuteScript)(ICoreWebView2*, LPCWSTR, ICoreWebView2ExecuteScriptCompletedHandler*);
	BtrcWebUnusedMethod slot30[4];
	HRESULT (STDMETHODCALLTYPE* add_WebMessageReceived)(ICoreWebView2*, ICoreWebView2WebMessageReceivedEventHandler*, EventRegistrationToken*);
	BtrcWebUnusedMethod slot35[9];
	HRESULT (STDMETHODCALLTYPE* add_NewWindowRequested)(ICoreWebView2*, ICoreWebView2NewWindowRequestedEventHandler*, EventRegistrationToken*);
	BtrcWebUnusedMethod slot45[10];
	HRESULT (STDMETHODCALLTYPE* add_WebResourceRequested)(ICoreWebView2*, ICoreWebView2WebResourceRequestedEventHandler*, EventRegistrationToken*);
	BtrcWebUnusedMethod slot56[1];
	HRESULT (STDMETHODCALLTYPE* AddWebResourceRequestedFilter)(ICoreWebView2*, LPCWSTR, COREWEBVIEW2_WEB_RESOURCE_CONTEXT);
} ICoreWebView2Vtbl;
struct ICoreWebView2 { const ICoreWebView2Vtbl* lpVtbl; };

typedef struct {
	BTRC_WEB_UNKNOWN(ICoreWebView2Settings);
	BtrcWebUnusedMethod slot3[7];
	HRESULT (STDMETHODCALLTYPE* put_IsStatusBarEnabled)(ICoreWebView2Settings*, BOOL);
	BtrcWebUnusedMethod slot11[1];
	HRESULT (STDMETHODCALLTYPE* put_AreDevToolsEnabled)(ICoreWebView2Settings*, BOOL);
} ICoreWebView2SettingsVtbl;
struct ICoreWebView2Settings { const ICoreWebView2SettingsVtbl* lpVtbl; };

typedef struct {
	BTRC_WEB_UNKNOWN(ICoreWebView2Controller);
	BtrcWebUnusedMethod slot3[1];
	HRESULT (STDMETHODCALLTYPE* put_IsVisible)(ICoreWebView2Controller*, BOOL);
	BtrcWebUnusedMethod slot5[1];
	HRESULT (STDMETHODCALLTYPE* put_Bounds)(ICoreWebView2Controller*, RECT);
	BtrcWebUnusedMethod slot7[5];
	HRESULT (STDMETHODCALLTYPE* MoveFocus)(ICoreWebView2Controller*, COREWEBVIEW2_MOVE_FOCUS_REASON);
	BtrcWebUnusedMethod slot13[11];
	HRESULT (STDMETHODCALLTYPE* Close)(ICoreWebView2Controller*);
	HRESULT (STDMETHODCALLTYPE* get_CoreWebView2)(ICoreWebView2Controller*, ICoreWebView2**);
} ICoreWebView2ControllerVtbl;
struct ICoreWebView2Controller { const ICoreWebView2ControllerVtbl* lpVtbl; };

typedef struct {
	BTRC_WEB_UNKNOWN(ICoreWebView2ControllerOptions);
	BtrcWebUnusedMethod slot3[3];
	HRESULT (STDMETHODCALLTYPE* put_IsInPrivateModeEnabled)(ICoreWebView2ControllerOptions*, BOOL);
} ICoreWebView2ControllerOptionsVtbl;
struct ICoreWebView2ControllerOptions { const ICoreWebView2ControllerOptionsVtbl* lpVtbl; };

typedef struct {
	BTRC_WEB_UNKNOWN(ICoreWebView2Environment);
	HRESULT (STDMETHODCALLTYPE* CreateCoreWebView2Controller)(ICoreWebView2Environment*, HWND, ICoreWebView2CreateCoreWebView2ControllerCompletedHandler*);
	HRESULT (STDMETHODCALLTYPE* CreateWebResourceResponse)(ICoreWebView2Environment*, IStream*, int, LPCWSTR, LPCWSTR, ICoreWebView2WebResourceResponse**);
} ICoreWebView2EnvironmentVtbl;
struct ICoreWebView2Environment { const ICoreWebView2EnvironmentVtbl* lpVtbl; };

typedef struct {
	BTRC_WEB_UNKNOWN(ICoreWebView2Environment10);
	BtrcWebUnusedMethod slot3[17];
	HRESULT (STDMETHODCALLTYPE* CreateCoreWebView2ControllerOptions)(ICoreWebView2Environment10*, ICoreWebView2ControllerOptions**);
	HRESULT (STDMETHODCALLTYPE* CreateCoreWebView2ControllerWithOptions)(ICoreWebView2Environment10*, HWND, ICoreWebView2ControllerOptions*, ICoreWebView2CreateCoreWebView2ControllerCompletedHandler*);
} ICoreWebView2Environment10Vtbl;
struct ICoreWebView2Environment10 { const ICoreWebView2Environment10Vtbl* lpVtbl; };

typedef struct {
	BTRC_WEB_UNKNOWN(ICoreWebView2WebMessageReceivedEventArgs);
	BtrcWebUnusedMethod slot3[2];
	HRESULT (STDMETHODCALLTYPE* TryGetWebMessageAsString)(ICoreWebView2WebMessageReceivedEventArgs*, LPWSTR*);
} ICoreWebView2WebMessageReceivedEventArgsVtbl;
struct ICoreWebView2WebMessageReceivedEventArgs { const ICoreWebView2WebMessageReceivedEventArgsVtbl* lpVtbl; };

typedef struct {
	BTRC_WEB_UNKNOWN(ICoreWebView2NewWindowRequestedEventArgs);
	HRESULT (STDMETHODCALLTYPE* get_Uri)(ICoreWebView2NewWindowRequestedEventArgs*, LPWSTR*);
	BtrcWebUnusedMethod slot4[2];
	HRESULT (STDMETHODCALLTYPE* put_Handled)(ICoreWebView2NewWindowRequestedEventArgs*, BOOL);
} ICoreWebView2NewWindowRequestedEventArgsVtbl;
struct ICoreWebView2NewWindowRequestedEventArgs { const ICoreWebView2NewWindowRequestedEventArgsVtbl* lpVtbl; };

typedef struct {
	BTRC_WEB_UNKNOWN(ICoreWebView2NavigationStartingEventArgs);
	HRESULT (STDMETHODCALLTYPE* get_Uri)(ICoreWebView2NavigationStartingEventArgs*, LPWSTR*);
	BtrcWebUnusedMethod slot4[4];
	HRESULT (STDMETHODCALLTYPE* put_Cancel)(ICoreWebView2NavigationStartingEventArgs*, BOOL);
} ICoreWebView2NavigationStartingEventArgsVtbl;
struct ICoreWebView2NavigationStartingEventArgs { const ICoreWebView2NavigationStartingEventArgsVtbl* lpVtbl; };

typedef struct {
	BTRC_WEB_UNKNOWN(ICoreWebView2WebResourceRequest);
	HRESULT (STDMETHODCALLTYPE* get_Uri)(ICoreWebView2WebResourceRequest*, LPWSTR*);
} ICoreWebView2WebResourceRequestVtbl;
struct ICoreWebView2WebResourceRequest { const ICoreWebView2WebResourceRequestVtbl* lpVtbl; };

typedef struct {
	BTRC_WEB_UNKNOWN(ICoreWebView2WebResourceResponse);
} ICoreWebView2WebResourceResponseVtbl;
struct ICoreWebView2WebResourceResponse { const ICoreWebView2WebResourceResponseVtbl* lpVtbl; };

typedef struct {
	BTRC_WEB_UNKNOWN(ICoreWebView2WebResourceRequestedEventArgs);
	HRESULT (STDMETHODCALLTYPE* get_Request)(ICoreWebView2WebResourceRequestedEventArgs*, ICoreWebView2WebResourceRequest**);
	BtrcWebUnusedMethod slot4[1];
	HRESULT (STDMETHODCALLTYPE* put_Response)(ICoreWebView2WebResourceRequestedEventArgs*, ICoreWebView2WebResourceResponse*);
} ICoreWebView2WebResourceRequestedEventArgsVtbl;
struct ICoreWebView2WebResourceRequestedEventArgs { const ICoreWebView2WebResourceRequestedEventArgsVtbl* lpVtbl; };

typedef struct {
	BTRC_WEB_UNKNOWN(ICoreWebView2EnvironmentOptions);
	HRESULT (STDMETHODCALLTYPE* get_AdditionalBrowserArguments)(ICoreWebView2EnvironmentOptions*, LPWSTR*);
	HRESULT (STDMETHODCALLTYPE* put_AdditionalBrowserArguments)(ICoreWebView2EnvironmentOptions*, LPCWSTR);
	HRESULT (STDMETHODCALLTYPE* get_Language)(ICoreWebView2EnvironmentOptions*, LPWSTR*);
	HRESULT (STDMETHODCALLTYPE* put_Language)(ICoreWebView2EnvironmentOptions*, LPCWSTR);
	HRESULT (STDMETHODCALLTYPE* get_TargetCompatibleBrowserVersion)(ICoreWebView2EnvironmentOptions*, LPWSTR*);
	HRESULT (STDMETHODCALLTYPE* put_TargetCompatibleBrowserVersion)(ICoreWebView2EnvironmentOptions*, LPCWSTR);
	HRESULT (STDMETHODCALLTYPE* get_AllowSingleSignOnUsingOSPrimaryAccount)(ICoreWebView2EnvironmentOptions*, BOOL*);
	HRESULT (STDMETHODCALLTYPE* put_AllowSingleSignOnUsingOSPrimaryAccount)(ICoreWebView2EnvironmentOptions*, BOOL);
} ICoreWebView2EnvironmentOptionsVtbl;
struct ICoreWebView2EnvironmentOptions { const ICoreWebView2EnvironmentOptionsVtbl* lpVtbl; };

typedef struct {
	BTRC_WEB_UNKNOWN(ICoreWebView2EnvironmentOptions4);
	HRESULT (STDMETHODCALLTYPE* GetCustomSchemeRegistrations)(ICoreWebView2EnvironmentOptions4*, UINT32*, ICoreWebView2CustomSchemeRegistration***);
	HRESULT (STDMETHODCALLTYPE* SetCustomSchemeRegistrations)(ICoreWebView2EnvironmentOptions4*, UINT32, ICoreWebView2CustomSchemeRegistration**);
} ICoreWebView2EnvironmentOptions4Vtbl;
struct ICoreWebView2EnvironmentOptions4 { const ICoreWebView2EnvironmentOptions4Vtbl* lpVtbl; };

typedef struct {
	BTRC_WEB_UNKNOWN(ICoreWebView2CustomSchemeRegistration);
	HRESULT (STDMETHODCALLTYPE* get_SchemeName)(ICoreWebView2CustomSchemeRegistration*, LPWSTR*);
	HRESULT (STDMETHODCALLTYPE* get_TreatAsSecure)(ICoreWebView2CustomSchemeRegistration*, BOOL*);
	HRESULT (STDMETHODCALLTYPE* put_TreatAsSecure)(ICoreWebView2CustomSchemeRegistration*, BOOL);
	HRESULT (STDMETHODCALLTYPE* GetAllowedOrigins)(ICoreWebView2CustomSchemeRegistration*, UINT32*, LPWSTR**);
	HRESULT (STDMETHODCALLTYPE* SetAllowedOrigins)(ICoreWebView2CustomSchemeRegistration*, UINT32, LPCWSTR*);
	HRESULT (STDMETHODCALLTYPE* get_HasAuthorityComponent)(ICoreWebView2CustomSchemeRegistration*, BOOL*);
	HRESULT (STDMETHODCALLTYPE* put_HasAuthorityComponent)(ICoreWebView2CustomSchemeRegistration*, BOOL);
} ICoreWebView2CustomSchemeRegistrationVtbl;
struct ICoreWebView2CustomSchemeRegistration { const ICoreWebView2CustomSchemeRegistrationVtbl* lpVtbl; };

typedef struct {
	BTRC_WEB_UNKNOWN(ICoreWebView2CreateCoreWebView2ControllerCompletedHandler);
	HRESULT (STDMETHODCALLTYPE* Invoke)(ICoreWebView2CreateCoreWebView2ControllerCompletedHandler*, HRESULT, ICoreWebView2Controller*);
} ICoreWebView2CreateCoreWebView2ControllerCompletedHandlerVtbl;
struct ICoreWebView2CreateCoreWebView2ControllerCompletedHandler { const ICoreWebView2CreateCoreWebView2ControllerCompletedHandlerVtbl* lpVtbl; };

typedef struct {
	BTRC_WEB_UNKNOWN(ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler);
	HRESULT (STDMETHODCALLTYPE* Invoke)(ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler*, HRESULT, ICoreWebView2Environment*);
} ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandlerVtbl;
struct ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler { const ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandlerVtbl* lpVtbl; };

typedef struct {
	BTRC_WEB_UNKNOWN(ICoreWebView2AddScriptToExecuteOnDocumentCreatedCompletedHandler);
	HRESULT (STDMETHODCALLTYPE* Invoke)(ICoreWebView2AddScriptToExecuteOnDocumentCreatedCompletedHandler*, HRESULT, LPCWSTR);
} ICoreWebView2AddScriptToExecuteOnDocumentCreatedCompletedHandlerVtbl;
struct ICoreWebView2AddScriptToExecuteOnDocumentCreatedCompletedHandler { const ICoreWebView2AddScriptToExecuteOnDocumentCreatedCompletedHandlerVtbl* lpVtbl; };

typedef struct {
	BTRC_WEB_UNKNOWN(ICoreWebView2NavigationStartingEventHandler);
	HRESULT (STDMETHODCALLTYPE* Invoke)(ICoreWebView2NavigationStartingEventHandler*, ICoreWebView2*, ICoreWebView2NavigationStartingEventArgs*);
} ICoreWebView2NavigationStartingEventHandlerVtbl;
struct ICoreWebView2NavigationStartingEventHandler { const ICoreWebView2NavigationStartingEventHandlerVtbl* lpVtbl; };

typedef struct {
	BTRC_WEB_UNKNOWN(ICoreWebView2NavigationCompletedEventHandler);
	HRESULT (STDMETHODCALLTYPE* Invoke)(ICoreWebView2NavigationCompletedEventHandler*, ICoreWebView2*, ICoreWebView2NavigationCompletedEventArgs*);
} ICoreWebView2NavigationCompletedEventHandlerVtbl;
struct ICoreWebView2NavigationCompletedEventHandler { const ICoreWebView2NavigationCompletedEventHandlerVtbl* lpVtbl; };

typedef struct {
	BTRC_WEB_UNKNOWN(ICoreWebView2NewWindowRequestedEventHandler);
	HRESULT (STDMETHODCALLTYPE* Invoke)(ICoreWebView2NewWindowRequestedEventHandler*, ICoreWebView2*, ICoreWebView2NewWindowRequestedEventArgs*);
} ICoreWebView2NewWindowRequestedEventHandlerVtbl;
struct ICoreWebView2NewWindowRequestedEventHandler { const ICoreWebView2NewWindowRequestedEventHandlerVtbl* lpVtbl; };

typedef struct {
	BTRC_WEB_UNKNOWN(ICoreWebView2WebMessageReceivedEventHandler);
	HRESULT (STDMETHODCALLTYPE* Invoke)(ICoreWebView2WebMessageReceivedEventHandler*, ICoreWebView2*, ICoreWebView2WebMessageReceivedEventArgs*);
} ICoreWebView2WebMessageReceivedEventHandlerVtbl;
struct ICoreWebView2WebMessageReceivedEventHandler { const ICoreWebView2WebMessageReceivedEventHandlerVtbl* lpVtbl; };

typedef struct {
	BTRC_WEB_UNKNOWN(ICoreWebView2WebResourceRequestedEventHandler);
	HRESULT (STDMETHODCALLTYPE* Invoke)(ICoreWebView2WebResourceRequestedEventHandler*, ICoreWebView2*, ICoreWebView2WebResourceRequestedEventArgs*);
} ICoreWebView2WebResourceRequestedEventHandlerVtbl;
struct ICoreWebView2WebResourceRequestedEventHandler { const ICoreWebView2WebResourceRequestedEventHandlerVtbl* lpVtbl; };

#undef BTRC_WEB_UNKNOWN
#endif
