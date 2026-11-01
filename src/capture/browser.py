"""Launching Chromium and wiring each page up to the recorder."""

import asyncio

from . import config
from .recording import on_response, on_websocket
from .state import state


async def launch(playwright, block_media_requests: bool):
    """A persistent-profile Chromium, so the login survives between runs."""
    ctx = await playwright.chromium.launch_persistent_context(
        str(config.PROFILE),
        headless=False,
        viewport={"width": 1300, "height": 900},
        # Long runs keep thousands of messages alive in the chat pane; a small
        # /dev/shm is a common way for that to end badly.
        args=["--disable-dev-shm-usage"],
    )
    if block_media_requests:
        await ctx.route("**/*", block_media)
    return ctx


def watch(page):
    """Record this page's responses. Also used for tabs Instagram opens itself."""
    page.on("response", lambda r: asyncio.ensure_future(on_response(r)))
    if config.CAPTURE_WEBSOCKET:
        page.on("websocket", on_websocket)


def watch_for_crash(page):
    def crashed(_=None):
        state["crashed"] = True
        print("\n  !! the page crashed (renderer died) — capturing will stop")

    page.on("crash", crashed)


async def block_media(route, request):
    """Refuse images/video/fonts: the renderer keeps every one of them alive."""
    if request.resource_type in config.BLOCKED_RESOURCES:
        state["blocked"] += 1
        try:
            await route.abort()
        except Exception:
            pass
        return
    try:
        await route.continue_()
    except Exception:
        pass


def page_gone(exc: BaseException, page) -> bool:
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


async def wait_for_chat_to_open(page=None) -> bool:
    """Block until the browser actually loads a page of messages.

    Returns False if the window went away while we were waiting, so the caller can
    report that instead of spinning forever against a dead browser.
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
    print(f"Letting it settle for {config.SETTLE_SECONDS}s.")
    await asyncio.sleep(config.SETTLE_SECONDS)
    return True
