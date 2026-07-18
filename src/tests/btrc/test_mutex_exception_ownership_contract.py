"""Exceptional ownership handoff contracts involving ``Mutex<T>``."""

from pathlib import Path

import pytest

from src.tests.btrc.test_mutex_value_contract import (
    COMPILERS,
    _compile_pair,
    _strict_matrix,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

pytestmark = pytest.mark.skipif(
    not COMPILERS,
    reason="requires a pthread C11 compiler",
)


def test_owned_mutex_return_is_cleaned_if_local_cleanup_throws(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>

        int payloadAlive = 0;
        int bombAlive = 0;

        class Payload {
            public Payload() { payloadAlive++; }
            public void __del__() { payloadAlive--; }
        }

        class Bomb {
            public Bomb() { bombAlive++; }
            public void __del__() {
                bombAlive--;
                throw "return cleanup";
            }
        }

        Mutex<Payload> makeDirect() {
            Bomb bomb = new Bomb();
            return Mutex(new Payload());
        }

        class Maker<T> {
            public Maker() {}
            public Mutex<Payload> make() {
                Bomb bomb = new Bomb();
                return Mutex(new Payload());
            }
        }

        int main() {
            try {
                Mutex<Payload> direct = makeDirect();
                assert(false);
            } catch (string error) {
                assert(error.equals("return cleanup"));
            }
            assert(payloadAlive == 0 && bombAlive == 0);

            Maker<int> maker = new Maker<int>();
            try {
                Mutex<Payload> generic = maker.make();
                assert(false);
            } catch (string error) {
                assert(error.equals("return cleanup"));
            }
            assert(payloadAlive == 0 && bombAlive == 0);
            return 0;
        }
    """
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "mutex-throwing-return-cleanup",
    )
    for artifact in compiled:
        _strict_matrix(artifact, tmp_path)


def test_call_result_is_cleaned_if_owned_argument_cleanup_throws(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>

        int payloadAlive = 0;
        int bombAlive = 0;

        class Payload {
            public Payload() { payloadAlive++; }
            public void __del__() { payloadAlive--; }
        }

        class Bomb {
            public Bomb() { bombAlive++; }
            public void __del__() {
                bombAlive--;
                throw "argument cleanup";
            }
        }

        Mutex<Payload> produceDirect(Bomb ignored) {
            return Mutex(new Payload());
        }

        class Factory<T> {
            public Factory() {}
            public Mutex<Payload> produce(Bomb ignored) {
                return Mutex(new Payload());
            }
        }

        int main() {
            try {
                Mutex<Payload> direct = produceDirect(new Bomb());
                assert(false);
            } catch (string error) {
                assert(error.equals("argument cleanup"));
            }
            assert(payloadAlive == 0 && bombAlive == 0);

            Factory<int> factory = new Factory<int>();
            try {
                Mutex<Payload> generic = factory.produce(new Bomb());
                assert(false);
            } catch (string error) {
                assert(error.equals("argument cleanup"));
            }
            assert(payloadAlive == 0 && bombAlive == 0);
            return 0;
        }
    """
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "mutex-throwing-call-suffix",
    )
    for artifact in compiled:
        _strict_matrix(artifact, tmp_path)


def test_optional_call_result_is_cleaned_if_receiver_cleanup_throws(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>

        int payloadAlive = 0;
        int factoryAlive = 0;

        class Payload {
            public Payload() { payloadAlive++; }
            public void __del__() { payloadAlive--; }
        }

        class Factory {
            public Factory() { factoryAlive++; }
            public Payload produce() { return new Payload(); }
            public void __del__() {
                factoryAlive--;
                throw "receiver cleanup";
            }
        }

        int main() {
            try {
                Payload? result = (new Factory())?.produce();
                assert(false);
            } catch (string error) {
                assert(error.equals("receiver cleanup"));
            }
            assert(payloadAlive == 0 && factoryAlive == 0);
            return 0;
        }
    """
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "optional-throwing-receiver-cleanup",
    )
    for artifact in compiled:
        _strict_matrix(artifact, tmp_path)
