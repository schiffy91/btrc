# Library.COM

The COM apartment and the runtime that compiler-generated COM bindings call
(interop step 5, [native-interop-ownership.md](../../../docs/design/native-interop-ownership.md)
section 2.4).

- `COMApartment` enters a single-threaded apartment on the calling thread
  (`initialize`, CoInitializeEx), reports the interface claims BTRC values
  hold (`liveClaims`) and the generated COM sinks not yet freed
  (`liveSinks`), and leaves it (`uninitialize`, CoUninitialize).
  Uninitializing with a claim still live terminates.
- `COM.h` and `COMRuntime.c` own the apartment's thread, the claim count and
  the sink count. Every generated adapter of an `ownership = "com"` resource
  checks that it runs on the apartment's thread before it calls COM, and
  counts each claim it adopts or ends; every generated sink counts itself
  while it is allocated. `btrcCOMTextUnits`, `btrcCOMTextLength` and
  `btrcCOMEncodeText` copy the UTF-16 BSTR and CoTaskMemAlloc strings of
  `copied-outputs` into BTRC strings. A program with COM resources must
  import `Library.COM.COMApartment`.

On Windows, CoInitializeEx and CoUninitialize come from ole32, and the
package's link records (`native.libraries`) link ole32, uuid (the SDK's IID
objects) and oleaut32 (SysFreeString) into every program that loads it.
Elsewhere there is no COM runtime, so the program supplies both functions, as
the proxy COM fixtures do (`src/tests/python/test_native_com_interfaces.py`,
`src/tests/python/test_native_com_sinks.py`).
