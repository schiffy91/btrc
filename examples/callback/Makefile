BTRC  := python3 -m src.compiler.python.main
ROOT  := ../..
SRC   := main.btrc
OUT_C := callback.c
OUT   := callback

.PHONY: run clean

run: $(OUT)
	./$(OUT)

$(OUT): $(OUT_C)
	$(CC) -std=c11 -Wall -Wextra -Werror -pedantic $(OUT_C) -o $(OUT) -lm -lpthread

$(OUT_C): $(SRC) ../../src/stdlib/callback.btrc
	cd $(ROOT) && $(BTRC) examples/callback/$(SRC) -o examples/callback/$(OUT_C)

clean:
	rm -f $(OUT_C) $(OUT)
