# Portable native GUI example: one window built through the GUI factory, on
# AppKit on macOS and the drawn provider on Linux. The SDK reader and the
# platform's GUI packages must be available in the build environment.
include ../Example.mk

.PHONY: all native run clean

all: native

native:
	cd $(BTRC_ROOT) && $(BTRC) $(EXAMPLE)/Native.btrc -o $(EXAMPLE)/native.c --emit-link-plan $(EXAMPLE)/native.link.json
	cd $(BTRC_ROOT) && $(NATIVE_PLAN) --plan $(EXAMPLE)/native.link.json --generated-c $(EXAMPLE)/native.c \
		--output $(EXAMPLE)/native --cc "$(NATIVE_CC)" --cxx "$(NATIVE_CXX)" --pkg-config "$(PKG_CONFIG)"

# Opens a window and runs until it is closed or Quit is pressed.
run: native
	./native

clean:
	rm -f native native.c native.link.json
