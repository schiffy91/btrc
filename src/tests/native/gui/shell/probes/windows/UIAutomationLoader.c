/* The UI Automation client's IIDs (initguid.h turns the header's DEFINE_GUID
 * declarations into definitions) and its factory. */
#include <initguid.h>
#include "UIAutomation.h"

HRESULT UIAutomationCreate(IUIAutomation **automation) {
    *automation = NULL;
    return CoCreateInstance(&CLSID_CUIAutomation, NULL, CLSCTX_INPROC_SERVER, &IID_IUIAutomation, (void **)automation);
}
