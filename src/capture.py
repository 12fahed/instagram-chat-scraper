"""
Capture Instagram DM network responses while auto-scrolling a chat upward.

Usage:
    pip install playwright
    playwright install chromium
    python capture.py

1. A Chromium window opens (persistent profile in ./.ig-profile, so you log in once).
2. Log in, open the chat you want, then press Enter in this terminal.
3. The script scrolls the chat to the top repeatedly and saves every matching
   response to ./captures/. It stops when nothing new loads for a while.
   Ctrl+C is safe at any time: every response is written to disk as it arrives.
"""

import asyncio
import json
import random
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote

from playwright.async_api import async_playwright

OUT = Path("captures")
PROFILE = Path(".ig-profile")

# Responses whose URL contains any of these get saved.
URL_PATTERNS = ("/graphql", "/api/graphql", "/api/v1/direct_v2")

# Form fields in the request that are auth tokens: never written to disk.
SECRET_FIELDS = {"fb_dtsg", "lsd", "jazoest", "__hs", "__hsi", "__rev", "__s", "__dyn", "__csr"}

IDLE_ROUNDS_TO_STOP = 10        # stop after this many scrolls with no new data
SCROLL_DELAY = (1.8, 3.5)       # random pause between scrolls, seconds (be gentle)
CAPTURE_WEBSOCKET = False       # set True to also log websocket text frames

state = {"count": 0, "last_capture": time.time()}


def parse_body(text: str):
    """IG bodies can be plain JSON, 'for (;;);'-prefixed, or several JSON objects, one per line."""
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
    if not post_data:
        return {}, None
    try:
        form = {k: v[0] for k, v in parse_qs(post_data).items()}
    except Exception:
        return {"raw": "<unparseable>"}, None
    for k in SECRET_FIELDS:
        form.pop(k, None)
    friendly = form.get("fb_api_req_friendly_name")
    if "variables" in form:
        try:
            form["variables"] = json.loads(form["variables"])
        except json.JSONDecodeError:
            pass
    return form, friendly


async def on_response(resp):
    url = resp.url
    if not any(p in url for p in URL_PATTERNS):
        return
    try:
        body = await resp.text()
    except Exception:
        return  # redirects / bodies already gone
    form, friendly = clean_request(resp.request.post_data)
    state["count"] += 1
    state["last_capture"] = time.time()
    name = re.sub(r"[^A-Za-z0-9_]+", "_", friendly or "unknown")[:60]
    record = {
        "seq": state["count"],
        "captured_at": time.time(),
        "url": url.split("?")[0],
        "status": resp.status,
        "friendly_name": friendly,
        "doc_id": form.get("doc_id"),
        "request": form,
        "chunks": parse_body(body),
        "raw": None,
    }
    if record["chunks"] is None:
        record["raw"] = body  # keep it so nothing is lost
    path = OUT / f"{state['count']:05d}_{name}.json"
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    print(f"  saved {path.name} ({len(body):,} bytes)")


def on_websocket(ws):
    log = OUT / "websocket_frames.jsonl"

    def frame(payload):
        if isinstance(payload, str):
            with log.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"t": time.time(), "url": ws.url, "data": payload}) + "\n")
            state["last_capture"] = time.time()

    ws.on("framereceived", frame)


# Finds the chat pane: the scrollable ancestor of whatever sits in the middle of
# the right-hand side of the screen (where IG renders the open conversation).
SCROLL_JS = r"""
() => {
  const isScrollable = (el) => {
    const s = getComputedStyle(el);
    return /(auto|scroll)/.test(s.overflowY) && el.scrollHeight > el.clientHeight + 20;
  };
  let el = window.__igChatPane;
  if (!el || !document.contains(el)) {
    let node = document.elementFromPoint(window.innerWidth * 0.65, window.innerHeight * 0.5);
    while (node && !isScrollable(node)) node = node.parentElement;
    if (!node) {
      const all = [...document.querySelectorAll('div')].filter(isScrollable);
      all.sort((a, b) => b.scrollHeight - a.scrollHeight);
      node = all[0];
    }
    if (!node) return null;
    window.__igChatPane = node;
    node.style.outline = '2px dashed #3797f0';  // shows you which pane is being scrolled
    el = node;
  }
  // Works for both normal and column-reverse layouts (the latter uses negative scrollTop).
  el.scrollTop = -el.scrollHeight;
  return { scrollHeight: el.scrollHeight, scrollTop: el.scrollTop };
}
"""


async def main():
    OUT.mkdir(exist_ok=True)
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(PROFILE), headless=False, viewport={"width": 1300, "height": 900}
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        page.on("response", lambda r: asyncio.ensure_future(on_response(r)))
        if CAPTURE_WEBSOCKET:
            page.on("websocket", on_websocket)

        await page.goto("https://www.instagram.com/direct/inbox/")
        await asyncio.to_thread(
            input, "\nLog in if needed, open the chat you want, then press Enter here... "
        )

        print("Scrolling. A dashed blue outline marks the pane being scrolled.")
        print("If the wrong pane is outlined, click inside the chat messages and restart.\n")
        last_height, idle = None, 0
        while idle < IDLE_ROUNDS_TO_STOP:
            before = state["count"]
            info = await page.evaluate(SCROLL_JS)
            if info is None:
                print("Couldn't find a scrollable chat pane yet; retrying...")
            await asyncio.sleep(random.uniform(*SCROLL_DELAY))
            height = info and info["scrollHeight"]
            grew = height != last_height
            got_new = state["count"] > before
            idle = 0 if (grew or got_new) else idle + 1
            last_height = height
            print(f"scroll: height={height} new_responses={state['count'] - before} idle={idle}")

        print(f"\nDone. {state['count']} responses saved in ./{OUT}/")
        await ctx.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\nStopped. {state['count']} responses saved in ./{OUT}/")
