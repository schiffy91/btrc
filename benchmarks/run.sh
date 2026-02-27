#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=== btrc benchmarks ==="
echo ""

cd "$PROJECT_ROOT"

for btrc_file in "$SCRIPT_DIR"/*.btrc; do
    name=$(basename "$btrc_file" .btrc)
    echo "--- $name ---"
    python3 -m src.compiler.python.main "$btrc_file" -o "/tmp/bench_${name}.c" 2>&1
    gcc -O2 "/tmp/bench_${name}.c" -o "/tmp/bench_${name}" -lm 2>&1

    # Time the execution
    start_time=$(date +%s%N 2>/dev/null || python3 -c "import time; print(int(time.time()*1e9))")
    "/tmp/bench_${name}"
    end_time=$(date +%s%N 2>/dev/null || python3 -c "import time; print(int(time.time()*1e9))")

    elapsed=$(( (end_time - start_time) / 1000000 ))
    echo "  time: ${elapsed}ms"
    echo ""
done

echo "=== done ==="
