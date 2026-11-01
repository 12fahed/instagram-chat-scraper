"""CLI for the offline analyser.

    python -m src.analyze report data/captures
    python -m src.analyze build  data/captures --me <your-username>
    python -m src.analyze build  data/captures --me <your-username> --media

Default input is data/captures, default output is data/out (both gitignored).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import load, pages, parse, schema


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
        sp.add_argument("input", nargs="?", default="data/captures", type=Path,
                        help="capture file or directory (default: data/captures)")
        sp.add_argument("-o", "--out", default=Path("data/out"), type=Path,
                        help="output directory (default: data/out)")
        if name == "build":
            sp.add_argument("--me", help="your username / igid / sender id, so your bubbles go right")
            sp.add_argument("--title", default="Instagram chat", help="page title")
            sp.add_argument("--media", action="store_true",
                            help="download IG CDN images into out/media and link locally")
            sp.add_argument("--media-video", action="store_true",
                            help="with --media, also download video originals (large)")
            sp.add_argument("--split", choices=("auto", "month", "year", "none"),
                            default="auto",
                            help="split the archive into one page per month or year "
                                 f"(auto: by year over {pages.YEAR_THRESHOLD:,} messages, "
                                 f"by month over {pages.MONTH_THRESHOLD:,})")

    args = ap.parse_args(argv)
    files = load.collect_files(args.input)
    captured = load.load_pages(files)
    chat = parse.build(captured)

    if args.cmd == "report":
        text = schema.report(captured, chat)
        print(text)
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "report.txt").write_text(text + "\n", encoding="utf-8")
        print(f"\nwritten: {args.out / 'report.txt'}")
        return

    me = _resolve_me(chat, args.me)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.media:
        print("downloading media…")
        print("  ", media_stats(chat, args.out, args.media_video))

    json_path = args.out / "chat.json"
    json_path.write_text(
        json.dumps({"thread_id": chat["thread_id"], "me": me, "people": chat["people"],
                    "messages": chat["messages"]}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    written = pages.render_all(chat, me, args.title, args.split)
    for name, page in written.items():
        (args.out / name).write_text(page, encoding="utf-8")

    msgs = chat["messages"]
    replies = sum(1 for m in msgs if m["reply"])
    reacts = sum(1 for m in msgs if m["reactions"])
    media = sum(len(m.get("media") or []) for m in msgs)
    removed = sum(1 for m in msgs if m["kind"] == "removed")
    unknown = sum(1 for m in msgs if m["kind"] == "unknown")
    print(f"{len(msgs):,} messages ({replies:,} replies, {reacts:,} reacted, "
          f"{media:,} attachments, {removed} removed)")
    if unknown:
        print(f"WARNING: {unknown} messages still render as Unsupported — run `report`")
    print(f"written: {json_path}")
    for name in sorted(written):
        print(f"         {args.out / name}")


def media_stats(chat: dict, out: Path, videos: bool = False) -> dict:
    from .media import mirror
    return mirror(chat, out, videos=videos)


if __name__ == "__main__":
    main()
