# Filesystems served by a program: Library.FileSystem.Userspace mounts three
# of them through the kernel's FUSE protocol and ordinary programs use them.
# The in-memory one answers everything itself; the forwarding one must behave
# exactly like the directory it forwards to, hand opened files to the kernel
# when that is agreed, and fail every use once its process is killed; the
# third answers late and drops a reply. Mounting needs root, which no test
# runner has, so it boots a NixOS VM.
{ pkgs, btrcpy, source }:
let
  program = pkgs.stdenv.mkDerivation {
    name = "btrc-userspace-mounts";
    src = source;
    nativeBuildInputs = [ btrcpy ];
    dontConfigure = true;
    buildPhase = ''
      export BTRC_CACHE_DIR="$TMPDIR/cache" BTRC_STATE_DIR="$TMPDIR/state" BTRC_PKG_CACHE="$TMPDIR/packages"
      btrcpy --strict-imports UserspaceMounts.btrc -o UserspaceMounts.c
      $CC -std=c11 -Wall -Wextra -Werror -pedantic-errors -D_GNU_SOURCE=1 UserspaceMounts.c -o userspace-mounts
    '';
    installPhase = ''
      install -Dm755 userspace-mounts "$out/bin/userspace-mounts"
      install -Dm644 file_operations.py "$out/share/file_operations.py"
    '';
  };
  mounts = "${program}/bin/userspace-mounts";
  operations = "${pkgs.python3}/bin/python3 ${program}/share/file_operations.py";
in pkgs.testers.runNixOSTest {
  name = "btrc-userspace-filesystem";
  nodes.machine = {
    boot.kernelPackages = pkgs.linuxPackages_latest;
    boot.kernelModules = [ "fuse" ];
    environment.systemPackages = [ pkgs.attr ];
    virtualisation.memorySize = 2048;
  };
  testScript = ''
    def serve(arguments, log):
        machine.succeed(f"${mounts} {arguments} > /tmp/{log} 2>&1 &")
        machine.wait_until_succeeds(f"grep -q READY /tmp/{log}")

    def finish(log, expected):
        machine.succeed("umount /mnt")
        machine.wait_until_succeeds(f"grep -q '{expected}' /tmp/{log}")
        machine.fail("pgrep -x userspace-mount")
        machine.fail("grep -q ' /mnt ' /proc/mounts")

    machine.wait_for_unit("multi-user.target")
    machine.succeed("mkdir -p /mnt /bare /source /twin")

    # In memory: every answer comes from the program.
    serve("memory /mnt", "memory.log")
    machine.succeed("cd /mnt && echo one > a && echo two >> a && mkdir -p d/e && mv a d/e/b && ln -s d/e/b l && ln d/e/b h")
    assert machine.succeed("cat /mnt/l /mnt/h") == "one\ntwo\none\ntwo\n"
    assert machine.succeed("stat -c '%h %s %a' /mnt/h") == "2 8 644\n"
    machine.succeed("chmod 600 /mnt/h && truncate -s 2 /mnt/h && printf XY | dd of=/mnt/h bs=1 seek=5 conv=notrunc status=none")
    assert machine.succeed("stat -c '%a %s' /mnt/d/e/b") == "600 7\n"
    assert machine.succeed("od -An -c /mnt/d/e/b | tr -s ' '") == " o n \\0 \\0 \\0 X Y\n"
    machine.fail("rmdir /mnt/d")
    machine.fail("mkdir /mnt/h")
    machine.succeed("cd /mnt && for i in $(seq 1 500); do echo $i > f$i; done && test $(ls | wc -l) = 503 && test $(cat f500) = 500")
    machine.succeed("cd /mnt && rm -r f* l h d && test -z \"$(ls -A)\"")
    # The same random operations as an ordinary directory, with the same results.
    assert machine.succeed("${operations} 7 1500 /mnt /bare").startswith("PASS:")
    machine.succeed("rm -rf /mnt/* /bare/*")
    finish("memory.log", "memory: 1 nodes left")

    # Forwarding, with the filesystem doing the reads and writes itself.
    serve("forward /source /mnt", "plain.log")
    assert machine.succeed("${operations} 11 3000 /mnt /twin").startswith("PASS:")
    # What went through the mount is what the directory underneath holds.
    machine.succeed("diff -r /source /twin")
    machine.succeed("setfattr -n user.note -v kept /mnt/n0 2>/dev/null || (echo x > /mnt/n0 && setfattr -n user.note -v kept /mnt/n0)")
    assert machine.succeed("getfattr -n user.note --only-values /mnt/n0") == "kept"
    assert machine.succeed("getfattr -n user.note --only-values /source/n0") == "kept"
    machine.succeed("dd if=/dev/urandom of=/mnt/big bs=1M count=24 status=none && cmp /mnt/big /source/big")
    machine.succeed("echo 3 > /proc/sys/vm/drop_caches && cmp /mnt/big /source/big")
    finish("plain.log", "forward: passthrough 0, reads [1-9]")

    # Forwarding, with opened files handed to the kernel: no read or write
    # reaches the filesystem, and a mapped file works.
    machine.succeed("rm -rf /source/* /twin/*")
    serve("forward /source /mnt passthrough", "direct.log")
    assert machine.succeed("${operations} 13 3000 /mnt /twin").startswith("PASS:")
    machine.succeed("diff -r /source /twin")
    machine.succeed("dd if=/dev/urandom of=/mnt/big bs=1M count=24 status=none && cmp /mnt/big /source/big")
    machine.succeed("echo 3 > /proc/sys/vm/drop_caches && cmp /mnt/big /source/big")
    machine.succeed("${pkgs.python3}/bin/python3 -c \"import mmap; f = open('/mnt/big', 'r+b'); m = mmap.mmap(f.fileno(), 0); m[0:4] = b'BTRC'; m.flush(); m.close(); f.close()\"")
    assert machine.succeed("head -c 4 /source/big") == "BTRC"
    finish("direct.log", "forward: passthrough 1, reads 0, writes 0")

    # A killed filesystem fails every use; it never answers with made-up data.
    machine.succeed("echo real > /source/kept")
    serve("forward /source /mnt", "killed.log")
    assert machine.succeed("cat /mnt/kept") == "real\n"
    machine.succeed("exec 9< /mnt/kept; pkill -9 -x userspace-mount; sleep 1; ! cat <&9 > /tmp/after-kill 2> /tmp/after-kill.error; test ! -s /tmp/after-kill")
    assert "not connected" in machine.fail("cat /mnt/kept 2>&1")
    assert "not connected" in machine.fail("ls /mnt 2>&1")
    assert "not connected" in machine.fail("sh -c 'echo new > /mnt/created' 2>&1")
    machine.succeed("umount /mnt")
    machine.fail("grep -q ' /mnt ' /proc/mounts")
    # A new filesystem takes the place of one that died without unmounting.
    serve("forward /source /mnt", "died.log")
    machine.succeed("pkill -9 -x userspace-mount; sleep 1")
    serve("forward /source /mnt", "again.log")
    assert machine.succeed("cat /mnt/kept") == "real\n"
    finish("again.log", "forward: passthrough 0")

    # One folder shown in place of another: found under the other's name
    # wherever that is moved, on another filesystem, with nothing mounted.
    machine.succeed("rm -rf /source/* && mkdir -p /source/a/stand /elsewhere && mount -t tmpfs none /elsewhere && echo there > /elsewhere/file && echo hidden > /source/a/stand/own")
    serve("forward /source /mnt show /source/a/stand /elsewhere", "shown.log")
    assert machine.succeed("cat /mnt/a/stand/file") == "there\n"
    assert machine.succeed("ls /mnt/a/stand") == "file\n"
    machine.succeed("echo made > /mnt/a/stand/new && test \"$(cat /elsewhere/new)\" = made && test ! -e /source/a/stand/new")
    assert "cross-device" in machine.fail("mv -T --no-copy /mnt/a/stand/new /mnt/a/moved 2>&1")
    machine.succeed("mv /mnt/a /mnt/b && test \"$(cat /mnt/b/stand/file)\" = there")
    finish("shown.log", "forward: passthrough 0")
    # With nothing to show, the folder is listed and cannot be entered: it
    # is neither empty nor gone.
    serve("forward /source /mnt show /source/b/stand \"\"", "absent.log")
    assert machine.succeed("ls /mnt/b") == "stand\n"
    assert "No such device or address" in machine.fail("ls /mnt/b/stand 2>&1")
    assert "No such device or address" in machine.fail("cat /mnt/b/stand/own 2>&1")
    finish("absent.log", "forward: passthrough 0")
    machine.succeed("umount /elsewhere")

    # Answers that come later do not hold up the others, and a reply that is
    # dropped fails its request instead of leaving the caller waiting.
    serve("held /mnt", "held.log")
    assert machine.succeed("cat /mnt/quick") == "quick\n"
    machine.succeed("cat /mnt/slow > /tmp/slow.out 2>&1 &")
    machine.succeed("sleep 1; test ! -s /tmp/slow.out")
    assert machine.succeed("cat /mnt/quick") == "quick\n"
    assert "Input/output error" in machine.fail("cat /mnt/dropped 2>&1")
    assert machine.succeed("cat /mnt/go") == "going\n"
    machine.wait_until_succeeds("test \"$(cat /tmp/slow.out)\" = later")
    finish("held.log", "held: 1 released")
  '';
}
