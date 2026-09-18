"""Backward-compatible entry point for the former external ASTK runner."""

from .execute_suppa import execute, main


__all__ = ["execute", "main"]


if __name__ == "__main__":
    main()
