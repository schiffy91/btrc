# btrc examples — builds all example projects
#
# Usage: make          (build all non-GPU examples)
#        make gpu      (build GPU examples — requires setup-gpu)
#        make clean    (clean all)

BTRC_ROOT := ..
BTRC      := python3 -m src.compiler.python.main

.PHONY: all todo gpu sgd clean

all: todo

todo: ## Build and run the todo example
	@echo "=== todo ==="
	@cd $(BTRC_ROOT) && $(BTRC) examples/todo/todo.btrc -o examples/todo/todo.c \
		&& gcc examples/todo/todo.c -o examples/todo/todo -lm -lpthread \
		&& ./examples/todo/todo

gpu: triangle sgd ## Build all GPU examples

triangle: ## Build and run the GPU triangle example
	@echo "=== gpu/triangle ==="
	@$(MAKE) -C gpu triangle

sgd: ## Build and run the GPU SGD example
	@echo "=== sgd ==="
	@$(MAKE) -C sgd sgd

clean:
	@$(MAKE) -C todo clean 2>/dev/null || true
	@$(MAKE) -C gpu clean 2>/dev/null || true
	@$(MAKE) -C sgd clean 2>/dev/null || true
	rm -f todo/todo.c todo/todo
