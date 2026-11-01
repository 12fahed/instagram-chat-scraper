"""Entry point: wire the browser, the recorder and the capture loop together.

    python -m src.capture
"""

import argparse
import asyncio
import traceback

from . import browser, config
from .paging import api_loop
from .recording import next_seq
from .resume import offer_resume
from .scrolling import scroll_loop
from .state import state
from .terminal import hold_open, install_pause_handler, report_outcome, summary, ainput


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Capture an Instagram DM thread.")
    ap.add_argument("--scroll", action="store_true",
                    help="drive the UI by scrolling instead of paging the query "
                         "(slower, and the renderer eventually runs out of memory)")
    ap.add_argument("--images", action="store_true",
                    help="let the page load images and video (uses far more memory)")
    ap.add_argument("--delay", type=float, default=config.API_DELAY,
                    help=f"seconds between paged requests (default {config.API_DELAY})")
    return ap.parse_args(argv)


async def capture_until_done(page):
    """Run the capture loop, then let the user resume it, until they are finished."""
    use_api = state["mode"] == "api"
    while True:
        state["pause"] = state["quit"] = False
        try:
            outcome = await (api_loop(page) if use_api else scroll_loop(page))
        except KeyboardInterrupt:
            outcome = {"reason": "interrupted", "detail": None}
        except Exception:
            outcome = {"reason": "error", "detail": traceback.format_exc()}
        # Paused means recording off, as does a page we can no longer reach.
        state["armed"] = outcome["reason"] not in ("paused", "page_gone")
        summary()
        report_outcome(outcome)
        if not await hold_open(page, outcome):
            return
        state["armed"] = True
        print("\nResuming — recording is back ON.\n")


async def main(args=None):
    args = args or parse_args()
    config.API_DELAY = args.delay
    config.OUT.mkdir(parents=True, exist_ok=True)
    state["count"] = next_seq()
    if state["count"]:
        print(f"{config.OUT} already holds {state['count']} responses; continuing after them.")

    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        ctx = await browser.launch(playwright, block_media_requests=not args.images)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        browser.watch(page)
        browser.watch_for_crash(page)
        ctx.on("page", browser.watch)   # IG sometimes opens the thread in a new tab

        await page.goto(config.INBOX_URL)
        await ainput(
            "\nLog in if needed and STAY on the inbox — do NOT open the chat yet."
            "\nPress Enter to start recording... "
        )
        state["armed"] = True

        try:
            if not await browser.wait_for_chat_to_open(page):
                report_outcome({"reason": "page_gone",
                                "detail": "closed before a chat was opened"})
                raise SystemExit(1)
            if install_pause_handler():
                print("Ctrl+C pauses (Ctrl+C twice stops).")

            state["mode"] = "scroll" if args.scroll else "api"
            if state["mode"] == "api" and not state["template"]:
                print("\nNo thread request was captured, so API paging is not possible.")
                print("Falling back to scrolling the UI.")
                state["mode"] = "scroll"
            if state["mode"] == "api":
                await offer_resume()

            await capture_until_done(page)
        finally:
            state["armed"] = False
            print(f"\nDone. {state['count']} responses in {config.OUT}")
            print("Next: python -m src.analyze report data/captures")
            try:
                await ctx.close()
            except Exception:
                pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\nStopped. {state['count']} responses saved in {config.OUT}")
