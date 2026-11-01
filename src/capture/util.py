"""Small helpers shared across the capture modules."""

from datetime import datetime


def walk(obj):
    """Every dict/list/scalar in a decoded JSON tree, parents before children."""
    yield obj
    if isinstance(obj, dict):
        for value in obj.values():
            yield from walk(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from walk(value)


def when(ms) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M") if ms else "?"
