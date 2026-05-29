BTRC  := python3 -m src.compiler.python.main
ROOT  := ../..
GUI   := ../../src/stdlib/gui
SRC   := main.btrc
OUT_C := main.c
OUT   := gui_demo

run: $(OUT)
	./$(OUT)

$(OUT): $(OUT_C) $(GUI)/btrc_gui.c
	gcc -std=c11 -I$(GUI) $(OUT_C) $(GUI)/btrc_gui.c -o $(OUT) -lm -lpthread

$(OUT_C): $(SRC)
	cd $(ROOT) && $(BTRC) examples/gui/$(SRC) -o examples/gui/$(OUT_C)

clean:
	rm -f $(OUT_C) $(OUT)
