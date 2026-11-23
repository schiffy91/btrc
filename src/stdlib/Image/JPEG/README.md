# JPEG

`Library.Image.JPEG` reads and writes JPEG bytes using BTRC and the host math library. It needs no native image codec. `JPEG.decode(bytes, maxPixels)` returns an `Image` in stored orientation. The default limit is 64 million pixels. The decoder checks padded coefficient storage separately. `JPEG.encode(image, quality)` writes an opaque baseline RGB image as full-resolution YCbCr, discarding alpha. Quality ranges from 1 to 100 and defaults to 82.

The reader supports 8-bit Huffman-coded sequential and progressive DCT, restart intervals, grayscale, YCbCr, RGB, CMYK, and Adobe YCCK. It expands subsampled chroma by replication. Color component conversion does not perform ICC color management. Arithmetic coding, lossless JPEG, and higher sample precisions are outside this codec's supported formats. Invalid data and unsupported formats throw.

Use `JPEGHeader.inspect(bytes)` for display dimensions and EXIF orientation without decoding pixels. `JPEGPhoto(bytes)` decodes once for multiple previews. Its `thumbnail(maxWidth, maxHeight, quality)` averages each output pixel's source area, fits either aspect ratio without upscaling, and applies all eight EXIF orientations. RGB photographs retain their embedded color profile. The output omits EXIF, including location data.
