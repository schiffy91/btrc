"""Owned {invoke, context, destroy} callback closure parity."""

from pathlib import Path

from src.tests.btrc.test_semantic_validation import (
    _compile_reference_source,
    _compile_source,
    _strict_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


def _compile_pair(semantic_btrcc: Path, tmp_path: Path, source: str):
    selfhost, selfhost_c = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_c = _compile_reference_source(tmp_path, source)
    return (selfhost, selfhost_c), (reference, reference_c)


def test_owned_closure_survives_return_alias_and_field_then_destroys_once(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        import std.callback;

        int destroyed = 0;

        int addContext(void* raw, int value) {
            return *(int*)raw + value;
        }

        void destroyContext(void* raw) {
            destroyed = destroyed + *(int*)raw;
            free(raw);
        }

        OwnedClosure<CFunction<int, void*, int>> makeClosure(int value) {
            int* context = (int*)malloc(sizeof(int));
            *context = value;
            return new OwnedClosure<CFunction<int, void*, int>>(
                addContext, context, destroyContext);
        }

        class Holder {
            public OwnedClosure<CFunction<int, void*, int>> callback;

            public Holder(OwnedClosure<CFunction<int, void*, int>> callback) {
                self.callback = callback;
            }

            public int call(int value) {
                CFunction<int, void*, int> invoke = self.callback.invokePointer();
                return invoke(self.callback.context(), value);
            }
        }

        int main() {
            {
                OwnedClosure<CFunction<int, void*, int>> first = makeClosure(40);
                {
                    OwnedClosure<CFunction<int, void*, int>> alias = first;
                    CFunction<int, void*, int> invoke = alias.invokePointer();
                    assert(invoke(alias.context(), 2) == 42);
                }
                assert(destroyed == 0);
                first.close();
                first.close();
                assert(destroyed == 40);
            }
            assert(destroyed == 40);
            {
                Holder holder = Holder(makeClosure(2));
                assert(holder.call(40) == 42);
            }
            assert(destroyed == 42);
            return 0;
        }
    """
    (selfhost, selfhost_c), (reference, reference_c) = _compile_pair(semantic_btrcc, tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(selfhost_c, tmp_path / "selfhost-owned-closure")
    _strict_build_and_run(reference_c, tmp_path / "reference-owned-closure")


def test_owned_closure_cannot_decay_to_cfunction(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        import std.callback;
        int invoke(void* context, int value) { return value; }
        void destroy(void* context) {}
        int main() {
            OwnedClosure<CFunction<int, void*, int>> closure =
                new OwnedClosure<CFunction<int, void*, int>>(invoke, null, destroy);
            CFunction<int, void*, int> erased = closure;
            return 0;
        }
    """
    (selfhost, _), (reference, _) = _compile_pair(semantic_btrcc, tmp_path, source)
    assert selfhost.returncode != 0
    assert reference.returncode != 0
    for diagnostic in (selfhost.stderr, reference.stderr):
        assert "OwnedClosure<CFunction<int, void*, int>>" in diagnostic
        assert "CFunction<int, void*, int>" in diagnostic
        assert "assign" in diagnostic.lower()


def test_owned_closure_requires_cfunction_invoke_type(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        import std.callback;
        void destroy(void* context) {}
        int main() {
            OwnedClosure<int> invalid = new OwnedClosure<int>(1, null, destroy);
            return 0;
        }
    """
    (selfhost, _), (reference, _) = _compile_pair(semantic_btrcc, tmp_path, source)
    assert selfhost.returncode != 0
    assert reference.returncode != 0
    expected = "OwnedClosure<Invoke> requires an exact CFunction<Signature> invoke type"
    assert expected in selfhost.stderr
    assert expected in reference.stderr
