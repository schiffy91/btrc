# Library.Java

The process's Java VM and the runtime that compiler-generated Java bindings
call (interop step 4, [native-interop-ownership.md](../../../docs/design/native-interop-ownership.md)
section 2.3).

- On Android, `JavaVirtualMachine` reports whether ART is running and adopted,
  the number of live global and weak references, attached threads and active
  native registrations. The application supplies the VM to `JNI_OnLoad`.
- Desktop programs that create a VM or call Java use the optional
  [JavaHost package](../../optional/JavaHost/README.md). Its migration keeps
  existing desktop lifecycle and reference-counting calls intact.
- `JNI.h` exposes the C interface for ART adoption and compiler-generated JNI
  adapters. Both providers share the reference counts, per-thread environment,
  class cache, UTF-16 string conversions and exception translation in
  `JavaRuntime.h`.
- For Java natives (interop step 7, `natives` in a Java binding), the
  generated RegisterNatives thunks install the `JNIEnv` Java called them with
  for the duration of each call (`btrcJavaEnter`/`btrcJavaLeave`), copy
  argument strings through UTF-16 (`btrcJavaCopyString`), raise Java
  exceptions with UTF-16 messages (`btrcJavaThrow`) and register through
  `btrcJavaRegisterNatives`, which terminates when the running class does not
  declare a native the class file did.
- Generated `JavaWeak<Class>` owners count their weak global references
  (`btrcJavaWeakClaim`/`btrcJavaWeakUnclaim`), and every adapter of a class
  or natives registration with `executor = "main"` calls
  `btrcJavaRequireMain`: the main thread is the thread of
  `android.os.Looper.getMainLooper()`, read once through checked JNI and
  cached as a global reference outside the user count. Any other thread
  terminates, and so does the first check in a VM with no main Looper, such
  as a host JVM that never prepared one.

A library that a running VM loads adopts it instead of creating one: its
`JNI_OnLoad` calls `btrcJavaAdopt(machine)` from C and returns
`JNI_VERSION_1_6`. That is how an Android application, or `app_process`, runs
BTRC code, and a host `java` process that calls `System.load` does the same.
The loading thread keeps the environment its VM gave it, other threads attach
and detach as above, and the VM is never destroyed: `shutdown` on an adopted
VM terminates, as do VM options and a second VM. A host program embedding the
VM this way compiles its `main` as `btrc_program_main` (`-Dmain=btrc_program_main`)
and calls it from a native method.

An adopted VM's application `ClassLoader` is the context class loader of the
thread that runs `JNI_OnLoad` (an Android application's main thread runs with
its `PathClassLoader`). `btrcJavaAdopt` caches it as a global reference, and
every class then resolves through its `loadClass` on every thread, so a thread
the runtime attached sees the application's classes; `FindClass` there would
search the system class loader. A class that loader does not know falls back
to `FindClass`.

The Android NDK sysroot supplies `jni.h`. The default desktop standard library
has no JDK requirement.
