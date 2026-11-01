"""Fallback capture mode: drive the UI the way a person would.

This is what the page itself does, but Instagram's DM pane does not virtualise,
so the renderer fills up and eventually dies on a long thread. Kept because it
never disagrees with what the page shows.
"""

import asyncio
import random

from playwright.async_api import Error as PlaywrightError

from . import config
from .browser import page_gone
from .state import state
from .util import when

# Finds the chat pane: the scrollable ancestor of whatever sits in the middle of
# the right-hand side of the screen, where IG renders the open conversation.
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
    node.style.outline = '2px dashed #3797f0';  // shows which pane is being scrolled
    el = node;
  }
  // Works for both normal and column-reverse layouts (the latter uses negative scrollTop).
  el.scrollTop = -el.scrollHeight;
  return { scrollHeight: el.scrollHeight, scrollTop: el.scrollTop };
}
"""


async def scroll_loop(page) -> dict:
    """Scroll until something stops us. Returns why, never raises for page trouble."""
    print("\nScrolling. A dashed blue outline marks the pane being scrolled.")
    print("If the wrong pane is outlined, click inside the chat messages and restart.\n")
    last_height, idle, quiet_after_end, rounds, failures = None, 0, 0, 0, 0
    state["mode"] = "scroll"
    state["scrolling"] = True
    try:
        while idle < config.IDLE_ROUNDS_TO_STOP:
            if state["quit"]:
                return {"reason": "interrupted", "detail": None, "rounds": rounds}
            if state["pause"]:
                return {"reason": "paused", "detail": None, "rounds": rounds}
            # The crash event can arrive between rounds, while evaluate() still
            # happens to succeed against a half-dead page, so check it up front.
            if state["crashed"] or page.is_closed():
                return {"reason": "page_gone",
                        "detail": "the renderer crashed" if state["crashed"]
                                  else "the page was closed",
                        "rounds": rounds}

            rounds += 1
            before = len(state["message_ids"])
            try:
                info = await page.evaluate(SCROLL_JS)
                failures = 0
            except (PlaywrightError, asyncio.TimeoutError) as exc:
                first_line = str(exc).strip().splitlines()[0][:160]
                if page_gone(exc, page):
                    return {"reason": "page_gone", "detail": first_line, "rounds": rounds}
                failures += 1
                print(f"  scroll failed ({type(exc).__name__}: {first_line}) — "
                      f"retry {failures}/{config.MAX_SCROLL_FAILURES}")
                if failures >= config.MAX_SCROLL_FAILURES:
                    return {"reason": "scroll_failed", "detail": first_line, "rounds": rounds}
                await asyncio.sleep(2 * failures)   # the pane is re-found on the next try
                continue

            if info is None:
                print("Couldn't find a scrollable chat pane yet; retrying...")
            await asyncio.sleep(random.uniform(*config.SCROLL_DELAY))
            height = info and info["scrollHeight"]
            new_msgs = len(state["message_ids"]) - before
            idle = 0 if (height != last_height or new_msgs) else idle + 1
            last_height = height
            print(f"scroll {rounds:>3}: +{new_msgs} messages  "
                  f"total={len(state['message_ids'])}  "
                  f"oldest={when(state['oldest_ms'])}  idle={idle}")

            if state["exhausted"]:
                quiet_after_end = quiet_after_end + 1 if not new_msgs else 0
                if quiet_after_end >= config.EXHAUSTED_CONFIRM:
                    return {"reason": "reached_top", "detail": None, "rounds": rounds}

        return {"reason": "idle", "detail": None, "rounds": rounds}
    finally:
        state["scrolling"] = False
