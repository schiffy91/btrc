/* Process-wide COM state for Library.COM (docs/design/native-interop-ownership.md
 * section 2.4): the one apartment, the count of interface claims BTRC holds
 * in it and the count of live generated sink holders. Every generated COM
 * adapter checks the apartment before it calls COM and counts each claim it
 * takes or ends, so the apartment is never uninitialized while a BTRC value
 * still holds an interface. The UTF-16 helpers decode copied-outputs strings.
 *
 * On Windows, CoInitializeEx and CoUninitialize come from ole32, which the
 * package's link records name with uuid and oleaut32. Elsewhere the program
 * supplies both, as the proxy COM fixtures do: a real COM runtime exists only
 * on Windows.
 *
 * Locking: comLock guards every field below. It is held across CoInitializeEx
 * and CoUninitialize, neither of which calls back into this file. */
#include "COM.h"
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <windows.h>
#include <objbase.h>
#else
/* The program's stand-ins for ole32, with the Windows ABI's types. */
int32_t CoInitializeEx(void* reserved, uint32_t model);
void CoUninitialize(void);
#define COINIT_APARTMENTTHREADED 0x2
#endif

static pthread_mutex_t comLock = PTHREAD_MUTEX_INITIALIZER;
static int comActive;
static pthread_t comThread;
static long long comClaims;

static void comAbort(const char* message) {
	fprintf(stderr, "Library.COM: %s\n", message);
	abort();
}

/* With comLock held: whether the calling thread is the apartment's. */
static int comOnApartment(void) { return comActive && pthread_equal(comThread, pthread_self()); }

int btrcCOMInitialize(void) {
	pthread_mutex_lock(&comLock);
	if (comActive) {
		pthread_mutex_unlock(&comLock);
		comAbort("a COM apartment is already initialized");
	}
	int status = (int)CoInitializeEx(NULL, COINIT_APARTMENTTHREADED);
	if (status >= 0) {
		comActive = 1;
		comThread = pthread_self();
	}
	pthread_mutex_unlock(&comLock);
	return status;
}

int btrcCOMInitialized(void) {
	pthread_mutex_lock(&comLock);
	int active = comActive;
	pthread_mutex_unlock(&comLock);
	return active;
}

long long btrcCOMLiveClaims(void) {
	pthread_mutex_lock(&comLock);
	long long claims = comClaims;
	pthread_mutex_unlock(&comLock);
	return claims;
}

void btrcCOMUninitialize(void) {
	pthread_mutex_lock(&comLock);
	if (!comOnApartment()) {
		pthread_mutex_unlock(&comLock);
		comAbort("uninitialize outside the COM apartment's thread");
	}
	if (comClaims != 0) {
		long long claims = comClaims;
		pthread_mutex_unlock(&comLock);
		fprintf(stderr, "Library.COM: uninitialize with %lld live COM claims\n", claims);
		abort();
	}
	comActive = 0;
	CoUninitialize();
	pthread_mutex_unlock(&comLock);
}

void btrcCOMRequireApartment(void) {
	pthread_mutex_lock(&comLock);
	int onApartment = comOnApartment();
	pthread_mutex_unlock(&comLock);
	if (!onApartment) { comAbort("COM call outside its apartment"); }
}

void btrcCOMClaim(void) {
	pthread_mutex_lock(&comLock);
	comClaims++;
	pthread_mutex_unlock(&comLock);
}

void btrcCOMUnclaim(void) {
	pthread_mutex_lock(&comLock);
	if (comClaims == 0) {
		pthread_mutex_unlock(&comLock);
		comAbort("COM release without a claim");
	}
	comClaims--;
	pthread_mutex_unlock(&comLock);
}

/* Sink holders the generated COM sinks have allocated and not yet freed. A
 * source may keep a sink past its registration, so this only reports. */
static long long comSinks;

long long btrcCOMLiveSinks(void) {
	pthread_mutex_lock(&comLock);
	long long sinks = comSinks;
	pthread_mutex_unlock(&comLock);
	return sinks;
}

void btrcCOMSinkOpened(void) {
	pthread_mutex_lock(&comLock);
	comSinks++;
	pthread_mutex_unlock(&comLock);
}

void btrcCOMSinkClosed(void) {
	pthread_mutex_lock(&comLock);
	if (comSinks == 0) {
		pthread_mutex_unlock(&comLock);
		comAbort("COM sink freed twice");
	}
	comSinks--;
	pthread_mutex_unlock(&comLock);
}

/* UTF-16 text of copied-outputs. A BSTR's length prefix counts bytes, in the
 * four bytes before its first unit; a CoTaskMemAlloc string ends at U+0000. */
long long btrcCOMTextUnits(const void* units, int prefixed) {
	const uint16_t* text = units;
	if (prefixed) {
		uint32_t bytes;
		memcpy(&bytes, (const unsigned char*)units - sizeof bytes, sizeof bytes);
		return (long long)(bytes / 2u);
	}
	long long count = 0;
	while (text[count] != 0) { count++; }
	return count;
}

static unsigned int comScalar(const uint16_t* units, long long count, long long index, long long* width) {
	unsigned int unit = units[index];
	*width = 1;
	if (unit >= 0xD800 && unit <= 0xDBFF && index + 1 < count && units[index + 1] >= 0xDC00 && units[index + 1] <= 0xDFFF) {
		*width = 2;
		return 0x10000 + ((unit - 0xD800) << 10) + (units[index + 1] - 0xDC00u);
	}
	return unit >= 0xD800 && unit <= 0xDFFF ? 0xFFFD : unit;
}

long long btrcCOMTextLength(const void* units, long long count) {
	long long length = 0;
	for (long long index = 0, width = 1; index < count; index += width) {
		unsigned int point = comScalar(units, count, index, &width);
		if (point == 0) { return -1; }
		length += point < 0x80 ? 1 : point < 0x800 ? 2 : point < 0x10000 ? 3 : 4;
	}
	return length;
}

void btrcCOMEncodeText(const void* units, long long count, char* text) {
	unsigned char* out = (unsigned char*)text;
	for (long long index = 0, width = 1; index < count; index += width) {
		unsigned int point = comScalar(units, count, index, &width);
		if (point < 0x80) { *out++ = (unsigned char)point; }
		else if (point < 0x800) {
			*out++ = (unsigned char)(0xC0 | (point >> 6));
			*out++ = (unsigned char)(0x80 | (point & 0x3F));
		} else if (point < 0x10000) {
			*out++ = (unsigned char)(0xE0 | (point >> 12));
			*out++ = (unsigned char)(0x80 | ((point >> 6) & 0x3F));
			*out++ = (unsigned char)(0x80 | (point & 0x3F));
		} else {
			*out++ = (unsigned char)(0xF0 | (point >> 18));
			*out++ = (unsigned char)(0x80 | ((point >> 12) & 0x3F));
			*out++ = (unsigned char)(0x80 | ((point >> 6) & 0x3F));
			*out++ = (unsigned char)(0x80 | (point & 0x3F));
		}
	}
}
