# PNG

`Library.Image.PNG` reads and writes PNG bytes in BTRC. It needs no native image codec and no zlib: the DEFLATE decoder and encoder, CRC-32 and Adler-32 are part of the module. `PNG.decode(bytes, maxPixels)` returns an `Image` of straight (not premultiplied) 8-bit RGBA. The default limit is 64 million pixels. `PNG.encode(image)` writes a non-interlaced 8-bit image, RGB when every pixel is opaque and RGBA otherwise.

The reader supports every colour type and bit depth of PNG 1.2: grayscale at 1, 2, 4, 8 and 16 bits, RGB at 8 and 16, palettes at 1, 2, 4 and 8, grayscale with alpha, and RGBA. It reads all five scanline filters, Adam7 interlacing, palette transparency, and `tRNS` colour keys. A 16-bit sample is rounded to the nearest 8-bit level, and a colour key is compared against the whole 16-bit sample first. By default pixels are returned as stored. The optional third argument to `PNG.decode` enables gamma conversion to 8-bit display RGB. Linux’s `SystemImageDecoder` uses this mode. It honors `gAMA` and `sRGB` and treats untagged 16-bit input as linear. Alpha and transparency keys stay in their original encoding. The decoder does not perform ICC profile conversion. An animated PNG decodes to its default image.

Use `PNGHeader.inspect(bytes)` for the dimensions, bit depth, colour type and interlacing without reading past the `IHDR` chunk.

## Untrusted input

Invalid data throws. The reader checks, in this order:

- the signature and the `IHDR` chunk, whose dimensions must fit an `Image` and `maxPixels` (`"PNG exceeds pixel limit"`). A scanline may not need more memory than the largest raster (`"PNG row exceeds limit"`);
- every chunk through `IEND`: its length against the file, its name, and its CRC-32. A damaged ancillary chunk is as fatal as a damaged critical one, and a file that ends before `IEND` is refused;
- that the `IDAT` bytes could inflate to the raster at all. DEFLATE expands at most 1032 times, so a file that claims more is refused before any raster is allocated;
- the zlib stream as it is read, one scanline at a time: the header, every block header and Huffman table, each back-reference against the declared window, each filter type, and at the end the Adler-32.

Memory is the raster, two scanlines and the 32 KiB DEFLATE window, whatever the stream claims. A failed raster or scanline allocation throws `"Could not allocate ..."`.

Some malformed files decode, as they do in libpng, because nothing in them is ambiguous: a `tRNS` chunk that is misplaced, repeated or the wrong length is ignored; a palette index past the palette is opaque black; a `PLTE` chunk in a grayscale image is ignored; and image data or bytes that follow a complete raster are left unread. An unknown critical chunk, a second `IHDR` or `PLTE`, and `IDAT` chunks separated by another chunk are refused.

## Writer

Each scanline takes the filter with the smallest sum of absolute differences. The zlib stream is one block of the fixed Huffman codes with greedy back-references through a hash of three-byte sequences. That is quick and compact for flat or smooth images; a tuned encoder with dynamic codes produces smaller files for photographs. The writer holds the filtered image in memory.
