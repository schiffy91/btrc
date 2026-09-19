# A small native UI, rendered headless to PPM frames, and those frames to a GIF.
#
# No display and no GPU required: the View tree is laid out and rasterized
# offscreen, which is the same tree a real window renders through the platform
# provider.

BTRC_ROOT := ../..
BTRC      := python3 -m src.compiler.python.main
GUI_DIR   := $(BTRC_ROOT)/src/stdlib/GUI

CC     := cc
CFLAGS := -std=c11 -I$(GUI_DIR) -O2

.PHONY: all run gif clean

all: native_ui

native_ui: NativeUI.btrc
	cd $(BTRC_ROOT) && $(BTRC) examples/native-ui/NativeUI.btrc -o examples/native-ui/native_ui.c
	$(CC) native_ui.c -o native_ui $(CFLAGS) -lm -lpthread

# Write the frames.
run: native_ui
	mkdir -p frames
	./native_ui

# Re-encode the committed animation from a fresh run. Needs Pillow.
gif: run
	python3 ../make_gif.py frames ui.gif

clean:
	rm -f native_ui native_ui.c
	rm -rf frames
