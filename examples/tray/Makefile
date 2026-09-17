# btrc native system tray example
#
# macOS builds generated AppKit adapters from the native link plan; Linux links
# libdbus-1 (pkg-config dbus-1) for the StatusNotifierItem provider. Windows has
# no provider.
#
#   make        Transpile, build, and run the tray demo
#   make build  Transpile + build only (don't run)
#   make clean

BTRC := python3 -m src.compiler.python.main
ROOT := ../..
CC ?= cc
CXX ?= c++

.PHONY: all build run clean

all: run

run: build
	./tray_demo

build:
	cd $(ROOT) && $(BTRC) examples/tray/Main.btrc -o examples/tray/main.c --emit-link-plan examples/tray/main.link.json
	cd $(ROOT) && python3 -m tools.native_plan --plan examples/tray/main.link.json --generated-c examples/tray/main.c --output examples/tray/tray_demo --cc $(CC) --cxx $(CXX)

clean:
	rm -f main.c main.link.json tray_demo
