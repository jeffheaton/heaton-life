"""Interactive playground (PyQt6). Install with the extra: pip install heaton-life[playground]."""

from __future__ import annotations


def main(argv: list[str] | None = None) -> int:
    try:
        from heaton_life.playground.app import run
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.split(".")[0] == "PyQt6":
            print(
                "The playground needs PyQt6. Install it with:\n"
                '    pip install "heaton-life[playground]"'
            )
            return 1
        raise
    return run(argv)


__all__ = ["main"]
