"""Saving responses to disk and tracking what they contain.

Every matching response is written the moment it arrives, so a crash at any point
loses nothing. Auth tokens are stripped before anything touches disk.
"""

import json
import re
import time
from urllib.parse import parse_qs

from . import config
from .state import state
from .util import walk


def parse_body(text: str):
    """IG bodies: plain JSON, 'for (;;);'-prefixed, or several JSON objects per line."""
    text = text.strip()
    if text.startswith("for (;;);"):
        text = text[len("for (;;);"):]
    try:
        return [json.loads(text)]
    except json.JSONDecodeError:
        pass
    chunks = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            chunks.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return chunks or None


def clean_request(post_data: str | None):
    """Decode the request form and drop the auth fields. -> (form, friendly_name)"""
    if not post_data:
        return {}, None
    try:
        form = {k: v[0] for k, v in parse_qs(post_data).items()}
    except Exception:
        return {"raw": "<unparseable>"}, None
    for key in config.SECRET_FIELDS:
        form.pop(key, None)
    friendly = form.get("fb_api_req_friendly_name")
    if "variables" in form:
        try:
            form["variables"] = json.loads(form["variables"])
        except json.JSONDecodeError:
            pass
    return form, friendly


def note_thread(chunks) -> int:
    """Track live progress from any slide_messages connection in the body.

    Returns how many messages this response added that had not been seen before,
    which is what tells the scroll loop whether it is still making progress.
    """
    added = 0
    for obj in walk(chunks or []):
        if not isinstance(obj, dict):
            continue
        conn = obj.get("slide_messages")
        if not isinstance(conn, dict) or not isinstance(conn.get("edges"), list):
            continue
        state["thread_pages"] += 1
        for edge in conn["edges"]:
            node = (edge or {}).get("node") or {}
            mid = node.get("message_id") or node.get("id")
            if not mid or mid in state["message_ids"]:
                continue
            state["message_ids"].add(mid)
            added += 1
            state["thread_fbid"] = node.get("thread_fbid") or state["thread_fbid"]
            ts = node.get("timestamp_ms")
            if str(ts).isdigit():
                ts = int(ts)
                state["oldest_ms"] = min(ts, state["oldest_ms"] or ts)
                state["newest_ms"] = max(ts, state["newest_ms"] or ts)
        page_info = conn.get("page_info") or {}
        # Edges come back newest-first, so the "next" page is the older one and
        # end_cursor is where to continue from.
        if page_info.get("end_cursor"):
            state["next_cursor"] = page_info["end_cursor"]
        if page_info.get("has_next_page") is False:
            state["exhausted"] = True
    return added


def next_seq() -> int:
    """Continue numbering after an earlier run instead of overwriting it."""
    seqs = [int(m.group(1))
            for path in config.OUT.glob("*.json")
            if (m := re.match(r"(\d{5})_", path.name))]
    return max(seqs, default=0)


async def on_response(resp):
    """Save one network response, if we are armed and it is one we care about."""
    if not state["armed"]:
        return
    if not any(pattern in resp.url for pattern in config.URL_PATTERNS):
        return
    try:
        body = await resp.text()
    except Exception:
        return  # redirects, or bodies already gone

    form, friendly = clean_request(resp.request.post_data)
    state["count"] += 1
    state["last_capture"] = time.time()
    chunks = parse_body(body)
    record = {
        "seq": state["count"],
        "captured_at": time.time(),
        "url": resp.url.split("?")[0],
        "status": resp.status,
        "friendly_name": friendly,
        "doc_id": form.get("doc_id"),
        "request": form,
        "chunks": chunks,
        "raw": body if chunks is None else None,   # keep it so nothing is lost
    }
    name = re.sub(r"[^A-Za-z0-9_]+", "_", friendly or "unknown")[:60]
    path = config.OUT / f"{state['count']:05d}_{name}.json"
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

    pages_before = state["thread_pages"]
    added = note_thread(chunks)
    if state["thread_pages"] > pages_before and state["template"] is None:
        await remember_template(resp)
    extra = f", +{added} messages" if added else ""
    print(f"  saved {path.name} ({len(body):,} bytes{extra})")


async def remember_template(resp):
    """Keep one genuine thread request so it can be replayed with a new cursor.

    Memory only. The body holds fb_dtsg and friends, which is exactly why
    clean_request() strips them before anything is written to disk.
    """
    post_data = resp.request.post_data
    if not post_data:
        return
    try:
        headers = await resp.request.all_headers()
    except Exception:
        headers = {}
    state["template"] = {
        "url": resp.url,
        "post_data": post_data,
        "headers": {k: v for k, v in headers.items()
                    if not k.startswith(":")
                    and k.lower() not in config.FETCH_FORBIDDEN_HEADERS},
    }
    print("  (captured the thread query — API paging is available)")


def on_websocket(ws):
    """Optional: log websocket text frames alongside the HTTP responses."""
    log = config.OUT / "websocket_frames.jsonl"

    def frame(payload):
        if state["armed"] and isinstance(payload, str):
            with log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"t": time.time(), "url": ws.url, "data": payload}) + "\n")
            state["last_capture"] = time.time()

    ws.on("framereceived", frame)
