"""Structural report over captured pages: what shapes are in there, and what
this parser does not yet understand.

The point is to make a full capture run self-checking — run `report` after it
and anything the renderer would silently drop shows up under UNHANDLED.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from .parse import normalise, parse_content

KNOWN_CONTENT = {
    "SlideMessageText",
    "SlideMessageAdminText",
    "SlideMessageXMAContent",
    "SlideMessageImageContent",
    "SlideMessageRavenImageContent",
    "SlideMessageRavenVideoContent",
    "SlideMessageVideosContent",
    "SlideMessageAudiosContent",
    "SlideMessageAnimatedMediaContent",
    None,  # content: null / content_type NOT_SET - rendered as "Message removed"
}
KNOWN_XMA = {
    "SlideMessagePortraitXMA",
    "SlideMessageStandardXMA",
    "SlideMessagePlaceholderXMA",
    "SlideMessageExpiredPlaceholderXMA",
}

PAGES_SHOWN = 3        # head and tail of the page list; the middle is summarised
GAPS_SHOWN = 5         # only the longest quiet stretches between pages

# Fields the renderer reads. Anything else on a node is listed as "carried but unused"
# so a new IG feature (polls, voice notes, ...) is visible rather than silent.
USED_NODE_KEYS = {
    "message_id", "id", "timestamp_ms", "sender_fbid", "sender", "content", "content_type",
    "text_body", "reactions", "replied_to_message", "replied_to_message_id", "mentions",
    "igd_is_forwarded", "is_pinned", "is_ai_generated", "slide_edit_history", "__typename",
}


def _cursors(page) -> set:
    pi = page.page_info or {}
    out = {pi.get("start_cursor"), pi.get("end_cursor")}
    out.update(page.edge_cursors)
    return {c for c in out if c}


def _fmt_delta(delta: timedelta) -> str:
    secs = int(delta.total_seconds())
    if secs < 90:
        return f"{secs}s"
    if secs < 5400:
        return f"{secs // 60}m"
    if secs < 172800:
        return f"{secs / 3600:.1f}h"
    return f"{secs / 86400:.1f} days"


def _when(ms: int | None) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S") if ms else "?"


def report(pages: list, chat: dict) -> str:
    out: list[str] = []
    w = out.append

    w("PAGES")
    rows = []
    for page in pages:
        pi = page.page_info or {}
        rows.append((page.source, len(page.nodes), page.ts_range, pi))

    def page_line(source, count, rng, pi):
        span = f"{_when(rng[0])}  ->  {_when(rng[1])}" if rng else "no timestamps"
        w(f"  {source:<40} {count:>4} messages   {span}")

    if len(rows) <= PAGES_SHOWN * 2 + 1:
        for row in rows:
            page_line(*row)
    else:
        for row in rows[:PAGES_SHOWN]:
            page_line(*row)
        middle = rows[PAGES_SHOWN:-PAGES_SHOWN]
        w(f"  ... {len(middle)} more pages, {sum(r[1] for r in middle):,} messages ...")
        for row in rows[-PAGES_SHOWN:]:
            page_line(*row)
    sizes = Counter(r[1] for r in rows)
    w(f"  {len(rows)} pages, {sizes.most_common(1)[0][0]} messages each "
      f"({sizes.most_common(1)[0][1]} of them)")

    msgs = chat["messages"]
    total_nodes = sum(len(p.nodes) for p in pages)
    w("")
    w("COVERAGE")
    w(f"  nodes seen            {total_nodes}")
    w(f"  unique messages       {len(msgs)}  ({total_nodes - len(msgs)} duplicate sightings)")
    if msgs:
        w(f"  oldest                {_when(msgs[0]['ts'])}")
        w(f"  newest                {_when(msgs[-1]['ts'])}")
    w(f"  thread_fbid           {chat['thread_id']}")
    w(f"  participants          {len(chat['people'])}")
    for p in chat["people"].values():
        w(f"    {p.get('username') or '?':<20} id={p['id']}  igid={p.get('igid')}  name={p.get('name')}")

    # Pages come back newest-first and are contiguous by construction, so a time
    # gap between two pages is normally just a quiet stretch in the chat. The only
    # hard evidence that a scroll step was dropped is the cursor chain: the cursor a
    # request asked for must be one some captured page handed out.
    ranged = sorted([p for p in pages if p.ts_range], key=lambda p: -p.ts_range[1])
    w("")
    w("CONTINUITY")
    if not ranged:
        w("  nothing to check")
    else:
        w(f"  newest page  {ranged[0].source}  up to {_when(ranged[0].ts_range[1])}")
        w(f"  oldest page  {ranged[-1].source}  back to {_when(ranged[-1].ts_range[0])}")
        gaps = []
        for newer, older in zip(ranged, ranged[1:]):
            gaps.append((newer.ts_range[0] - older.ts_range[1], newer, older))
        gaps.sort(key=lambda g: -g[0])
        w(f"  longest quiet stretches between pages (not necessarily missing data):")
        for delta, newer, older in gaps[:GAPS_SHOWN]:
            w(f"    {_fmt_delta(timedelta(milliseconds=delta)):>10}  "
              f"{_when(older.ts_range[1])} -> {_when(newer.ts_range[0])}")

    # The bottom-of-thread page is fetched with a cursor the inbox handed out
    # before recording started, so it can never chain. Everything after it must.
    initial = ranged[0] if ranged else None
    chained = [p for p in pages if p.request_cursor and p is not initial]
    w("")
    if not chained:
        w("  cursor chain: not checkable (captures hold responses only, no request variables)")
    else:
        handed_out = {c for p in pages for c in _cursors(p)}
        orphans = [p for p in chained if p.request_cursor not in handed_out]
        if orphans:
            w(f"  cursor chain: {len(orphans)} of {len(chained)} paged requests asked for a cursor")
            w(f"  no captured page handed out - a scroll step is missing before each of these:")
            for p in orphans[:GAPS_SHOWN]:
                w(f"    {p.source}")
            if len(orphans) > GAPS_SHOWN:
                w(f"    ... and {len(orphans) - GAPS_SHOWN} more")
        else:
            w(f"  cursor chain: all {len(chained)} paged requests follow a captured page")

    nodes = [n for p in pages for n in p.nodes]
    ct, tn, xt, kinds = Counter(), Counter(), Counter(), Counter()
    unhandled_nodes, extra_keys = [], Counter()
    for n in nodes:
        ct[n.get("content_type")] += 1
        content = n.get("content") or {}
        tn[content.get("__typename")] += 1
        if content.get("__typename") == "SlideMessageXMAContent":
            xt[(content.get("xma") or {}).get("__typename")] += 1
        kinds[parse_content(n)["kind"]] += 1
        extra_keys.update(k for k in n if k not in USED_NODE_KEYS)
        if content.get("__typename") not in KNOWN_CONTENT or (
            content.get("__typename") == "SlideMessageXMAContent"
            and (content.get("xma") or {}).get("__typename") not in KNOWN_XMA
        ):
            unhandled_nodes.append(n)

    w("")
    w("SHAPES")
    for label, counter in (("content_type", ct), ("content.__typename", tn), ("content.xma.__typename", xt)):
        if counter:
            w(f"  {label}")
            for k, v in counter.most_common():
                mark = "" if k in KNOWN_CONTENT | KNOWN_XMA or label == "content_type" else "   <- NEW"
                w(f"    {str(k):<34} {v:>4}{mark}")
    w("  rendered as")
    for k, v in kinds.most_common():
        w(f"    {k:<34} {v:>4}")

    feats = Counter()
    for m in (normalise(n) for n in nodes):
        for flag in ("reply", "reactions", "mentions", "is_forwarded", "is_pinned", "is_ai_generated"):
            if m[flag]:
                feats[flag] += 1
        if m["edits"]:
            feats["edited"] += 1
    w("")
    w("FEATURES PRESENT")
    for k, v in feats.most_common() or [("none", 0)]:
        w(f"  {k:<34} {v:>4}")

    w("")
    w("UNHANDLED")
    if unhandled_nodes:
        for n in unhandled_nodes[:10]:
            c = n.get("content") or {}
            w(f"  {n.get('message_id')}  content_type={n.get('content_type')}"
              f"  __typename={c.get('__typename')}  xma={(c.get('xma') or {}).get('__typename')}")
        if len(unhandled_nodes) > 10:
            w(f"  ... and {len(unhandled_nodes) - 10} more")
    else:
        w("  every message matched a known shape")
    w("")
    w("NODE KEYS CARRIED BUT NOT RENDERED")
    w("  " + ", ".join(f"{k}×{v}" for k, v in extra_keys.most_common()) if extra_keys else w("  none"))
    return "\n".join(out)
