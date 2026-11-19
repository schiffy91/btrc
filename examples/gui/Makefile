# Portable native GUI examples: windows built through the GUI factory, on
# AppKit on macOS, GTK4 on Linux, Win32 on Windows and Android's views. The SDK reader and the
# platform's GUI packages must be available in the build environment.
include ../Example.mk

.PHONY: all native showcase run run-showcase clean

all: native showcase

native:
	cd $(BTRC_ROOT) && $(BTRC) $(EXAMPLE)/Native.btrc -o $(EXAMPLE)/native.c --emit-link-plan $(EXAMPLE)/native.link.json
	cd $(BTRC_ROOT) && $(NATIVE_PLAN) --plan $(EXAMPLE)/native.link.json --generated-c $(EXAMPLE)/native.c \
		--output $(EXAMPLE)/native --cc "$(NATIVE_CC)" --cxx "$(NATIVE_CXX)" --pkg-config "$(PKG_CONFIG)"

# Native controls, a GPU view and a web view in one window (Showcase.btrc;
# captures/ holds what it looks like on Linux, Windows and Android).
showcase:
	cd $(BTRC_ROOT) && $(BTRC) $(EXAMPLE)/Showcase.btrc -o $(EXAMPLE)/showcase.c --emit-link-plan $(EXAMPLE)/showcase.link.json
	cd $(BTRC_ROOT) && $(NATIVE_PLAN) --plan $(EXAMPLE)/showcase.link.json --generated-c $(EXAMPLE)/showcase.c \
		--output $(EXAMPLE)/showcase --cc "$(NATIVE_CC)" --cxx "$(NATIVE_CXX)" --pkg-config "$(PKG_CONFIG)"

# Opens a window and runs until it is closed or Quit is pressed.
run: native
	./native

run-showcase: showcase
	./showcase

clean:
	rm -f native native.c native.link.json showcase showcase.c showcase.link.json
