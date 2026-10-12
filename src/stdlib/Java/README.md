# Library.Java

The process's Java VM and the runtime that compiler-generated Java bindings
call (interop step 4, [native-interop-ownership.md](../../../docs/design/native-interop-ownership.md)
section 2.3).

- `JavaVirtualMachine` starts a host VM (`createHost`), reports live global
  references and attached threads, and shuts the VM down (`shutdown`).
- `JNI.h` and `JavaRuntime.c` own the one VM, the per-thread `JNIEnv` (lazy
  `AttachCurrentThreadAsDaemon`, detached when the thread exits), user claim
  counting, the class and member ID cache, UTF-16 string transcoding and Java
  exception messages. Generated adapters call them by name.

On macOS and Linux the `btrc-jni` pkg-config package supplies JDK 17's headers
and HotSpot (the flake's dev shell provides it). On Android the NDK sysroot
supplies `jni.h` and the application supplies the VM.
