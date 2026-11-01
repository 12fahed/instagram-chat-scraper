"""Everything one run needs to know about itself.

A single mutable dict rather than globals scattered across modules: the capture
loops, the response handler and the terminal prompts all read and write the same
progress, and passing it around explicitly would thread it through every call.
"""

import time

state = {
    "armed": False,             # nothing is written until you press Enter
    "count": 0,                 # responses saved so far, and the file number
    "last_capture": time.time(),
    "thread_pages": 0,          # responses that actually carried chat messages
    "thread_fbid": None,
    "message_ids": set(),       # dedupes across pages and across runs
    "oldest_ms": None,
    "newest_ms": None,
    "exhausted": False,         # IG said there is nothing older left
    "crashed": False,           # the renderer died (usually out of memory)
    "pause": False,             # Ctrl+C asked us to pause at the end of this round
    "quit": False,              # Ctrl+C again: stop altogether
    "prompt": None,             # the future a waiting prompt is parked on, if any
    "scrolling": False,         # only pause/stop while a capture loop is running
    "mode": "api",              # "api" (paging the query) or "scroll" (driving the UI)
    # The live thread request, kept so it can be replayed with a different cursor.
    # It carries auth tokens, so it lives in memory for the length of the run and
    # is never written to disk or printed.
    "template": None,
    "next_cursor": None,        # end_cursor of the furthest-back page seen
    "blocked": 0,               # media requests refused
}
