"""Run the same file operations in two directories, then compare the trees.

Usage: file_operations.py SEED COUNT DIRECTORY DIRECTORY

One directory is a mount of a userspace filesystem and the other an ordinary
directory. Every operation must succeed or fail the same way in both, and
the trees must end identical: names, kinds, sizes, permissions, link counts,
link targets and contents.
"""

import hashlib
import os
import random
import stat
import sys


def outcome(root, step):
    try:
        apply(root, step)
    except OSError as error:
        return error.errno
    return 0


def apply(root, step):
    kind, first, second, number = step
    a = os.path.join(root, first)
    b = os.path.join(root, second)
    if kind == "write":
        with open(a, "wb") as file:
            file.write(bytes([number % 251]) * (number * 37 % 20000))
    elif kind == "append":
        with open(a, "ab") as file:
            file.write(b"more" * (number % 50))
    elif kind == "patch":
        with open(a, "r+b") as file:
            file.seek(number % 5000)
            file.write(b"patched")
    elif kind == "truncate":
        os.truncate(a, number % 3000)
    elif kind == "mkdir":
        os.mkdir(a, 0o755)
    elif kind == "rmdir":
        os.rmdir(a)
    elif kind == "remove":
        os.unlink(a)
    elif kind == "rename":
        os.rename(a, b)
    elif kind == "symlink":
        os.symlink(second, a)
    elif kind == "link":
        os.link(a, b)
    elif kind == "chmod":
        os.chmod(a, 0o600 if number % 2 else 0o644)
    elif kind == "touch":
        os.utime(a, (1_600_000_000 + number, 1_600_000_000 + number))


def steps(seed, count):
    source = random.Random(seed)
    names = [f"n{index}" for index in range(12)]
    folders = ["", "d0", "d1", os.path.join("d0", "inner")]
    kinds = [
        "write",
        "write",
        "append",
        "patch",
        "truncate",
        "mkdir",
        "rmdir",
        "remove",
        "rename",
        "symlink",
        "link",
        "chmod",
        "touch",
    ]
    for _ in range(count):
        yield (
            source.choice(kinds),
            os.path.join(source.choice(folders), source.choice(names)),
            os.path.join(source.choice(folders), source.choice(names)),
            source.randrange(1_000_000),
        )


def describe(root):
    seen = {}
    for folder, folders, files in os.walk(root):
        for name in sorted(folders + files):
            path = os.path.join(folder, name)
            status = os.lstat(path)
            facts = [stat.S_IFMT(status.st_mode), stat.S_IMODE(status.st_mode)]
            if stat.S_ISLNK(status.st_mode):
                facts.append(os.readlink(path))
            elif stat.S_ISREG(status.st_mode):
                with open(path, "rb") as file:
                    facts += [
                        status.st_size,
                        status.st_nlink,
                        int(status.st_mtime),
                        hashlib.sha256(file.read()).hexdigest(),
                    ]
            seen[os.path.relpath(path, root)] = facts
    return seen


def main():
    seed, count, left, right = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3], sys.argv[4]
    for index, step in enumerate(steps(seed, count)):
        results = [outcome(root, step) for root in (left, right)]
        if results[0] != results[1]:
            print(f"FAIL: step {index} {step}: {results[0]} in {left}, {results[1]} in {right}")
            return 1
    one, other = describe(left), describe(right)
    if one != other:
        for name in sorted(set(one) | set(other)):
            if one.get(name) != other.get(name):
                print(f"FAIL: {name}: {one.get(name)} in {left}, {other.get(name)} in {right}")
        return 1
    print(f"PASS: {count} operations, {len(one)} entries alike")
    return 0


if __name__ == "__main__":
    sys.exit(main())
