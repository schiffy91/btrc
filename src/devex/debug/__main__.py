"""Package entry point for ``python -m src.devex.debug``."""

from .runtime.bootstrap import LldbBootstrap


def main() -> None:
    LldbBootstrap().run()


if __name__ == "__main__":
    main()
