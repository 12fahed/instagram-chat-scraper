"""
Capture Instagram DM network responses while auto-scrolling a chat upward.

Usage:
    pip install playwright
    playwright install chromium
    python src/capture.py

How a run goes:

1. A Chromium window opens (persistent profile in ./.ig-profile, so you log in once)
   and lands on the DM inbox. Nothing is recorded yet.
2. Log in if needed and STAY on the inbox — do not open the chat yet. Press Enter
   in this terminal: that arms the recorder.
3. Now open the chat you want. The very first thread request — the one that paints
   the bottom of the conversation — is recorded too, so the archive has its
   starting point.
4. As soon as that first page of messages lands, the script starts scrolling up and
   keeps recording until the thread runs out or nothing new loads for a while.

The browser is never closed behind your back. Whatever happens - the top of the
thread, an idle stall, a renderer crash, an unexpected error - the script says what
happened and leaves Chromium open, so you can look at the page and, when the chat
pane is still alive, type `r` to carry on scrolling from exactly where it stopped
instead of starting the whole thread again.

Ctrl+C is safe at any time: every response is written to disk as it arrives.
Output goes to data/captures/, which is gitignored — keep it that way.
"""

import asyncio
import json
import random
import os
import re
import signal
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs

from playwright.async_api import Error as PlaywrightError, async_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "captures"      # under data/ so .gitignore covers it
PROFILE = ROOT / ".ig-profile"

# Responses whose URL contains any of these get saved.
URL_PATTERNS = ("/graphql", "/api/graphql", "/api/v1/direct_v2")

# Form fields in the request that are auth tokens: never written to disk.
SECRET_FIELDS = {"fb_dtsg", "lsd", "jazoest", "__hs", "__hsi", "__rev", "__s", "__dyn", "__csr"}

IDLE_ROUNDS_TO_STOP = 10        # stop after this many scrolls with no new data
MAX_SCROLL_FAILURES = 5         # consecutive failed scrolls before giving up
EXHAUSTED_CONFIRM = 2           # extra quiet scrolls after IG says there is no more
SETTLE_SECONDS = 2.5            # let the chat finish opening before the first scroll
SCROLL_DELAY = (1.8, 3.5)       # random pause between scrolls, seconds (be gentle)
CAPTURE_WEBSOCKET = False       # set True to also log websocket text frames

state = {
    "armed": False,             # nothing is written until you press Enter
    "count": 0,
    "last_capture": time.time(),
    "thread_pages": 0,          # responses that actually carried chat messages
    "thread_fbid": None,
    "message_ids": set(),
    "oldest_ms": None,
    "newest_ms": None,
    "exhausted": False,         # IG said there is nothing older left
    "crashed": False,           # the renderer died (usually out of memory)
    "pause": False,             # Ctrl+C asked us to pause at the end of this round
    "quit": False,              # Ctrl+C again: stop altogether
    "prompt": None,             # the future a waiting prompt is parked on, if any
    "scrolling": False,         # only pause/stop the scroll while there is one
}


async def ainput(prompt: str) -> str:
    """Read one line without blocking the event loop and without a helper thread.

    Not asyncio.to_thread(input) and not a daemon thread: either leaves a thread
    blocked in input() holding the stdin lock, and the interpreter then dies with
    "_enter_buffered_busy: could not acquire lock for <stdin>" on Ctrl+C. Reading
    through the loop has no thread to strand, and cancellation works normally.

    Blocking the loop with a plain input() is also not an option: a pause can last
    minutes, and Playwright needs the loop running to keep its connection alive.
    """
    loop = asyncio.get_running_loop()
    sys.stdout.write(prompt)
    sys.stdout.flush()

    future = loop.create_future()
    buffer = bytearray()
    fd = sys.stdin.fileno()

    def readable():
        try:
            chunk = os.read(fd, 1024)
        except (BlockingIOError, InterruptedError):
            return
        except OSError as exc:
            if not future.done():
                future.set_exception(exc)
            return
        if not chunk:                      # EOF
            if not future.done():
                future.set_result(buffer.decode(errors="replace"))
            return
        buffer.extend(chunk)
        if b"\n" in buffer and not future.done():
            future.set_result(buffer.split(b"\n", 1)[0].decode(errors="replace"))

    try:
        loop.add_reader(fd, readable)
    except (NotImplementedError, OSError, ValueError):
        return await asyncio.to_thread(input)   # Windows and other odd stdin
    state["prompt"] = future
    try:
        return await future
    finally:
        state["prompt"] = None
        try:
            loop.remove_reader(fd)
        except (NotImplementedError, OSError, ValueError):
            pass


def install_pause_handler() -> bool:
    """Ctrl+C pauses the scroll instead of killing the run.

    While scrolling: first Ctrl+C pauses, a second one stops.
    While a prompt is waiting: Ctrl+C answers it with "stop".

    The handler is installed once and never removed. Taking it off would call
    loop.remove_signal_handler(), which overwrites asyncio.Runner's own SIGINT
    handler with the plain default - and then Ctrl+C raises KeyboardInterrupt
    inside the selector instead of cancelling cleanly, with a traceback to match.

    Returns False where the platform has no signal handler support (Windows),
    in which case Ctrl+C keeps its usual meaning.
    """
    def on_sigint():
        waiting = state["prompt"]
        if waiting is not None and not waiting.done():
            print("\n  Ctrl+C — stopping.")
            waiting.set_result("")       # same as answering the prompt with Enter
            return
        if not state["scrolling"]:
            return                       # already stopping; do not confuse the user
        if state["pause"]:
            state["quit"] = True
            print("\n  Ctrl+C again — stopping after this scroll.")
        else:
            state["pause"] = True
            print("\n  Ctrl+C — pausing after this scroll (again to stop).")

    try:
        asyncio.get_running_loop().add_signal_handler(signal.SIGINT, on_sigint)
        return True
    except (NotImplementedError, RuntimeError):
        return False


def walk(obj):
    yield obj
    if isinstance(obj, dict):
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


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


def note_thread(chunks) -> int:
    """Track live progress from any slide_messages connection in the body.

    Returns how many messages this response added that we had not seen before,
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
        # Edges come back newest-first, so the "next" page is the older one.
        if page_info.get("has_next_page") is False:
            state["exhausted"] = True
    return added


def next_seq() -> int:
    """Continue numbering after an earlier run instead of overwriting it."""
    seqs = [int(m.group(1)) for p in OUT.glob("*.json") if (m := re.match(r"(\d{5})_", p.name))]
    return max(seqs, default=0)


async def on_response(resp):
    if not state["armed"]:
        return
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
    chunks = parse_body(body)
    record = {
        "seq": state["count"],
        "captured_at": time.time(),
        "url": url.split("?")[0],
        "status": resp.status,
        "friendly_name": friendly,
        "doc_id": form.get("doc_id"),
        "request": form,
        "chunks": chunks,
        "raw": None,
    }
    if chunks is None:
        record["raw"] = body  # keep it so nothing is lost
    path = OUT / f"{state['count']:05d}_{name}.json"
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    added = note_thread(chunks)
    extra = f", +{added} messages" if added else ""
    print(f"  saved {path.name} ({len(body):,} bytes{extra})")


def on_websocket(ws):
    log = OUT / "websocket_frames.jsonl"

    def frame(payload):
        if state["armed"] and isinstance(payload, str):
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


def watch(page):
    page.on("response", lambda r: asyncio.ensure_future(on_response(r)))
    if CAPTURE_WEBSOCKET:
        page.on("websocket", on_websocket)


def when(ms):
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M") if ms else "?"


async def wait_for_chat_to_open(page=None):
    """Block until the browser actually loads a page of messages.

    Returns False if the window went away while we were waiting, so the caller
    can report that instead of spinning forever against a dead browser.
    """
    print("\nRecording is ON. Open the chat you want to archive in the browser.")
    print("(The first request it makes is the bottom of the conversation — that is the")
    print(" starting point the account export never gives you.)\n")
    waited = 0.0
    while state["thread_pages"] == 0:
        if page is not None and (state["crashed"] or page.is_closed()):
            return False
        await asyncio.sleep(0.5)
        waited += 0.5
        if waited % 20 == 0:
            print(f"  still waiting for a thread to open... ({int(waited)}s, "
                  f"{state['count']} unrelated responses recorded so far)")
    print(f"\nThread {state['thread_fbid']} opened: {len(state['message_ids'])} messages so far.")
    print(f"Letting it settle for {SETTLE_SECONDS}s before scrolling.")
    await asyncio.sleep(SETTLE_SECONDS)
    return True


def _page_gone(exc: BaseException, page) -> bool:
    """Playwright does not export TargetClosedError, so match on the message too."""
    if state["crashed"] or page.is_closed():
        return True
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "target page, context or browser has been closed",
            "target closed",
            "browser has been closed",
            "page has been closed",
            "connection closed",
            "browser closed",
        )
    )


async def scroll_loop(page) -> dict:
    """Scroll until something stops us. Returns why, never raises for page trouble."""
    print("\nScrolling. A dashed blue outline marks the pane being scrolled.")
    print("If the wrong pane is outlined, click inside the chat messages and restart.\n")
    last_height, idle, quiet_after_end, rounds, failures = None, 0, 0, 0, 0
    state["scrolling"] = True
    try:
        while idle < IDLE_ROUNDS_TO_STOP:
            if state["quit"]:
                return {"reason": "interrupted", "detail": None, "rounds": rounds}
            if state["pause"]:
                return {"reason": "paused", "detail": None, "rounds": rounds}
            # The crash event can arrive between rounds, while evaluate() still
            # happens to succeed against a half-dead page, so check it up front.
            if state["crashed"] or page.is_closed():
                return {
                    "reason": "page_gone",
                    "detail": "the renderer crashed" if state["crashed"] else "the page was closed",
                    "rounds": rounds,
                }
            rounds += 1
            before_msgs = len(state["message_ids"])
            try:
                info = await page.evaluate(SCROLL_JS)
                failures = 0
            except (PlaywrightError, asyncio.TimeoutError) as exc:
                first_line = str(exc).strip().splitlines()[0][:160]
                if _page_gone(exc, page):
                    return {"reason": "page_gone", "detail": first_line, "rounds": rounds}
                failures += 1
                print(f"  scroll failed ({type(exc).__name__}: {first_line}) — "
                      f"retry {failures}/{MAX_SCROLL_FAILURES}")
                if failures >= MAX_SCROLL_FAILURES:
                    return {"reason": "scroll_failed", "detail": first_line, "rounds": rounds}
                await asyncio.sleep(2 * failures)   # the pane is re-found on the next try
                continue

            if info is None:
                print("Couldn't find a scrollable chat pane yet; retrying...")
            await asyncio.sleep(random.uniform(*SCROLL_DELAY))
            height = info and info["scrollHeight"]
            new_msgs = len(state["message_ids"]) - before_msgs
            idle = 0 if (height != last_height or new_msgs) else idle + 1
            last_height = height
            print(f"scroll {rounds:>3}: +{new_msgs} messages  total={len(state['message_ids'])}  "
                  f"oldest={when(state['oldest_ms'])}  idle={idle}")

            if state["exhausted"]:
                quiet_after_end = quiet_after_end + 1 if not new_msgs else 0
                if quiet_after_end >= EXHAUSTED_CONFIRM:
                    return {"reason": "reached_top", "detail": None, "rounds": rounds}

        return {"reason": "idle", "detail": None, "rounds": rounds}
    finally:
        state["scrolling"] = False


def summary():
    print(f"\n{state['count']} responses in {OUT}")
    print(f"{len(state['message_ids'])} unique messages across {state['thread_pages']} thread pages")
    if state["message_ids"]:
        print(f"range: {when(state['oldest_ms'])}  ..  {when(state['newest_ms'])}")


def report_outcome(outcome: dict):
    reason, detail = outcome["reason"], outcome.get("detail")
    line = "=" * 72
    print(f"\n{line}")
    if reason == "paused":
        print("PAUSED. Recording is OFF — nothing is being written while paused.")
        print(f"Captured so far: {len(state['message_ids'])} messages back to "
              f"{when(state['oldest_ms'])}")
        print("The chat pane keeps its position, so resuming carries on from here.")
    elif reason == "reached_top":
        print("REACHED THE TOP. Instagram reports no older messages in this thread.")
        print(f"Oldest message captured: {when(state['oldest_ms'])}")
    elif reason == "idle":
        print(f"STALLED. No new messages for {IDLE_ROUNDS_TO_STOP} scrolls.")
        if not state["exhausted"]:
            print("Instagram never said the thread was exhausted, so this is probably")
            print("NOT the top — the chat pane may have stopped loading. Try resuming.")
    elif reason == "page_gone":
        print("THE BROWSER PAGE IS GONE — it was closed, or the renderer crashed.")
        print("On a long run this is usually Chromium running out of memory: the chat")
        print("pane holds every message you scrolled past, plus their images.")
        print(f"Playwright said: {detail}")
        print("\nEverything captured so far is already on disk. Re-run the script to")
        print("continue; file numbering carries on and the analyser de-duplicates.")
    elif reason == "scroll_failed":
        print(f"SCROLLING FAILED {MAX_SCROLL_FAILURES} times in a row.")
        print(f"Playwright said: {detail}")
    elif reason == "interrupted":
        print("INTERRUPTED (Ctrl+C).")
    else:
        print("UNEXPECTED ERROR — everything captured so far is still on disk.")
        print(detail or "")
    print(line)


async def hold_open(ctx, page, outcome: dict) -> bool:
    """Keep Chromium alive and hand control back. True = resume scrolling."""
    dead = outcome["reason"] == "page_gone"
    if not dead:
        try:
            dead = page.is_closed()
        except Exception:
            dead = True

    if dead:
        print("\nThe browser window is gone, so scrolling cannot resume here.")
        prompt = "Press Enter to exit... "
    elif outcome["reason"] == "paused":
        print("\nThe browser is yours — scroll, open a reply, let things load.")
        print("Nothing is recorded until you resume, so you can move around freely.")
        prompt = "Type r then Enter to resume recording and scrolling, or just Enter to stop... "
    elif outcome["reason"] != "reached_top":
        print("\nThe browser is still open — go look at it if you want.")
        print("Scrolling can carry on from exactly where the chat pane is now,")
        print("so you do not have to walk the whole thread again.")
        prompt = "Type r then Enter to resume scrolling, or just Enter to close... "
    else:
        print("\nThe browser is still open — go look at it if you want.")
        prompt = "Press Enter to close the browser... "

    try:
        answer = (await ainput(prompt)).strip().lower()
    except (EOFError, KeyboardInterrupt, asyncio.CancelledError):
        # asyncio.run() turns a Ctrl+C here into CancelledError, and re-raises
        # KeyboardInterrupt itself once we return - so treat all of them as "stop".
        answer = ""
    return answer == "r" and not dead and outcome["reason"] != "reached_top"


def watch_for_crash(page):
    def crashed(_=None):
        state["crashed"] = True
        print("\n  !! the page crashed (renderer died) — scrolling will stop")

    page.on("crash", crashed)


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    state["count"] = next_seq()
    if state["count"]:
        print(f"{OUT} already holds {state['count']} responses; continuing after them.")

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(PROFILE),
            headless=False,
            viewport={"width": 1300, "height": 900},
            # Long runs keep thousands of messages and their images alive in the
            # chat pane; a small /dev/shm is a common way for that to end badly.
            args=["--disable-dev-shm-usage"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        watch(page)
        watch_for_crash(page)
        ctx.on("page", watch)  # IG sometimes opens the thread in a new tab

        await page.goto("https://www.instagram.com/direct/inbox/")
        await ainput(
            "\nLog in if needed and STAY on the inbox — do NOT open the chat yet."
            "\nPress Enter to start recording... "
        )
        state["armed"] = True

        try:
            if not await wait_for_chat_to_open(page):
                report_outcome({"reason": "page_gone",
                                "detail": "closed before a chat was opened"})
                raise SystemExit(1)
            if install_pause_handler():
                print("Ctrl+C pauses the scroll (Ctrl+C twice stops).")
            while True:
                state["pause"] = state["quit"] = False
                try:
                    outcome = await scroll_loop(page)
                except KeyboardInterrupt:
                    outcome = {"reason": "interrupted", "detail": None}
                except Exception:
                    outcome = {"reason": "error", "detail": traceback.format_exc()}
                # Paused means recording off, as does a page we can no longer reach.
                state["armed"] = outcome["reason"] not in ("paused", "page_gone")
                summary()
                report_outcome(outcome)
                if not await hold_open(ctx, page, outcome):
                    break
                state["armed"] = True
                print("\nResuming — recording is back ON.\n")
        finally:
            state["armed"] = False
            print(f"\nDone. {state['count']} responses in {OUT}")
            print("Next: python -m src.analyze report data/captures")
            try:
                await ctx.close()
            except Exception:
                pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\nStopped. {state['count']} responses saved in {OUT}")
