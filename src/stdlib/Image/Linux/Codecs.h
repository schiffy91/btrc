/* libpng's simplified API keeps its control block behind a struct with an
 * inline message array the typed importer does not lower; these adapters
 * expose the two calls the decoder needs as plain scalars and buffers. */
#include <png.h>
#include <turbojpeg.h>
#include <string.h>

/* Reads dimensions; 1 on success, 0 when the bytes are not a readable PNG. */
static inline int btrcPngHeader(const unsigned char* data, size_t size, unsigned int* width, unsigned int* height) {
	png_image image;
	memset(&image, 0, sizeof(image));
	image.version = PNG_IMAGE_VERSION;
	if (!png_image_begin_read_from_memory(&image, data, size)) { png_image_free(&image); return 0; }
	*width = image.width;
	*height = image.height;
	png_image_free(&image);
	return 1;
}

/* Decodes straight RGBA rows into `pixels`, which holds width * height * 4 bytes. */
static inline int btrcPngDecode(const unsigned char* data, size_t size, unsigned char* pixels, unsigned int expectedWidth, unsigned int expectedHeight) {
	png_image image;
	memset(&image, 0, sizeof(image));
	image.version = PNG_IMAGE_VERSION;
	if (!png_image_begin_read_from_memory(&image, data, size)) { png_image_free(&image); return 0; }
	if (image.width != expectedWidth || image.height != expectedHeight) { png_image_free(&image); return 0; }
	image.format = PNG_FORMAT_RGBA;
	int ok = png_image_finish_read(&image, NULL, pixels, 0, NULL) ? 1 : 0;
	png_image_free(&image);
	return ok;
}
