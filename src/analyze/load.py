"""Find SlideMessage nodes inside whatever shape the capture file has.

Accepts, transparently:
  * a raw GraphQL response body            {"data": {"fetch__SlideThread": ...}}
  * a capture.py record                    {"seq": .., "chunks": [ ...bodies... ]}
  * a list of either
  * .jsonl / .ndjson files (one body per line)

so the same code works on data/sample and on a full capture run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

MESSAGE_TYPENAME = "SlideMessage"


def walk(obj: Any) -> Iterator[Any]:
    """Every dict/list/scalar in the tree, parents before children."""
    yield obj
    if isinstance(obj, dict):
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


def read_json_file(path: Path) -> list[Any]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("for (;;);"):
        text = text[len("for (;;);"):]
    try:
        return [json.loads(text)]
    except json.JSONDecodeError:
        pass
    docs = []
    for line in text.splitlines():  # jsonl, or IG's multi-object streaming bodies
        line = line.strip()
        if not line:
            continue
        try:
            docs.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return docs


@dataclass
class Page:
    """One GraphQL response's worth of messages."""

    source: str
    nodes: list[dict] = field(default_factory=list)
    page_info: dict | None = None
    thread_id: str | None = None
    # Cursor the request asked for, when the capture kept the request variables.
    # Chaining these is the only hard proof that no page was skipped.
    request_cursor: str | None = None
    # Cursors this page handed out. They live on the *edge*, not the node, so they
    # have to be kept here - nodes carry no cursor at all.
    edge_cursors: list[str] = field(default_factory=list)

    @property
    def ts_range(self) -> tuple[int, int] | None:
        stamps = [int(n["timestamp_ms"]) for n in self.nodes if n.get("timestamp_ms")]
        return (min(stamps), max(stamps)) if stamps else None


CURSOR_KEYS = ("cursor", "before", "after")


def request_cursor(doc: Any) -> str | None:
    """capture.py keeps the decoded request form; pull the pagination cursor out of it."""
    for obj in walk(doc):
        if not isinstance(obj, dict):
            continue
        variables = obj.get("variables")
        if isinstance(variables, str):
            try:
                variables = json.loads(variables)
            except json.JSONDecodeError:
                continue
        if not isinstance(variables, dict):
            continue
        for k, v in variables.items():
            if isinstance(v, str) and v and any(c in k.lower() for c in CURSOR_KEYS):
                return v
    return None


def pages_from_doc(doc: Any, source: str) -> list[Page]:
    """One Page per slide_messages connection found; falls back to a bare node scan."""
    pages: list[Page] = []
    claimed: set[int] = set()

    for obj in walk(doc):
        if not isinstance(obj, dict):
            continue
        conn = obj.get("slide_messages")
        if not isinstance(conn, dict) or not isinstance(conn.get("edges"), list):
            continue
        edges = [e for e in conn["edges"] if isinstance(e, dict)]
        nodes = [e["node"] for e in edges if isinstance(e.get("node"), dict)]
        cursors = [e["cursor"] for e in edges if isinstance(e.get("cursor"), str)]
        claimed.update(id(n) for n in nodes)
        pages.append(
            Page(
                source=source,
                nodes=nodes,
                page_info=conn.get("page_info"),
                thread_id=obj.get("id"),
                request_cursor=request_cursor(doc),
                edge_cursors=cursors,
            )
        )

    loose = [
        o
        for o in walk(doc)
        if isinstance(o, dict) and o.get("__typename") == MESSAGE_TYPENAME and id(o) not in claimed
    ]
    if loose:
        pages.append(Page(source=source, nodes=loose))
    return pages


def load_pages(paths: list[Path]) -> list[Page]:
    pages: list[Page] = []
    for path in paths:
        for i, doc in enumerate(read_json_file(path)):
            label = path.name if i == 0 else f"{path.name}#{i}"
            pages.extend(pages_from_doc(doc, label))
    return pages


def collect_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    files = [
        p
        for p in sorted(target.rglob("*"))
        if p.is_file() and p.suffix.lower() in {".json", ".jsonl", ".ndjson"}
    ]
    if not files:
        raise SystemExit(f"no .json/.jsonl files under {target}")
    return files
