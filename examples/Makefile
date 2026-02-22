# ─────────────────────────────────────────────────────────────────────────────
# btrc examples
#
# Usage:  make          Build all examples (CPU + GPU if available)
#         make cpu      Build CPU-only examples
#         make gpu      Build GPU examples (requires: make gpu in root)
#         make clean    Clean all build artifacts
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: all cpu gpu todo game triangle sgd clean

GPU_LIB := ../src/stdlib/gpu/build/libbtrc_gpu.a

all: cpu gpu

cpu: todo

gpu: game triangle sgd

todo: ## Build the todo example
	@echo "=== todo ==="
	@$(MAKE) -C todo

game: ## Build the 3D engine game
	@if [ -f "$(GPU_LIB)" ]; then \
		echo "=== game ===" && $(MAKE) -C game; \
	else \
		echo "=== game === (skipped — run 'make gpu' in project root first)"; \
	fi

triangle: ## Build the GPU triangle example
	@if [ -f "$(GPU_LIB)" ]; then \
		echo "=== triangle ===" && $(MAKE) -C triangle; \
	else \
		echo "=== triangle === (skipped — run 'make gpu' in project root first)"; \
	fi

sgd: ## Build the GPU SGD example
	@if [ -f "$(GPU_LIB)" ]; then \
		echo "=== sgd ===" && $(MAKE) -C sgd; \
	else \
		echo "=== sgd === (skipped — run 'make gpu' in project root first)"; \
	fi

clean:
	@$(MAKE) -C todo clean 2>/dev/null || true
	@$(MAKE) -C game clean 2>/dev/null || true
	@$(MAKE) -C triangle clean 2>/dev/null || true
	@$(MAKE) -C sgd clean 2>/dev/null || true
