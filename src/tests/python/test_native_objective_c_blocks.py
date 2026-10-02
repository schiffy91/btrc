"""Objective-C block callbacks: call-scoped blocks, object inputs and one-shot completion blocks."""

import json
import subprocess
from pathlib import Path

import pytest

from src.tests.python.native_import_fixtures import apple_environment, compile_source
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder


@pytest.fixture
def objective_c_block_project(native_project):
    source, _, _ = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "#import <Foundation/Foundation.h>\n"
        "typedef NS_ENUM(NSInteger, BlockNumber) { BlockNumberSeven = 7 };\n"
        "@interface BlockProbe : NSObject\n"
        "+ (instancetype)make;\n+ (NSInteger)live;\n"
        "- (NSInteger)visit:(NSInteger)seed using:(NSInteger (^)(NSInteger))callback;\n"
        "+ (NSInteger)pair:(NSInteger (^)(NSInteger))first with:(NSInteger (^)(NSInteger))second;\n"
        "+ (BlockNumber)number:(BlockNumber (^)(BlockNumber))callback;\n"
        "+ (instancetype)newResultUsing:(void (^)(void))callback;\n"
        "+ (void)wrongThread:(void (^)(void))callback;\n@end\n"
    )
    (root / "Probe.m").write_text(
        '#import "Foundation.h"\n#include <pthread.h>\n#include <assert.h>\n'
        "static NSInteger live;\n"
        "struct Delivery { __unsafe_unretained void (^callback)(void); };\n"
        "static void *deliver(void *raw) { ((struct Delivery*)raw)->callback(); return NULL; }\n"
        "@implementation BlockProbe\n"
        "+ (instancetype)make { return [self new]; }\n"
        "- (instancetype)init { self = [super init]; if (self) ++live; return self; }\n"
        "- (void)dealloc { --live; }\n+ (NSInteger)live { return live; }\n"
        "- (NSInteger)visit:(NSInteger)seed using:(NSInteger (^)(NSInteger))callback {\n"
        "  NSInteger first = callback(seed); NSInteger second = callback(seed + 1);\n"
        "  assert([self description] != nil); return first + second;\n}\n"
        "+ (NSInteger)pair:(NSInteger (^)(NSInteger))first with:(NSInteger (^)(NSInteger))second {\n"
        "  NSInteger result = first(3); return result + second(4);\n}\n"
        "+ (BlockNumber)number:(BlockNumber (^)(BlockNumber))callback { return callback(BlockNumberSeven); }\n"
        "+ (instancetype)newResultUsing:(void (^)(void))callback { callback(); return [self new]; }\n"
        "+ (void)wrongThread:(void (^)(void))callback {\n"
        "  struct Delivery delivery = { callback }; pthread_t thread;\n"
        "  assert(pthread_create(&thread, NULL, deliver, &delivery) == 0);\n"
        "  assert(pthread_join(thread, NULL) == 0);\n}\n@end\n"
    )
    symbols = [
        "+[BlockProbe make]",
        "+[BlockProbe live]",
        "-[BlockProbe visit:using:]",
        "+[BlockProbe pair:with:]",
        "+[BlockProbe number:]",
        "+[BlockProbe newResultUsing:]",
        "+[BlockProbe wrongThread:]",
        "+[NSProcessInfo processInfo]",
        "-[NSProcessInfo performActivityWithOptions:reason:usingBlock:]",
        "+[NSString stringWithUTF8String:]",
        "NSActivityBackground",
    ]
    mappings = {
        "-[BlockProbe visit:using:].callback": "ITransform",
        "+[BlockProbe pair:with:].first": "ITransform",
        "+[BlockProbe pair:with:].second": "ITransform",
        "+[BlockProbe number:].callback": "INumber",
        "+[BlockProbe newResultUsing:].callback": "INotification",
        "+[BlockProbe wrongThread:].callback": "INotification",
        "-[NSProcessInfo performActivityWithOptions:reason:usingBlock:].block": "INotification",
    }
    manifest = (
        'manifest-version = 1\n[package]\nname = "nativeBlocks"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "objective-c"\nstandard = "c11"\n'
        f"symbols = {json.dumps(symbols)}\n"
    )
    for parameter, interface in mappings.items():
        manifest += (
            f'[native.bindings.callbacks."{parameter}"]\ninterface = "{interface}"\n'
            'lifetime = "call"\nfailure = "abort"\nexecutor = "caller"\n'
        )
    manifest += (
        '[[native.sources]]\npath = "Probe.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
        '[[native.frameworks]]\nname = "Foundation"\n'
    )
    (root / "btrc.toml").write_text(manifest)
    (source.parent / "Foundation.btrc").write_text("")
    return source


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("scenario", ["lifetime", "sdk", "reentry", "result-cleanup", "wrong-thread", "failure"])
def test_objective_c_block_callback(objective_c_block_project, native_compile, sanitize, scenario):
    source = objective_c_block_project
    root = source.parent.parent
    bodies = {
        "lifetime": """
int destroyed = 0;
class Holder { public ITransform? visitor; public BlockProbe? probe; }
class Visitor implements ITransform {
	private Holder owner;
	public Visitor(Holder owner) { self.owner = owner; }
	public long invoke(long value) {
		self.owner.visitor = null; self.owner.probe = null;
		assert(destroyed == 0); assert(BlockProbe.live() == 1);
		return value * 2;
	}
	public void __del__() { destroyed++; }
}
int main() {
	var owner = Holder(); owner.probe = BlockProbe.make(); owner.visitor = Visitor(owner);
	assert(owner.probe.visit(20, owner.visitor) == 82);
	assert(destroyed == 1); assert(BlockProbe.live() == 0); return 0;
}
""",
        "sdk": """
int delivered = 0;
int destroyed = 0;
class Notification implements INotification {
	public void invoke() { delivered++; }
	public void __del__() { destroyed++; }
}
class Number implements INumber { public long invoke(long value) { return value; } }
int main() {
	char bytes[32]; strcpy(bytes, "BTRC native callback");
	var reason = NSString.stringWithUTF8String(bytes);
	var process = NSProcessInfo.processInfo();
	for (int index = 0; index < 100; index++) {
		process.performActivityWithOptions(NSActivityBackground, reason, Notification());
		assert(delivered == index + 1); assert(destroyed == index + 1);
	}
	assert(BlockProbe.number(Number()) == 7); return 0;
}
""",
        "reentry": """
int delivered = 0;
int destroyed = 0;
class Visitor implements ITransform {
	private int depth = 0;
	public long invoke(long value) {
		delivered++;
		if (self.depth == 0) {
			self.depth = 1; assert(BlockProbe.pair(self, self) == 7); self.depth = 0;
		}
		return value;
	}
	public void __del__() { destroyed++; }
}
int main() {
	{ var visitor = Visitor(); assert(BlockProbe.pair(visitor, visitor) == 7); }
	assert(delivered == 6); assert(destroyed == 1); return 0;
}
""",
        "result-cleanup": """
int destroyed = 0;
class Notification implements INotification {
	public void invoke() { }
	public void __del__() { destroyed++; throw "destructor failure"; }
}
int main() {
	bool caught = false;
	try { var value = BlockProbe.newResultUsing(Notification()); }
	catch (string message) { caught = message == "destructor failure"; }
	assert(caught); assert(destroyed == 1); assert(BlockProbe.live() == 0); return 0;
}
""",
        "wrong-thread": """
class Notification implements INotification { public void invoke() { assert(false); } }
int main() { BlockProbe.wrongThread(Notification()); return 0; }
""",
        "failure": """
class Notification implements INotification { public void invoke() { throw "callback failure"; } }
int main() { var value = BlockProbe.newResultUsing(Notification()); return 0; }
""",
    }
    source.write_text("import ./Foundation.btrc;\n#include <assert.h>\n" + bodies[scenario])
    plan = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    reference = compile_source(source)
    assert reference.successful, reference.failure
    assert json.loads(plan.read_text()) == reference.native_plan.as_dict()
    generated = root / "Program.c"
    generated.write_text(compiled.c_source)

    def run(command, **kwargs):
        flags = ["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitize else ["-O2"]
        if "objective-c" in command:
            flags.append("-fobjc-arc")
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    executable = root / "Program"
    NativePlanBuilder(runner=run).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    if scenario in {"wrong-thread", "failure"}:
        assert completed.returncode != 0
        assert ("wrong thread" if scenario == "wrong-thread" else "callback failure") in completed.stderr
    else:
        assert completed.returncode == 0, (completed.returncode, completed.stderr)
        assert not completed.stderr


@pytest.mark.parametrize(
    "old,new,message",
    [
        (
            'interface = "ITransform"',
            'interface = "ITransform"\ncontext = "callback"\ncontext-index = 0',
            "block context is compiler-owned",
        ),
        ('lifetime = "call"', 'lifetime = "stored"', "unregister"),
        ('failure = "abort"', 'failure = "ignore"', "failure currently requires abort"),
        ('executor = "caller"', 'executor = "worker"', "executor currently requires caller"),
        ('interface = "INotification"', 'interface = "ITransform"', "conflicting native declaration"),
        ("-[BlockProbe visit:using:].callback", "-[BlockProbe visit:using:].missing", "unknown function parameter"),
    ],
)
def test_objective_c_block_invalid_mapping(objective_c_block_project, native_compile, old, new, message):
    source = objective_c_block_project
    manifest = source.parent.parent / "btrc.toml"
    manifest.write_text(manifest.read_text().replace(old, new))
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert message in str(compiled.failure) + str(compiled.diagnostics)


@pytest.mark.parametrize(
    "signature,message",
    [
        ("NSInteger (^)(char*)", "non-scalar arguments require a borrow mapping"),
        ("NSInteger (^)(Class)", "protocol/generic/dynamic objects require managed native lowering"),
        ("NSInteger (^)(id<NSCopying>)", "protocol/generic/dynamic objects require managed native lowering"),
        ("NSInteger (^)(NSArray<NSString*>*)", "protocol/generic/dynamic objects require managed native lowering"),
        ("NSInteger (^)(NSString* volatile)", "unsupported Objective-C object qualifiers"),
        ("NSString* (^)(NSInteger)", "object callback results require a stored Objective-C block"),
        ("NSInteger (*)(NSInteger)", "Objective-C method callbacks require block parameters"),
        ("NSInteger (^ volatile)(NSInteger)", "unsupported Objective-C block qualifiers"),
    ],
)
def test_objective_c_block_rejects_unmapped_type(objective_c_block_project, native_compile, signature, message):
    source = objective_c_block_project
    header = source.parent.parent / "Foundation.h"
    header.write_text(header.read_text().replace("NSInteger (^)(NSInteger)", signature))
    source.write_text("import ./Foundation.btrc;\nint main() { return 0; }\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert message in str(compiled.failure) + str(compiled.diagnostics)


@pytest.mark.parametrize("conflict", [False, True])
def test_objective_c_block_method_union(objective_c_block_project, native_compile, conflict):
    source = objective_c_block_project
    manifest = source.parent.parent / "btrc.toml"
    text = manifest.read_text()
    binding = text.split("[[native.bindings]]", 1)[1].split("[[native.sources]]", 1)[0]
    binding = binding.replace('module = "Foundation"', 'module = "Other"')
    if conflict:
        binding = binding.replace('interface = "ITransform"', 'interface = "IOtherTransform"')
    manifest.write_text(text + "\n[[native.bindings]]" + binding)
    (source.parent / "Other.btrc").write_text("")
    source.write_text(
        "import ./Foundation.btrc;\nimport ./Other.btrc;\n"
        "class Visitor implements ITransform { public long invoke(long value) { return value; } }\n"
        "int main() { var visitor = Visitor(); return BlockProbe.pair(visitor, visitor) == 7 ? 0 : 1; }\n"
    )
    compiled = native_compile(source)
    if conflict:
        assert not compiled.successful
        assert "conflicting native declaration" in str(compiled.failure) + str(compiled.diagnostics)
    else:
        assert compiled.successful, (compiled.failure, compiled.diagnostics)


@pytest.mark.parametrize("sanitize", [False, True])
def test_objective_c_block_native_failure_cleanup(objective_c_block_project, native_compile, sanitize):
    source = objective_c_block_project
    root = source.parent.parent
    native = root / "Probe.m"
    native.write_text(
        native.read_text().replace(
            "callback(); return [self new];",
            'callback(); @throw [NSException exceptionWithName:@"ProbeFailure" reason:@"native failure" userInfo:nil];',
        )
    )
    source.write_text("""import ./Foundation.btrc;
#include <assert.h>
int delivered = 0;
int destroyed = 0;
class Notification implements INotification {
	public void invoke() { delivered++; }
	public void __del__() { destroyed++; }
}
int main() {
	bool caught = false;
	try { var value = BlockProbe.newResultUsing(Notification()); }
	catch (string message) { caught = message == "Objective-C exception in +[BlockProbe newResultUsing:]"; }
	assert(caught); assert(delivered == 1); assert(destroyed == 1); assert(BlockProbe.live() == 0);
	return 0;
}
""")
    plan = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Program.c"
    generated.write_text(compiled.c_source)

    def run(command, **kwargs):
        flags = ["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitize else ["-O2"]
        if "objective-c" in command:
            flags.append("-fobjc-arc")
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    executable = root / "Program"
    NativePlanBuilder(runner=run).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    assert not completed.stderr


@pytest.fixture
def objective_c_object_block_project(native_project):
    source, _, _ = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text("""#import <Foundation/Foundation.h>
@interface Payload : NSObject
+ (NSInteger)live;
+ (NSInteger)destroyed;
+ (void)discard;
+ (void)visit:(void (^ _Nonnull)(Payload* _Nonnull, Payload* _Nonnull, Payload* _Nullable))callback;
- (NSInteger)number;
@end
""")
    (root / "Probe.m").write_text("""#import "Foundation.h"
static Payload* current;
static NSInteger live, destroyed;
@implementation Payload
- (instancetype)init { self = [super init]; if (self) ++live; return self; }
- (void)dealloc { --live; ++destroyed; }
+ (NSInteger)live { return live; }
+ (NSInteger)destroyed { return destroyed; }
+ (void)discard { current = nil; }
+ (void)visit:(void (^)(Payload*, Payload*, Payload*))callback {
    current = [self new];
    __unsafe_unretained Payload* borrowed = current;
    callback(borrowed, borrowed, nil);
}
- (NSInteger)number { return 41; }
@end
""")
    symbols = [
        "+[Payload live]",
        "+[Payload destroyed]",
        "+[Payload discard]",
        "+[Payload visit:]",
        "-[Payload number]",
        "+[NSMutableArray new]",
        "-[NSMutableArray addObject:]",
        "-[NSMutableArray objectAtIndex:]",
        "-[NSMutableArray sortUsingComparator:]",
        "+[NSString stringWithUTF8String:]",
    ]
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "objectBlocks"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "objective-c"\nstandard = "c11"\n'
        f"symbols = {json.dumps(symbols)}\n"
        '[native.bindings.callbacks."+[Payload visit:].callback"]\n'
        'interface = "IReceiver"\nlifetime = "call"\nfailure = "abort"\nexecutor = "caller"\n'
        '[native.bindings.callbacks."-[NSMutableArray sortUsingComparator:].cmptr"]\n'
        'interface = "IComparator"\nlifetime = "call"\nfailure = "abort"\nexecutor = "caller"\n'
        '[[native.sources]]\npath = "Probe.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
        '[[native.frameworks]]\nname = "Foundation"\n'
    )
    (source.parent / "Foundation.btrc").write_text("")
    return source


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize("scenario", ["borrow", "retain", "sdk", "nonnull", "failure"])
def test_objective_c_block_object_inputs(objective_c_object_block_project, native_compile, sanitize, scenario):
    source = objective_c_object_block_project
    root = source.parent.parent
    body = """
class Receiver implements IReceiver {
	public Payload? saved;
	private bool save;
	public Receiver(bool save) { self.save = save; }
	public void invoke(Payload value, Payload alias, Payload? optional) {
		assert(value == alias); assert(optional == null);
		Payload.discard(); assert(Payload.live() == 1); assert(Payload.destroyed() == 0);
		assert(value.number() == 41); assert(alias.number() == 41);
		if (self.save) { self.saved = value; }
	}
}
int main() {
	var receiver = Receiver(SAVE);
	Payload.visit(receiver);
	assert(Payload.live() == (SAVE ? 1 : 0));
	if (SAVE) { assert(receiver.saved.number() == 41); receiver.saved = null; }
	assert(Payload.live() == 0); assert(Payload.destroyed() == 1); return 0;
}
""".replace("SAVE", "true" if scenario == "retain" else "false")
    if scenario == "nonnull":
        native = root / "Probe.m"
        native.write_text(
            native.read_text().replace("callback(borrowed, borrowed, nil)", "callback(borrowed, nil, nil)")
        )
    if scenario == "failure":
        body = body.replace("if (self.save) { self.saved = value; }", 'throw "object callback failure";')
    if scenario == "sdk":
        body = """
int comparisons = 0;
int destroyed = 0;
class Comparator implements IComparator {
	private id? low;
	private id? high;
	public Comparator(id? low, id? high) { self.low = low; self.high = high; }
	public long invoke(id left, id right) {
		comparisons++;
		if (left == right) { return 0; }
		return left == self.low || right == self.high ? -1 : 1;
	}
	public void __del__() { destroyed++; }
}
int main() {
	char a[8]; strcpy(a, "a"); char b[8]; strcpy(b, "b"); char c[8]; strcpy(c, "c");
	id? low = NSString.stringWithUTF8String(a); id? middle = NSString.stringWithUTF8String(b); id? high = NSString.stringWithUTF8String(c);
	var array = NSMutableArray.new();
	if (array == null || low == null || middle == null || high == null) { return 1; }
	array.addObject(high); array.addObject(low); array.addObject(middle);
	array.sortUsingComparator(Comparator(low, high));
	assert(comparisons > 0); assert(destroyed == 1);
	assert(array.objectAtIndex(0) == low); assert(array.objectAtIndex(1) == middle); assert(array.objectAtIndex(2) == high);
	return 0;
}
"""
    source.write_text("import ./Foundation.btrc;\n#include <assert.h>\n" + body)
    plan = root / "Program.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    reference = compile_source(source)
    assert reference.successful, reference.failure
    assert json.loads(plan.read_text()) == reference.native_plan.as_dict()
    generated = root / "Program.c"
    generated.write_text(compiled.c_source)

    def run(command, **kwargs):
        flags = ["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitize else ["-O2"]
        if "objective-c" in command:
            flags.append("-fobjc-arc")
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    executable = root / "Program"
    NativePlanBuilder(runner=run).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    if scenario in {"nonnull", "failure"}:
        assert completed.returncode != 0
        assert ("null argument 1" if scenario == "nonnull" else "object callback failure") in completed.stderr
    else:
        assert completed.returncode == 0, (completed.returncode, completed.stderr)
        assert not completed.stderr


@pytest.fixture
def one_shot_project(native_project):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").write_text(
        "#import <Foundation/Foundation.h>\n"
        "@interface OneShotProbe : NSObject\n"
        "+ (void)inlineWork:(void (^)(void))work;\n"
        "+ (void)drain;\n@end\n"
    )
    (root / "Probe.m").write_text(
        '#import "Foundation.h"\n@implementation OneShotProbe\n'
        "+ (void)inlineWork:(void (^)(void))work { work(); }\n"
        "+ (void)drain { [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.01]]; }\n"
        "@end\n"
    )
    (root / "src/Foundation.btrc").write_text("")
    (root / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "oneShotConsumer"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["+[NSRunLoop currentRunLoop]", "-[NSRunLoop performBlock:]", '
        '"+[OneShotProbe inlineWork:]", "+[OneShotProbe drain]"]\n'
        + "".join(
            f'[native.bindings.callbacks."{method}.{parameter}"]\n'
            'interface = "IWork"\nlifetime = "one-shot"\nfailure = "abort"\nexecutor = "caller"\n'
            'activation-failure = "abort"\ncancellation = "abandon"\n'
            for method, parameter in (("-[NSRunLoop performBlock:]", "block"), ("+[OneShotProbe inlineWork:]", "work"))
        )
        + '[[native.sources]]\npath = "Probe.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
        '[[native.frameworks]]\nname = "Foundation"\nos = ["macos"]\n'
    )
    source.write_text("""import Library.Callback;
import ./Foundation.btrc;
int delivered = 0;
int destroyed = 0;
class Work implements IWork {
	public CallbackScope? scope;
	public void invoke() {
		delivered++;
		if (self.scope != null) { assert(self.scope.cancel() == CallbackCancellation.Pending); }
	}
	public void __del__() { destroyed++; }
}
void run(bool inlineWork, bool cancelled) {
	int before = delivered;
	int beforeDestroyed = destroyed;
	var scope = CallbackScope();
	var work = Work();
	if (inlineWork && cancelled) { work.scope = scope; }
	var request = inlineWork ? OneShotProbe.inlineWork(work, scope) : NSRunLoop.currentRunLoop().performBlock(work, scope);
	work = null;
	if (inlineWork) {
		assert(request.pollCompletion() == CallbackCancellation.Complete);
		assert(delivered == before + 1);
	} else {
		assert(delivered == before && destroyed == beforeDestroyed);
		if (cancelled) { assert(scope.cancel() == CallbackCancellation.Pending); }
		OneShotProbe.drain();
		assert(request.pollCompletion() == CallbackCancellation.Complete);
		assert(delivered == before + (cancelled ? 0 : 1));
	}
	assert(destroyed == beforeDestroyed + 1);
	assert(scope.cancel() == CallbackCancellation.Complete);
	assert(scope.pendingCount() == 0);
}
int main() {
	run(true, false); run(true, true); run(false, false); run(false, true);
	assert(delivered == 3 && destroyed == 4);
	return 0;
}
""")
    return source


@pytest.mark.parametrize("sanitize", [False, True])
def test_one_shot_native_blocks_complete_inline_and_on_run_loop(one_shot_project, native_compile, sanitize):
    source = one_shot_project
    root = source.parent.parent
    plan = root / "OneShot.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "OneShot.c"
    generated.write_text(compiled.c_source)
    executable = root / "OneShot"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    "file, old, new, diagnostic",
    [
        (
            "btrc.toml",
            'cancellation = "abandon"',
            'cancellation = "entry-barrier"',
            "one-shot cancellation requires abandon",
        ),
        (
            "btrc.toml",
            'activation-failure = "abort"',
            'activation-failure = "guess"',
            "activation-failure requires unpublished or abort",
        ),
        (
            "btrc.toml",
            'cancellation = "abandon"',
            'cancellation = "abandon"\nunregister = ""',
            "without unregister/context",
        ),
        ("btrc.toml", 'executor = "caller"', 'executor = "any"', "executor currently requires caller"),
        ("Foundation.h", "+ (void)inlineWork:", "+ (id)inlineWork:", "requires void native and callback results"),
        ("Foundation.h", "(void (^)(void))work", "(int (^)(void))work", "requires void native and callback results"),
        ("Foundation.h", "(void (^)(void))work", "(void (NS_NOESCAPE ^)(void))work", "escaping Objective-C block"),
    ],
)
def test_one_shot_native_blocks_reject_unproven_mapping(one_shot_project, native_compile, file, old, new, diagnostic):
    root = one_shot_project.parent.parent
    path = root / file
    original = path.read_text()
    assert old in original
    path.write_text(original.replace(old, new))
    compiled = native_compile(one_shot_project)
    assert not compiled.successful
    assert diagnostic in str(compiled.failure) + str(compiled.diagnostics)


@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize(
    "scenario",
    ["duplicate", "callback-throw", "wrong-thread", "published-throw", "unpublished-throw", "inline-unpublished-throw"],
)
def test_one_shot_native_failure_boundaries(one_shot_project, native_compile, sanitize, scenario):
    source = one_shot_project
    root = source.parent.parent
    recoverable = scenario in {"unpublished-throw", "inline-unpublished-throw"}
    if recoverable:
        manifest = root / "btrc.toml"
        manifest.write_text(
            manifest.read_text().replace('activation-failure = "abort"', 'activation-failure = "unpublished"')
        )
    failure = '[NSException raise:NSInternalInconsistencyException format:@"native failure"];'
    bodies = {
        "duplicate": "work(); work();",
        "callback-throw": "work();",
        "wrong-thread": "pthread_t thread; assert(pthread_create(&thread, NULL, invokeWork, (void*)work) == 0); assert(pthread_join(thread, NULL) == 0);",
        "published-throw": "[[NSRunLoop currentRunLoop] performBlock:work]; " + failure,
        "unpublished-throw": "(void)work; " + failure,
        "inline-unpublished-throw": "work(); " + failure,
    }
    driver = root / "Probe.m"
    driver.write_text(
        "#include <assert.h>\n#include <pthread.h>\n"
        + (
            "static void* invokeWork(void* context) { ((void (^)(void))context)(); return NULL; }\n"
            if scenario == "wrong-thread"
            else ""
        )
        + driver.read_text().replace("{ work(); }", "{ " + bodies[scenario] + " }")
    )
    callback = 'throw "expected one-shot error";' if scenario == "callback-throw" else "delivered++;"
    verification = (
        f"assert(caught && destroyed == 1 && delivered == {int(scenario == 'inline-unpublished-throw')}); "
        "assert(scope.cancel() == CallbackCancellation.Complete); return 0;"
        if recoverable
        else "return 99;"
    )
    source.write_text(f"""import Library.Callback;
import ./Foundation.btrc;
int delivered = 0;
int destroyed = 0;
class Work implements IWork {{
	public void invoke() {{ {callback} }}
	public void __del__() {{ destroyed++; fprintf(stderr, "receiver destroyed\\n"); }}
}}
int main() {{
	var scope = CallbackScope();
	bool caught = false;
	try {{ OneShotProbe.inlineWork(Work(), scope); }} catch (string error) {{ caught = true; }}
	{verification}
}}
""")
    plan = root / "OneShot.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "OneShot.c"
    generated.write_text(compiled.c_source)
    executable = root / "OneShot"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == (0 if recoverable else -6), completed.stderr
    if not recoverable:
        diagnostic = {
            "duplicate": "cannot deliver twice",
            "callback-throw": "expected one-shot error",
            "wrong-thread": "creating thread",
            "published-throw": "publication state is unknown",
        }[scenario]
        assert diagnostic in completed.stderr
        assert "receiver destroyed" not in completed.stderr
    assert "ERROR: AddressSanitizer" not in completed.stderr
    assert "runtime error:" not in completed.stderr


@pytest.mark.parametrize("reverse", [False, True])
def test_one_shot_native_lifetime_conflict(one_shot_project, native_compile, reverse):
    source = one_shot_project
    manifest = source.parent.parent / "btrc.toml"
    binding = manifest.read_text().split("[[native.bindings]]", 1)[1].split("[[native.sources]]", 1)[0]
    binding = binding.replace('module = "Foundation"', 'module = "Other"').replace(
        'lifetime = "one-shot"', 'lifetime = "call"'
    )
    binding = binding.replace('activation-failure = "abort"\n', "").replace('cancellation = "abandon"\n', "")
    manifest.write_text(manifest.read_text() + "[[native.bindings]]" + binding)
    (source.parent / "Other.btrc").write_text("")
    imports = ["import ./Foundation.btrc;", "import ./Other.btrc;"]
    source.write_text("\n".join(reversed(imports) if reverse else imports) + "\nint main() { return 0; }\n")
    compiled = native_compile(source)
    assert not compiled.successful
    assert "conflicting native declaration" in str(compiled.failure) + str(compiled.diagnostics)


@pytest.mark.parametrize("sanitize", [False, True])
def test_one_shot_native_late_object_claims(one_shot_project, native_compile, sanitize):
    source = one_shot_project
    root = source.parent.parent
    header = root / "Foundation.h"
    header.write_text(
        header.read_text()
        .replace("@interface OneShotProbe", "NS_ASSUME_NONNULL_BEGIN\n@interface OneShotProbe")
        .replace(
            "@end",
            "+ (void)objectWork:(void (^)(NSObject* _Nonnull))work;\n+ (int)liveObjects;\n@end\nNS_ASSUME_NONNULL_END",
        )
    )
    driver = root / "Probe.m"
    driver.write_text(
        driver.read_text()
        .replace(
            "@implementation OneShotProbe",
            "static int liveObjects;\n@interface WorkObject : NSObject\n@end\n@implementation WorkObject\n"
            "- (id)init { self = [super init]; if (self) liveObjects++; return self; }\n"
            "- (void)dealloc { liveObjects--; [super dealloc]; }\n@end\n@implementation OneShotProbe",
        )
        .replace(
            "+ (void)drain",
            "+ (int)liveObjects { return liveObjects; }\n"
            "+ (void)objectWork:(void (^)(NSObject*))work { NSObject* object = [WorkObject new]; "
            "[[NSRunLoop currentRunLoop] performBlock:^{ work(object); }]; [object release]; }\n"
            "+ (void)drain",
        )
    )
    manifest = root / "btrc.toml"
    manifest.write_text(
        manifest.read_text()
        .replace(
            '"+[OneShotProbe drain]"]',
            '"+[OneShotProbe drain]", "+[OneShotProbe objectWork:]", "+[OneShotProbe liveObjects]"]',
        )
        .replace(
            "[[native.sources]]",
            '[native.bindings.callbacks."+[OneShotProbe objectWork:].work"]\n'
            'interface = "IObjectWork"\nlifetime = "one-shot"\nfailure = "abort"\nexecutor = "caller"\n'
            'activation-failure = "abort"\ncancellation = "abandon"\n[[native.sources]]',
        )
    )
    source.write_text("""import Library.Callback;
import ./Foundation.btrc;
class Work implements IObjectWork {
	public NSObject? value;
	public void invoke(NSObject value) { assert(OneShotProbe.liveObjects() == 1); self.value = value; }
}
void run(bool cancelled) {
	var scope = CallbackScope();
	var receiver = Work();
	var request = OneShotProbe.objectWork(receiver, scope);
	assert(OneShotProbe.liveObjects() == 1);
	if (cancelled) { assert(scope.cancel() == CallbackCancellation.Pending); }
	OneShotProbe.drain();
	assert(request.pollCompletion() == CallbackCancellation.Complete);
	assert(scope.cancel() == CallbackCancellation.Complete);
	assert((receiver.value == null) == cancelled);
	assert(OneShotProbe.liveObjects() == (cancelled ? 0 : 1));
	receiver.value = null;
	assert(OneShotProbe.liveObjects() == 0);
}
int main() { run(false); run(true); return 0; }
""")
    plan = root / "OneShot.link.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "OneShot.c"
    generated.write_text(compiled.c_source)
    executable = root / "OneShot"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    completed = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr


def test_one_shot_native_rejects_replacement_lifecycle(one_shot_project, native_compile):
    one_shot_project.write_text("""import ./Foundation.btrc;
class CallbackScope {}
class CallbackRequest<TReceiver> {
	private TReceiver receiver;
	public CallbackRequest(TReceiver receiver) { self.receiver = receiver; }
	public void activate(CallbackScope scope) {}
	public void publish() {}
	public void abortActivation() {}
	public TReceiver? enter() { return self.receiver; }
	public void leave() {}
	public bool isOpen() { return true; }
	public bool close() { return true; }
	public int cancel() { return 0; }
	public int complete() { return 0; }
	public int pollCompletion() { return 0; }
}
int main() { return 0; }
""")
    compiled = native_compile(one_shot_project)
    assert not compiled.successful
    assert "require import Library.Callback" in str(compiled.failure) + str(compiled.diagnostics)
