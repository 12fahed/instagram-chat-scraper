"""
Turn ./captures/*.json into chat.json and chat.html.

    python build_html.py

Adjust CONFIG after running inspect_captures.py --find "<a reply you remember>".
"""

import html
import json
from datetime import datetime
from pathlib import Path

from src.inspect_captures import expand_strings, load, walk

CONFIG = {
    # Only read responses with these friendly names (empty = all). Fill in from the summary.
    "only_queries": [],
    # Candidate keys, first match wins. Edit to match what --find showed you.
    "id": ["message_id", "item_id", "mid", "id"],
    "timestamp": ["timestamp_ms", "timestamp_precise", "timestamp", "created_at"],
    "sender": ["sender_fbid", "sender_id", "user_id", "author_id"],
    "sender_name": ["sender_name", "username", "full_name"],
    "text": ["text", "message", "content", "body"],
    "reply": ["replied_to_message", "replied_to_item", "reply_to_message", "replied_to"],
    "reactions": ["reactions", "emoji_reactions"],
    # Your own user id, so your messages render on the right.
    "me": None,
    # Optional id -> display name overrides.
    "names": {},
    "title": "Chat",
}


def first(d, keys):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, "", []):
            return d[k]
    return None


def to_ms(ts):
    try:
        ts = float(ts)
    except (TypeError, ValueError):
        return None
    if ts > 1e17: return ts / 1e6   # nanoseconds
    if ts > 1e14: return ts / 1e3   # microseconds
    if ts > 1e11: return ts         # milliseconds
    return ts * 1000                # seconds


def media_urls(d):
    urls = []
    for _, v in walk(d):
        if isinstance(v, str) and v.startswith("https://") and ("cdninstagram" in v or "fbcdn" in v):
            if v not in urls:
                urls.append(v)
    return urls[:1]  # one preview per message; IG lists many sizes of the same image


def looks_like_message(d):
    return (
        isinstance(d, dict)
        and first(d, CONFIG["id"]) is not None
        and to_ms(first(d, CONFIG["timestamp"])) is not None
        and first(d, CONFIG["sender"]) is not None
    )


def normalise(d):
    reply = first(d, CONFIG["reply"])
    reply_info = None
    if isinstance(reply, dict):
        reply_info = {
            "id": first(reply, CONFIG["id"]),
            "text": first(reply, CONFIG["text"]),
            "sender": first(reply, CONFIG["sender"]),
        }
    elif reply:
        reply_info = {"id": str(reply), "text": None, "sender": None}
    reactions = first(d, CONFIG["reactions"]) or []
    if isinstance(reactions, dict):
        reactions = reactions.get("emojis") or reactions.get("likes") or list(reactions.values())
    emojis = []
    for r in reactions if isinstance(reactions, list) else []:
        e = r.get("emoji") or r.get("reaction") if isinstance(r, dict) else r
        if isinstance(e, str):
            emojis.append(e)
    text = first(d, CONFIG["text"])
    return {
        "id": str(first(d, CONFIG["id"])),
        "ts": to_ms(first(d, CONFIG["timestamp"])),
        "sender": str(first(d, CONFIG["sender"])),
        "sender_name": first(d, CONFIG["sender_name"]),
        "text": text if isinstance(text, str) else None,
        "reply": reply_info,
        "reactions": emojis,
        "media": media_urls({k: v for k, v in d.items() if k not in CONFIG["reply"]}),
    }


def extract():
    msgs = {}
    for _, rec in load():
        if CONFIG["only_queries"] and rec.get("friendly_name") not in CONFIG["only_queries"]:
            continue
        data = expand_strings(rec.get("chunks") or [])
        for _, v in walk(data):
            if looks_like_message(v):
                m = normalise(v)
                old = msgs.get(m["id"])
                # Later captures win, but don't lose fields an earlier one had.
                msgs[m["id"]] = {**old, **{k: x for k, x in m.items() if x}} if old else m
    out = sorted(msgs.values(), key=lambda m: m["ts"])
    by_id = {m["id"]: m for m in out}
    for m in out:  # fill reply snippets that only came as an id
        r = m["reply"]
        if r and r["id"] in by_id:
            r["text"] = r["text"] or by_id[r["id"]]["text"]
            r["sender"] = r["sender"] or by_id[r["id"]]["sender"]
    return out


def name_of(sender, msgs):
    if sender in CONFIG["names"]:
        return CONFIG["names"][sender]
    if sender == str(CONFIG["me"]):
        return "You"
    for m in msgs:
        if m["sender"] == sender and m["sender_name"]:
            return m["sender_name"]
    return sender


def render(msgs):
    e = html.escape
    rows, last_day, last_sender = [], None, None
    for m in msgs:
        dt = datetime.fromtimestamp(m["ts"] / 1000)
        day = dt.strftime("%A, %d %B %Y")
        if day != last_day:
            rows.append(f'<div class="day">{e(day)}</div>')
            last_day, last_sender = day, None
        mine = CONFIG["me"] is not None and m["sender"] == str(CONFIG["me"])
        side = "me" if mine else "them"
        parts = []
        if m["sender"] != last_sender and not mine:
            parts.append(f'<div class="who">{e(name_of(m["sender"], msgs))}</div>')
        if m["reply"]:
            r = m["reply"]
            who = name_of(r["sender"], msgs) if r["sender"] else "a message"
            snippet = e((r["text"] or "Attachment")[:140])
            target = f' href="#m{e(r["id"])}"' if r["id"] else ""
            parts.append(
                f'<a class="quote"{target}><span class="qlabel">Replied to {e(who)}</span>'
                f'<span class="qtext">{snippet}</span></a>'
            )
        body = ""
        if m["text"]:
            body += f'<div class="text">{e(m["text"])}</div>'
        for u in m["media"]:
            body += f'<img src="{e(u)}" loading="lazy" alt="Attachment (link may have expired)">'
        if not body:
            body = '<div class="text muted">Unsupported message</div>'
        react = f'<div class="react">{e("".join(m["reactions"]))}</div>' if m["reactions"] else ""
        parts.append(
            f'<div class="bubble" title="{e(dt.strftime("%d %b %Y, %H:%M"))}">{body}</div>{react}'
        )
        rows.append(f'<div class="row {side}" id="m{e(m["id"])}">{"".join(parts)}</div>')
        last_sender = m["sender"]

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(CONFIG["title"])}</title>
<style>
:root {{ --bg:#fff; --fg:#000; --muted:#737373; --them:#efefef; --me:#3797f0; --line:#dbdbdb; --quote:#f5f5f5; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#000; --fg:#f5f5f5; --muted:#a8a8a8; --them:#262626; --line:#262626; --quote:#1a1a1a; color-scheme:dark; }}
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg);
  font:14px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }}
header {{ position:sticky; top:0; background:var(--bg); border-bottom:1px solid var(--line);
  padding:14px 20px; font-weight:600; font-size:16px; z-index:1; }}
header small {{ color:var(--muted); font-weight:400; margin-left:8px; }}
main {{ max-width:760px; margin:0 auto; padding:16px 16px 60px; }}
.day {{ text-align:center; color:var(--muted); font-size:12px; margin:24px 0 10px; }}
.row {{ display:flex; flex-direction:column; margin:2px 0; max-width:70%; }}
.row.them {{ align-items:flex-start; }}
.row.me {{ align-items:flex-end; margin-left:auto; }}
.who {{ color:var(--muted); font-size:12px; margin:10px 12px 2px; }}
.bubble {{ border-radius:22px; padding:8px 12px; background:var(--them); overflow-wrap:anywhere; white-space:pre-wrap; }}
.me .bubble {{ background:var(--me); color:#fff; }}
.bubble img {{ display:block; max-width:240px; border-radius:16px; margin:-4px -8px; }}
.quote {{ display:flex; flex-direction:column; text-decoration:none; color:var(--muted); margin:6px 0 -10px;
  padding:8px 12px 16px; border-radius:18px; background:var(--quote); border:1px solid var(--line);
  font-size:12px; max-width:100%; }}
.qlabel {{ font-size:11px; margin-bottom:2px; }}
.qtext {{ color:var(--fg); opacity:.75; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.react {{ font-size:13px; background:var(--them); border:2px solid var(--bg); border-radius:12px;
  padding:0 6px; margin:-6px 8px 4px; }}
.muted {{ color:var(--muted); font-style:italic; }}
.flash .bubble {{ outline:2px solid var(--me); outline-offset:2px; }}
a.quote:focus-visible {{ outline:2px solid var(--me); }}
</style></head><body>
<header>{e(CONFIG["title"])}<small>{len(msgs):,} messages</small></header>
<main>{"".join(rows)}</main>
<script>
document.addEventListener('click', ev => {{
  const a = ev.target.closest('a.quote'); if (!a || !a.hash) return;
  const t = document.querySelector(a.hash); if (!t) return;
  ev.preventDefault(); t.scrollIntoView({{block:'center'}});
  t.classList.add('flash'); setTimeout(() => t.classList.remove('flash'), 1500);
}});
window.scrollTo(0, document.body.scrollHeight);
</script></body></html>"""


if __name__ == "__main__":
    msgs = extract()
    if not msgs:
        print("No messages found. Run inspect_captures.py --find '<known text>' and update CONFIG keys.")
    else:
        Path("chat.json").write_text(json.dumps(msgs, ensure_ascii=False, indent=1), encoding="utf-8")
        Path("chat.html").write_text(render(msgs), encoding="utf-8")
        senders = sorted({m["sender"] for m in msgs})
        print(f"{len(msgs)} messages, {sum(1 for m in msgs if m['reply'])} replies -> chat.html")
        print(f"Sender ids seen: {senders}  (put yours in CONFIG['me'])")
