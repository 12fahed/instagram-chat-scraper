"""Picking a stopped run back up.

Pagination is driven by a cursor, and every response is already on disk, so the
cursor that points further back than anything else is enough to continue from.
"""

import json

from . import config
from .state import state
from .terminal import ainput
from .util import walk, when


def find_resume_point():
    """The furthest-back cursor already on disk, or None.

    Pages are fetched oldest-last, so the answer is in one of the newest files;
    there is no need to parse thousands of them to find it.
    """
    best = None
    for path in reversed(sorted(config.OUT.glob("*.json"))[-config.RESUME_SCAN_FILES:]):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for obj in walk(record):
            if not isinstance(obj, dict):
                continue
            conn = obj.get("slide_messages")
            if not isinstance(conn, dict) or not isinstance(conn.get("edges"), list):
                continue
            page_info = conn.get("page_info") or {}
            stamps = [
                int(node["timestamp_ms"])
                for edge in conn["edges"]
                for node in [(edge or {}).get("node") or {}]
                if str(node.get("timestamp_ms", "")).isdigit()
            ]
            if not page_info.get("end_cursor") or not stamps:
                continue
            oldest = min(stamps)
            if best is None or oldest < best["oldest"]:
                best = {"cursor": page_info["end_cursor"], "oldest": oldest,
                        "file": path.name, "has_next": page_info.get("has_next_page")}
    return best


async def offer_resume():
    """Ask whether to continue where a previous run stopped."""
    point = find_resume_point()
    if not point:
        return
    if point["has_next"] is False:
        print(f"\n{config.OUT} already reaches the top of the thread — nothing older to fetch.")
        return
    # Ignore a saved cursor that is newer than where this run already is.
    if state["oldest_ms"] and point["oldest"] >= state["oldest_ms"]:
        return

    print(f"\n{config.OUT} already reaches back to {when(point['oldest'])} ({point['file']}).")
    print("Continuing from there picks up exactly where the last run stopped.")
    answer = (await ainput("Press Enter to continue from there, or type f to "
                           "start again from the newest messages... ")).strip().lower()
    if answer == "f":
        print("Starting again from the newest messages.")
        return
    state["next_cursor"] = point["cursor"]
    print(f"Continuing from {when(point['oldest'])}.")
