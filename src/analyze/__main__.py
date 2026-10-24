"""CLI for the offline analyser.

    python -m src.analyze report data/sample
    python -m src.analyze build  data/sample --me __fahedkhan
    python -m src.analyze build  data/sample --me __fahedkhan --media

Default input is data/sample, default output is data/out (gitignored).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import load, parse, render, schema


def _resolve_me(chat: dict, wanted: str | None) -> str | None:
    """--me may be a username, an igid or a sender id."""
    if not wanted:
        return None
    for pid, person in chat["people"].items():
        if wanted in {pid, person.get("igid"), person.get("username"), person.get("name")}:
            return pid
    known = ", ".join(sorted(p.get("username") or p["id"] for p in chat["people"].values()))
    raise SystemExit(f"--me {wanted!r} matches nobody in this capture. Seen: {known}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m src.analyze")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name, help_text in (("report", "describe what is in the captures"),
                            ("build", "write chat.json + chat.html")):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("input", nargs="?", default="data/sample", type=Path,
                        help="capture file or directory (default: data/sample)")
        sp.add_argument("-o", "--out", default=Path("data/out"), type=Path,
                        help="output directory (default: data/out)")
        if name == "build":
            sp.add_argument("--me", help="your username / igid / sender id, so your bubbles go right")
            sp.add_argument("--title", default="Instagram chat", help="page title")
            sp.add_argument("--media", action="store_true",
                            help="download IG CDN images into out/media and link locally")

    args = ap.parse_args(argv)
    files = load.collect_files(args.input)
    pages = load.load_pages(files)
    chat = parse.build(pages)

    if args.cmd == "report":
        text = schema.report(pages, chat)
        print(text)
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "report.txt").write_text(text + "\n", encoding="utf-8")
        print(f"\nwritten: {args.out / 'report.txt'}")
        return

    me = _resolve_me(chat, args.me)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.media:
        print("downloading media…")
        print("  ", parse_stats := media_stats(chat, args.out))
    html_path = args.out / "chat.html"
    json_path = args.out / "chat.json"
    json_path.write_text(
        json.dumps({"thread_id": chat["thread_id"], "me": me, "people": chat["people"],
                    "messages": chat["messages"]}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    html_path.write_text(render.render(chat, me, args.title), encoding="utf-8")
    replies = sum(1 for m in chat["messages"] if m["reply"])
    reacts = sum(1 for m in chat["messages"] if m["reactions"])
    print(f"{len(chat['messages'])} messages ({replies} replies, {reacts} with reactions)")
    print(f"written: {json_path}\n         {html_path}")


def media_stats(chat: dict, out: Path) -> dict:
    from .media import mirror
    return mirror(chat, out)


if __name__ == "__main__":
    main()
