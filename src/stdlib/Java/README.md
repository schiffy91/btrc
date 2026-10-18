# Library.Java

The process's Java VM and the runtime that compiler-generated Java bindings
call (interop step 4, [native-interop-ownership.md](../../../docs/design/native-interop-ownership.md)
section 2.3).

- `JavaVirtualMachine` starts a host VM (`createHost`), reports whether the
  running VM was adopted (`adopted`), live global references, attached
  threads and Java natives registrations not yet freed (`liveNatives`), and
  shuts a created VM down (`shutdown`).
- `JNI.h` and `JavaRuntime.c` own the one VM, the per-thread `JNIEnv` (lazy
  `AttachCurrentThreadAsDaemon`, detached when the thread exits), user claim
  counting, the class and member ID cache, UTF-16 string transcoding and Java
  exception messages. Generated adapters call them by name.
- For Java natives (interop step 7, `natives` in a Java binding), the
  generated RegisterNatives thunks install the `JNIEnv` Java called them with
  for the duration of each call (`btrcJavaEnter`/`btrcJavaLeave`), copy
  argument strings through UTF-16 (`btrcJavaCopyString`), raise Java
  exceptions with UTF-16 messages (`btrcJavaThrow`) and register through
  `btrcJavaRegisterNatives`, which terminates when the running class does not
  declare a native the class file did.

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

On macOS and Linux the `btrc-jni` pkg-config package supplies JDK 17's headers
and HotSpot (the flake's dev shell provides it). On Android the NDK sysroot
supplies `jni.h` and the application supplies the VM.
