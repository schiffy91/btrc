/* COM for Library.COM. The manifest binds the btrcCOM* functions below to
 * COMApartment.btrc, and compiler-generated COM adapters call the claim,
 * apartment, sink and text functions by name
 * (docs/design/native-interop-ownership.md section 2.4). COMRuntime.c owns
 * the apartment, its claim count and its sink count, because that state is
 * process-wide. */
#ifndef BTRC_COM_H
#define BTRC_COM_H

/* The apartment, for COMApartment.btrc. Initialization enters a
 * single-threaded apartment on the calling thread and returns CoInitializeEx's
 * HRESULT: S_OK, S_FALSE, or a failure that leaves no apartment. */
int btrcCOMInitialize(void);
int btrcCOMInitialized(void);
long long btrcCOMLiveClaims(void);
long long btrcCOMLiveSinks(void);
void btrcCOMUninitialize(void);

/* For generated adapters. Every COM call, AddRef and Release first checks that
 * it runs on the apartment's thread; each interface pointer BTRC adopts or
 * AddRefs is one claim, and each Release ends one. */
void btrcCOMRequireApartment(void);
void btrcCOMClaim(void);
void btrcCOMUnclaim(void);

/* For generated sink holders: one call when a holder is allocated, one when
 * it frees itself. */
void btrcCOMSinkOpened(void);
void btrcCOMSinkClosed(void);

/* For copied-outputs: a UTF-16 string's unit count, from a BSTR's length
 * prefix (prefixed) or up to its terminating U+0000; the UTF-8 length of its
 * first `count` units, or -1 when one is U+0000; and that encoding, written to
 * `text`, which holds the length's bytes. Unpaired surrogates become U+FFFD. */
long long btrcCOMTextUnits(const void* units, int prefixed);
long long btrcCOMTextLength(const void* units, long long count);
void btrcCOMEncodeText(const void* units, long long count, char* text);

#endif
