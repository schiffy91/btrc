/* Process-wide COM state for Library.COM (docs/design/native-interop-ownership.md
 * section 2.4): the one apartment and the count of interface claims BTRC holds
 * in it. Every generated COM adapter checks the apartment before it calls COM
 * and counts each claim it takes or ends, so the apartment is never
 * uninitialized while a BTRC value still holds an interface.
 *
 * On Windows, CoInitializeEx and CoUninitialize come from ole32. Elsewhere the
 * program supplies both, as the proxy COM fixtures do: a real COM runtime
 * exists only on Windows.
 *
 * Locking: comLock guards every field below. It is held across CoInitializeEx
 * and CoUninitialize, neither of which calls back into this file. */
#include "COM.h"
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

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
