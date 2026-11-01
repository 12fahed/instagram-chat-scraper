"""The default capture mode: replay the thread's own GraphQL query, cursor by cursor.

Nothing accumulates in the DOM this way, so the length of the thread sets no
memory ceiling, and each page chains exactly off the one before it.
"""

import asyncio
import json
import random
from urllib.parse import parse_qsl, urlencode

from playwright.async_api import Error as PlaywrightError

from . import config
from .browser import page_gone
from .state import state
from .util import when


def body_with_cursor(post_data: str, cursor: str) -> str | None:
    """Swap the pagination cursor in a captured request body, change nothing else.

    The body is form-encoded with one field holding the GraphQL variables as JSON;
    every other field (doc_id, the auth tokens, the dozens of __ fields) is copied
    through byte for byte, so the replay is the request Instagram's own page makes.
    """
    pairs = parse_qsl(post_data, keep_blank_values=True)
    if not any(key == "variables" for key, _ in pairs):
        return None
    out, swapped = [], False
    for key, value in pairs:
        if key == "variables":
            try:
                variables = json.loads(value)
            except json.JSONDecodeError:
                return None
            if not isinstance(variables, dict):
                return None
            name = next((v for v in config.CURSOR_VARS if v in variables), config.CURSOR_VARS[0])
            variables[name] = cursor
            value = json.dumps(variables, separators=(",", ":"))
            swapped = True
        out.append((key, value))
    return urlencode(out) if swapped else None


# Runs inside the page, so the request carries the session exactly as Instagram's
# own code would, and Playwright's response event fires for it - which means
# on_response() saves the body with no extra work. Only pagination metadata comes
# back across the bridge; the messages themselves never pass through Python here.
FETCH_JS = r"""
async ([url, body, headers]) => {
  let res;
  try {
    res = await fetch(url, { method: 'POST', body, headers, credentials: 'include' });
  } catch (e) {
    return { ok: false, status: 0, error: String(e) };
  }
  const text = await res.text();
  const info = { ok: res.ok, status: res.status, bytes: text.length,
                 count: 0, end_cursor: null, has_next_page: null };
  if (!res.ok) { info.error = text.slice(0, 200); return info; }
  let data;
  try {
    data = JSON.parse(text.replace(/^for \(;;\);/, ''));
  } catch (e) {
    info.error = 'unparseable body: ' + text.slice(0, 120);
    return info;
  }
  const stack = [data];
  while (stack.length) {
    const node = stack.pop();
    if (!node || typeof node !== 'object') continue;
    const conn = node.slide_messages;
    if (conn && Array.isArray(conn.edges)) {
      info.count += conn.edges.length;
      if (conn.page_info) {
        if (conn.page_info.end_cursor) info.end_cursor = conn.page_info.end_cursor;
        info.has_next_page = conn.page_info.has_next_page;
      }
    }
    for (const v of Object.values(node)) stack.push(v);
  }
  return info;
}
"""


async def api_loop(page) -> dict:
    """Request page after page until something stops us. Returns why."""
    template = state["template"]
    if not template:
        return {"reason": "no_template", "detail": "never saw a thread request", "rounds": 0}

    state["mode"] = "api"
    cursor, rounds = state["next_cursor"], 0
    print("\nPaging the thread query directly (no scrolling, constant memory).")
    print(f"One request every ~{config.API_DELAY}s.\n")
    state["scrolling"] = True
    try:
        while True:
            if state["quit"]:
                return {"reason": "interrupted", "detail": None, "rounds": rounds}
            if state["pause"]:
                return {"reason": "paused", "detail": None, "rounds": rounds}
            if state["crashed"] or page.is_closed():
                return {"reason": "page_gone",
                        "detail": "the renderer crashed" if state["crashed"]
                                  else "the page was closed",
                        "rounds": rounds}
            if not cursor:
                return {"reason": "reached_top", "detail": "no cursor to follow",
                        "rounds": rounds}

            body = body_with_cursor(template["post_data"], cursor)
            if body is None:
                return {"reason": "no_template",
                        "detail": "could not place a cursor in the request body",
                        "rounds": rounds}

            rounds += 1
            try:
                info = await page.evaluate(
                    FETCH_JS, [template["url"], body, template["headers"]]
                )
            except (PlaywrightError, asyncio.TimeoutError) as exc:
                first_line = str(exc).strip().splitlines()[0][:160]
                reason = "page_gone" if page_gone(exc, page) else "api_failed"
                return {"reason": reason, "detail": first_line, "rounds": rounds}

            if not info.get("ok"):
                return {"reason": "api_rejected",
                        "detail": f"HTTP {info.get('status')} — {info.get('error', '')[:140]}",
                        "rounds": rounds}
            if info.get("error"):
                return {"reason": "api_rejected", "detail": info["error"][:160], "rounds": rounds}
            if not info.get("count"):
                return {"reason": "reached_top", "detail": "a page came back empty",
                        "rounds": rounds}

            print(f"page {rounds:>4}: +{info['count']} messages  "
                  f"total={len(state['message_ids'])}  oldest={when(state['oldest_ms'])}")

            if info.get("has_next_page") is False:
                state["exhausted"] = True
                return {"reason": "reached_top", "detail": None, "rounds": rounds}
            if not info.get("end_cursor"):
                return {"reason": "reached_top", "detail": "no further cursor",
                        "rounds": rounds}

            cursor = info["end_cursor"]
            await asyncio.sleep(random.uniform(config.API_DELAY * 0.8, config.API_DELAY * 1.4))
    finally:
        state["scrolling"] = False
