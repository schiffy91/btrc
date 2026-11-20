#pragma once

#include <string.h>
#include <sodium.h>
#include <stddef.h>

/* libsodium declares its inputs `const unsigned char*`, and its stream state
 * as a structure of its own. btrc passes plain byte pointers, so each
 * operation the seam needs is one adapter over them. The state adapters take
 * the SODIUM_STREAM_STATE bytes the seam reserves; the assertion keeps that
 * size honest against the linked library's headers. */
_Static_assert(sizeof(crypto_secretstream_xchacha20poly1305_state) <= 64, "the seam's stream state is too small for libsodium's");
_Static_assert(crypto_secretstream_xchacha20poly1305_ABYTES == 17 && crypto_secretstream_xchacha20poly1305_HEADERBYTES == 24, "the seam's stream sizes differ from libsodium's");
_Static_assert(crypto_sign_SEEDBYTES == 32 && crypto_sign_PUBLICKEYBYTES == 32 && crypto_sign_SECRETKEYBYTES == 64 && crypto_sign_BYTES == 64, "the seam's signature sizes differ from libsodium's");
_Static_assert(crypto_kx_PUBLICKEYBYTES == 32 && crypto_kx_SECRETKEYBYTES == 32 && crypto_kx_SESSIONKEYBYTES == 32, "the seam's exchange sizes differ from libsodium's");

static inline int btrcSodiumStart(void) { return sodium_init() >= 0; }

static inline void btrcSodiumRandom(unsigned char* out, int length) { randombytes_buf(out, (size_t)length); }

static inline void btrcSodiumWipe(unsigned char* data, int length) { sodium_memzero(data, (size_t)length); }

static inline int btrcSodiumSigningKeys(unsigned char* seed, unsigned char* publicKey, unsigned char* secretKey) { return crypto_sign_seed_keypair(publicKey, secretKey, seed) == 0; }

static inline int btrcSodiumSign(unsigned char* signature, unsigned char* message, int length, unsigned char* secretKey) {
	return crypto_sign_detached(signature, NULL, message, (unsigned long long)length, secretKey) == 0;
}

static inline int btrcSodiumVerify(unsigned char* signature, unsigned char* message, int length, unsigned char* publicKey) {
	return crypto_sign_verify_detached(signature, message, (unsigned long long)length, publicKey) == 0;
}

static inline void btrcSodiumExchangeKeys(unsigned char* publicKey, unsigned char* secretKey) { crypto_kx_keypair(publicKey, secretKey); }

/* The two directions' keys; the side that connected is the client. Fails for
 * a peer key that is not a usable curve point. */
static inline int btrcSodiumSessionKeys(int initiator, unsigned char* receiving, unsigned char* sending, unsigned char* publicKey, unsigned char* secretKey, unsigned char* peerKey) {
	if (initiator) { return crypto_kx_client_session_keys(receiving, sending, publicKey, secretKey, peerKey) == 0; }
	return crypto_kx_server_session_keys(receiving, sending, publicKey, secretKey, peerKey) == 0;
}

/* BLAKE2b, 32 bytes. */
static inline void btrcSodiumHash(unsigned char* out, unsigned char* data, int length) { crypto_generichash(out, (size_t)32, data, (unsigned long long)length, NULL, (size_t)0); }

static inline void btrcSodiumSHA256(unsigned char* out, unsigned char* data, int length) { crypto_hash_sha256(out, data, (unsigned long long)length); }

static inline int btrcSodiumBeginSending(unsigned char* state, unsigned char* header, unsigned char* key) {
	crypto_secretstream_xchacha20poly1305_state stream;
	if (crypto_secretstream_xchacha20poly1305_init_push(&stream, header, key) != 0) { return 0; }
	memcpy(state, &stream, sizeof(stream));
	sodium_memzero(&stream, sizeof(stream));
	return 1;
}

static inline int btrcSodiumBeginReceiving(unsigned char* state, unsigned char* header, unsigned char* key) {
	crypto_secretstream_xchacha20poly1305_state stream;
	if (crypto_secretstream_xchacha20poly1305_init_pull(&stream, header, key) != 0) { return 0; }
	memcpy(state, &stream, sizeof(stream));
	sodium_memzero(&stream, sizeof(stream));
	return 1;
}

/* Seal one message into `sealed` (length + 17 bytes); the sealed length, or -1. */
static inline int btrcSodiumSeal(unsigned char* state, unsigned char* sealed, unsigned char* message, int length) {
	crypto_secretstream_xchacha20poly1305_state stream;
	unsigned long long written = 0;
	memcpy(&stream, state, sizeof(stream));
	int failed = crypto_secretstream_xchacha20poly1305_push(&stream, sealed, &written, message, (unsigned long long)length, NULL, 0, 0);
	memcpy(state, &stream, sizeof(stream));
	sodium_memzero(&stream, sizeof(stream));
	return failed ? -1 : (int)written;
}

/* Open one sealed message into `message`; its length, or -1 when the frame is
 * not the next one this stream's sender sealed. */
static inline int btrcSodiumOpen(unsigned char* state, unsigned char* message, unsigned char* sealed, int length) {
	crypto_secretstream_xchacha20poly1305_state stream;
	unsigned long long written = 0;
	unsigned char tag = 0;
	if (length < (int)crypto_secretstream_xchacha20poly1305_ABYTES) { return -1; }
	memcpy(&stream, state, sizeof(stream));
	int failed = crypto_secretstream_xchacha20poly1305_pull(&stream, message, &written, &tag, sealed, (unsigned long long)length, NULL, 0);
	memcpy(state, &stream, sizeof(stream));
	sodium_memzero(&stream, sizeof(stream));
	return failed ? -1 : (int)written;
}
