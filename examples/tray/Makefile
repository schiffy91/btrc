# btrc native system tray example
#
# macOS: links the Cocoa NSStatusBar shim (-framework Cocoa).
# Linux: links the StatusNotifierItem/D-Bus shim (needs base dbus-1 dev lib).
#
#   make        Transpile, build, and run the tray demo
#   make build  Transpile + build only (don't run)
#   make clean

BTRC := python3 -m src.compiler.python.main
ROOT := ../..
TRAY := ../../src/stdlib/tray

UNAME := $(shell uname -s)
ifeq ($(UNAME),Darwin)
  CC      := clang
  SHIM    := $(TRAY)/btrc_tray_macos.m
  TRAY_LD := -framework Cocoa
  TRAY_CF := -fobjc-arc
else
  CC      := cc
  SHIM    := $(TRAY)/btrc_tray_linux.c
  TRAY_LD := $(shell pkg-config --libs dbus-1 2>/dev/null)
  TRAY_CF := $(shell pkg-config --cflags dbus-1 2>/dev/null)
endif

.PHONY: all build run clean

all: run

run: build
	./tray_demo

build: main.c
	$(CC) -std=c11 $(TRAY_CF) -I$(TRAY) main.c $(SHIM) $(TRAY_LD) -lm -lpthread -o tray_demo

main.c: main.btrc
	cd $(ROOT) && $(BTRC) examples/tray/main.btrc -o examples/tray/main.c

clean:
	rm -f main.c tray_demo
