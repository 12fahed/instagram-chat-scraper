"""Structural report over captured pages: what shapes are in there, and what
this parser does not yet understand.

The point is to make a full capture run self-checking — run `report` after it
and anything the renderer would silently drop shows up under UNHANDLED.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from .parse import normalise, parse_content

KNOWN_CONTENT = {"SlideMessageText", "SlideMessageAdminText", "SlideMessageXMAContent"}
KNOWN_XMA = {"SlideMessagePortraitXMA", "SlideMessageStandardXMA", "SlideMessagePlaceholderXMA"}

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
    out.update(n.get("cursor") for n in page.nodes if isinstance(n, dict))
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
    for p in pages:
        rng = p.ts_range
        pi = p.page_info or {}
        rows.append((p.source, len(p.nodes), rng, pi))
    for source, count, rng, pi in rows:
        span = f"{_when(rng[0])}  ->  {_when(rng[1])}" if rng else "no timestamps"
        w(f"  {source:<28} {count:>4} messages   {span}")
        if pi:
            w(f"  {'':<28}      prev={pi.get('has_previous_page')} next={pi.get('has_next_page')}"
              f"  start={str(pi.get('start_cursor'))[:14]}… end={str(pi.get('end_cursor'))[:14]}…")

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
    # request asked for must be one the previous page handed out.
    ranged = sorted([p for p in pages if p.ts_range], key=lambda p: -p.ts_range[1])
    w("")
    w("CONTINUITY  (newest page first)")
    if not ranged:
        w("  nothing to check")
    for i, page in enumerate(ranged):
        lo, hi = page.ts_range
        w(f"  {page.source:<28} {_when(lo)}  ..  {_when(hi)}")
        if i + 1 < len(ranged):
            nxt_hi = ranged[i + 1].ts_range[1]
            delta = timedelta(milliseconds=lo - nxt_hi)
            w(f"  {'':<28}      {_fmt_delta(delta)} to the next page down")

    chained = [p for p in pages if p.request_cursor]
    w("")
    if not chained:
        w("  cursor chain: not checkable (captures hold responses only, no request variables)")
    else:
        handed_out = {c for p in pages for c in _cursors(p)}
        orphans = [p for p in chained if p.request_cursor not in handed_out]
        if orphans:
            for p in orphans:
                w(f"  cursor chain: {p.source} asked for a cursor no captured page handed out"
                  f" -> a scroll step is missing before it")
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
