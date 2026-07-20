"""Switch cases preserve source scope and declaration-specific C identity."""

from pathlib import Path

from src.tests.btrc.production_readiness_harness import run_strict_pair
from src.tests.btrc.string_coercion_harness import compile_pair

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


def test_switch_cases_restore_type_and_managed_outer_bindings(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        int resourcesAlive = 0;

        class Item {
            class int marker() { return 42; }
        }

        class Resource {
            public Resource() { resourcesAlive++; }
            public void __del__() { resourcesAlive--; }
        }

        int run(int selected) {
            Resource owner = new Resource();
            switch (selected) {
                case 0:
                    int owner = 7;
                    int Item = Item.marker();
                    if (owner == 7 && Item == 42) { return 0; }
                    break;
                case 1:
                    int owner = 8;
                    int Item = Item.marker();
                    if (owner != 8 || Item != 42) { return 1; }
                    break;
                default:
                    break;
            }
            bool valid = owner != null && Item.marker() == 42;
            return valid ? 0 : 1;
        }

        int main() {
            if (run(0) != 0 || resourcesAlive != 0) { return 1; }
            if (run(1) != 0 || resourcesAlive != 0) { return 2; }
            return 0;
        }
    """
    compiled = compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "switch-shadowing",
        include_stdlib=False,
    )
    run_strict_pair(compiled, tmp_path)
