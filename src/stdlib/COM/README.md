# Library.COM

The COM apartment and the runtime that compiler-generated COM bindings call
(interop step 5, [native-interop-ownership.md](../../../docs/design/native-interop-ownership.md)
section 2.4).

- `COMApartment` enters a single-threaded apartment on the calling thread
  (`initialize`, CoInitializeEx), reports the interface claims BTRC values
  hold (`liveClaims`), and leaves it (`uninitialize`, CoUninitialize).
  Uninitializing with a claim still live terminates.
- `COM.h` and `COMRuntime.c` own the apartment's thread and the claim count.
  Every generated adapter of an `ownership = "com"` resource checks that it
  runs on the apartment's thread before it calls COM, and counts each claim
  it adopts or ends. A program with COM resources must import
  `Library.COM.COMApartment`.

On Windows, CoInitializeEx and CoUninitialize come from ole32. Elsewhere there
is no COM runtime, so the program supplies both functions, as the proxy COM
fixtures do (`src/tests/python/test_native_com_interfaces.py`).
