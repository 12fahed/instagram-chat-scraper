"""Decide how many pages the archive becomes, and build the index.

One file is fine for a short thread. A long one has to be broken up: a year of a
busy conversation can be tens of thousands of messages, which no browser enjoys
opening or searching. Replies that quote a message in another bucket are
rewritten to point at that file, so the links keep working across the split.
"""

from __future__ import annotations

from datetime import datetime

from .assets import CSS, NAV_CSS
from .render import _avatar, _esc, display_name, render

YEAR_THRESHOLD = 3_000       # above this, "auto" splits the archive by year
MONTH_THRESHOLD = 20_000     # above this, by month - a year can be 80k messages



def _bucket_key(msg: dict, unit: str) -> str:
    dt = datetime.fromtimestamp((msg["ts"] or 0) / 1000)
    return dt.strftime("%Y-%m") if unit == "month" else dt.strftime("%Y")


def _file(key: str) -> str:
    return f"chat-{key}.html"


def _label(key: str) -> str:
    return datetime.strptime(key, "%Y-%m").strftime("%b") if "-" in key else key


def _nav(keys: list[str], current: str, unit: str) -> str:
    """Years always; the current year's months underneath when split by month."""
    years = sorted({k[:4] for k in keys})
    current_year = current[:4]
    links = ['<a href="chat.html">All</a>']
    for year in years:
        # Jumping to a year means its earliest bucket when months are separate files.
        target = _file(year if unit == "year"
                       else min(k for k in keys if k.startswith(year)))
        on = ' class="on"' if year == current_year else ""
        links.append(f'<a href="{_esc(target)}"{on}>{_esc(year)}</a>')
    rows = [f'<nav class="years">{"".join(links)}</nav>']
    if unit == "month":
        chips = []
        for key in sorted(k for k in keys if k.startswith(current_year)):
            on = ' class="on"' if key == current else ""
            chips.append(f'<a href="{_esc(_file(key))}"{on}>{_esc(_label(key))}</a>')
        rows.append(f'<nav class="years months">{"".join(chips)}</nav>')
    return f'<div class="navwrap">{"".join(rows)}</div>'


def _index(chat: dict, me: str | None, title: str, buckets: dict, unit: str) -> str:
    people = chat["people"]
    others = sorted((p for pid, p in people.items() if pid != me),
                    key=lambda p: -p.get("messages", 0))
    head = others[0] if others else next(iter(people.values()), {})
    total = sum(len(v) for v in buckets.values())

    rows = []
    if unit == "month":
        by_year: dict[str, list[str]] = {}
        for key in sorted(buckets):
            by_year.setdefault(key[:4], []).append(key)
        for year in sorted(by_year, reverse=True):
            months = by_year[year]
            count = sum(len(buckets[k]) for k in months)
            chips = "".join(
                f'<a href="{_esc(_file(k))}">{_esc(_label(k))}'
                f'<em>{len(buckets[k]):,}</em></a>' for k in months
            )
            rows.append(f'<div class="yearblock"><div class="yearhead"><b>{_esc(year)}</b>'
                        f'<span class="n">{count:,} messages</span></div>'
                        f'<div class="monthrow">{chips}</div></div>')
    else:
        for key in sorted(buckets, reverse=True):
            msgs = buckets[key]
            first = datetime.fromtimestamp(msgs[0]["ts"] / 1000).strftime("%d %b")
            last = datetime.fromtimestamp(msgs[-1]["ts"] / 1000).strftime("%d %b")
            rows.append(f'<a href="{_esc(_file(key))}"><b>{_esc(key)}</b>'
                        f'<span>{_esc(first)} – {_esc(last)}</span>'
                        f'<span class="n">{len(msgs):,} messages</span></a>')

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>{CSS}{NAV_CSS}</style>
</head>
<body>
<header><div class="hwrap">
  {_avatar(head, "av")}
  <div>
    <div class="htitle">{_esc(display_name(head, title))}</div>
    <div class="hsub">{_esc(head.get("username") or "")} · {total:,} messages</div>
  </div>
</div></header>
<div class="index">{"".join(rows)}</div>
</body></html>"""


def render_all(chat: dict, me: str | None, title: str, split: str = "auto") -> dict[str, str]:
    """-> {filename: html}. One file, or one per year/month plus an index.

    Splitting keeps each page small enough to open and search. A reply quoting a
    message in another bucket is rewritten to point at that file's anchor, so the
    links keep working across the split.
    """
    msgs = chat["messages"]
    if split == "auto":
        unit = ("month" if len(msgs) > MONTH_THRESHOLD
                else "year" if len(msgs) > YEAR_THRESHOLD else "none")
    else:
        unit = split
    if unit == "none" or not msgs:
        return {"chat.html": render(chat, me, title)}

    buckets: dict[str, list] = {}
    for m in msgs:
        buckets.setdefault(_bucket_key(m, unit), []).append(m)
    keys = sorted(buckets)
    locate = {m["id"]: _file(k) for k in keys for m in buckets[k]}

    out = {"chat.html": _index(chat, me, title, buckets, unit)}
    for key in keys:
        name = _file(key)
        heading = (datetime.strptime(key, "%Y-%m").strftime("%B %Y")
                   if unit == "month" else key)
        page = render(chat, me, f"{title} — {heading}", msgs=buckets[key],
                      locate=locate, current=name, nav=_nav(keys, key, unit))
        page = page.replace("<style>" + CSS + "</style>",
                            "<style>" + CSS + NAV_CSS + "</style>")
        out[name] = page
    return out
