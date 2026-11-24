# JavaHost

JavaHost lets a desktop BTRC program start a JVM or use the JVM that loaded
its native library. It provides the desktop API formerly exposed by
`Library.Java.JavaVirtualMachine`.

Add a dependency in the application’s `btrc.toml`. Give the path from that
manifest to the JavaHost directory in your checkout or compiler distribution.
A source checkout carries it in `src/optional`. A relocatable compiler archive
carries it in `share/btrc/optional`.

```toml
[dependencies]
JavaHost = { path = "../btrc/src/optional/JavaHost" }
```

Change the import to `JavaHost.JavaVirtualMachine`. Existing lifecycle and
reference-accounting calls retain their signatures.

```btrc
import JavaHost.JavaVirtualMachine;
import Library.Vector;

int main() {
	Vector<string> options = ["-Xcheck:jni"];
	JavaVirtualMachine.createHost(options);
	JavaVirtualMachine.shutdown();
	return 0;
}
```

The package requires a JDK for the target and a `btrc-jni.pc` visible to
pkg-config. Its Cflags select the JDK include directory and the platform
subdirectory with `jni_md.h`. Its Libs select the JDK's invocation library.
The host process must be able to load that library at runtime. On Linux, for
example, a JDK installed in `/opt/jdk` can provide these settings:

```pkg-config
prefix=/opt/jdk
Name: btrc-jni
Description: JDK headers and HotSpot for an optional desktop host
Version: 17
Cflags: -I${prefix}/include -I${prefix}/include/linux
Libs: -L${prefix}/lib/server -Wl,-rpath,${prefix}/lib/server -ljvm
```

A Java process loading BTRC through `System.load` can adopt its existing VM.
Call `btrcJavaAdopt` from the library's `JNI_OnLoad`. Threads, references and
class loading follow the same rules as [ART adoption](../../stdlib/Java/README.md).
The process owns an adopted VM for its entire lifetime.

Android code continues to import `Library.Java.JavaVirtualMachine` and uses
the application's ART VM and the NDK.
