BTRC  := python3 -m src.compiler.python.main
ROOT  := ../..
SRC   := todo.btrc
OUT_C := todo.c
OUT   := todo

.PHONY: run clean

run: $(OUT)
	./$(OUT)

$(OUT): $(OUT_C)
	gcc $(OUT_C) -o $(OUT) -lm -lpthread

$(OUT_C): $(SRC)
	cd $(ROOT) && $(BTRC) examples/todo/$(SRC) -o examples/todo/$(OUT_C)

clean:
	rm -f $(OUT_C) $(OUT)
