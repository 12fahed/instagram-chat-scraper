"""Build one self-contained HTML page from a normalised chat."""

from __future__ import annotations

import html
from collections import Counter
from datetime import datetime, timedelta

from .assets import CSS, JS

TIME_DIVIDER_GAP = timedelta(minutes=45)   # show a clock line when the chat goes quiet
GROUP_GAP = timedelta(minutes=5)           # bubbles closer than this stack together


GROUP_GAP = timedelta(minutes=5)           # bubbles closer than this stack together




def _esc(s) -> str:
    return html.escape(str(s), quote=True)


def display_name(person: dict, fallback: str | None = None) -> str:
    """Deleted accounts come back with a blank name and no user_dict, so fall
    through username -> igid -> sender id rather than rendering an empty label."""
    return (
        person.get("name")
        or person.get("username")
        or person.get("igid")
        or person.get("id")
        or fallback
        or "Unknown"
    )


def _initials(person: dict) -> str:
    name = display_name(person)
    return "".join(w[0] for w in name.split()[:2]).upper()[:2] or "?"


def _avatar(person: dict, cls: str = "av") -> str:
    url = person.get("avatar")
    alt = _esc(display_name(person))
    if url:
        return (f'<img class="{cls}" src="{_esc(url)}" alt="{alt}" loading="lazy" '
                f'onerror="this.replaceWith(Object.assign(document.createElement(\'div\'),'
                f'{{className:\'{cls}\',textContent:\'{_esc(_initials(person))}\'}}))">')
    return f'<div class="{cls}">{_esc(_initials(person))}</div>'


MEDIA_LABELS = {"image": "Photo", "video": "Video", "audio": "Voice message",
                "animation": "GIF"}


def _kind_label(entry: dict) -> str:
    if entry.get("kind") == "removed":
        return "Message removed"
    media = entry.get("media") or []
    if media:
        label = MEDIA_LABELS.get(media[0].get("kind"), "Attachment")
        if media[0].get("is_sticker"):
            label = "Sticker"
        return f"{label} ×{len(media)}" if len(media) > 1 else label
    card = entry.get("card") or {}
    deco = ((card.get("image") or {}).get("decoration") or "").upper()
    if entry.get("kind") == "story_share":
        return "Story"
    if entry.get("kind") == "unavailable":
        return card.get("title") or "Message unavailable"
    if entry.get("kind") == "share":
        return {"REEL": "Reel", "COLLAGE": "Post"}.get(deco, "Post")
    return ""


def _card_html(card: dict, kind: str) -> str:
    title = card.get("title")
    if kind == "unavailable" or (not card.get("image") and not card.get("url")):
        note = card.get("caption") or card.get("subtitle") or ""
        return (f'<div class="card dead"><b>{_esc(title or "Message unavailable")}</b>'
                + (f"<span>{_esc(note)}</span>" if note else "")
                + "</div>")

    parts = ['<div class="card">']
    if card.get("eyebrow"):
        parts.append(f'<div class="eyebrow">{_esc(card["eyebrow"])}</div>')
    img = card.get("image") or {}
    if img.get("url"):
        w, h = img.get("width") or 0, img.get("height") or 0
        ratio = f' style="aspect-ratio:{w}/{h}"' if w and h else ""
        parts.append(
            f'<img class="shot" src="{_esc(img["url"])}"{ratio} loading="lazy" alt="shared media"'
            f' onerror="this.classList.add(\'hidden\')">'
        )
    author = card.get("author")
    badge = _kind_label({"kind": kind, "card": card})
    caption = card.get("caption") or card.get("subtitle")
    if author:
        who = {"username": author, "name": author, "avatar": card.get("author_avatar")}
        parts.append(
            f'<div class="foot">{_avatar(who)}<b>{_esc(author)}</b>'
            f'{" &#10003;" if card.get("verified") else ""}'
            f'<span class="badge">{_esc(badge)}</span></div>'
        )
    elif title:
        # No header author: IG puts the shared post's own caption in title_text.
        caption = caption or title
        parts.append(f'<div class="foot"><b>instagram.com</b><span class="badge">{_esc(badge)}</span></div>')
    if caption:
        parts.append(f'<div class="cap">{_esc(caption)}</div>')
    parts.append("</div>")
    body = "".join(parts)
    if card.get("url"):
        return (f'<a class="cardlink" href="{_esc(card["url"])}"'
                f' target="_blank" rel="noreferrer noopener">{body}</a>')
    return body


def _media_html(media: list[dict]) -> str:
    tiles = []
    for item in media:
        w, h = item.get("width") or 0, item.get("height") or 0
        ratio = f' style="aspect-ratio:{w}/{h}"' if w and h else ' style="aspect-ratio:4/5"'
        badges = ""
        if item.get("kind") == "video":
            badges += '<span class="play">&#9654;</span>'
        if item.get("ephemeral"):
            badges += '<span class="once">VIEW ONCE</span>'
        label = _kind_label({"media": [item]})
        if item.get("kind") == "audio":
            ms = item.get("duration_ms") or 0
            spoken = f'<span class="dur">{int(ms // 60000)}:{int(ms // 1000) % 60:02d}</span>' if ms else ""
            tiles.append(
                f'<div class="voice"><audio controls preload="none" '
                f'src="{_esc(item["full"])}"></audio>{spoken}</div>'
            )
            continue
        if item.get("placeholder"):
            # The original exists but IG gave us no usable poster frame. Fold the
            # badges into the text - overlaying them makes the tile unreadable.
            icon = "&#9654; " if item.get("kind") == "video" else ""
            note = "view once · open original" if item.get("ephemeral") else "open original"
            tiles.append(
                f'<a class="medialink" href="{_esc(item["full"])}" target="_blank"'
                f' rel="noreferrer noopener"><div class="mediadead">{icon}{_esc(label)}'
                f'<br><small>{_esc(note)}</small></div></a>'
            )
            continue
        # If the CDN url has expired, leave a visible placeholder. Hiding it would
        # silently drop a message from the archive.
        fallback = (f"this.replaceWith(Object.assign(document.createElement('div'),"
                    f"{{className:'mediadead',textContent:'{label} unavailable'}}))")
        img = (f'<img class="media" src="{_esc(item["preview"])}"{ratio} loading="lazy"'
               f' alt="{_esc(label)}" onerror="{_esc(fallback)}">')
        cls = "medialink sticker" if item.get("is_sticker") else "medialink"
        tiles.append(
            f'<a class="{cls}" href="{_esc(item["full"])}" target="_blank"'
            f' rel="noreferrer noopener">{img}{badges}</a>'
        )
    wrap = "mediagrid" if len(tiles) > 1 else ""
    return f'<div class="{wrap}">{"".join(tiles)}</div>' if wrap else tiles[0]


def _quote_html(reply: dict, people: dict, me: str | None, known: set,
                locate: dict | None = None, current: str | None = None) -> str:
    who = people.get(reply.get("sender_id") or "", {})
    name = display_name(who, reply.get("sender_name")) if who or reply.get("sender_name") else "a message"
    label = "You replied to yourself" if reply.get("sender_id") == me else f"Replied to {name}"
    if reply.get("text"):
        body = _esc(reply["text"])
    else:
        tag = _kind_label(reply) or "Attachment"
        body = f'<span class="tag">{_esc(tag)}</span>'
    # Only link when the quoted message was actually captured; older replies point
    # at messages further up the thread than we scrolled. When the archive is split
    # by year the target may live in a different file, so address it by file+anchor.
    rid = reply.get("id")
    href = ""
    if rid in known:
        where = (locate or {}).get(rid)
        anchor = f"#m-{_esc(rid)}"
        href = f' href="{anchor}"' if not where or where == current else f' href="{_esc(where)}{anchor}"'

    return (f'<a class="quote"{href}><span class="qlabel">{_esc(label)}</span>'
            f'<span class="qbody">{body}</span></a>')


def render(chat: dict, me: str | None, title: str, msgs: list | None = None,
           locate: dict | None = None, current: str | None = None, nav: str = "") -> str:
    people = chat["people"]
    msgs = chat["messages"] if msgs is None else msgs
    known_ids = {m["id"] for m in chat["messages"]}
    # Deleted / departed accounts arrive unhydrated; they should not turn a 1:1
    # conversation into a group and put a name label over every incoming bubble.
    is_group = sum(1 for p in people.values() if p.get("hydrated")) > 2
    rows: list[str] = []
    prev_dt = prev_sender = None

    for m in msgs:
        dt = datetime.fromtimestamp((m["ts"] or 0) / 1000)

        if prev_dt is None or dt.date() != prev_dt.date():
            rows.append(f'<div class="day"><span>{_esc(dt.strftime("%A, %d %B %Y"))}</span></div>')
            prev_sender = None
        elif dt - prev_dt > TIME_DIVIDER_GAP:
            rows.append(f'<div class="clock">{_esc(dt.strftime("%H:%M"))}</div>')
            prev_sender = None

        if m["kind"] == "admin":
            rows.append(f'<div class="sys" data-log="{"1" if m["is_reaction_log"] else "0"}">'
                        f'<span>{_esc(m["text"] or "")}</span></div>')
            prev_dt, prev_sender = dt, None
            continue

        mine = me is not None and m["sender_id"] == me
        grouped = (m["sender_id"] == prev_sender) and (dt - prev_dt <= GROUP_GAP if prev_dt else False)
        side = "me" if mine else "them"
        person = people.get(m["sender_id"] or "", {})

        inner: list[str] = []
        if not mine and not grouped and is_group:
            inner.append(f'<div class="who">{_esc(display_name(person, m["sender_id"]))}</div>')
        if m["reply"]:
            inner.append(_quote_html(m["reply"], people, me, known_ids, locate, current))

        if m["kind"] == "removed":
            inner.append('<div class="removed">Message removed</div>')
        elif m.get("media"):
            inner.append(f'<div class="bubble plain">{_media_html(m["media"])}</div>')
            if m["text"]:
                inner.append(f'<div class="bubble xtext">{_esc(m["text"])}</div>')
        elif m["card"]:
            inner.append(f'<div class="bubble plain">{_card_html(m["card"], m["kind"])}</div>')
            if m["text"]:
                inner.append(f'<div class="bubble xtext">{_esc(m["text"])}</div>')
        elif m["text"]:
            inner.append(f'<div class="bubble">{_esc(m["text"])}</div>')
        else:
            inner.append('<div class="card dead"><b>Unsupported message</b>'
                         f'<span>{_esc(m["content_type"] or m["typename"] or "unknown")}</span></div>')

        if m["reactions"]:
            counts = Counter(r["emoji"] for r in m["reactions"] if r.get("emoji"))
            chips = "".join(
                f'<span title="{_esc(_reactors(m, people))}">{_esc(e)}{"" if n == 1 else f" {n}"}</span>'
                for e, n in counts.items()
            )
            inner.append(f'<div class="reacts">{chips}</div>')

        flags = []
        if m["is_forwarded"]:
            flags.append("Forwarded")
        if m["is_pinned"]:
            flags.append("Pinned")
        if m["edits"]:
            flags.append(f"Edited ×{m['edits']}")
        if flags:
            inner.append(f'<div class="flags">{_esc(" · ".join(flags))}</div>')

        avatar = "" if mine else _avatar(person)
        rows.append(
            f'<div class="row {side}{" grouped" if grouped else ""}" id="m-{_esc(m["id"])}"'
            f' title="{_esc(dt.strftime("%d %b %Y, %H:%M:%S"))}">'
            f'{avatar}<div class="stack">{"".join(inner)}</div></div>'
        )
        prev_dt, prev_sender = dt, m["sender_id"]

    others = [p for pid, p in people.items() if pid != me]
    # Pick by who actually talks, not by who was seen first - otherwise a ghost
    # with 43 messages can end up naming the whole archive.
    others.sort(key=lambda p: -p.get("messages", 0))
    head_person = others[0] if others else next(iter(people.values()), {})
    subtitle_bits = [f"{len(msgs):,} messages"]
    if msgs:
        subtitle_bits.append(
            datetime.fromtimestamp(msgs[0]["ts"] / 1000).strftime("%d %b %Y")
            + " – "
            + datetime.fromtimestamp(msgs[-1]["ts"] / 1000).strftime("%d %b %Y")
        )
    body = "".join(rows) or '<div class="empty">No messages parsed.</div>'

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>{CSS}</style>
</head>
<body>
<header><div class="hwrap">
  {_avatar(head_person, "av")}
  <div>
    <div class="htitle">{_esc(display_name(head_person, title))}</div>
    <div class="hsub">{_esc(" · ".join(filter(None, [head_person.get("username"), *subtitle_bits])))}</div>
  </div>
  <div class="hspace"></div>
  <div class="tools">
    <input id="q" type="search" placeholder="Search messages" autocomplete="off">
    <button id="sysBtn" aria-pressed="true" type="button">System</button>
    <button id="themeBtn" type="button">Dark</button>
  </div>
</div></header>
{nav}
<main>{body}</main>
<style>body.nosys .sys{{display:none}}</style>
<script>{JS}</script>
</body></html>"""


def _reactors(msg: dict, people: dict) -> str:
    names = []
    for r in msg["reactions"]:
        who = people.get(r.get("sender_id") or "", {})
        names.append(f"{display_name(who, r.get('sender_id'))} {r.get('emoji')}")
    return ", ".join(names)
