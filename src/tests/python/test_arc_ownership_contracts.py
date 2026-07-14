"""Runtime contracts for compiler-owned ARC references."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.analyzer.analyzer import Analyzer
from src.compiler.python.ir.emitter import CEmitter
from src.compiler.python.ir.gen.errors import CodegenError
from src.compiler.python.ir.gen.generator import IRGenerator
from src.compiler.python.ir.optimizer import optimize
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))

OWNERSHIP_SOURCE = r"""
    #include <assert.h>

    int itemsAlive = 0;
    int keepersAlive = 0;
    int linksAlive = 0;
    int failuresAlive = 0;
    int optionalCalls = 0;

    class Item {
        public int id;
        public Item(int id) { self.id = id; itemsAlive++; }
        public void __del__() { itemsAlive--; }
    }

    class Holder {
        public Item? item { get; set; }
        public void store(keep Item value) { self.item = value; }
    }

    class ConstructorHolder {
        public Item? item { get; set; }
        public ConstructorHolder(keep Item value) { self.item = value; }
    }

    class Link {
        public Link? next { get; set; }
        public Link() { linksAlive++; }
        public void __del__() { linksAlive--; }
    }

    class Keeper {
        public Keeper() { keepersAlive++; }
        public void __del__() { keepersAlive--; }
        public bool accept(keep Item value) {
            optionalCalls++;
            return value != null;
        }
        public bool fail(keep Item value) {
            optionalCalls++;
            throw "optional failure";
        }
        public bool failAfter(keep Item value, int at) {
            optionalCalls++;
            if (optionalCalls == at) { throw "repeated failure"; }
            return true;
        }
    }

    class Failure {
        public Item? item { get; set; }
        public Failure() {
            failuresAlive++;
            self.item = new Item(90);
            throw "constructor failure";
        }
        public void __del__() { failuresAlive--; }
    }

    void stash(Holder holder, keep Item value) {
        holder.item = value;
    }

    bool returnKeepCall(Keeper keeper, Item value) {
        return keeper.accept(value);
    }

    void localReassignment() {
        {
            Item? left = new Item(1);
            Item? right = new Item(2);
            left = new Item(3);
            assert(itemsAlive == 2);
            left = right;
            assert(itemsAlive == 1);
            left = left;
            left = null;
            assert(itemsAlive == 1);
        }
        assert(itemsAlive == 0);
    }

    void discardedAndRepeatedCalls() {
        for (int i = 0; i < 3; i++) {
            new Item(i);
            assert(itemsAlive == 0);
        }
        Keeper keeper = new Keeper();
        for (int i = 0; i < 3; i++) {
            assert(itemsAlive == 0);
            keeper.accept(new Item(i));
        }
        assert(itemsAlive == 0);
    }

    void propertyOwnership() {
        {
            Holder holder = new Holder();
            Item? first = new Item(10);
            holder.item = first;
            holder.item = holder.item;
            holder.item = new Item(11);
            assert(itemsAlive == 2);
            holder.item = null;
            assert(itemsAlive == 1);
        }
        assert(itemsAlive == 0);
    }

    void propertyCycle() {
        {
            Link left = new Link();
            Link right = new Link();
            left.next = right;
            right.next = left;
        }
        assert(linksAlive == 0);
    }

    void keepCallsAreCallScoped() {
        {
            Holder methodHolder = new Holder();
            Item methodItem = new Item(20);
            methodHolder.store(methodItem);
            delete methodHolder;
            delete methodItem;
        }
        assert(itemsAlive == 0);

        {
            Holder functionHolder = new Holder();
            Item functionItem = new Item(21);
            stash(functionHolder, functionItem);
            delete functionHolder;
            delete functionItem;
        }
        assert(itemsAlive == 0);

        {
            Item constructorItem = new Item(22);
            ConstructorHolder constructorHolder = new ConstructorHolder(constructorItem);
            delete constructorHolder;
            delete constructorItem;
        }
        assert(itemsAlive == 0);

        {
            Holder left = new Holder();
            Holder right = new Holder();
            Item sharedItem = new Item(23);
            left.store(sharedItem);
            right.store(sharedItem);
            delete left;
            delete right;
            delete sharedItem;
        }
        assert(itemsAlive == 0);

        {
            Keeper? keeper = new Keeper();
            Item optionalItem = new Item(24);
            assert(keeper?.accept(optionalItem));
            delete keeper;
            delete optionalItem;
        }
        assert(itemsAlive == 0 && keepersAlive == 0);
    }

    void keepCallsInExpressionContexts() {
        Keeper contextKeeper = new Keeper();
        Item contextItem = new Item(25);
        assert(returnKeepCall(contextKeeper, contextItem));

        bool contextResult = contextKeeper.accept(new Item(26));
        assert(contextResult && itemsAlive == 1);
        contextResult = contextKeeper.accept(new Item(27));
        assert(contextResult && itemsAlive == 1);
        if (contextKeeper.accept(new Item(28))) {
            assert(itemsAlive == 1);
        }
        assert(returnKeepCall(contextKeeper, new Item(29)));
        assert(itemsAlive == 1);

        delete contextKeeper;
        delete contextItem;
        assert(itemsAlive == 0 && keepersAlive == 0);
    }

    void repeatedKeepCleanupInTry() {
        Keeper repeatedKeeper = new Keeper();
        Item repeatedItem = new Item(30);
        int caught = 0;
        optionalCalls = 0;
        try {
            for (int i = 0; i < 4; i++) {
                repeatedKeeper.failAfter(repeatedItem, 3);
            }
        } catch (string error) {
            caught++;
        }
        assert(caught == 1 && itemsAlive == 1);
        delete repeatedKeeper;
        delete repeatedItem;
        assert(itemsAlive == 0 && keepersAlive == 0);
    }

    bool optionalEarly(Keeper? keeper, Item value) {
        return keeper?.accept(value);
    }

    void optionalOwnership() {
        optionalCalls = 0;
        {
            int i = 0;
            while (i < 3 && (new Keeper())?.accept(new Item(i))) { i++; }
            assert(i == 3);
            assert(keepersAlive == 0);
        }
        assert(itemsAlive == 0);

        {
            Keeper? missing = null;
            bool result = missing?.accept(new Item(40));
            assert(!result && itemsAlive == 0 && optionalCalls == 3);
        }

        {
            Keeper keeper = new Keeper();
            Item item = new Item(50);
            for (int i = 0; i < 3; i++) {
                assert(optionalEarly(keeper, item));
            }
        }
        assert(itemsAlive == 0 && keepersAlive == 0);
    }

    void exceptionOwnership() {
        int caught = 0;
        try {
            Failure failure = new Failure();
        } catch (string error) {
            caught++;
        }
        assert(caught == 1 && failuresAlive == 0 && itemsAlive == 0);

        try {
            (new Keeper())?.fail(new Item(60));
        } catch (string error) {
            caught++;
        }
        assert(caught == 2 && keepersAlive == 0 && itemsAlive == 0);
    }

    int main() {
        localReassignment();
        discardedAndRepeatedCalls();
        propertyOwnership();
        propertyCycle();
        keepCallsAreCallScoped();
        keepCallsInExpressionContexts();
        repeatedKeepCleanupInTry();
        optionalOwnership();
        exceptionOwnership();
        assert(itemsAlive == 0 && keepersAlive == 0
                && linksAlive == 0 && failuresAlive == 0);
        return 0;
    }
"""


RETURN_PROJECTION_SOURCE = r"""
    #include <assert.h>

    int itemsAlive = 0;
    int ownersAlive = 0;
    int sinksAlive = 0;

    class Item {
        public int id;
        public Item(int id) { self.id = id; itemsAlive++; }
        public void __del__() { itemsAlive--; }
    }

    class Owner {
        public Item child;
        public int value;
        public Owner(int id) {
            ownersAlive++;
            self.child = new Item(id);
            self.value = id;
        }
        public void __del__() { ownersAlive--; }
        public Item borrowedChild() { return self.child; }
        public Owner fluent() { return self; }
    }

    class TextOwner {
        public string text;
        public TextOwner(string value) { self.text = value + "!"; }
    }

    class Sink {
        public Sink() { sinksAlive++; }
        public void __del__() { sinksAlive--; }
        public bool accept(Item value) { return value != null; }
        public bool acceptDefault(keep Item value = new Item(61)) {
            return value != null;
        }
        public bool failDefault(keep Item value = new Item(62)) {
            assert(value != null);
            throw "optional default failed";
        }
    }

    class DefaultOwner {
        public Item child;
        public DefaultOwner(keep Item child = new Item(50)) {
            self.child = child;
        }
    }

    class ThrowingOwner {
        public Item child;
        public ThrowingOwner(keep Item child) {
            self.child = child;
            throw "constructor failed";
        }
    }

    class GenericRunner<T> {
        public bool run() {
            return (new Sink()).accept(new Item(60));
        }
    }

    Owner makeOwner(int id) { return new Owner(id); }
    TextOwner makeTextOwner(string value) {
        return new TextOwner(value);
    }
    Item identity(Item value) { return value; }

    Item childFromLocal(int id) {
        Owner owner = new Owner(id);
        return owner.child;
    }

    Item choose(bool fresh, Item existing) {
        return fresh ? new Item(20) : existing;
    }

    Item chooseCoalesced(Item? candidate) {
        return candidate ?? new Item(30);
    }

    bool defaultArgument(keep Item value = new Item(40)) {
        return value != null;
    }

    void throwingDefault(keep Item value = new Item(41)) {
        assert(value != null);
        throw "default failed";
    }

    int main() {
        {
            Item original = new Item(1);
            Item alias = identity(original);
            assert(alias == original && itemsAlive == 1);
        }
        assert(itemsAlive == 0);

        Item escaped = childFromLocal(2);
        assert(ownersAlive == 0 && itemsAlive == 1 && escaped.id == 2);
        delete escaped;
        assert(itemsAlive == 0);

        assert(makeOwner(3).value == 3);
        assert(ownersAlive == 0 && itemsAlive == 0);
        assert(makeTextOwner("TYPE").text == "TYPE!");
        Item projected = makeOwner(4).child;
        assert(ownersAlive == 0 && itemsAlive == 1 && projected.id == 4);
        delete projected;
        assert(itemsAlive == 0);

        assert(makeOwner(5) != null);
        assert(makeOwner(6) != makeOwner(7));
        makeOwner(8).fluent().fluent();
        assert(ownersAlive == 0 && itemsAlive == 0);

        {
            Item existing = new Item(9);
            choose(true, existing);
            choose(false, existing);
            assert(itemsAlive == 1);
            Item selectedFresh = choose(true, existing);
            Item selectedAlias = choose(false, existing);
            Item coalescedAlias = chooseCoalesced(existing);
            Item coalescedFresh = chooseCoalesced(null);
            assert(selectedFresh.id == 20 && selectedAlias == existing);
            assert(coalescedAlias == existing && coalescedFresh.id == 30);
            assert(itemsAlive == 3);

            Sink sink = new Sink();
            assert(sink.accept(true ? new Item(21) : existing));
            assert(sink.accept(false ? new Item(22) : existing));
            assert(itemsAlive == 3);
        }
        assert(itemsAlive == 0 && sinksAlive == 0);

        {
            Sink? absent = null;
            assert(!absent?.acceptDefault());
            assert(itemsAlive == 0);
            Sink present = new Sink();
            assert(present?.acceptDefault());
            assert(itemsAlive == 0);
            int optionalCaught = 0;
            try { present?.failDefault(); }
            catch (string error) { optionalCaught++; }
            assert(optionalCaught == 1 && itemsAlive == 0);
        }
        assert(itemsAlive == 0 && sinksAlive == 0);

        assert(defaultArgument());
        assert(itemsAlive == 0);
        {
            DefaultOwner owner = new DefaultOwner();
            assert(owner.child.id == 50 && itemsAlive == 1);
        }
        assert(itemsAlive == 0);

        int caught = 0;
        try { throwingDefault(); }
        catch (string error) { caught++; }
        try { new ThrowingOwner(new Item(51)); }
        catch (string error) { caught++; }
        assert(caught == 2 && itemsAlive == 0);

        {
            GenericRunner<int> runner = new GenericRunner<int>();
            assert(runner.run());
            assert(itemsAlive == 0 && sinksAlive == 0);
        }
        assert(itemsAlive == 0 && ownersAlive == 0 && sinksAlive == 0);
        return 0;
    }
"""


def _emit(source: str) -> str:
    program = Parser(Lexer(source, "<arc-ownership>").tokenize()).parse()
    analyzed = Analyzer().analyze(program)
    assert analyzed.errors == []
    return CEmitter().emit(optimize(IRGenerator(analyzed).generate()))


def _asan_environment(compiler: str) -> dict[str, str] | None:
    """Isolate the host Apple toolchain from an enclosing Nix build shell."""
    if sys.platform != "darwin" or os.path.realpath(compiler) != "/usr/bin/clang":
        return None

    environment = {
        name: os.environ[name]
        for name in ("HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE")
        if name in os.environ
    }
    environment.update(
        {
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "TMPDIR": "/tmp",
        }
    )
    return environment


def _find_asan_compiler(tmp_path: Path) -> str:
    """Return the first compiler that can both build and link ASan here."""
    probe = tmp_path / "asan-probe.c"
    executable = tmp_path / "asan-probe"
    probe.write_text("int main(void) { return 0; }\n")
    failures = []
    candidates = list(COMPILERS)
    if sys.platform == "darwin":
        system_clang = "/usr/bin/clang"
        if os.access(system_clang, os.X_OK):
            candidates.append(system_clang)
    unique_candidates = []
    seen = set()
    for compiler in candidates:
        identity = os.path.realpath(compiler)
        if identity not in seen:
            seen.add(identity)
            unique_candidates.append(compiler)

    for compiler in unique_candidates:
        environment = _asan_environment(compiler)
        result = subprocess.run(
            [
                compiler,
                "-std=c11",
                "-fsanitize=address",
                str(probe),
                "-o",
                str(executable),
            ],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )
        name = Path(compiler).name
        if result.returncode != 0:
            failures.append(f"{name}: {result.stderr[:120]}")
            continue
        try:
            probe_run = subprocess.run(
                [str(executable)],
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
                env=environment,
            )
        except subprocess.TimeoutExpired:
            failures.append(f"{name}: linked ASan runtime timed out")
            continue
        if probe_run.returncode == 0:
            return compiler
        failures.append(f"{name}: ASan probe exited {probe_run.returncode}: {probe_run.stderr[:120]}")
    pytest.skip("AddressSanitizer unavailable: " + "; ".join(failures))


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_arc_ownership_is_balanced_at_runtime(tmp_path: Path, c_compiler: str):
    source = tmp_path / f"ownership-{Path(c_compiler).name}.c"
    executable = source.with_suffix("")
    source.write_text(_emit(OWNERSHIP_SOURCE))
    compiled = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(source),
            "-lm",
            "-lpthread",
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert compiled.returncode == 0, compiled.stderr
    subprocess.run([str(executable)], check=True, timeout=15)


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_managed_returns_and_owned_projections_are_balanced(
    tmp_path: Path,
    c_compiler: str,
):
    source = tmp_path / f"return-projection-{Path(c_compiler).name}.c"
    executable = source.with_suffix("")
    source.write_text(_emit(RETURN_PROJECTION_SOURCE))
    compiled = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(source),
            "-lm",
            "-lpthread",
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert compiled.returncode == 0, compiled.stderr
    subprocess.run([str(executable)], check=True, timeout=15)


def test_ownership_lowering_stays_structured():
    emitted = _emit(OWNERSHIP_SOURCE)
    assert "__auto_type" not in emitted
    assert "({" not in emitted
    assert "__btrc_register_cleanup" in emitted


def test_borrowed_managed_local_initializers_acquire_scope_ownership():
    emitted = _emit(
        """
        class Item {
            public int id;
            public Item(int id) { self.id = id; }
        }
        class State {
            public Item current;
            public State(Item current) { self.current = current; }
            public void round(Item replacement) {
                Item saved = self.current;
                self.current = replacement;
                self.current = saved;
            }
        }
        class GenericState<T> {
            public Item current;
            public GenericState(Item current) { self.current = current; }
            public void round(Item replacement) {
                Item saved = self.current;
                self.current = replacement;
                self.current = saved;
            }
        }
        class PropertyState {
            public Item current { get; set; }
            public PropertyState(Item current) { self.current = current; }
            public void round(Item replacement) {
                Item saved = self.current;
                self.current = replacement;
                self.current = saved;
            }
        }
        int main() {
            State plain = new State(new Item(1));
            GenericState<int> generic =
                new GenericState<int>(new Item(2));
            PropertyState property = new PropertyState(new Item(3));
            plain.round(new Item(4));
            generic.round(new Item(5));
            property.round(new Item(6));
            return 0;
        }
        """
    )
    field_local = "Item* saved = self->current;\n    (void)(__btrc_arc_retain(saved));"
    property_local = "Item* saved = PropertyState_get_current(self);\n    (void)(__btrc_arc_retain(saved));"
    assert emitted.count(field_local) == 2
    assert property_local in emitted


@pytest.mark.parametrize(
    "source",
    [
        """
        class Item { public Item() {} }
        int main() {
            (int, Item) value = (1, new Item());
            return 0;
        }
        """,
        """
        class Item { public Item() {} }
        struct Slot { Item value; };
        int main() {
            Slot slot = {new Item()};
            return 0;
        }
        """,
        """
        class Item { public Item() {} }
        enum class Payload { Some(Item value), None }
        int main() {
            Payload payload = Payload.Some(new Item());
            return 0;
        }
        """,
        """
        class Item { public Item() {} }
        struct Slot { Item value; };
        int main() {
            Item owner = new Item();
            Slot slot = {owner};
            slot.value = new Item();
            return 0;
        }
        """,
        """
        class Item { public Item() {} }
        int main() {
            Item slots[1];
            slots[0] = new Item();
            return 0;
        }
        """,
    ],
)
def test_shallow_aggregates_reject_owned_temporaries(source: str):
    with pytest.raises(CodegenError, match=r"shallow|rich-enum"):
        _emit(source)


def test_shallow_aggregates_accept_explicit_borrowed_elements():
    emitted = _emit(
        """
        class Item { public int id; public Item(int id) { self.id = id; } }
        struct Slot { Item value; };
        enum class Payload { Some(Item value), None }
        int main() {
            Item owner = new Item(7);
            (int, Item) tupleValue = (1, owner);
            Slot slot = {owner};
            Payload payload = Payload.Some(owner);
            assert(tupleValue._1 == owner);
            assert(slot.value == owner);
            assert(payload.data.Some.value == owner);
            return 0;
        }
        """
    )
    assert "Payload_Some(owner)" in emitted


@pytest.mark.skipif(not COMPILERS, reason="requires an AddressSanitizer compiler")
@pytest.mark.parametrize(
    ("case", "source_text"),
    [
        ("call-guards", OWNERSHIP_SOURCE),
        ("returns-projections", RETURN_PROJECTION_SOURCE),
    ],
)
def test_managed_ownership_is_asan_clean(
    tmp_path: Path,
    case: str,
    source_text: str,
):
    compiler = _find_asan_compiler(tmp_path)
    environment = _asan_environment(compiler)
    source = tmp_path / f"ownership-{case}-asan.c"
    executable = source.with_suffix("")
    source.write_text(_emit(source_text))
    compiled = subprocess.run(
        [
            compiler,
            "-std=c11",
            "-pedantic-errors",
            "-fsanitize=address",
            "-fno-omit-frame-pointer",
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
    assert compiled.returncode == 0, compiled.stderr
    result = subprocess.run(
        [str(executable)],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
        env=environment,
    )
    assert result.returncode == 0, result.stderr
