# FreeType provider boundary

The BTRC font domain is implemented in `FontFace.btrc`, `Font.btrc` and
`Raster.btrc`. `FontSnapshotConformance.btrc` exercises copied signed-pitch
bitmap data, coverage, UTF-8, metrics, layout and explicit surface ownership.
Those deterministic snapshots do not qualify the native FreeType adapter.

The private `FreeType/FreeTypeFace.btrc` setup transaction performs
`FT_Init_FreeType`, `FT_New_Face` with face index zero, and
`FT_Set_Pixel_Sizes(face, 0, pixelSize)`. It uses existing native unique owners,
retains the library dependency and explicitly closes the face first. No raw
native handle crosses the provider boundary. Actual Arial load, missing-path
failure, invalid-size failure and repeated teardown passed both compilers with
optimized and ASan/UBSan builds (100 iterations each). This is setup proof,
not glyph rasterization or allocation-fault qualification.

The cleanup policy is specific to valid freshly initialized claims whose
reference count remains one; this provider does not import native retain
functions or expose handles. In FreeType 2.14.3, `FT_Done_Face` removes and
destroys that face, and `FT_Done_FreeType` destroys the library and its memory
manager. See the actual [face/library implementation](https://github.com/freetype/freetype/blob/VER-2-14-3/src/base/ftobjs.c)
and [FreeType teardown implementation](https://github.com/freetype/freetype/blob/VER-2-14-3/src/base/ftinit.c).

The implemented compiler primitive is an owner-admitted record-path snapshot
with bounded byte copying. Each glyph call serializes face mutation and performs
all of the following before another `FT_Load_Char` is admitted:

1. Call `FT_Load_Char(face, codepoint, render ? FT_LOAD_RENDER : FT_LOAD_DEFAULT)`.
   On failure return no glyph and do not advance the pen.
2. Read `face->glyph->advance.x`, `bitmap_left`, `bitmap_top`, and bitmap
   `width`, `rows`, signed `pitch`, `pixel_mode`, and `num_grays`.
3. Validate dimensions before narrowing unsigned native values to BTRC ints.
   For supported nonempty bitmaps validate a non-null buffer and row extent,
   then copy `abs((int64)pitch) * rows` bytes into owned storage. The copy must
   precede the next glyph load; retaining the face alone does not stabilize its
   mutable glyph-slot buffer. Preserve padding and signed pitch. Unsupported
   pixel modes carry advance but produce no ink.
4. Construct the owned `FontGlyph`; native pointers are no longer needed.

Metrics similarly snapshot `face->size->metrics.ascender` and `height` as signed
26.6 values under admission. Domain code truncates fixed-point values toward
zero, saturates geometry and widths, and modulates the caller's alpha by glyph
coverage before using the existing BTRC source-over blender.

The `record-snapshots` binding table projects selected nested SDK paths into
ordinary owning classes. The optional `byte-plane` table names its copied byte
field and the SDK pointer, pixel width, row count and signed pitch. These paths
are checked by Clang and the importer; they do not expose native pointers to
BTRC consumers. Generated copy functions take an authenticated owner and, for
a byte plane, an explicit `maximumBytes` argument. Negative bounds or invalid
metadata return null with every owner lease unwound. Zero width or rows yields
owned empty bytes without reading a data pointer. Native allocation follows
the existing fail-fast class/Bytes policy.

The foreign SDK promises storage valid for the whole strided span while the
provider's mutation gate is held. For negative pitch the native pointer names
the logical first row: after checked address arithmetic, copying begins at the
lowest-address row and preserves signed pitch in the snapshot. Pixel width is
not interpreted as a byte count by the compiler; FontGlyph checks supported
format-specific row coverage. The provider uses a 64 MiB per-glyph bound.

`GUI.FreeType.load(path, pixelSize)` is the optional public factory. Core Font
and Raster remain SDK-free. Face metrics are copied during initialization;
the private glyph gate covers FT_Load_Char, snapshot copying and construction
of the immutable domain glyph. Measurement uses a scalar advance snapshot.
The admission method assigns the result inside try/finally and returns after
the finalizer; BTRC currently does not run finally on early return from try.

Reference native qualification now passes: actual Arial load, missing-path and
invalid-size cleanup, accented glyph loading/measurement, empty space glyphs,
glyph bytes surviving subsequent loads and owner closure, Unicode alpha
rasterization, explicit surface selection retention/deselection, and 100
repeated setup/teardown cycles. The test-only SDK fixture covers unique and RC
owners, positive/negative pitch, padding, empty planes, null intermediate
paths, invalid dimensions, zero/LLONG_MIN pitch, oversized spans and address
underflow/overflow. Optimized and ASan/UBSan runs pass. Allocation fault
injection and overlapping native thread admission are not yet qualified.

The fresh snapshot-enabled selfhost gate passed. The real factory drives
`GuiFontConformance.btrc` and `examples/gui/FontSmoke.btrc`. The old C loader,
process-global font dispatcher, color helper, old boundary test, archive build
rules, hosted ABI entries and runtime feature hooks have been removed. Existing
global-font thread synchronization was deliberately replaced by explicit
per-surface ownership, not another process-global mechanism. Color/coverage
proof lives in the actual BTRC font-domain and native raster tests.

Qualification checkpoint: `FontDomainMatrix.log` records 12 passing domain,
surface and example cases; `FreeTypeSetupMatrix.log` records four passing native
setup cases with compiler `bd227d05ba928b633ae3d47a267f5e1d`.
The subsequent `FontFinalMatrix.log` has nine passing reference/headless cases;
its eight selfhost cases stop at package resolution because the concurrently
extended CoreAudio owned-output manifest requires a newer compiler schema.
That current-snapshot selfhost rerun remains open, not a passing font matrix.
The corpus direct-import audit passes all four checks.

Latest reference checkpoint: `RecordSnapshotReference.log` has 20 passing
cases, `FreeTypeSnapshotReference.log` has four, and
`FreeTypeFactoryReference.log` has four. Both compiler implementations are
mirrored and the complete compiler semantic preflight reports zero errors.
The header reader with requested record paths is built separately at
`build/nativeHeaderReaderSnapshot/bin/btrc-native-header`.

`FontSnapshotSelfhost.log` records 36 passing cases with compiler
`7234ec4f05e2978942909725734e7f5f`; `FontDomainFinalMatrix.log` adds four passing
SDK-free domain cases across both compilers with optimized and sanitizer
builds. Allocation fault injection and simultaneous native face admission
remain explicitly unqualified; neither is represented as passing coverage.
