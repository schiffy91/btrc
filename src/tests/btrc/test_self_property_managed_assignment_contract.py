"""Managed mixed properties preserve virtual assignment results."""

from pathlib import Path

from src.tests.btrc.test_self_property_update_contract import (
    _strict_dual_frontend_runtime,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


SOURCE = """
    #include <assert.h>

    int managedAlive = 0;
    int managedSetterCalls = 0;

    class ManagedItem {
        public int id;

        public ManagedItem(int id) {
            self.id = id;
            managedAlive++;
        }

        public void __del__() { managedAlive--; }
    }

    class ManagedOwner {
        public ManagedItem item {
            get;
            set { managedSetterCalls++; self.item = value; }
        }

        public ManagedOwner(ManagedItem initial) {
            self.item = initial;
        }

        public ManagedItem replace(ManagedItem next) {
            return self.item = next;
        }
    }

    int main() {
        assert(managedAlive == 0);
        {
            ManagedOwner owner =
                new ManagedOwner(new ManagedItem(1));
            assert(managedAlive == 1);
            assert(managedSetterCalls == 1);
            managedSetterCalls = 0;

            {
                ManagedItem next = new ManagedItem(2);
                ManagedItem result = owner.replace(next);
                assert(managedSetterCalls == 1);
                assert(result == next);
                assert(result == owner.item);
                assert(result.id == 2);
                assert(managedAlive == 1);
            }

            assert(managedAlive == 1);
            assert(owner.item.id == 2);
        }
        assert(managedAlive == 0);
        return 0;
    }
"""


def test_managed_mixed_property_assignment_result_keeps_identity_alive(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    _strict_dual_frontend_runtime(
        semantic_btrcc,
        tmp_path,
        SOURCE,
        "managed-mixed-property-assignment",
    )
