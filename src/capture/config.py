"""Tunables and fixed values for a capture run."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "data" / "captures"      # under data/ so .gitignore covers it
PROFILE = ROOT / ".ig-profile"        # persistent browser profile: log in once

INBOX_URL = "https://www.instagram.com/direct/inbox/"

# Responses whose URL contains any of these get saved.
URL_PATTERNS = ("/graphql", "/api/graphql", "/api/v1/direct_v2")

# Form fields in the request that are auth tokens: never written to disk.
SECRET_FIELDS = {"fb_dtsg", "lsd", "jazoest", "__hs", "__hsi", "__rev", "__s", "__dyn", "__csr"}

# fetch() refuses to let a page set these; the browser supplies them itself.
FETCH_FORBIDDEN_HEADERS = {
    "host", "connection", "content-length", "cookie", "accept-encoding",
    "origin", "referer", "user-agent", "sec-fetch-mode", "sec-fetch-site",
    "sec-fetch-dest", "te", "transfer-encoding", "upgrade", "keep-alive",
}

# Instagram's DM pane does not virtualise: every message scrolled past stays in the
# DOM with its images decoded, and the renderer dies somewhere around 20k messages.
# Media is never read from the page - the archive takes every URL from the JSON -
# so refusing to load it costs nothing and buys a lot of headroom.
BLOCKED_RESOURCES = {"image", "media", "font"}

API_DELAY = 1.2                 # seconds between paged API requests; --delay overrides
CURSOR_VARS = ("after", "cursor", "before")
RESUME_SCAN_FILES = 40          # newest capture files searched for a resume cursor

IDLE_ROUNDS_TO_STOP = 10        # stop after this many scrolls with no new data
MAX_SCROLL_FAILURES = 5         # consecutive failed scrolls before giving up
EXHAUSTED_CONFIRM = 2           # extra quiet scrolls after IG says there is no more
SETTLE_SECONDS = 2.5            # let the chat finish opening before the first scroll
SCROLL_DELAY = (1.8, 3.5)       # random pause between scrolls, seconds (be gentle)
CAPTURE_WEBSOCKET = False       # set True to also log websocket text frames
