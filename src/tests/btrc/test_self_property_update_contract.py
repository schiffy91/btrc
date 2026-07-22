"""Custom properties on ``self`` remain virtual update targets."""

from pathlib import Path

from src.tests.btrc.test_ownership_semantics_contract import (
    _compile_reference_source,
)
from src.tests.btrc.test_semantic_validation import (
    _compile_source,
    _strict_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


SCALAR_UPDATE_SOURCE = """
    #include <assert.h>

    int getterCalls = 0;
    int setterCalls = 0;
    int rhsCalls = 0;
    int mixedGetterCalls = 0;
    int mixedSetterCalls = 0;
    int mixedGetterRhsCalls = 0;
    int mixedSetterRhsCalls = 0;
    int genericGetterCalls = 0;
    int genericSetterCalls = 0;
    int inheritedGetterCalls = 0;
    int inheritedSetterCalls = 0;
    int inheritedRhsCalls = 0;

    int tick() {
        rhsCalls++;
        return 3;
    }

    int tickMixedGetter() {
        mixedGetterRhsCalls++;
        return 2;
    }

    int tickMixedSetter() {
        mixedSetterRhsCalls++;
        return 3;
    }

    int tickInherited() {
        inheritedRhsCalls++;
        return 5;
    }

    class Gauge {
        private int stored;

        public Gauge(int initial) { self.stored = initial; }

        public int value {
            get { getterCalls++; return self.stored; }
            set { setterCalls++; self.stored = value; }
        }

        public int compound() { return self.value += tick(); }
        public int postfix() { return self.value++; }
        public int prefix() { return ++self.value; }
        public int readStored() { return self.stored; }
    }

    class MixedGauge {
        public int getterMixed {
            get { mixedGetterCalls++; return self.getterMixed; }
            set;
        }

        public int setterMixed {
            get;
            set { mixedSetterCalls++; self.setterMixed = value; }
        }

        public MixedGauge(int initial) {
            self.getterMixed = initial;
            self.setterMixed = initial * 2;
        }

        public int updateGetterMixed() {
            return self.getterMixed += tickMixedGetter();
        }

        public int updateSetterMixed() {
            return self.setterMixed += tickMixedSetter();
        }
    }

    class GenericGauge<T> {
        private T marker;

        public int value {
            get;
            set { genericSetterCalls++; self.value = value; }
        }

        public GenericGauge(T marker, int initial) {
            self.marker = marker;
            self.value = initial;
        }

        public int compound(int delta) {
            return self.value += delta;
        }
    }

    class GenericGetterGauge<T> {
        private T marker;

        public int value {
            get { genericGetterCalls++; return self.value; }
            set;
        }

        public GenericGetterGauge(T marker, int initial) {
            self.marker = marker;
            self.value = initial;
        }

        public int compound(int delta) {
            return self.value += delta;
        }
    }

    class ParentGauge {
        private int stored;

        public int inheritedValue {
            get { inheritedGetterCalls++; return self.stored; }
            set { inheritedSetterCalls++; self.stored = value; }
        }
    }

    class ChildGauge extends ParentGauge {
        public ChildGauge(int initial) {
            self.inheritedValue = initial;
        }

        public int compound() {
            return self.inheritedValue += tickInherited();
        }
    }

    int main() {
        Gauge gauge = new Gauge(10);

        assert(gauge.compound() == 13);
        assert(gauge.readStored() == 13);
        assert(getterCalls == 1);
        assert(setterCalls == 1);
        assert(rhsCalls == 1);

        assert(gauge.postfix() == 13);
        assert(gauge.readStored() == 14);
        assert(getterCalls == 2);
        assert(setterCalls == 2);
        assert(rhsCalls == 1);

        assert(gauge.prefix() == 15);
        assert(gauge.readStored() == 15);
        assert(getterCalls == 3);
        assert(setterCalls == 3);
        assert(rhsCalls == 1);

        MixedGauge mixed = new MixedGauge(20);
        assert(mixedSetterCalls == 1);
        mixedSetterCalls = 0;

        assert(mixed.updateGetterMixed() == 22);
        assert(mixed.getterMixed == 22);
        assert(mixedGetterCalls == 2);
        assert(mixedGetterRhsCalls == 1);

        assert(mixed.updateSetterMixed() == 43);
        assert(mixed.setterMixed == 43);
        assert(mixedSetterCalls == 1);
        assert(mixedSetterRhsCalls == 1);

        GenericGauge<int> generic = new GenericGauge<int>(0, 7);
        assert(genericSetterCalls == 1);
        genericSetterCalls = 0;
        assert(generic.compound(4) == 11);
        assert(generic.value == 11);
        assert(genericSetterCalls == 1);

        GenericGetterGauge<int> genericGetter =
            new GenericGetterGauge<int>(0, 9);
        assert(genericGetter.compound(6) == 15);
        assert(genericGetter.value == 15);
        assert(genericGetterCalls == 2);

        ChildGauge child = new ChildGauge(30);
        assert(inheritedSetterCalls == 1);
        inheritedSetterCalls = 0;
        assert(child.compound() == 35);
        assert(child.inheritedValue == 35);
        assert(inheritedGetterCalls == 2);
        assert(inheritedSetterCalls == 1);
        assert(inheritedRhsCalls == 1);

        delete child;
        delete genericGetter;
        delete generic;
        delete mixed;
        delete gauge;
        return 0;
    }
"""


def _strict_dual_frontend_runtime(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    stem: str,
) -> None:
    selfhost, selfhost_source = _compile_source(
        semantic_btrcc,
        tmp_path,
        source,
    )
    reference, reference_source = _compile_reference_source(
        tmp_path,
        source,
    )
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr

    _strict_build_and_run(
        selfhost_source,
        tmp_path / f"selfhost-{stem}",
    )
    _strict_build_and_run(
        reference_source,
        tmp_path / f"reference-{stem}",
    )


def test_custom_self_property_updates_use_accessors_once(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    _strict_dual_frontend_runtime(
        semantic_btrcc,
        tmp_path,
        SCALAR_UPDATE_SOURCE,
        "self-property-updates",
    )
