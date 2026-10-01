include ../Example.mk

.PHONY: run clean

run: todo
	./todo

todo: todo.c
	$(CC) $(STRICT_CFLAGS) todo.c -o todo $(HOSTED_LIBS)

todo.c: Todo.btrc
	cd $(BTRC_ROOT) && $(BTRC) $(EXAMPLE)/Todo.btrc -o $(EXAMPLE)/todo.c

clean:
	rm -f todo.c todo
