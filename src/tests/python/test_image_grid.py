"""End-to-end headless GPU and interaction tests for Library.GUI ImageGrid, ImageTileCache, and ImageGallery."""

import subprocess
from pathlib import Path

from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder


def _run_btrc(native_project, native_compile, source_code: str) -> subprocess.CompletedProcess:
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "btrc.toml").write_text('manifest-version = 1\n[package]\nname = "imageGridE2E"\n')
    source.write_text(source_code)
    plan = root / "Probe.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Probe.c"
    generated.write_text(compiled.c_source)

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    binary = root / "probe"
    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=binary, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    return subprocess.run([str(binary)], capture_output=True, text=True, check=False, timeout=60)


def test_image_grid_dynamic_layouts_shapes_and_cache(native_project, native_compile):
    program = """import Library.App;
import Library.GPU.GPUDevice;
import Library.GPU.GPUTexture;
import Library.GUI.ImageGallery;
import Library.GUI.ImageGrid;
import Library.GUI.ImageTileCache;
import Library.GUI.MediaPagerInteraction;
import Library.GUI.ZoomGridInteraction;
import Library.Image.Pixels;
import Library.IO;
import Library.Math;
import Library.Testing;
import Library.Vector;

class SyntheticSource implements IImageGridSource {
\tpublic int count;

\tpublic SyntheticSource(int count) { self.count = count; }

\tpublic int itemCount() { return self.count; }

\tpublic float itemAspectRatio(int index) {
\t\tif (index % 3 == 0) { return 0.6667f; }
\t\tif (index % 3 == 1) { return 1.5f; }
\t\treturn 1.3333f;
\t}

\tpublic bool itemDimmed(int index) { return false; }

\tpublic bool itemFlagged(int index) { return false; }

\tpublic Image decodeItem(int index, int maxEdge) {
\t\tImage img = Image(32, 32);
\t\tfor (int y = 0; y < 32; y++) {
\t\t\tfor (int x = 0; x < 32; x++) {
\t\t\t\timg.setPixel(x, y, RGBA(220, 60, 40, 255));
\t\t\t}
\t\t}
\t\treturn img;
\t}

\tpublic void onAspectRatioResolved(int index, float aspectRatio) {}
}

int main() {
\t/* Confirm ImageGridOptions defaults (Justified + Cover/CenterFill + Rect). */
\tImageGridOptions opts = ImageGridOptions();
\tExpect.isTrue(opts.layout == IMAGE_GRID_JUSTIFIED, "default layout is justified");
\tExpect.isTrue(opts.fit == IMAGE_FIT_COVER, "default fit is cover/center-fill");
\tExpect.isTrue(opts.shape == IMAGE_SHAPE_RECT, "default shape is rect");

\tSyntheticSource source = SyntheticSource(48);
\tVector<int> order = [];
\tfor (int i = 0; i < 48; i++) { order.push(i); }

\tGPUDevice device = GPUDevice.openHeadless();
\tImageMicroAtlas micro = ImageMicroAtlas(device, 64, 4096, 32);
\tImageThumbnailAtlas thumbs = ImageThumbnailAtlas(device, 1, 1024, 256);
\tImagePreviewCache previews = ImagePreviewCache(device, 4);
\tImageGrid grid = ImageGrid.createForFormat(device, GPU_FORMAT_RGBA8_UNORM, 256);
\tGPUTexture rt = GPUTexture.create2D(device, 1000, 640, GPU_FORMAT_RGBA8_UNORM, false, true, true, true);

\t/* Seed item 0 (portrait 2:3): left half red, right half blue, full-cell packed. */
\tImage portrait = Image(40, 60);
\tfor (int y = 0; y < 60; y++) {
\t\tfor (int x = 0; x < 40; x++) {
\t\t\tportrait.setPixel(x, y, x < 20 ? RGBA(230, 30, 30, 255) : RGBA(30, 70, 235, 255));
\t\t}
\t}
\tImage solidGreen = Image(32, 32);
\tfor (int y = 0; y < 32; y++) {
\t\tfor (int x = 0; x < 32; x++) {
\t\t\tsolidGreen.setPixel(x, y, RGBA(30, 220, 50, 255));
\t\t}
\t}
\tmicro.uploadCell(0, portrait.scaled(32, 32));
\tfor (int i = 1; i < 48; i++) { micro.uploadCell(i, solidGreen); }

\t/* 1. Justified layout: constant outer border (gap) on left and right, shared row height. */
\tgrid.setLayout(IMAGE_GRID_JUSTIFIED);
\tgrid.setGap(8.0f);
\tgrid.setTargetTileSize(160.0f);
\tgrid.setCornerRadiusPx(5.0f);
\tint drawnJustified = grid.renderGridOffscreen(rt, source, order, micro, thumbs);
\tExpect.isTrue(drawnJustified > 8, "justified renders visible rows");
\tvar r0 = grid.lastVisibleRects.get(0);
\tfloat row0Right = 0.0f;
\tfor (int i = 0; i < grid.lastVisibleRects.length; i++) {
\t\tvar ri = grid.lastVisibleRects.get(i);
\t\tif (Math.fabs(ri.y - r0.y) < 1.0f) {
\t\t\tExpect.isTrue(Math.fabs(ri.height - r0.height) < 0.5f, "row items share height");
\t\t\trow0Right = ri.x + ri.width;
\t\t}
\t}
\tExpect.isTrue(Math.fabs(r0.x - 8.0f) < 0.5f, "justified left margin equals gap");
\tExpect.isTrue(Math.fabs(row0Right - 992.0f) < 1.0f, "justified right margin equals viewportW - gap");

\t/* 2. Dynamic runtime switch to Fixed Square (1:1) with CenterFill (Cover) vs Contain. */
\tgrid.setLayout(IMAGE_GRID_FIXED);
\tgrid.setFixedAspect(1.0f);
\tgrid.setFit(IMAGE_FIT_COVER);
\tgrid.setShape(IMAGE_SHAPE_RECT);
\tgrid.setCornerRadiusPx(0.0f);
\tint drawnSq = grid.renderGridOffscreen(rt, source, order, micro, thumbs);
\tExpect.isTrue(drawnSq > 8, "fixed square renders tiles");
\tvar sq0 = grid.lastVisibleRects.get(0);
\tExpect.isTrue(Math.fabs(sq0.width - sq0.height) < 1.5f, "fixed 1:1 produces square cells");
\tImage sqSnap = rt.readbackImage();
\t/* Portrait (0.667) inside square with COVER fills full width: left=red, right=blue. */
\tvar sqLeft = sqSnap.pixel((int)(sq0.x + sq0.width * 0.2f), (int)(sq0.y + sq0.height * 0.5f));
\tvar sqRight = sqSnap.pixel((int)(sq0.x + sq0.width * 0.8f), (int)(sq0.y + sq0.height * 0.5f));
\tExpect.isTrue(sqLeft.red > 180 && sqRight.blue > 180, "cover fills square width with photo pixels");

\t/* Switch to IMAGE_FIT_CONTAIN: portrait in square gets dark pillarbox bars on far left/right. */
\tgrid.setFit(IMAGE_FIT_CONTAIN);
\tgrid.renderGridOffscreen(rt, source, order, micro, thumbs);
\tImage containSnap = rt.readbackImage();
\tvar barPx = containSnap.pixel((int)(sq0.x + 3.0f), (int)(sq0.y + sq0.height * 0.5f));
\tExpect.isTrue(barPx.red < 60 && barPx.blue < 60, "contain renders pillarbox mat for portrait in square");

\t/* 3. Dynamic runtime switch to Fixed 4:3 rectangle + Circle shape (corners clip to background). */
\tgrid.setFixedAspect(4.0f / 3.0f);
\tgrid.setFit(IMAGE_FIT_COVER);
\tgrid.setShape(IMAGE_SHAPE_CIRCLE);
\tgrid.renderGridOffscreen(rt, source, order, micro, thumbs);
\tvar rect0 = grid.lastVisibleRects.get(0);
\tExpect.isTrue(Math.fabs((rect0.width / rect0.height) - (4.0f / 3.0f)) < 0.05f, "fixed 4:3 cell aspect");
\tImage circleSnap = rt.readbackImage();
\tvar cornerPx = circleSnap.pixel((int)(rect0.x + 2.0f), (int)(rect0.y + 2.0f));
\tExpect.isTrue(cornerPx.red < 40 && cornerPx.green < 40 && cornerPx.blue < 45, "circle shape clips tile corners to background");

\t/* 4. Dynamic runtime switch to Squircle, Capsule, and vertical column Masonry (constant outer border). */
\tgrid.setShape(IMAGE_SHAPE_SQUIRCLE);
\tgrid.renderGridOffscreen(rt, source, order, micro, thumbs);
\tgrid.setShape(IMAGE_SHAPE_CAPSULE);
\tgrid.renderGridOffscreen(rt, source, order, micro, thumbs);
\tgrid.setLayout(IMAGE_GRID_MASONRY);
\tgrid.setShape(IMAGE_SHAPE_RECT);
\tgrid.setCornerRadiusPx(5.0f);
\tint drawnMasonry = grid.renderGridOffscreen(rt, source, order, micro, thumbs);
\tExpect.isTrue(drawnMasonry > 8, "column masonry renders visible tiles");
\tvar m0 = grid.lastVisibleRects.get(0);
\tExpect.isTrue(m0.height > m0.width * 1.4f, "column masonry preserves portrait height");

\t/* 5. ImagePreviewCache active pinning & eviction + ImageTileStreamer cancellation. */
\tpreviews.setActiveItem(0);
\tpreviews.uploadImage(0, portrait);
\tfor (int k = 1; k <= 6; k++) { previews.uploadImage(k, solidGreen); }
\tExpect.isTrue(previews.has(0), "pinned active preview survives eviction");
\tImageTileTier tier = grid.renderPreviewOffscreen(rt, source, 0, micro, thumbs, previews);
\tExpect.isTrue(tier == IMAGE_TILE_PREVIEW, "resident preview renders directly from preview cache");

\tImageTileStreamer streamer = ImageTileStreamer(source, micro, thumbs, previews, 2, 8);
\tstreamer.beginViewportJump(10);
\tstreamer.requestThumbnail(10, true);
\tstreamer.pumpDispatch();
\tstreamer.drainUploads(2.0f, true);
\tExpect.intEq(streamer.totalCancelledGenerations, 1, "viewport jump cancels stale generation");
\tstreamer.close();

\t/* 6. MediaPagerInteraction + ZoomGridInteraction smoke check. */
\tMediaPagerInteraction pager = MediaPagerInteraction();
\tpager.open(1, 10, 1.5);
\tExpect.intEq(pager.stepImmediate(1), 2, "pager step advances");
\tZoomGridInteraction zg = ZoomGridInteraction(180.0, 56.0, 0.56, 1.18);
\tvar z = zg.magnify(AppMagnifyEvent(0.2, 400.0, 300.0, APP_GESTURE_BEGAN), 800.0, 3);
\tExpect.isTrue(z.cellWidth > 200.0, "zoom grid scales continuously");

\trt.close();
\tgrid.close();
\tpreviews.close();
\tthumbs.close();
\tmicro.close();
\tdevice.close();
\tprint("PASS_IMAGE_GRID_STDLIB\\n");
\treturn 0;
}
"""
    res = _run_btrc(native_project, native_compile, program)
    assert res.returncode == 0, (res.stdout, res.stderr)
    assert "PASS_IMAGE_GRID_STDLIB" in res.stdout


def test_pager_settle_animation_and_dock_scrubber(native_project, native_compile):
    program = """import Library.App;
import Library.GUI.FilmstripScrubber;
import Library.GUI.MediaPagerInteraction;
import Library.IO;
import Library.Math;
import Library.Testing;

int main() {
\t/* 1. Regression oracle for drag-to-next-photo settle animation bug:
\t * Calling setAspectRatio() and onResize() every frame during settle MUST NOT reset page to 0. */
\tMediaPagerInteraction pager = MediaPagerInteraction();
\tpager.open(2, 20, 1.5);
\tdouble stageW = 1200.0;
\tdouble stageH = 800.0;
\tpager.pointerDown(800.0, 400.0, stageW, stageH, 0.0);
\tpager.pointerMove(600.0, 400.0, stageW, stageH, 20.0);
\tpager.pointerMove(300.0, 400.0, stageW, stageH, 40.0);
\tExpect.isTrue(pager.page < -400.0, "drag left moves page negative");
\tbool wasTap = pager.pointerUp(stageW, stageH, 45.0, false);
\tExpect.isTrue(!wasTap, "drag release is not a tap");
\tExpect.isTrue(pager.animating, "release starts settle animation to next photo");

\t/* Simulate 120fps render loop calling setAspectRatio every frame (even with refined ratio). */
\tdouble prevPage = pager.page;
\tint animatedFrames = 0;
\tbool committed = false;
\tfor (int step = 1; step <= 40; step++) {
\t\tdouble tMs = 45.0 + (double)step * 8.0;
\t\t/* Even if preview finishes decoding mid-animation with slightly different ratio: */
\t\tpager.setAspectRatio(1.501, stageW, stageH);
\t\tpager.onResize(stageW, stageH);
\t\tvar out = pager.tick(tMs, stageW, stageH);
\t\tif (out.kind == PAGER_EVENT_INDEX_CHANGED) {
\t\t\tExpect.intEq(out.index, 3, "commits to next photo after sliding into place");
\t\t\tExpect.isTrue(Math.fabs(pager.page) < 0.01, "resets page to 0 upon commit");
\t\t\tcommitted = true;
\t\t\tbreak;
\t\t}
\t\t/* During settle animation, page MUST progress monotonically toward -stageW (never reset to 0!). */
\t\tExpect.isTrue(pager.page < -400.0, "page must never snap back to 0 during settle animation");
\t\tExpect.isTrue(pager.page <= prevPage + 0.01, "page slides monotonically left toward -stageW");
\t\tprevPage = pager.page;
\t\tanimatedFrames++;
\t}
\tExpect.isTrue(committed, "settle animation committed index change");
\tExpect.isTrue(animatedFrames >= 15, "smooth multi-frame slide animation before commit");

\t/* 2. Dock-style FilmstripScrubber interaction oracle:
\t * Auto-hidden pill -> tap expands & pins -> two-finger scroll -> click-drag scrub -> tap selects -> tap outside collapses. */
\tFilmstripScrubber scrubber = FilmstripScrubber();
\tscrubber.reset(50, 0);
\tExpect.isTrue(!scrubber.isExpanded(), "starts auto-hidden as tiny pill");
\tvar pill = scrubber.collapsedPillRect(stageW, stageH, 1.0);
\tExpect.isTrue(pill.height <= 10.0f && pill.width <= 120.0f, "collapsed pill is compact");

\t/* Tap on collapsed pill expands and pins open. */
\tAppKeyModifiers noMod = AppKeyModifiers(false, false, false, false);
\tAppPointerEvent tapDown = AppPointerEvent(APP_POINTER_PRESSED, APP_POINTER_BUTTON_PRIMARY, stageW * 0.5, stageH - 12.0, noMod, 1);
\tvar o1 = scrubber.onPointer(tapDown, stageW * 0.5, stageH - 12.0, stageW, stageH, 1.0, 100.0);
\tExpect.isTrue(o1.consumed, "tapping collapsed pill consumes press");
\tExpect.isTrue(scrubber.isPinnedOpen(), "tapping collapsed pill pins Dock open");
\tfor (int f = 1; f <= 30; f++) {
\t\tscrubber.tick(100.0 + (double)f * 10.0, stageW, stageH, 1.0);
\t}
\tExpect.isTrue(scrubber.openProgress > 0.95, "Dock smoothly animates to expanded");
\tvar tiles = scrubber.layoutVisibleTiles(stageW, stageH, 1.0);
\tExpect.isTrue(tiles.length > 5, "expanded Dock lays out visible thumbnails");

\t/* Two-finger horizontal scroll over expanded Dock scrolls scrubber and consumes event. */
\tdouble scrollBefore = scrubber.scrollX;
\tAppScrollEvent hScroll = AppScrollEvent(-120.0, 0.0, stageW * 0.5, stageH - 40.0, true, APP_SCROLL_CHANGED, APP_SCROLL_NONE, noMod);
\tbool scrollHandled = scrubber.onScroll(hScroll, 1.0, stageW, stageH, 450.0);
\tExpect.isTrue(scrollHandled, "two-finger scroll over expanded Dock is consumed");
\tExpect.isTrue(scrubber.scrollX > scrollBefore + 50.0, "two-finger horizontal scroll advances filmstrip");

\t/* Click-and-drag scrubbing inside expanded Dock moves scrollX with momentum. */
\tdouble beforeDrag = scrubber.scrollX;
\tAppPointerEvent dDown = AppPointerEvent(APP_POINTER_PRESSED, APP_POINTER_BUTTON_PRIMARY, 700.0, stageH - 40.0, noMod, 1);
\tAppPointerEvent dMove = AppPointerEvent(APP_POINTER_DRAGGED, APP_POINTER_BUTTON_PRIMARY, 520.0, stageH - 40.0, noMod, 1);
\tAppPointerEvent dUp = AppPointerEvent(APP_POINTER_RELEASED, APP_POINTER_BUTTON_PRIMARY, 520.0, stageH - 40.0, noMod, 1);
\tscrubber.onPointer(dDown, 700.0, stageH - 40.0, stageW, stageH, 1.0, 500.0);
\tscrubber.onPointer(dMove, 520.0, stageH - 40.0, stageW, stageH, 1.0, 520.0);
\tvar dragOut = scrubber.onPointer(dUp, 520.0, stageH - 40.0, stageW, stageH, 1.0, 530.0);
\tExpect.isTrue(dragOut.consumed && dragOut.kind == SCRUBBER_EVENT_NONE, "drag scrub does not accidentally fire tap select");
\tExpect.isTrue(scrubber.scrollX > beforeDrag + 150.0, "drag scrub translates filmstrip");

\t/* Tap on a visible thumbnail jumps directly to that photo. */
\tvar afterTiles = scrubber.layoutVisibleTiles(stageW, stageH, 1.0);
\tvar targetSlot = afterTiles.get(afterTiles.length / 2);
\tdouble tapX = (double)(targetSlot.x + targetSlot.width * 0.5f);
\tdouble tapY = (double)(targetSlot.y + targetSlot.height * 0.5f);
\tscrubber.onPointer(AppPointerEvent(APP_POINTER_PRESSED, APP_POINTER_BUTTON_PRIMARY, tapX, tapY, noMod, 1), tapX, tapY, stageW, stageH, 1.0, 600.0);
\tvar selOut = scrubber.onPointer(AppPointerEvent(APP_POINTER_RELEASED, APP_POINTER_BUTTON_PRIMARY, tapX, tapY, noMod, 1), tapX, tapY, stageW, stageH, 1.0, 615.0);
\tExpect.isTrue(selOut.kind == SCRUBBER_EVENT_SELECT_POS, "tapping scrubber thumbnail selects photo");
\tExpect.intEq(selOut.position, targetSlot.visiblePos, "selected position matches tapped thumbnail");

\t/* Tapping outside expanded Dock collapses it back to tiny pill. */
\tvar outTap = scrubber.onPointer(AppPointerEvent(APP_POINTER_PRESSED, APP_POINTER_BUTTON_PRIMARY, 600.0, 200.0, noMod, 1), 600.0, 200.0, stageW, stageH, 1.0, 700.0);
\tExpect.isTrue(!outTap.consumed, "tap outside Dock passes through to viewer");
\tfor (int f = 1; f <= 40; f++) {
\t\tscrubber.tick(700.0 + (double)f * 12.0, stageW, stageH, 1.0);
\t}
\tExpect.isTrue(scrubber.openProgress < 0.05, "Dock smoothly auto-hides back to collapsed pill");

\tprint("PASS_PAGER_AND_SCRUBBER\\n");
\treturn 0;
}
"""
    res = _run_btrc(native_project, native_compile, program)
    assert res.returncode == 0, (res.stdout, res.stderr)
    assert "PASS_PAGER_AND_SCRUBBER" in res.stdout
