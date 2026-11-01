"""Terminal I/O: reading a line, Ctrl+C handling, and the end-of-run reports."""

import asyncio
import os
import signal
import sys

from . import config
from .state import state
from .util import when


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
    """Make Ctrl+C pause the capture instead of killing the run.

    While a loop is running: first Ctrl+C pauses, a second one stops.
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
            print("\n  Ctrl+C again — stopping.")
        else:
            state["pause"] = True
            unit = "request" if state["mode"] == "api" else "scroll"
            print(f"\n  Ctrl+C — pausing after this {unit} (again to stop).")

    try:
        asyncio.get_running_loop().add_signal_handler(signal.SIGINT, on_sigint)
        return True
    except (NotImplementedError, RuntimeError):
        return False


def summary():
    print(f"\n{state['count']} responses in {config.OUT}")
    print(f"{len(state['message_ids'])} unique messages across {state['thread_pages']} thread pages")
    if state["blocked"]:
        print(f"{state['blocked']} media requests blocked (they are downloaded later by --media)")
    if state["message_ids"]:
        print(f"range: {when(state['oldest_ms'])}  ..  {when(state['newest_ms'])}")


def report_outcome(outcome: dict):
    """Say in plain terms why the run stopped, and what to do about it."""
    reason, detail = outcome["reason"], outcome.get("detail")
    rule = "=" * 72
    print(f"\n{rule}")
    if reason == "paused":
        print("PAUSED. Recording is OFF — nothing is being written while paused.")
        print(f"Captured so far: {len(state['message_ids'])} messages back to "
              f"{when(state['oldest_ms'])}")
        if state["mode"] == "api":
            print("Resuming carries on from the last cursor Instagram handed out.")
        else:
            print("The chat pane keeps its position, so resuming carries on from here.")
    elif reason == "api_rejected":
        print("INSTAGRAM REFUSED THE REPLAYED REQUEST.")
        print(f"It said: {detail}")
        print("\nThe captured request may have aged out. Re-run with --scroll to go")
        print("back to driving the UI, which is slower but always matches the page.")
    elif reason in ("api_failed", "no_template"):
        print("CAPTURE COULD NOT CONTINUE.")
        print(f"Reason: {detail}")
        print("\nRe-run with --scroll to fall back to scrolling the UI.")
    elif reason == "reached_top":
        print("REACHED THE TOP. Instagram reports no older messages in this thread.")
        print(f"Oldest message captured: {when(state['oldest_ms'])}")
    elif reason == "idle":
        print(f"STALLED. No new messages for {config.IDLE_ROUNDS_TO_STOP} scrolls.")
        if not state["exhausted"]:
            print("Instagram never said the thread was exhausted, so this is probably")
            print("NOT the top — the chat pane may have stopped loading. Try resuming.")
    elif reason == "page_gone":
        print("THE BROWSER PAGE IS GONE — it was closed, or the renderer crashed.")
        if state["mode"] == "scroll":
            print("While scrolling this is usually Chromium running out of memory: the")
            print("chat pane holds every message scrolled past, plus their images.")
        print(f"Playwright said: {detail}")
        print("\nEverything captured so far is already on disk. Run the script again:")
        print(f"it will offer to continue from {when(state['oldest_ms'])} using the saved")
        print("cursor, so nothing above that is fetched twice.")
    elif reason == "scroll_failed":
        print(f"SCROLLING FAILED {config.MAX_SCROLL_FAILURES} times in a row.")
        print(f"Playwright said: {detail}")
    elif reason == "interrupted":
        print("INTERRUPTED (Ctrl+C).")
    else:
        print("UNEXPECTED ERROR — everything captured so far is still on disk.")
        print(detail or "")
    print(rule)


async def hold_open(page, outcome: dict) -> bool:
    """Keep Chromium alive and hand control back. True means resume capturing."""
    dead = outcome["reason"] == "page_gone"
    if not dead:
        try:
            dead = page.is_closed()
        except Exception:
            dead = True

    if dead:
        print("\nThe browser window is gone, so this run cannot continue.")
        prompt = "Press Enter to exit... "
    elif outcome["reason"] == "paused":
        print("\nThe browser is yours — scroll, open a reply, let things load.")
        print("Nothing is recorded until you resume, so you can move around freely.")
        prompt = "Type r then Enter to resume recording, or just Enter to stop... "
    elif outcome["reason"] != "reached_top":
        print("\nThe browser is still open — go look at it if you want.")
        print("Capturing can carry on from where it stopped, so the thread does not")
        print("have to be walked again.")
        prompt = "Type r then Enter to resume, or just Enter to close... "
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
