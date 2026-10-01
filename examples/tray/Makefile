# btrc native system tray example
#
# macOS builds generated AppKit adapters from the native link plan; Linux links
# libdbus-1 (pkg-config dbus-1) for the StatusNotifierItem provider. Windows has
# no provider.
#
#   make        Transpile, build, and run the tray demo
#   make build  Transpile + build only (don't run)
#   make clean

include ../Example.mk

.PHONY: all build run clean

all: run

run: build
	./tray_demo

build:
	cd $(BTRC_ROOT) && $(BTRC) $(EXAMPLE)/Main.btrc -o $(EXAMPLE)/main.c --emit-link-plan $(EXAMPLE)/main.link.json
	cd $(BTRC_ROOT) && $(NATIVE_PLAN) --plan $(EXAMPLE)/main.link.json --generated-c $(EXAMPLE)/main.c \
		--output $(EXAMPLE)/tray_demo --cc "$(NATIVE_CC)" --cxx "$(NATIVE_CXX)" --pkg-config "$(PKG_CONFIG)"

clean:
	rm -f main.c main.link.json tray_demo
