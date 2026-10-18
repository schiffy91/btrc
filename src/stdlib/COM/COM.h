/* COM for Library.COM. The manifest binds the btrcCOM* functions below to
 * COMApartment.btrc, and compiler-generated COM adapters call the claim and
 * apartment functions by name (docs/design/native-interop-ownership.md
 * section 2.4). COMRuntime.c owns the apartment and its claim count, because
 * that state is process-wide. */
#ifndef BTRC_COM_H
#define BTRC_COM_H

/* The apartment, for COMApartment.btrc. Initialization enters a
 * single-threaded apartment on the calling thread and returns CoInitializeEx's
 * HRESULT: S_OK, S_FALSE, or a failure that leaves no apartment. */
int btrcCOMInitialize(void);
int btrcCOMInitialized(void);
long long btrcCOMLiveClaims(void);
void btrcCOMUninitialize(void);

/* For generated adapters. Every COM call, AddRef and Release first checks that
 * it runs on the apartment's thread; each interface pointer BTRC adopts or
 * AddRefs is one claim, and each Release ends one. */
void btrcCOMRequireApartment(void);
void btrcCOMClaim(void);
void btrcCOMUnclaim(void);

#endif
