/* Raw C source helper. When imported via `import ./cinterop/triple.c`, the
   front-end splices this as `#include "<abs path>"` rather than parsing it as
   btrc. This file is intentionally NOT named test_*.btrc so the runner skips
   it as a test and only collects it as an import target. */
int triple(int x) {
    return x * 3;
}
