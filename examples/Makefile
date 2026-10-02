# ─────────────────────────────────────────────────────────────────────────────
# btrc examples
#
# Usage:  make          Build all examples (CPU + GPU if available)
#         make cpu      Build CPU-only examples
#         make gpu      Build GPU examples (requires: make gpu in root)
#         make clean    Clean all build artifacts
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: all cpu gpu callback realtime-primitives todo tray game triangle sgd sgd-render gui native-package clean

GPU_LIB := ../build/stdlib/GPU/libbtrc_gpu.a

all: cpu gpu

cpu: callback realtime-primitives todo gui

gpu: game triangle sgd sgd-render

callback: ## Build the owned callback closure example
	@echo "=== callback ==="
	@$(MAKE) -C callback

tray: ## Build and run the native tray example (macOS or Linux session bus)
	@echo "=== tray ==="
	@$(MAKE) -C tray

todo: ## Build the todo example
	@echo "=== todo ==="
	@$(MAKE) -C todo

realtime-primitives: ## Build and run the bounded primitive and @realtime gain examples
	@echo "=== realtime-primitives ==="
	@$(MAKE) -C realtime-primitives

gui: ## Build the portable native GUI example (needs the platform GUI SDK)
	@echo "=== gui ==="
	@$(MAKE) -C gui

game: ## Build the 3D engine game
	@$(MAKE) -C game

triangle: ## Build the GPU triangle example
	@$(MAKE) -C triangle

sgd: ## Build the GPU SGD example
	@if [ -f "$(GPU_LIB)" ]; then \
		echo "=== sgd ===" && $(MAKE) -C sgd; \
	else \
		echo "=== sgd === (skipped — run 'make gpu' in project root first)"; \
	fi

sgd-render: ## Render the GPU SGD example to frames for the README animation
	@if [ -f "$(GPU_LIB)" ]; then \
		echo "=== sgd-render ===" && $(MAKE) -C sgd-render run; \
	else \
		echo "=== sgd-render === (skipped — run 'make gpu' in project root first)"; \
	fi

clean:
	@$(MAKE) -C callback clean 2>/dev/null || true
	@$(MAKE) -C todo clean 2>/dev/null || true
	@$(MAKE) -C realtime-primitives clean 2>/dev/null || true
	@$(MAKE) -C game clean 2>/dev/null || true
	@$(MAKE) -C triangle clean 2>/dev/null || true
	@$(MAKE) -C sgd clean 2>/dev/null || true
	@$(MAKE) -C gui clean 2>/dev/null || true
	@$(MAKE) -C sgd-render clean 2>/dev/null || true
	@$(MAKE) -C tray clean 2>/dev/null || true
	@$(MAKE) -C native-package clean 2>/dev/null || true

native-package: ## Build the recursive C/C++ package through its emitted plan
	@test -n "$(TARGET)" || { echo "TARGET is required" >&2; exit 2; }
	@$(MAKE) -C native-package TARGET="$(TARGET)" run
