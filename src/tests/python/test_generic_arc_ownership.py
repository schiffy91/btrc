"""Runtime ARC contracts for monomorphized generic method bodies."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.tests.python.test_arc_ownership_contracts import (
    COMPILERS,
    _asan_environment,
    _emit,
    _find_asan_compiler,
)

GENERIC_LOCAL_SOURCE = r"""
    #include <assert.h>

    int itemsAlive = 0;
    int containersAlive = 0;

    class Item {
        public int id;
        public Item(int id) { self.id = id; itemsAlive++; }
        public void __del__() { itemsAlive--; }
    }

    class Container {
        public Item child;
        public int value;
        public Container(int value) {
            self.child = new Item(value);
            self.value = value;
            containersAlive++;
        }
        public void __del__() { containersAlive--; }
    }

    class PropertyHolder {
        private Item? storage;
        public Item? value {
            get { return self.storage; }
            set { self.storage = value; }
        }
    }

    Container makeContainer(int value) {
        return new Container(value);
    }

    void ordinaryControlExits() {
        switch (1) {
            case 1:
                Item local = new Item(19);
                assert(local.id == 19);
                break;
            default:
                break;
        }
    }

    class GenericOwner<T> {
        public Item? slot;

        public void normal() {
            Item outer = new Item(1);
            if (true) {
                Item inner = new Item(2);
                assert(itemsAlive >= 2);
            }
            assert(outer.id == 1);
        }

        public void discard() {
            new Item(3);
        }

        public int scalarProjection() {
            return makeContainer(60).value;
        }

        public Item managedProjection() {
            return makeContainer(61).child;
        }

        public bool compareOwnedCalls() {
            return makeContainer(70) != makeContainer(71);
        }

        public void mutateOwnedReceiver() {
            makeContainer(72).value = 73;
        }

        public Item choose(bool fresh, Item borrowed) {
            return fresh ? new Item(80) : borrowed;
        }

        public Item coalesce(Item? candidate) {
            return candidate ?? new Item(81);
        }

        public void replace(Item borrowed) {
            Item local = new Item(4);
            local = borrowed;
            assert(local == borrowed);
        }

        public void store(Item value) {
            self.slot = value;
        }

        public void storeProperty(PropertyHolder holder) {
            holder.value = new Item(102);
        }

        public Item transfer() {
            Item sibling = new Item(5);
            Item result = new Item(6);
            assert(sibling != result);
            return result;
        }

        public Item borrow(Item value) {
            Item scratch = new Item(7);
            assert(scratch != value);
            return value;
        }

        public void controlExits() {
            for (int i = 0; i < 3; i++) {
                Item local = new Item(10 + i);
                if (i < 2) { continue; }
                break;
            }
            switch (1) {
                case 1:
                    Item local = new Item(20);
                    assert(local.id == 20);
                    break;
                default:
                    break;
            }
        }

        public void throwCleanup() {
            try {
                Item local = new Item(30);
                assert(local.id == 30);
                throw "generic cleanup";
            } catch (string error) {
                assert(error.equals("generic cleanup"));
            }
        }

        public Item returnFromTry(Item value) {
            try {
                Item scratch = new Item(40);
                assert(scratch != value);
                return value;
            } catch (string error) {
                assert(error != null);
                return value;
            }
        }

        public void breakFromTry() {
            int entered = 0;
            while (true) {
                try {
                    Item local = new Item(50);
                    assert(local.id == 50);
                    entered++;
                    break;
                } catch (string error) {
                    assert(error != null);
                }
            }
            assert(entered == 1);
        }
    }

    int main() {
        ordinaryControlExits();
        assert(itemsAlive == 0);
        GenericOwner<int> owner = new GenericOwner<int>();
        owner.normal();
        assert(itemsAlive == 0);
        owner.discard();
        assert(itemsAlive == 0);
        assert(owner.scalarProjection() == 60);
        assert(itemsAlive == 0 && containersAlive == 0);
        {
            Item projected = owner.managedProjection();
            assert(projected.id == 61);
            assert(itemsAlive == 1 && containersAlive == 0);
        }
        assert(itemsAlive == 0 && containersAlive == 0);

        Item borrowed = new Item(100);
        assert(owner.compareOwnedCalls());
        assert(itemsAlive == 1 && containersAlive == 0);
        owner.mutateOwnedReceiver();
        assert(itemsAlive == 1 && containersAlive == 0);
        {
            Item chooseAlias = owner.choose(false, borrowed);
            assert(chooseAlias == borrowed && itemsAlive == 1);
        }
        {
            Item chooseFresh = owner.choose(true, borrowed);
            assert(chooseFresh.id == 80 && itemsAlive == 2);
        }
        {
            Item coalescedAlias = owner.coalesce(borrowed);
            assert(coalescedAlias == borrowed && itemsAlive == 1);
        }
        {
            Item coalescedFresh = owner.coalesce(null);
            assert(coalescedFresh.id == 81 && itemsAlive == 2);
        }
        assert(itemsAlive == 1);
        owner.store(borrowed);
        assert(itemsAlive == 1 && owner.slot == borrowed);
        owner.store(new Item(101));
        assert(itemsAlive == 2 && owner.slot.id == 101);
        owner.store(borrowed);
        assert(itemsAlive == 1 && owner.slot == borrowed);
        {
            PropertyHolder holder = new PropertyHolder();
            owner.storeProperty(holder);
            assert(itemsAlive == 2 && holder.value.id == 102);
            delete holder;
            assert(itemsAlive == 1);
        }
        owner.replace(borrowed);
        assert(itemsAlive == 1);
        {
            Item borrowedAlias = owner.borrow(borrowed);
            assert(borrowedAlias == borrowed && itemsAlive == 1);
        }
        assert(itemsAlive == 1);
        {
            Item made = owner.transfer();
            assert(made.id == 6 && itemsAlive == 2);
        }
        assert(itemsAlive == 1);
        {
            Item tryAlias = owner.returnFromTry(borrowed);
            assert(tryAlias == borrowed && itemsAlive == 1);
        }
        assert(itemsAlive == 1);

        owner.controlExits();
        assert(itemsAlive == 1);
        owner.throwCleanup();
        assert(itemsAlive == 1);
        owner.breakFromTry();
        assert(itemsAlive == 1);
        return 0;
    }
"""


def _compile(
    tmp_path: Path,
    compiler: str,
    *flags: str,
    environment: dict[str, str] | None = None,
) -> Path:
    source = tmp_path / f"generic-arc-{Path(compiler).name}.c"
    executable = source.with_suffix("")
    source.write_text(_emit(GENERIC_LOCAL_SOURCE))
    result = subprocess.run(
        [
            compiler,
            "-std=c11",
            "-pedantic-errors",
            *flags,
            str(source),
            "-lm",
            "-lpthread",
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    assert result.returncode == 0, result.stderr
    return executable


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize(
    "c_compiler",
    COMPILERS,
    ids=lambda path: Path(path).name,
)
def test_generic_local_arc_is_balanced(tmp_path: Path, c_compiler: str):
    executable = _compile(
        tmp_path,
        c_compiler,
        "-Wall",
        "-Wextra",
        "-Werror",
    )
    subprocess.run([str(executable)], check=True, timeout=15)


@pytest.mark.skipif(not COMPILERS, reason="requires AddressSanitizer")
def test_generic_local_arc_is_asan_clean(tmp_path: Path):
    compiler = _find_asan_compiler(tmp_path)
    environment = _asan_environment(compiler)
    executable = _compile(
        tmp_path,
        compiler,
        "-fsanitize=address",
        "-fno-omit-frame-pointer",
        environment=environment,
    )
    result = subprocess.run(
        [str(executable)],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
        env=environment,
    )
    assert result.returncode == 0, result.stderr
