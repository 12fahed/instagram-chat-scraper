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

import re
from typing import Any

TOMBSTONE_TITLES = {"Message expired", "Message unavailable"}

# Photos/videos/GIFs sent straight into the chat (as opposed to shared posts).
# "Raven" is Meta's internal name for disappearing / view-once media. All four
# expose the same url fields; they differ only in dict-vs-list and, for animated
# media, in the url names.
MEDIA_CONTENT = {
    "SlideMessageImageContent": "image",
    "SlideMessageRavenImageContent": "image",
    "SlideMessageRavenVideoContent": "video",
    "SlideMessageAnimatedMediaContent": "animation",
}


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


# IG encodes the render size in the url as "_s<W>x<H>". A view-once photo that has
# already been consumed comes back as a 12x12 blur with no larger url anywhere -
# there is no image left to show, so such an attachment is dropped and the message
# falls through to the "unavailable" tombstone.
PLACEHOLDER_PX = 64


def _render_px(url: str | None) -> int | None:
    m = re.search(r"_s(\d+)x(\d+)", url or "")
    return max(int(m.group(1)), int(m.group(2))) if m else None


def _usable(url: str | None) -> str | None:
    px = _render_px(url)
    return url if url and (px is None or px > PLACEHOLDER_PX) else None


def _media_items(content: dict, typename: str) -> list[dict]:
    animated = typename == "SlideMessageAnimatedMediaContent"
    if animated:
        raw = content.get("animated_media") or []
    else:
        one = content.get("attachment")
        raw = [one] if isinstance(one, dict) else (content.get("attachments") or [])

    items = []
    for att in raw:
        if not isinstance(att, dict):
            continue
        preview = _s(att.get("preview_cdn_url"))
        if animated:
            preview = preview or _s(att.get("attachment_webp_url"))
            full = _s(att.get("attachment_mp4_url")) or _s(att.get("attachment_webp_url"))
        else:
            full = _s(att.get("attachment_cdn_url"))
        # *_cdn_fallback_url is a bare path into IG's media_fallback endpoint, not a
        # usable URL on its own, so it is deliberately ignored.
        preview, full = _usable(preview), _usable(full)
        if not preview and not full:
            continue
        items.append({
            "kind": MEDIA_CONTENT[typename],
            # No preview but a real original: show a labelled tile rather than
            # stretching a blur placeholder across the bubble.
            "preview": preview,
            "placeholder": preview is None,
            "full": full or preview,
            "width": att.get("preview_width"),
            "height": att.get("preview_height"),
            "fbid": _s(att.get("attachment_fbid")),
            "is_sticker": bool(att.get("is_sticker")),
            "ephemeral": typename.startswith("SlideMessageRaven"),
        })
    return items


def parse_content(node: dict) -> dict:
    """-> {kind, text, card} for a message node (or a replied_to_message node)."""
    content = node.get("content")
    node_text = _s(node.get("text_body"))
    if content is None:
        # content_type NOT_SET with no tombstone_reason: an empty shell where a
        # message used to be. Shown rather than dropped, so the archive stays honest.
        return {"kind": "removed", "text": None, "card": None, "media": []}
    typename = content.get("__typename")

    if typename in MEDIA_CONTENT:
        media = _media_items(content, typename)
        if not media:
            # A view-once photo that was consumed, or an attachment IG has dropped:
            # the message is real but carries attachment: null / attachments: [].
            label = {"image": "Photo", "video": "Video", "animation": "GIF"}[MEDIA_CONTENT[typename]]
            return {
                "kind": "unavailable",
                "text": None,
                "card": {"title": f"{label} unavailable",
                         "caption": "The attachment is no longer available.",
                         "variant": typename},
                "media": [],
            }
        return {
            "kind": "media",
            "text": _s(content.get("caption")) or node_text,
            "card": None,
            "media": media,
        }

    if typename == "SlideMessageAdminText":
        fragments = content.get("text_fragments") or []
        text = "".join(f.get("plaintext") or "" for f in fragments).strip()
        return {
            "kind": "admin",
            "text": text or node_text,
            "card": None,
            "media": [],
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
            return {"kind": "unavailable", "text": None, "card": card, "media": []}
        kind = "story_share" if node.get("content_type") == "MONTAGE_SHARE_XMA" else "share"
        return {"kind": kind, "text": _s(content.get("xma_text_body")) or node_text,
                "card": card, "media": []}

    text = _s(content.get("text_body")) or node_text
    return {"kind": "text" if text else "unknown", "text": text, "card": None, "media": []}


def _reply(node: dict) -> dict | None:
    src = node.get("replied_to_message")
    if not isinstance(src, dict):
        rid = _s(node.get("replied_to_message_id"))
        return (
            {"id": rid, "sender_id": None, "sender_name": None, "kind": "unknown",
             "text": None, "card": None, "media": []}
            if rid
            else None
        )
    parsed = parse_content(src)
    sender = src.get("sender") or {}
    return {
        "id": _s(src.get("message_id")) or _s(src.get("id")),
        "sender_id": _s(src.get("sender_fbid")) or _s(sender.get("id")),
        "sender_name": _s(sender.get("name")),
        "kind": parsed["kind"],
        "text": parsed["text"],
        "card": parsed["card"],
        "media": parsed.get("media") or [],
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
        # Deleted accounts and people who left come back with no user_dict and a
        # blank name. They are real senders, but they should not turn a 1:1 chat
        # into a "group" for rendering purposes.
        "hydrated": bool(ud),
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
        "media": parsed.get("media") or [],
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
    for msg in ordered:
        who = people.get(msg["sender_id"] or "")
        if who is not None:
            who["messages"] = who.get("messages", 0) + 1
    return {
        "thread_id": sorted(thread_ids)[0] if thread_ids else None,
        "people": people,
        "messages": ordered,
    }
