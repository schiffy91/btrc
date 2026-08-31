# ─────────────────────────────────────────────────────────────────────────────
# btrc examples
#
# Usage:  make          Build all examples (CPU + GPU if available)
#         make cpu      Build CPU-only examples
#         make gpu      Build GPU examples (requires: make gpu in root)
#         make clean    Clean all build artifacts
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: all cpu gpu callback todo game triangle sgd gui clean

GPU_LIB := ../build/stdlib/gpu/libbtrc_gpu.a

all: cpu gpu

cpu: callback todo gui

gpu: game triangle sgd

callback: ## Build the owned callback closure example
	@echo "=== callback ==="
	@$(MAKE) -C callback

todo: ## Build the todo example
	@echo "=== todo ==="
	@$(MAKE) -C todo

gui: ## Build + run the headless GUI example (offscreen, no display needed)
	@echo "=== gui ==="
	@$(MAKE) -C gui

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
	@$(MAKE) -C callback clean 2>/dev/null || true
	@$(MAKE) -C todo clean 2>/dev/null || true
	@$(MAKE) -C game clean 2>/dev/null || true
	@$(MAKE) -C triangle clean 2>/dev/null || true
	@$(MAKE) -C sgd clean 2>/dev/null || true
	@$(MAKE) -C gui clean 2>/dev/null || true
	@$(MAKE) -C tray clean 2>/dev/null || true
