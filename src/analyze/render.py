"""Render the normalised chat into one self-contained Instagram-like HTML file."""

from __future__ import annotations

import html
import json
from collections import Counter
from datetime import datetime, timedelta

TIME_DIVIDER_GAP = timedelta(minutes=45)   # show a clock line when the chat goes quiet
GROUP_GAP = timedelta(minutes=5)           # bubbles closer than this stack together

CSS = """
:root{
  --bg:#fff; --fg:#000; --muted:#737373; --line:#dbdbdb; --panel:#fafafa;
  --them:#efefef; --me:#3797f0; --me-fg:#fff; --card:#fff; --chip:#fff;
  --shadow:0 1px 2px rgba(0,0,0,.08);
}
:root:not([data-theme=light]) { color-scheme:light dark; }
@media (prefers-color-scheme:dark){
  :root:not([data-theme=light]){
    --bg:#000; --fg:#f5f5f5; --muted:#a8a8a8; --line:#262626; --panel:#121212;
    --them:#262626; --card:#1a1a1a; --chip:#262626; --shadow:none;
  }
}
:root[data-theme=dark]{
  --bg:#000; --fg:#f5f5f5; --muted:#a8a8a8; --line:#262626; --panel:#121212;
  --them:#262626; --card:#1a1a1a; --chip:#262626; --shadow:none; color-scheme:dark;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
  font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,"Apple Color Emoji","Segoe UI Emoji",sans-serif}
a{color:inherit}

header{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line)}
.hwrap{max-width:880px;margin:0 auto;display:flex;align-items:center;gap:12px;padding:10px 16px}
.hwrap .av{width:44px;height:44px;flex:0 0 auto}
.htitle{font-weight:600;font-size:16px;line-height:1.2}
.hsub{color:var(--muted);font-size:13px}
.hspace{flex:1}
.tools{display:flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:flex-end}
.tools input[type=search]{background:var(--panel);border:1px solid var(--line);color:var(--fg);
  border-radius:999px;padding:7px 12px;font:inherit;font-size:13px;width:170px;min-width:0}
.tools button{background:var(--panel);border:1px solid var(--line);color:var(--fg);
  border-radius:999px;padding:7px 12px;font:inherit;font-size:13px;cursor:pointer}
.tools button[aria-pressed=true]{background:var(--me);border-color:var(--me);color:#fff}

main{max-width:880px;margin:0 auto;padding:12px 16px 80px}
.day{position:sticky;top:var(--sticky,64px);z-index:2;text-align:center;
  background:var(--bg);padding:8px 0;margin:16px 0 6px}
.day span{color:var(--muted);font-size:12px;font-weight:600;letter-spacing:.3px}
.clock{text-align:center;color:var(--muted);font-size:11px;margin:16px 0 8px}

.row{display:flex;align-items:flex-end;gap:8px;margin-top:2px}
.row.grouped{margin-top:1px}
.row.me{flex-direction:row-reverse}
.stack{display:flex;flex-direction:column;max-width:min(74%,520px);min-width:0}
.row.me .stack{align-items:flex-end}
.who{color:var(--muted);font-size:12px;margin:12px 0 3px 12px}
.av{width:28px;height:28px;border-radius:50%;flex:0 0 auto;object-fit:cover;background:var(--them);
  display:grid;place-items:center;font-size:11px;font-weight:600;color:var(--muted);overflow:hidden}
.av.ghost{visibility:hidden}

.bubble{background:var(--them);border-radius:20px;padding:8px 13px;overflow-wrap:anywhere;
  white-space:pre-wrap;max-width:100%}
.row.me .bubble{background:var(--me);color:var(--me-fg)}
.row.grouped.them .bubble{border-top-left-radius:6px}
.row.grouped.me  .bubble{border-top-right-radius:6px}
.row.cont.them .bubble{border-bottom-left-radius:6px}
.row.cont.me   .bubble{border-bottom-right-radius:6px}
/* must outrank ".row.me .bubble", or cards and photos you sent sit on a blue slab */
.row .bubble.plain{background:none;padding:0}

.quote{display:block;text-decoration:none;margin:10px 0 -12px;padding:8px 12px 18px;
  border-radius:18px;background:var(--panel);border:1px solid var(--line);max-width:100%}
.row.me .quote{text-align:right}
.qlabel{display:block;color:var(--muted);font-size:11px;margin-bottom:2px}
.qbody{display:block;color:var(--muted);font-size:13px;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap}
.qbody .tag{color:var(--fg);opacity:.6}

.cardlink{display:block;text-decoration:none;color:inherit}
.card{width:230px;max-width:100%;border-radius:18px;overflow:hidden;background:var(--card);
  border:1px solid var(--line);box-shadow:var(--shadow)}
.card .eyebrow{font-size:12px;color:var(--muted);padding:8px 12px 0}
.card .shot{display:block;width:100%;max-height:340px;background:var(--them);
  aspect-ratio:9/16;object-fit:cover}
.card .foot{display:flex;align-items:center;gap:8px;padding:9px 11px;font-size:13px;min-width:0}
.card .foot .av{width:22px;height:22px}
.card .foot b{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.card .cap{padding:0 12px 11px;font-size:13px;color:var(--muted);white-space:pre-wrap;
  display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden}
.card .badge{margin-left:auto;font-size:11px;color:var(--muted);flex:0 0 auto}
.card.dead{display:flex;flex-direction:column;gap:4px;padding:14px;width:auto;max-width:300px;
  border-style:dashed;background:none}
.card.dead b{font-size:13px;font-weight:600}
.card.dead span{font-size:12px;color:var(--muted)}

.media{display:block;width:100%;max-width:260px;border-radius:18px;background:var(--them);
  object-fit:cover}
.medialink{position:relative;display:block;line-height:0;text-decoration:none;max-width:260px}
.medialink .play{position:absolute;inset:0;display:grid;place-items:center;font-size:34px;
  color:#fff;text-shadow:0 2px 8px rgba(0,0,0,.7);pointer-events:none}
.medialink .once{position:absolute;left:8px;top:8px;background:rgba(0,0,0,.55);color:#fff;
  font-size:10px;letter-spacing:.4px;border-radius:999px;padding:2px 7px;pointer-events:none}
.mediagrid{display:flex;flex-wrap:wrap;gap:3px;max-width:100%}
.voice{display:flex;align-items:center;gap:10px;background:var(--them);border-radius:22px;
  padding:7px 12px 7px 10px;max-width:300px}
.row.me .voice{background:var(--me)}
.voice audio{height:34px;max-width:230px}
.voice .dur{font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}
.row.me .voice .dur{color:#e8f2fd}
.mediadead{border:1px dashed var(--line);border-radius:18px;padding:18px 20px;color:var(--muted);
  font-size:13px;line-height:1.5;text-align:center;min-width:150px}
.mediadead small{opacity:.75}
.sticker .media{background:none;border-radius:8px;max-width:160px}
.removed{border:1px dashed var(--line);border-radius:18px;padding:9px 14px;color:var(--muted);
  font-size:13px;font-style:italic}
.xtext{margin-top:6px}
.reacts{display:flex;gap:3px;margin:-11px 10px 6px;z-index:1}
.reacts span{background:var(--chip);border:1px solid var(--line);border-radius:999px;
  padding:1px 6px;font-size:12px;line-height:1.5;box-shadow:var(--shadow)}
.flags{font-size:11px;color:var(--muted);margin:3px 10px 0}

.sys{text-align:center;margin:10px 0}
.sys span{color:var(--muted);font-size:12px;background:var(--panel);border-radius:999px;padding:3px 12px}
.hidden{display:none!important}
.hit .bubble,.hit .card{outline:2px solid var(--me);outline-offset:2px}
mark{background:rgba(55,151,240,.35);color:inherit;border-radius:3px}
.empty{text-align:center;color:var(--muted);padding:40px 0}
@media (max-width:560px){
  .stack{max-width:84%}
  .tools input[type=search]{width:120px}
}
"""

JS = """
// The header and the year/month nav wrap differently at different widths, so the
// day divider's sticky offset is measured rather than guessed.
function setOffsets() {
  const header = document.querySelector('header');
  const nav = document.querySelector('.navwrap');
  const top = header ? header.offsetHeight : 0;
  document.documentElement.style.setProperty('--hdr', top + 'px');
  document.documentElement.style.setProperty('--sticky', (top + (nav ? nav.offsetHeight : 0)) + 'px');
}
setOffsets();
addEventListener('resize', setOffsets);

const main = document.querySelector('main');
const q = document.getElementById('q');
const sysBtn = document.getElementById('sysBtn');
const themeBtn = document.getElementById('themeBtn');

sysBtn.addEventListener('click', () => {
  const on = sysBtn.getAttribute('aria-pressed') !== 'true';
  sysBtn.setAttribute('aria-pressed', on);
  document.body.classList.toggle('nosys', !on);
});

themeBtn.addEventListener('click', () => {
  const now = document.documentElement.getAttribute('data-theme');
  const next = now === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  themeBtn.textContent = next === 'dark' ? 'Light' : 'Dark';
});

document.addEventListener('click', ev => {
  const a = ev.target.closest('a.quote');
  if (!a || !a.getAttribute('href')) return;
  // A link into another year's file is a real navigation; leave it alone.
  if (!a.getAttribute('href').startsWith('#')) return;
  // IDs are IG message ids like "m-mid.$cAAA..." - '.' and '$' make them invalid
  // CSS selectors, so never querySelector them.
  const t = document.getElementById(a.getAttribute('href').slice(1));
  if (!t) return;
  ev.preventDefault();
  t.scrollIntoView({block: 'center', behavior: 'smooth'});
  t.classList.add('hit');
  setTimeout(() => t.classList.remove('hit'), 1600);
});

let timer;
q.addEventListener('input', () => {
  clearTimeout(timer);
  timer = setTimeout(() => {
    const term = q.value.trim().toLowerCase();
    document.querySelectorAll('.row, .sys').forEach(el => {
      el.classList.toggle('hidden', !!term && !el.textContent.toLowerCase().includes(term));
    });
    document.querySelectorAll('.day, .clock').forEach(el => el.classList.toggle('hidden', !!term));
  }, 120);
});

function flash(el) {
  el.scrollIntoView({block: 'center'});
  el.classList.add('hit');
  setTimeout(() => el.classList.remove('hit'), 1600);
}

// Arriving from another year's file: land on the quoted message, not the bottom.
const deep = location.hash && document.getElementById(location.hash.slice(1));
if (deep) flash(deep); else window.scrollTo(0, document.body.scrollHeight);
"""


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


YEAR_THRESHOLD = 3_000       # above this, "auto" splits the archive by year
MONTH_THRESHOLD = 20_000     # above this, by month - a year can be 80k messages

NAV_CSS = """
.navwrap{position:sticky;top:var(--hdr,64px);z-index:3;background:var(--bg);
  border-bottom:1px solid var(--line)}
nav.years{padding:8px 16px 0;display:flex;gap:6px;flex-wrap:wrap;justify-content:center}
nav.months{padding:6px 16px 8px}
nav.years a{text-decoration:none;color:var(--muted);font-size:13px;border:1px solid var(--line);
  border-radius:999px;padding:3px 11px}
nav.months a{font-size:12px;padding:2px 9px}
nav.years a.on{background:var(--me);border-color:var(--me);color:#fff}
.index{max-width:680px;margin:0 auto;padding:24px 16px 60px}
.yearblock{border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin-bottom:10px}
.yearhead{display:flex;align-items:baseline;gap:12px;margin-bottom:10px}
.yearhead b{font-size:19px}
.yearhead .n{margin-left:auto;color:var(--muted);font-size:13px;font-variant-numeric:tabular-nums}
.monthrow{display:flex;flex-wrap:wrap;gap:6px}
.monthrow a{display:flex;align-items:baseline;gap:6px;text-decoration:none;color:inherit;
  border:1px solid var(--line);border-radius:999px;padding:4px 11px;font-size:13px}
.monthrow a:hover{background:var(--panel)}
.monthrow em{font-style:normal;color:var(--muted);font-size:12px;font-variant-numeric:tabular-nums}
.index > a{display:flex;align-items:baseline;gap:12px;text-decoration:none;color:inherit;
  border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin-bottom:8px}
.index > a:hover{background:var(--panel)}
.index > a b{font-size:18px;min-width:3.5em}
.index > a span{color:var(--muted);font-size:13px}
.index .n{margin-left:auto;font-variant-numeric:tabular-nums}
"""


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
