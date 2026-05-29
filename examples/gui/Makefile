BTRC  := python3 -m src.compiler.python.main
ROOT  := ../..
GUI   := ../../src/stdlib/gui

# Headless examples — run offscreen, no display required.
run: demo declarative font

# Immediate-mode widget demo.
demo: main.c
	gcc -std=c11 -I$(GUI) main.c $(GUI)/btrc_gui.c -o gui_demo -lm -lpthread && ./gui_demo

main.c: main.btrc
	cd $(ROOT) && $(BTRC) examples/gui/main.btrc -o examples/gui/main.c

# Declarative View tree: layout, events-by-id, resize reflow, UTF-8 metrics.
declarative: declarative.c
	gcc -std=c11 -I$(GUI) declarative.c $(GUI)/btrc_gui.c -o gui_declarative -lm -lpthread && ./gui_declarative

declarative.c: declarative.btrc
	cd $(ROOT) && $(BTRC) examples/gui/declarative.btrc -o examples/gui/declarative.c

# Scalable FreeType fonts — needs FreeType (FONT_CFLAGS/FONT_LDFLAGS from the
# devshell); skipped gracefully when the headers are absent.
font: font_smoke.c
	@gcc -std=c11 $(FONT_CFLAGS) -I$(GUI) font_smoke.c $(GUI)/btrc_gui.c $(GUI)/btrc_gui_font.c $(FONT_LDFLAGS) -o gui_font -lm -lpthread 2>/dev/null \
		&& ./gui_font || echo "gui font example skipped (missing FreeType headers)"

font_smoke.c: font_smoke.btrc
	cd $(ROOT) && $(BTRC) examples/gui/font_smoke.btrc -o examples/gui/font_smoke.c

clean:
	rm -f main.c gui_demo declarative.c gui_declarative font_smoke.c gui_font
