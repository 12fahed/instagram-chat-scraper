"""Turn raw SlideMessage nodes into a flat, render-ready message list.

Shapes observed in data/sample (two scrolls, 40 messages):

  content.__typename
    SlideMessageText        -> plain text            (content.text_body)
    SlideMessageAdminText   -> system line           (content.text_fragments[].plaintext)
    SlideMessageXMAContent  -> an attachment card, further split by content.xma.__typename:
        SlideMessagePortraitXMA      reel / post / story share, has preview_image
        SlideMessageStandardXMA      link-ish share, or the "Message expired" tombstone
        SlideMessagePlaceholderXMA   "Message unavailable" (deleted / privacy)

Replies live on node.replied_to_message as a *full nested message object* (the
thing the JSON/HTML account export throws away), so the same content parser is
reused on it to build the quoted preview.
"""

from __future__ import annotations

from typing import Any

TOMBSTONE_TITLES = {"Message expired", "Message unavailable"}


def _s(v: Any) -> str | None:
    """Non-empty string or None (IG uses "" a lot where it means absent)."""
    return v.strip() if isinstance(v, str) and v.strip() else None


def _image(d: Any) -> dict | None:
    if not isinstance(d, dict):
        return None
    url = _s(d.get("url")) or _s(d.get("fallback_url"))
    if not url:
        return None
    return {
        "url": url,
        "fallback_url": _s(d.get("fallback_url")),
        "width": d.get("width"),
        "height": d.get("height"),
        "decoration": _s(d.get("preview_image_decoration_type")),
    }


def parse_content(node: dict) -> dict:
    """-> {kind, text, card} for a message node (or a replied_to_message node)."""
    content = node.get("content") or {}
    typename = content.get("__typename")
    node_text = _s(node.get("text_body"))

    if typename == "SlideMessageAdminText":
        fragments = content.get("text_fragments") or []
        text = "".join(f.get("plaintext") or "" for f in fragments).strip()
        return {
            "kind": "admin",
            "text": text or node_text,
            "card": None,
            "is_reaction_log": bool(content.get("is_reaction_action_log")),
        }

    if typename == "SlideMessageXMAContent":
        xma = content.get("xma") or {}
        title = _s(xma.get("title_text")) or _s(xma.get("xmaTitle"))
        caption = _s(xma.get("caption_body_text"))
        subtitle = _s(xma.get("subtitle_text"))
        image = _image(xma.get("preview_image")) or _image(xma.get("xmaPreviewImage"))
        url = _s(xma.get("target_url"))
        card = {
            "variant": xma.get("__typename"),
            "title": title,
            "subtitle": subtitle,
            "caption": caption,
            "eyebrow": _s(xma.get("eyebrow_text")),
            "url": url,
            "target_id": _s(xma.get("target_id")),
            "author": _s(xma.get("header_title_text")) or _s(xma.get("xmaHeaderTitle")),
            "author_avatar": _s((xma.get("header_icon") or {}).get("url"))
            if isinstance(xma.get("header_icon"), dict)
            else None,
            "verified": xma.get("verified_type") not in (None, "NOT_VERIFIED"),
            "image": image,
        }
        # A card with no image, no link and a tombstone title is a dead message.
        if not image and not url and (title in TOMBSTONE_TITLES or not title):
            return {"kind": "unavailable", "text": None, "card": card}
        kind = "story_share" if node.get("content_type") == "MONTAGE_SHARE_XMA" else "share"
        return {"kind": kind, "text": _s(content.get("xma_text_body")) or node_text, "card": card}

    text = _s(content.get("text_body")) or node_text
    return {"kind": "text" if text else "unknown", "text": text, "card": None}


def _reply(node: dict) -> dict | None:
    src = node.get("replied_to_message")
    if not isinstance(src, dict):
        rid = _s(node.get("replied_to_message_id"))
        return {"id": rid, "sender_id": None, "sender_name": None, "kind": "unknown", "text": None, "card": None} if rid else None
    parsed = parse_content(src)
    sender = src.get("sender") or {}
    return {
        "id": _s(src.get("message_id")) or _s(src.get("id")),
        "sender_id": _s(src.get("sender_fbid")) or _s(sender.get("id")),
        "sender_name": _s(sender.get("name")),
        "kind": parsed["kind"],
        "text": parsed["text"],
        "card": parsed["card"],
    }


def participant(node: dict) -> dict | None:
    sender = node.get("sender") or {}
    sid = _s(sender.get("id")) or _s(node.get("sender_fbid"))
    if not sid:
        return None
    ud = sender.get("user_dict") or {}
    return {
        "id": sid,
        "igid": _s(sender.get("igid")) or _s(ud.get("id")),
        "name": _s(sender.get("name")) or _s(ud.get("full_name")),
        "username": _s(ud.get("username")),
        "avatar": _s(ud.get("profile_pic_url")),
    }


def normalise(node: dict) -> dict:
    parsed = parse_content(node)
    sender = node.get("sender") or {}
    ts = node.get("timestamp_ms")
    reactions = [
        {"emoji": r.get("reaction"), "sender_id": _s(r.get("sender_fbid"))}
        for r in (node.get("reactions") or [])
        if isinstance(r, dict) and r.get("reaction")
    ]
    return {
        "id": _s(node.get("message_id")) or _s(node.get("id")),
        "ts": int(ts) if str(ts).isdigit() else None,
        "sender_id": _s(node.get("sender_fbid")) or _s(sender.get("id")),
        "kind": parsed["kind"],
        "text": parsed["text"],
        "card": parsed["card"],
        "reply": _reply(node),
        "reactions": reactions,
        "is_reaction_log": parsed.get("is_reaction_log", False),
        "is_forwarded": bool(node.get("igd_is_forwarded")),
        "is_pinned": bool(node.get("is_pinned")),
        "is_ai_generated": bool(node.get("is_ai_generated")),
        "mentions": node.get("mentions") or [],
        "edits": len(node.get("slide_edit_history") or []),
        "content_type": node.get("content_type"),
        "typename": (node.get("content") or {}).get("__typename"),
    }


def build(pages: list) -> dict:
    """Dedupe across pages, sort oldest-first, return {messages, people, thread_id}."""
    messages: dict[str, dict] = {}
    people: dict[str, dict] = {}
    thread_ids: set[str] = set()

    for page in pages:
        if page.thread_id:
            thread_ids.add(page.thread_id)
        for node in page.nodes:
            msg = normalise(node)
            if not msg["id"]:
                continue
            prev = messages.get(msg["id"])
            # Later sightings win field-by-field, but never blank out what we had.
            messages[msg["id"]] = (
                {**prev, **{k: v for k, v in msg.items() if v not in (None, [], "", False)}}
                if prev
                else msg
            )
            who = participant(node)
            if who:
                people[who["id"]] = {**people.get(who["id"], {}), **{k: v for k, v in who.items() if v}}
            reply = msg["reply"]
            if reply and reply.get("sender_id") and reply.get("sender_name"):
                people.setdefault(reply["sender_id"], {"id": reply["sender_id"], "name": reply["sender_name"]})

    ordered = sorted(messages.values(), key=lambda m: (m["ts"] or 0, m["id"]))
    return {
        "thread_id": sorted(thread_ids)[0] if thread_ids else None,
        "people": people,
        "messages": ordered,
    }
