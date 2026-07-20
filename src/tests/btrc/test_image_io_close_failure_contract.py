"""Deterministic image close failures without a production test hook."""

from pathlib import Path

from src.tests.btrc.production_readiness_harness import run_strict_pair
from src.tests.btrc.string_coercion_harness import compile_pair

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


SOURCE = """
    import std.image;
    import std.fs;

    #include <assert.h>

    extern void imageIoFailNextFileClose();

    int main() {
        string dir = FileSystem.tempDir("btrc_image_close_failures");
        assert(FileSystem.isDir(dir));

        Image source = Image(1, 1);
        source.setRGBA(0, 0, 10, 20, 30, 40);
        string ppmPath = PathTools.join(dir, "valid.ppm");
        string bmpPath = PathTools.join(dir, "valid.bmp");
        assert(ImageIO.savePpm(source, ppmPath));
        assert(ImageIO.saveBmp(source, bmpPath));

        imageIoFailNextFileClose();
        ImageLoad automatic = ImageIO.load(ppmPath);
        assert(!automatic.ok());
        assert(automatic.error.equals(f"cannot close image: {ppmPath}"));

        imageIoFailNextFileClose();
        ImageLoad ppm = ImageIO.loadPpm(ppmPath);
        assert(!ppm.ok());
        assert(ppm.error.equals(f"cannot close PPM: {ppmPath}"));

        imageIoFailNextFileClose();
        ImageLoad bmp = ImageIO.loadBmp(bmpPath);
        assert(!bmp.ok());
        assert(bmp.error.equals(f"cannot close BMP: {bmpPath}"));

        FileSystem.removeRecursive(dir);
        return 0;
    }
"""


def _instrument_file_close(generated: Path) -> None:
    """Replace only File.close's fclose edge in this generated test unit."""
    source = generated.read_text(encoding="utf-8")
    signature = "bool File_close(File* self) {"
    close_call = "fclose(self->handle)"
    assert source.count(signature) == 1
    assert source.count(close_call) == 1
    hook = """
static bool imageIoTestCloseFailure = false;

void imageIoFailNextFileClose(void) {
    imageIoTestCloseFailure = true;
}

static int imageIoTestClose(FILE* stream) {
    int status = fclose(stream);
    if (status == 0 && imageIoTestCloseFailure) {
        imageIoTestCloseFailure = false;
        return EOF;
    }
    return status;
}

"""
    source = source.replace(signature, hook + signature, 1)
    source = source.replace(close_call, "imageIoTestClose(self->handle)", 1)
    generated.write_text(source, encoding="utf-8", newline="\n")


def test_image_loaders_report_close_failures_without_shipping_a_test_api(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_pair(
        semantic_btrcc,
        tmp_path,
        SOURCE,
        "image-close-failure",
        include_stdlib=True,
    )
    for _frontend, generated in compiled:
        _instrument_file_close(generated)
    run_strict_pair(compiled, tmp_path)
