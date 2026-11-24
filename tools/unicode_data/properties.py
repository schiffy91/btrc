"""Read property ranges from the pinned Unicode 17.0.0 Character Database."""

VERSION = "17.0.0"
SOURCE = "unicode-org/unicodetools@725fb6055cd42915c74bcf77b91aa8fb8ef18669"


def records(path):
    for line in path.read_text().splitlines():
        fields = line.partition("#")[0].strip()
        if fields:
            yield [field.strip() for field in fields.split(";")]


def interval(field):
    ends = field.split("..")
    return int(ends[0], 16), int(ends[-1], 16) + 1
